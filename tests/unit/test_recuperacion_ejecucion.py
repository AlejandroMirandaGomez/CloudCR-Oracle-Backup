import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import oracledb
import pytest

from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.domain.alertas import CodigoAlerta, Condicion
from cloudcr_backup.domain.enums import EstadoPrueba, EstadoScript, TipoRespaldo
from cloudcr_backup.domain.errores import OperacionNoPermitida, RecursoNoEncontrado, RepositorioNoDisponible
from cloudcr_backup.domain.perfil_bd import PerfilBD
from cloudcr_backup.domain.recuperacion import (
    Diagnostico,
    Escenario,
    EstadoPdb,
    FallaDetectada,
    PuntoRecuperacion,
    RegistroRecuperacion,
    ResultadoRecuperacion,
)
from cloudcr_backup.execution.apertura import ResultadoApertura
from cloudcr_backup.execution.destino import BaseDestino, EstadoApertura, consulta_de
from cloudcr_backup.execution.parser import analizar
from cloudcr_backup.execution.runner import InvocacionRman, ResultadoRman
from cloudcr_backup.recovery import calendario
from cloudcr_backup.recovery.ejecucion import (
    ESCENARIOS_CON_RESETLOGS,
    RECORDATORIO_ARCHIVELOG,
    RECORDATORIO_RESETLOGS,
    clasificar,
)
from cloudcr_backup.recovery.en_linea import ObjetoEnLinea, ResultadoEnLinea
from cloudcr_backup.recovery.procedimientos import AVISO_EN_LINEA_PDB
from cloudcr_backup.repository import alertas as repositorio_alertas
from cloudcr_backup.repository import bases_datos as repositorio_bases_datos
from cloudcr_backup.repository import conexion as repositorio_conexion
from cloudcr_backup.repository import ejecuciones as repositorio_ejecuciones
from cloudcr_backup.repository import esquema
from cloudcr_backup.repository import estrategias as repositorio_estrategias
from cloudcr_backup.repository import parametros as repositorio_parametros
from cloudcr_backup.repository import piezas as repositorio_piezas
from cloudcr_backup.repository import recuperaciones as repositorio_recuperaciones
from cloudcr_backup.repository.bases_datos import Ambiente, BaseDatosRegistrada
from cloudcr_backup.services import recuperacion
from tests.unit.oracle_falso import ConexionConFallaPorTexto, ConexionFalsa

BD_PRUEBAS = BaseDatosRegistrada(id=1, nombre="XE", oracle_home=r"C:\oracle", ambiente=Ambiente.PRUEBAS, activa=True)
LOG_CORRECTO = (
    "connected to target database: XE (DBID=1)\nFinished recover at 11-OCT-26\n\nRecovery Manager complete.\n"
)
LOG_CON_ERROR = (
    "connected to target database: XE (DBID=1)\nRMAN-00571: ===\nRMAN-03002: failure of restore command\n"
    "ORA-19870: error while restoring backup piece\nRecovery Manager complete.\n"
)


class RepositorioFalso:
    def __init__(self) -> None:
        self.registros: dict[int, RegistroRecuperacion] = {}

    def registrar(
        self, c: Any, bd_id: int, escenario: Escenario, objetivo: Any, ruta: str, contenido: str, hash_: str, en: Any
    ) -> RegistroRecuperacion:
        registro = RegistroRecuperacion(
            id=len(self.registros) + 1,
            bd_id=bd_id,
            escenario=escenario,
            objetivo=objetivo,
            ruta_script=ruta,
            contenido=contenido,
            hash_sha256=hash_,
            estado=EstadoScript.BORRADOR,
            generado_en=en,
        )
        self.registros[registro.id] = registro
        return registro

    def obtener(self, c: Any, procedimiento_id: int) -> RegistroRecuperacion | None:
        return self.registros.get(procedimiento_id)

    def borrador_sin_usar(self, c: Any, bd_id: int, escenario: Escenario, hash_: str) -> RegistroRecuperacion | None:
        return next(
            (
                r
                for r in reversed(self.registros.values())
                if (r.bd_id, r.escenario, r.hash_sha256) == (bd_id, escenario, hash_)
                and r.estado is EstadoScript.BORRADOR
                and r.resultado is None
            ),
            None,
        )

    def _cambiar(self, procedimiento_id: int, **cambios: Any) -> None:
        self.registros[procedimiento_id] = self.registros[procedimiento_id].model_copy(update=cambios)

    def aprobar(self, c: Any, procedimiento_id: int, por: str) -> bool:
        if self.registros[procedimiento_id].estado is not EstadoScript.BORRADOR:
            return False
        self._cambiar(
            procedimiento_id, estado=EstadoScript.APROBADO, aprobado_por=por, aprobado_en=datetime(2026, 1, 1)
        )
        return True

    def marcar_en_curso(self, c: Any, procedimiento_id: int, ruta_log: str) -> bool:
        registro = self.registros[procedimiento_id]
        if registro.estado is not EstadoScript.APROBADO or registro.resultado is not None:
            return False
        self._cambiar(procedimiento_id, resultado=ResultadoRecuperacion.EN_CURSO, ruta_log=ruta_log)
        return True

    def registrar_resultado(
        self, c: Any, procedimiento_id: int, resultado: ResultadoRecuperacion, mensaje: str
    ) -> None:
        self._cambiar(procedimiento_id, resultado=resultado, mensaje=mensaje)


@dataclass
class Entorno:
    ajustes: Ajustes
    repositorio: RepositorioFalso
    base: BaseDatosRegistrada = BD_PRUEBAS
    invocaciones: list[InvocacionRman] = field(default_factory=list)
    notificadas: list[Condicion] = field(default_factory=list)
    resueltas: list[int] = field(default_factory=list)

    def lanzador(self, log: str = LOG_CORRECTO, codigo: int = 0) -> Callable[[InvocacionRman], ResultadoRman]:
        def lanzar(invocacion: InvocacionRman) -> ResultadoRman:
            self.invocaciones.append(invocacion)
            invocacion.log.parent.mkdir(parents=True, exist_ok=True)
            invocacion.log.write_text(log, encoding="utf-8")
            return ResultadoRman(codigo_salida=codigo, agotado=False, duracion_segundos=1.0)

        return lanzar

    def notificar(self, condiciones: Any, ajustes: Ajustes) -> None:
        self.notificadas.extend(condiciones)


@pytest.fixture
def entorno(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Entorno:
    datos = Entorno(Ajustes(work_dir=tmp_path, repositorio_dsn="x"), RepositorioFalso())
    monkeypatch.setattr(repositorio_conexion, "abrir_repositorio", lambda a: ConexionFalsa())
    monkeypatch.setattr(recuperacion, "preparar_cliente_oracle", lambda: None)
    monkeypatch.setattr(repositorio_bases_datos, "obtener", lambda c, n: datos.base if n == "XE" else None)
    monkeypatch.setattr(repositorio_bases_datos, "ultimo_perfil", lambda c, i: None)
    monkeypatch.setattr(repositorio_estrategias, "listar", lambda c, b: [])
    monkeypatch.setattr(repositorio_ejecuciones, "historial_detallado", lambda c, f, limite: [])
    monkeypatch.setattr(repositorio_piezas, "de_base", lambda c, b: [])
    monkeypatch.setattr(repositorio_parametros, "obtener", lambda c, clave: None)
    monkeypatch.setattr(repositorio_recuperaciones, "asegurar_tabla", lambda c: None)
    for nombre in ("registrar", "obtener", "borrador_sin_usar", "aprobar", "marcar_en_curso", "registrar_resultado"):
        monkeypatch.setattr(repositorio_recuperaciones, nombre, getattr(datos.repositorio, nombre))
    monkeypatch.setattr(
        repositorio_alertas, "vigentes", lambda c: [SimpleNamespace(id=5, clave_dedup="CAIDA_DETECTADA:bd:1")]
    )
    monkeypatch.setattr(repositorio_alertas, "resolver_vigente", lambda c, i: datos.resueltas.append(i))
    return datos


def instancia(
    filas_recover: list[tuple[Any, ...]] | None = None,
    filas_pdbs: list[tuple[Any, ...]] | None = None,
    filas_redo: list[tuple[Any, ...]] | None = None,
) -> Callable[[BaseDestino], Any]:
    @contextmanager
    def abrir(base: BaseDestino) -> Iterator[Callable[[str, dict[str, Any]], list[tuple[Any, ...]]]]:
        def consulta(sql: str, parametros: dict[str, Any]) -> list[tuple[Any, ...]]:
            if "v$database" in sql and "corruption" not in sql:
                return [("ARCHIVELOG", "READ WRITE", 3114375768)]
            if "v$recover_file" in sql:
                return filas_recover or []
            if "v$pdbs" in sql:
                return filas_pdbs or []
            if "v$logfile" in sql:
                return filas_redo or []
            return []

        yield consulta

    return abrir


def instancia_de(conexion: ConexionFalsa) -> Callable[[BaseDestino], Any]:
    @contextmanager
    def abrir(base: BaseDestino) -> Iterator[Callable[[str, dict[str, Any]], list[tuple[Any, ...]]]]:
        yield consulta_de(conexion)

    return abrir


DATAFILE_7 = [(7, "C:\\ORADATA\\XE\\USERS01.DBF", "USERS", "CDB$ROOT", "OFFLINE", "FILE NOT FOUND", 9)]


def caida(base: BaseDestino) -> Any:
    @contextmanager
    def abrir() -> Iterator[None]:
        raise RuntimeError("ORA-01034: ORACLE not available")
        yield

    return abrir()


def generado(entorno: Entorno, escenario: str = "datafile", objetivo: str | None = None) -> int:
    procedimiento = recuperacion.plan(entorno.ajustes, "XE", escenario, objetivo, abrir=instancia(DATAFILE_7))
    assert procedimiento.posible, procedimiento.motivo
    assert procedimiento.id is not None
    return procedimiento.id


def aprobado(entorno: Entorno, escenario: str = "datafile", objetivo: str | None = None) -> int:
    procedimiento_id = generado(entorno, escenario, objetivo)
    recuperacion.aprobar(entorno.ajustes, "XE", procedimiento_id, "Ana DBA", True)
    return procedimiento_id


def test_el_plan_queda_registrado_como_borrador_con_su_huella(entorno: Entorno) -> None:
    procedimiento = recuperacion.plan(entorno.ajustes, "XE", "datafile", abrir=instancia(DATAFILE_7))
    assert procedimiento.id == 1
    assert procedimiento.estado is EstadoScript.BORRADOR
    registro = entorno.repositorio.registros[1]
    assert registro.ruta_script == procedimiento.archivo
    assert Path(registro.ruta_script).read_text(encoding="ascii") == procedimiento.script
    assert registro.hash_sha256 == procedimiento.hash_sha256
    otro = recuperacion.plan(entorno.ajustes, "XE", "datafile", abrir=instancia(DATAFILE_7))
    assert otro.archivo != procedimiento.archivo


def test_si_el_repositorio_falla_el_plan_se_genera_igual(entorno: Entorno, monkeypatch: pytest.MonkeyPatch) -> None:
    def falla(*argumentos: Any) -> None:
        raise RepositorioNoDisponible("sin repositorio")

    monkeypatch.setattr(repositorio_recuperaciones, "registrar", falla)
    procedimiento = recuperacion.plan(entorno.ajustes, "XE", "datafile", abrir=instancia(DATAFILE_7))
    assert procedimiento.posible
    assert procedimiento.id is None
    assert procedimiento.archivo is not None
    assert any("no quedó registrado" in aviso for aviso in procedimiento.avisos)


def sugiriendo(*escenarios: Escenario) -> Diagnostico:
    return Diagnostico(bd="XE", generado_en=datetime(2026, 10, 11, 18, 34), sugeridos=list(escenarios))


def test_los_procedimientos_sugeridos_se_generan_y_se_reutilizan_mientras_sean_borrador(entorno: Entorno) -> None:
    sugerido = sugiriendo(Escenario.DATAFILE)
    [primero] = recuperacion.procedimientos_sugeridos(entorno.ajustes, sugerido, instancia(DATAFILE_7))
    assert primero.posible
    assert primero.id == 1
    assert primero.estado is EstadoScript.BORRADOR
    assert primero.archivo is not None
    [repetido] = recuperacion.procedimientos_sugeridos(entorno.ajustes, sugerido, instancia(DATAFILE_7))
    assert repetido.id == 1
    assert repetido.archivo == primero.archivo
    assert repetido.hash_sha256 == primero.hash_sha256
    assert list(entorno.repositorio.registros) == [1]
    assert len(list(Path(primero.archivo).parent.glob("*.rman"))) == 1
    recuperacion.aprobar(entorno.ajustes, "XE", 1, "Ana DBA", True)
    [nuevo] = recuperacion.procedimientos_sugeridos(entorno.ajustes, sugerido, instancia(DATAFILE_7))
    assert nuevo.id == 2
    assert nuevo.archivo != primero.archivo


def test_un_borrador_con_el_archivo_alterado_no_se_reutiliza(entorno: Entorno) -> None:
    sugerido = sugiriendo(Escenario.DATAFILE)
    [primero] = recuperacion.procedimientos_sugeridos(entorno.ajustes, sugerido, instancia(DATAFILE_7))
    assert primero.archivo is not None
    Path(primero.archivo).write_bytes(b"SHUTDOWN ABORT;\n")
    [nuevo] = recuperacion.procedimientos_sugeridos(entorno.ajustes, sugerido, instancia(DATAFILE_7))
    assert nuevo.id == 2
    assert nuevo.archivo != primero.archivo


def test_sin_escenarios_sugeridos_no_se_genera_ni_se_registra_nada(entorno: Entorno) -> None:
    assert recuperacion.procedimientos_sugeridos(entorno.ajustes, sugiriendo(), instancia()) == []
    assert entorno.repositorio.registros == {}


def test_el_plan_manual_sigue_creando_un_borrador_nuevo_cada_vez(entorno: Entorno) -> None:
    primero = recuperacion.plan(entorno.ajustes, "XE", "datafile", abrir=instancia(DATAFILE_7))
    segundo = recuperacion.plan(entorno.ajustes, "XE", "datafile", abrir=instancia(DATAFILE_7))
    assert (primero.id, segundo.id) == (1, 2)


def test_el_repositorio_busca_un_borrador_sin_usar_por_su_huella() -> None:
    huella = "a" * 64
    vacia = ConexionFalsa()
    assert repositorio_recuperaciones.borrador_sin_usar(vacia, 1, Escenario.DATAFILE, huella) is None  # type: ignore[arg-type]
    assert "estado = 'BORRADOR' AND resultado IS NULL" in vacia.sql(0)
    sin_aprobar = (None,) * 7
    fila = (4, 1, "datafile", "7", "C:\\w\\d.rman", "RESTORE DATAFILE 7;\n", huella, "BORRADOR", datetime(2026, 10, 11))
    conexion = ConexionFalsa([(*fila, *sin_aprobar)])
    encontrada = repositorio_recuperaciones.borrador_sin_usar(conexion, 1, Escenario.DATAFILE, huella)  # type: ignore[arg-type]
    assert encontrada is not None
    assert (encontrada.id, encontrada.estado) == (4, EstadoScript.BORRADOR)


def test_aprobar_exige_confirmacion_nombre_y_script_intacto(entorno: Entorno) -> None:
    procedimiento_id = generado(entorno)
    with pytest.raises(OperacionNoPermitida, match="confirmar"):
        recuperacion.aprobar(entorno.ajustes, "XE", procedimiento_id, "Ana", False)
    with pytest.raises(OperacionNoPermitida, match="quién aprueba"):
        recuperacion.aprobar(entorno.ajustes, "XE", procedimiento_id, "  ", True)
    with pytest.raises(RecursoNoEncontrado):
        recuperacion.aprobar(entorno.ajustes, "XE", 99, "Ana", True)
    ruta = Path(entorno.repositorio.registros[procedimiento_id].ruta_script)
    original = ruta.read_bytes()
    ruta.write_bytes(original + b"SHUTDOWN ABORT;\n")
    with pytest.raises(OperacionNoPermitida, match="modificado"):
        recuperacion.aprobar(entorno.ajustes, "XE", procedimiento_id, "Ana", True)
    ruta.write_bytes(original)
    vista = recuperacion.aprobar(entorno.ajustes, "XE", procedimiento_id, "Ana", True)
    assert vista.registro.estado is EstadoScript.APROBADO
    assert vista.registro.aprobado_por == "Ana"
    assert vista.puede_ejecutar
    with pytest.raises(OperacionNoPermitida, match="APROBADO"):
        recuperacion.aprobar(entorno.ajustes, "XE", procedimiento_id, "Ana", True)


def test_ejecutar_aprobado_e_intacto(entorno: Entorno) -> None:
    procedimiento_id = aprobado(entorno)
    with pytest.raises(OperacionNoPermitida, match="confirmar"):
        recuperacion.ejecutar(entorno.ajustes, "XE", procedimiento_id, False, entorno.lanzador())
    vista = recuperacion.ejecutar(entorno.ajustes, "XE", procedimiento_id, True, entorno.lanzador())
    assert vista.registro.resultado is ResultadoRecuperacion.EJECUTADO_OK
    assert "sin errores" in (vista.registro.mensaje or "")
    assert "Recovery Manager complete." in (vista.log_rman or "")
    [invocacion] = entorno.invocaciones
    script = Path(entorno.repositorio.registros[procedimiento_id].ruta_script)
    assert invocacion.script == script
    assert invocacion.log == script.with_suffix(".log")
    assert invocacion.sid == "XE"
    guardado = json.loads(script.with_suffix(".resultado.json").read_text(encoding="utf-8"))
    assert guardado["resultado"] == "EJECUTADO_OK"
    with pytest.raises(OperacionNoPermitida, match="ya se ejecutó"):
        recuperacion.ejecutar(entorno.ajustes, "XE", procedimiento_id, True, entorno.lanzador())
    assert len(entorno.invocaciones) == 1


@pytest.mark.parametrize("ambiente", list(Ambiente))
def test_ejecutar_funciona_en_cualquier_ambiente(entorno: Entorno, ambiente: Ambiente) -> None:
    entorno.base = replace(BD_PRUEBAS, ambiente=ambiente)
    procedimiento_id = aprobado(entorno)
    vista = recuperacion.estado_procedimiento(entorno.ajustes, "XE", procedimiento_id)
    assert vista.ambiente == ambiente.value
    assert vista.puede_ejecutar
    ejecutada = recuperacion.ejecutar(entorno.ajustes, "XE", procedimiento_id, True, entorno.lanzador())
    assert ejecutada.registro.resultado is ResultadoRecuperacion.EJECUTADO_OK
    assert len(entorno.invocaciones) == 1


def test_ejecutar_se_bloquea_sin_aprobar_o_con_script_alterado(entorno: Entorno) -> None:
    borrador = generado(entorno)
    with pytest.raises(OperacionNoPermitida, match="apruébelo"):
        recuperacion.ejecutar(entorno.ajustes, "XE", borrador, True, entorno.lanzador())
    procedimiento_id = aprobado(entorno)
    ruta = Path(entorno.repositorio.registros[procedimiento_id].ruta_script)
    ruta.write_bytes(ruta.read_bytes().replace(b"RESTORE", b"DELETE"))
    with pytest.raises(OperacionNoPermitida, match="huella SHA-256"):
        recuperacion.ejecutar(entorno.ajustes, "XE", procedimiento_id, True, entorno.lanzador())
    ruta.unlink()
    with pytest.raises(OperacionNoPermitida, match="No se encuentra"):
        recuperacion.ejecutar(entorno.ajustes, "XE", procedimiento_id, True, entorno.lanzador())
    assert entorno.invocaciones == []


def test_si_el_script_cambia_despues_de_preparar_no_se_lanza(entorno: Entorno) -> None:
    procedimiento_id = aprobado(entorno)
    recuperacion.preparar_ejecucion(entorno.ajustes, "XE", procedimiento_id, True)
    ruta = Path(entorno.repositorio.registros[procedimiento_id].ruta_script)
    ruta.write_bytes(b"SHUTDOWN ABORT;\n")
    vista = recuperacion.completar_ejecucion(entorno.ajustes, "XE", procedimiento_id, entorno.lanzador())
    assert vista.registro.resultado is ResultadoRecuperacion.NO_LANZADO
    assert entorno.invocaciones == []


def test_errores_de_rman_se_informan(entorno: Entorno) -> None:
    procedimiento_id = aprobado(entorno)
    vista = recuperacion.ejecutar(entorno.ajustes, "XE", procedimiento_id, True, entorno.lanzador(LOG_CON_ERROR, 1))
    assert vista.registro.resultado is ResultadoRecuperacion.EJECUTADO_CON_ERRORES
    assert "ORA-19870" in (vista.registro.mensaje or "")
    assert "código de salida 1" in (vista.registro.mensaje or "")


def test_escenario_que_reinicia_la_instancia_reabre_la_base_y_sus_pdb(entorno: Entorno) -> None:
    procedimiento_id = aprobado(entorno, "datafile-critico", "1")
    comprobaciones: list[BaseDestino] = []

    def comprobar(base: BaseDestino) -> EstadoApertura:
        comprobaciones.append(base)
        return EstadoApertura(True, "La base de datos y sus PDB están abiertas en lectura y escritura.")

    vista = recuperacion.ejecutar(entorno.ajustes, "XE", procedimiento_id, True, entorno.lanzador(), comprobar)
    assert vista.registro.resultado is ResultadoRecuperacion.EJECUTADO_OK
    assert "PDB están abiertas" in (vista.registro.mensaje or "")
    assert len(entorno.invocaciones) == 4
    assert entorno.invocaciones[-1].script.read_text(encoding="ascii") == "ALTER PLUGGABLE DATABASE ALL OPEN;\n"
    assert comprobaciones == [BaseDestino(Path(r"C:\oracle"), "XE")]


def test_el_estado_se_reconcilia_desde_el_resultado_en_disco(entorno: Entorno) -> None:
    procedimiento_id = aprobado(entorno)
    recuperacion.preparar_ejecucion(entorno.ajustes, "XE", procedimiento_id, True)
    en_curso = recuperacion.estado_procedimiento(entorno.ajustes, "XE", procedimiento_id)
    assert en_curso.en_curso
    assert not en_curso.puede_ejecutar
    ruta = Path(entorno.repositorio.registros[procedimiento_id].ruta_script).with_suffix(".resultado.json")
    ruta.write_text(json.dumps({"resultado": "EJECUTADO_OK", "mensaje": "RMAN terminó sin errores."}), encoding="utf-8")
    vista = recuperacion.estado_procedimiento(entorno.ajustes, "XE", procedimiento_id)
    assert vista.registro.resultado is ResultadoRecuperacion.EJECUTADO_OK


def test_diagnostico_con_dano_anota_la_falla_y_notifica(entorno: Entorno) -> None:
    resultado = recuperacion.diagnostico(entorno.ajustes, "XE", instancia(DATAFILE_7), entorno.notificar)
    assert resultado.sugeridos == [Escenario.DATAFILE]
    [condicion] = entorno.notificadas
    assert condicion.codigo_regla == CodigoAlerta.CAIDA_DETECTADA.value
    assert condicion.bd_id == 1
    assert condicion.clave_dedup == "CAIDA_DETECTADA:bd:1"
    assert "7 (USERS)" in condicion.mensaje
    [falla] = recuperacion.fallas_detectadas(entorno.ajustes, "XE")
    assert falla.sugeridos == [Escenario.DATAFILE]
    semana = recuperacion.calendario(
        entorno.ajustes, "XE", falla.detectada_en.astimezone(ZoneInfo(entorno.ajustes.zona_horaria)).date()
    )
    assert [m.falla for m in semana.fallas] == [True]
    assert entorno.resueltas == []


def test_diagnostico_sano_resuelve_la_alerta_y_no_anota(entorno: Entorno) -> None:
    resultado = recuperacion.diagnostico(entorno.ajustes, "XE", instancia([]), entorno.notificar)
    assert resultado.sin_danos
    assert entorno.notificadas == []
    assert entorno.resueltas == [5]
    assert recuperacion.fallas_detectadas(entorno.ajustes, "XE") == []


def test_diagnostico_sano_cierra_las_fallas_anotadas_y_el_calendario_queda_sin_rojo(entorno: Entorno) -> None:
    recuperacion.diagnostico(entorno.ajustes, "XE", instancia(DATAFILE_7), entorno.notificar)
    recuperacion.diagnostico(entorno.ajustes, "XE", instancia(DATAFILE_7), entorno.notificar)
    assert len(recuperacion.fallas_detectadas(entorno.ajustes, "XE")) == 2
    sano = recuperacion.diagnostico(entorno.ajustes, "XE", instancia([]), entorno.notificar)
    assert sano.sin_danos
    assert recuperacion.fallas_detectadas(entorno.ajustes, "XE") == []
    zona = ZoneInfo(entorno.ajustes.zona_horaria)
    semana = recuperacion.calendario(entorno.ajustes, "XE", sano.generado_en.astimezone(zona).date())
    assert semana.fallas == []
    assert not any(marca.falla for fila in semana.filas for celda in fila.celdas for marca in celda)
    recuperacion.diagnostico(entorno.ajustes, "XE", instancia([]), entorno.notificar)
    ruta = recuperacion._carpeta(entorno.ajustes, "XE") / recuperacion.ARCHIVO_FALLAS
    assert len(ruta.read_text(encoding="utf-8").splitlines()) == 3


def test_una_falla_nueva_despues_de_un_diagnostico_sano_vuelve_a_marcarse(entorno: Entorno) -> None:
    recuperacion.diagnostico(entorno.ajustes, "XE", instancia(DATAFILE_7), entorno.notificar)
    recuperacion.diagnostico(entorno.ajustes, "XE", instancia([]), entorno.notificar)
    recuperacion.diagnostico(entorno.ajustes, "XE", instancia(DATAFILE_7), entorno.notificar)
    assert len(recuperacion.fallas_detectadas(entorno.ajustes, "XE")) == 1


def test_sin_conexion_sugiere_controlfile_o_spfile(entorno: Entorno) -> None:
    resultado = recuperacion.diagnostico(entorno.ajustes, "XE", caida, entorno.notificar)
    assert resultado.sin_conexion
    assert "ORA-01034" in resultado.avisos[0]
    assert "control file" in resultado.avisos[1] and "SPFILE" in resultado.avisos[1]
    assert resultado.sugeridos == [Escenario.CONTROLFILE, Escenario.SPFILE]
    assert len(entorno.notificadas) == 1


def test_un_fallo_al_notificar_no_rompe_el_diagnostico(entorno: Entorno) -> None:
    def falla(condiciones: Any, ajustes: Ajustes) -> None:
        raise RuntimeError("SMTP caído")

    resultado = recuperacion.diagnostico(entorno.ajustes, "XE", instancia(DATAFILE_7), falla)
    assert resultado.archivos
    assert any("SMTP caído" in aviso for aviso in resultado.avisos)


def punto(id_: int, completado: datetime, tipo: TipoRespaldo) -> PuntoRecuperacion:
    return PuntoRecuperacion(
        ejecucion_id=id_,
        estrategia="EST001",
        tarea="T1",
        tipo_respaldo=tipo,
        completado_en=completado,
        base_completa=True,
        estado_prueba=EstadoPrueba.OK,
    )


def test_calendario_ubica_respaldos_y_fallas_en_hora_local() -> None:
    puntos = [
        punto(1, datetime(2026, 10, 6, 3, 30), TipoRespaldo.COMPLETO),
        punto(2, datetime(2026, 10, 8, 14, 0), TipoRespaldo.ARCHIVELOG),
        punto(3, datetime(2026, 10, 12, 7, 0), TipoRespaldo.INCREMENTAL_N0),
        punto(4, datetime(2026, 10, 4, 12, 0), TipoRespaldo.INCREMENTAL_N1_DIFERENCIAL),
    ]
    fallas = [FallaDetectada(bd="XE", detectada_en=datetime(2026, 10, 8, 15, 10), resumen="datafile 7")]
    semana = calendario.construir("XE", puntos, fallas, date(2026, 10, 7), "America/Costa_Rica")
    assert (semana.inicio, semana.fin) == (date(2026, 10, 5), date(2026, 10, 11))
    assert (semana.anterior, semana.siguiente) == (date(2026, 9, 28), date(2026, 10, 12))
    assert [d.dia.value for d in semana.dias] == ["LUN", "MAR", "MIE", "JUE", "VIE", "SAB", "DOM"]
    assert len(semana.filas) == 24
    assert [m.simbolo for m in semana.filas[21].celdas[0]] == ["●"]
    assert [m.simbolo for m in semana.filas[8].celdas[3]] == ["·"]
    assert [m.simbolo for m in semana.filas[9].celdas[3]] == ["⚠"]
    assert semana.respaldos == 2
    assert semana.fallas[0].falla
    assert "Falla detectada en 2026-10-08 09:10" in semana.fallas[0].detalle
    assert ("⚠", "Falla detectada") in semana.leyenda


def test_clasificacion_de_la_corrida() -> None:
    correcta = ResultadoRman(codigo_salida=0, agotado=False, duracion_segundos=1)
    assert clasificar(correcta, analizar(LOG_CORRECTO), None)[0] is ResultadoRecuperacion.EJECUTADO_OK
    cerrada = ResultadoApertura(abierta=False, detalle="La base de datos está en modo MOUNTED.")
    resultado, mensaje = clasificar(correcta, analizar(LOG_CORRECTO), cerrada)
    assert resultado is ResultadoRecuperacion.EJECUTADO_CON_ERRORES
    assert "MOUNTED" in mensaje
    incompleta = clasificar(correcta, analizar("connected to target database: XE\n"), None)
    assert incompleta[0] is ResultadoRecuperacion.EJECUTADO_CON_ERRORES
    agotada = ResultadoRman(codigo_salida=None, agotado=True, duracion_segundos=9)
    assert "tiempo máximo" in clasificar(agotada, analizar(""), None)[1]
    sin_lanzar = ResultadoRman(codigo_salida=None, agotado=False, duracion_segundos=0, error_lanzamiento="sin rman")
    assert clasificar(sin_lanzar, analizar(""), None) == (ResultadoRecuperacion.NO_LANZADO, "sin rman")


def test_repositorio_crea_la_tabla_solo_si_falta_y_usa_binds_coherentes() -> None:
    existente = ConexionFalsa([(1,)])
    repositorio_recuperaciones.asegurar_tabla(existente)  # type: ignore[arg-type]
    assert len(existente.ejecutados) == 1
    nueva = ConexionFalsa([(0,)])
    repositorio_recuperaciones.asegurar_tabla(nueva)  # type: ignore[arg-type]
    assert "CREATE TABLE IF NOT EXISTS recuperacion_procedimiento" in nueva.sql(1)
    conexion = ConexionFalsa()
    conexion.siguiente_id = 8
    registro = repositorio_recuperaciones.registrar(
        conexion,  # type: ignore[arg-type]
        1,
        Escenario.SPFILE,
        "ñ" * 300,
        "C:\\w\\spfile.rman",
        "STARTUP;\n",
        "a" * 64,
        datetime(2026, 10, 11),
    )
    assert registro.id == 8
    assert len((registro.objetivo or "").encode("utf-8")) <= repositorio_recuperaciones.LARGO_MAXIMO_OBJETIVO
    assert repositorio_recuperaciones.aprobar(conexion, 8, "Ana")  # type: ignore[arg-type]
    assert repositorio_recuperaciones.marcar_en_curso(conexion, 8, "C:\\w\\spfile.log")  # type: ignore[arg-type]
    repositorio_recuperaciones.registrar_resultado(conexion, 8, ResultadoRecuperacion.EJECUTADO_OK, "x" * 5000)  # type: ignore[arg-type]
    assert len(conexion.ejecutados[-1][1]["mensaje"]) == repositorio_recuperaciones.LARGO_MAXIMO_MENSAJE
    assert repositorio_recuperaciones.obtener(conexion, 8) is None  # type: ignore[arg-type]
    assert "UTC_TIMESTAMP" not in conexion.sql(0)


def test_el_esquema_instala_la_tabla_de_recuperacion_sin_exigirla_en_repositorios_existentes() -> None:
    conexion = ConexionFalsa()
    esquema.instalar(conexion)  # type: ignore[arg-type]
    sentencias = [sql for sql, _ in conexion.ejecutados]
    assert sentencias[0].startswith("DROP TABLE IF EXISTS recuperacion_procedimiento")
    assert sentencias[-1].startswith("CREATE TABLE IF NOT EXISTS recuperacion_procedimiento")
    assert "RECUPERACION_PROCEDIMIENTO" not in esquema.TABLAS
    desinstalada = ConexionFalsa()
    esquema.desinstalar(desinstalada)  # type: ignore[arg-type]
    assert desinstalada.sql(0).startswith("DROP TABLE IF EXISTS recuperacion_procedimiento")


def test_una_falla_inesperada_no_deja_el_procedimiento_en_curso(entorno: Entorno) -> None:
    procedimiento_id = aprobado(entorno)

    def revienta(invocacion: InvocacionRman) -> ResultadoRman:
        raise RuntimeError("se cortó la luz")

    vista = recuperacion.ejecutar(entorno.ajustes, "XE", procedimiento_id, True, revienta)
    assert vista.registro.resultado is ResultadoRecuperacion.EJECUTADO_CON_ERRORES
    assert "se cortó la luz" in (vista.registro.mensaje or "")


DATAFILE_PDB = [(17, r"C:\ORADATA\XE\CLIENTEPDB\A1_01.DBF", "A1", "CLIENTEPDB", "OFFLINE", "FILE NOT FOUND", 9)]
DATAFILE_17_DE_LA_PDB = ObjetoEnLinea(pdb="CLIENTEPDB", datafile=17)


class PonedorFalso:
    def __init__(self, resultado: ResultadoEnLinea) -> None:
        self.resultado = resultado
        self.llamadas: list[ObjetoEnLinea] = []

    def __call__(self, base: BaseDestino, objeto: ObjetoEnLinea) -> ResultadoEnLinea:
        self.llamadas.append(objeto)
        return self.resultado


def aprobado_en_pdb(entorno: Entorno) -> int:
    procedimiento = recuperacion.plan(entorno.ajustes, "XE", "datafile", abrir=instancia(DATAFILE_PDB))
    assert procedimiento.id is not None
    recuperacion.aprobar(entorno.ajustes, "XE", procedimiento.id, "Ana DBA", True)
    return procedimiento.id


def test_un_datafile_de_pdb_se_pone_en_linea_al_terminar_rman(entorno: Entorno) -> None:
    procedimiento_id = aprobado_en_pdb(entorno)
    detalle = "Se puso en línea el tablespace CLIENTEPDB:A1, que había quedado OFFLINE."
    ponedor = PonedorFalso(ResultadoEnLinea(detalle=detalle))
    vista = recuperacion.ejecutar(entorno.ajustes, "XE", procedimiento_id, True, entorno.lanzador(), ponedor=ponedor)
    assert ponedor.llamadas == [DATAFILE_17_DE_LA_PDB]
    assert vista.registro.resultado is ResultadoRecuperacion.EJECUTADO_OK
    assert detalle in (vista.registro.mensaje or "")


def test_si_no_se_puede_poner_en_linea_la_ejecucion_queda_con_errores(entorno: Entorno) -> None:
    procedimiento_id = aprobado_en_pdb(entorno)
    ponedor = PonedorFalso(ResultadoEnLinea(errores=["RMAN terminó, pero no se pudo poner en línea: ORA-01113"]))
    vista = recuperacion.ejecutar(entorno.ajustes, "XE", procedimiento_id, True, entorno.lanzador(), ponedor=ponedor)
    assert vista.registro.resultado is ResultadoRecuperacion.EJECUTADO_CON_ERRORES
    assert "ORA-01113" in (vista.registro.mensaje or "")


def test_si_rman_falla_no_se_intenta_poner_en_linea(entorno: Entorno) -> None:
    procedimiento_id = aprobado_en_pdb(entorno)
    ponedor = PonedorFalso(ResultadoEnLinea())
    vista = recuperacion.ejecutar(
        entorno.ajustes, "XE", procedimiento_id, True, entorno.lanzador(LOG_CON_ERROR, 1), ponedor=ponedor
    )
    assert vista.registro.resultado is ResultadoRecuperacion.EJECUTADO_CON_ERRORES
    assert ponedor.llamadas == []


def test_un_datafile_de_la_raiz_no_necesita_el_paso_en_linea(entorno: Entorno) -> None:
    procedimiento_id = aprobado(entorno)
    ponedor = PonedorFalso(ResultadoEnLinea())
    vista = recuperacion.ejecutar(entorno.ajustes, "XE", procedimiento_id, True, entorno.lanzador(), ponedor=ponedor)
    assert vista.registro.resultado is ResultadoRecuperacion.EJECUTADO_OK
    assert ponedor.llamadas == []


def test_el_plan_de_un_datafile_de_pdb_avisa_que_la_herramienta_lo_pone_en_linea(entorno: Entorno) -> None:
    en_pdb = recuperacion.plan(entorno.ajustes, "XE", "datafile", abrir=instancia(DATAFILE_PDB))
    assert AVISO_EN_LINEA_PDB in en_pdb.avisos
    en_la_raiz = recuperacion.plan(entorno.ajustes, "XE", "datafile", abrir=instancia(DATAFILE_7))
    assert AVISO_EN_LINEA_PDB not in en_la_raiz.avisos


PERFIL_XE = PerfilBD.model_validate_json(
    (Path(__file__).resolve().parents[1] / "fixtures" / "perfiles_bd" / "xe_noarchivelog.json").read_text(
        encoding="utf-8"
    )
)
PDB_CERRADA = [(3, "CLIENTEPDB", "MOUNTED")]
SYSTEM_DE_LA_PDB = [
    (11, r"C:\ORADATA\XE\CLIENTEPDB\SYSTEM01.DBF", "SYSTEM", "CLIENTEPDB", "OFFLINE", "FILE NOT FOUND", 9)
]
REDO_SIN_INVALID = [
    (1, r"C:\R\REDO01A.LOG", None, "INACTIVE", 1, 40),
    (2, r"C:\R\REDO02A.LOG", None, "CURRENT", 1, 41),
    (2, r"C:\R\REDO02B.LOG", None, "CURRENT", 1, 41),
]


def test_con_la_pdb_cerrada_el_plan_no_vuelve_a_cerrarla(entorno: Entorno) -> None:
    resultado = recuperacion.diagnostico(
        entorno.ajustes, "XE", instancia(SYSTEM_DE_LA_PDB, PDB_CERRADA), entorno.notificar
    )
    assert resultado.pdbs == [EstadoPdb(con_id=3, nombre="CLIENTEPDB", modo="MOUNTED")]
    cerrada = recuperacion.plan(entorno.ajustes, "XE", "datafile", abrir=instancia(SYSTEM_DE_LA_PDB, PDB_CERRADA))
    assert cerrada.script == ("RESTORE DATAFILE 11;\nRECOVER DATAFILE 11;\nALTER PLUGGABLE DATABASE CLIENTEPDB OPEN;\n")
    abierta = recuperacion.plan(
        entorno.ajustes, "XE", "datafile", abrir=instancia(SYSTEM_DE_LA_PDB, [(3, "CLIENTEPDB", "READ WRITE")])
    )
    assert (abierta.script or "").startswith("ALTER PLUGGABLE DATABASE CLIENTEPDB CLOSE IMMEDIATE;\n")


def test_si_no_se_puede_leer_v_pdbs_el_plan_conserva_el_cierre_de_la_pdb(entorno: Entorno) -> None:
    conexion = ConexionConFallaPorTexto(
        "v$pdbs",
        oracledb.DatabaseError("ORA-00942: table or view does not exist"),
        [
            [("ARCHIVELOG", "MOUNTED", 3114375768)],
            [(11, r"C:\ORADATA\XE\CLIENTEPDB\SYSTEM01.DBF", "SYSTEM", "CLIENTEPDB", "OFFLINE", "FILE NOT FOUND", 9)],
            [],
            [],
            [],
        ],
    )
    procedimiento = recuperacion.plan(entorno.ajustes, "XE", "datafile", abrir=instancia_de(conexion))
    assert (procedimiento.script or "").startswith("ALTER PLUGGABLE DATABASE CLIENTEPDB CLOSE IMMEDIATE;\n")
    assert any("No se pudo consultar V$PDBS" in aviso for aviso in procedimiento.avisos)


def test_un_datafile_de_pdb_cerrada_tambien_se_pone_en_linea_al_terminar_rman(entorno: Entorno) -> None:
    procedimiento = recuperacion.plan(entorno.ajustes, "XE", "datafile", abrir=instancia(DATAFILE_PDB, PDB_CERRADA))
    assert procedimiento.id is not None
    assert "CLOSE IMMEDIATE" not in (procedimiento.script or "")
    recuperacion.aprobar(entorno.ajustes, "XE", procedimiento.id, "Ana DBA", True)
    ponedor = PonedorFalso(ResultadoEnLinea(detalle="Se puso en línea el tablespace CLIENTEPDB:A1."))
    vista = recuperacion.ejecutar(entorno.ajustes, "XE", procedimiento.id, True, entorno.lanzador(), ponedor=ponedor)
    assert ponedor.llamadas == [DATAFILE_17_DE_LA_PDB]
    assert vista.registro.resultado is ResultadoRecuperacion.EJECUTADO_OK


def test_un_miembro_de_redo_ausente_en_disco_se_diagnostica_y_se_planifica(entorno: Entorno) -> None:
    def existe(ruta: str) -> bool:
        return not ruta.endswith("REDO02B.LOG")

    abrir = instancia(filas_redo=REDO_SIN_INVALID)
    resultado = recuperacion.diagnostico(entorno.ajustes, "XE", abrir, entorno.notificar, existe=existe)
    assert resultado.sugeridos == [Escenario.MIEMBRO_REDOLOG]
    assert [(m.grupo, m.estado_miembro, m.grupo_perdido) for m in resultado.miembros_redo] == [(2, "FALTANTE", False)]
    assert [(g.grupo, g.estado) for g in resultado.grupos_redo] == [(1, "INACTIVE"), (2, "CURRENT")]
    assert not resultado.sin_danos
    procedimiento = recuperacion.plan(entorno.ajustes, "XE", "miembro-redolog", abrir=abrir, existe=existe)
    assert procedimiento.script == (
        "ALTER SYSTEM SWITCH LOGFILE;\nALTER SYSTEM CHECKPOINT;\n"
        "ALTER DATABASE DROP LOGFILE MEMBER 'C:\\R\\REDO02B.LOG';\n"
        "ALTER DATABASE ADD LOGFILE MEMBER 'C:\\R\\REDO02B.LOG' REUSE TO GROUP 2;\n"
    )


def test_un_grupo_current_sin_ningun_miembro_en_disco_sugiere_el_grupo_actual(entorno: Entorno) -> None:
    abrir = instancia(filas_redo=REDO_SIN_INVALID)
    resultado = recuperacion.diagnostico(
        entorno.ajustes, "XE", abrir, entorno.notificar, existe=lambda ruta: "REDO01" in ruta
    )
    assert resultado.sugeridos == [Escenario.GRUPO_REDOLOG_ACTUAL]
    procedimiento = recuperacion.plan(
        entorno.ajustes, "XE", "grupo-redolog-actual", abrir=abrir, existe=lambda ruta: "REDO01" in ruta
    )
    assert "SET UNTIL SEQUENCE 41 THREAD 1;" in (procedimiento.script or "")
    assert any("CLEAR UNARCHIVED LOGFILE GROUP 2;" in aviso for aviso in procedimiento.avisos)
    assert any("RENAME FILE" in aviso for aviso in procedimiento.avisos)


def test_si_v_containers_falla_el_diagnostico_sigue_viendo_los_archivos_y_no_sugiere_controlfile(
    entorno: Entorno,
) -> None:
    conexion = ConexionConFallaPorTexto(
        "v$containers",
        oracledb.DatabaseError("ORA-01219: database or pluggable database not open"),
        [
            [("ARCHIVELOG", "MOUNTED", 3114375768)],
            PDB_CERRADA,
            [(17, r"C:\ORADATA\XE\CLIENTEPDB\A1_01.DBF", "A1", 3, "OFFLINE", "FILE NOT FOUND", 9)],
            [],
            [],
            [],
        ],
    )
    resultado = recuperacion.diagnostico(entorno.ajustes, "XE", instancia_de(conexion), entorno.notificar)
    assert not resultado.sin_conexion and not resultado.fallo_consulta
    assert [(a.file_id, a.contenedor) for a in resultado.archivos] == [(17, "CLIENTEPDB")]
    assert resultado.sugeridos == [Escenario.DATAFILE]
    assert Escenario.CONTROLFILE not in resultado.sugeridos
    assert any("V$CONTAINERS no respondió" in aviso for aviso in resultado.avisos)
    assert all("v$containers" not in sql.lower() for sql, _ in conexion.ejecutados)
    assert len(entorno.notificadas) == 1


@pytest.mark.parametrize(
    "texto",
    ["ORA-01034: ORACLE not available", "ORA-12560: TNS:protocol adapter error", "ORA-01507: database not mounted"],
)
def test_solo_la_instancia_caida_o_sin_montar_cuenta_como_sin_conexion(entorno: Entorno, texto: str) -> None:
    conexion = ConexionConFallaPorTexto("v$database", oracledb.DatabaseError(texto))
    resultado = recuperacion.diagnostico(entorno.ajustes, "XE", instancia_de(conexion), entorno.notificar)
    assert resultado.sin_conexion and not resultado.fallo_consulta
    assert resultado.sugeridos == [Escenario.CONTROLFILE, Escenario.SPFILE]
    assert texto.split(":")[0] in resultado.avisos[0]


def test_otro_error_de_consulta_no_se_toma_por_instancia_caida_ni_por_base_sana(entorno: Entorno) -> None:
    recuperacion.diagnostico(entorno.ajustes, "XE", instancia(DATAFILE_7), entorno.notificar)
    previas = len(entorno.notificadas)
    conexion = ConexionConFallaPorTexto(
        "v$recover_file", oracledb.DatabaseError("ORA-00942: table or view does not exist")
    )
    resultado = recuperacion.diagnostico(entorno.ajustes, "XE", instancia_de(conexion), entorno.notificar)
    assert resultado.fallo_consulta and not resultado.sin_conexion
    assert resultado.sugeridos == []
    assert not resultado.sin_danos
    assert "ORA-00942" in resultado.avisos[0]
    assert "controlfile" in resultado.avisos[1]
    assert len(entorno.notificadas) == previas
    assert len(recuperacion.fallas_detectadas(entorno.ajustes, "XE")) == 1
    assert entorno.resueltas == []


def con_perfil_y_destino(entorno: Entorno, monkeypatch: pytest.MonkeyPatch, destino: str | None) -> None:
    monkeypatch.setattr(repositorio_bases_datos, "ultimo_perfil", lambda c, i: PERFIL_XE)
    entorno.ajustes = entorno.ajustes.model_copy(update={"destino_defecto": None if destino is None else Path(destino)})


def test_con_la_instancia_caida_la_perdida_total_tambien_restaura_el_control_file(
    entorno: Entorno, monkeypatch: pytest.MonkeyPatch
) -> None:
    con_perfil_y_destino(entorno, monkeypatch, "C:\\backups\\XE")
    procedimiento = recuperacion.plan(entorno.ajustes, "XE", "total-noarchivelog", abrir=caida)
    assert procedimiento.posible
    assert (procedimiento.script or "").startswith(f"STARTUP FORCE NOMOUNT;\nSET DBID {PERFIL_XE.dbid};\n")
    assert "RESTORE CONTROLFILE FROM AUTOBACKUP;" in (procedimiento.script or "")
    assert (procedimiento.script or "").endswith("RECOVER DATABASE NOREDO;\nALTER DATABASE OPEN RESETLOGS;\n")


def test_con_la_instancia_sana_la_perdida_total_solo_pide_el_control_file_si_se_indica(
    entorno: Entorno, monkeypatch: pytest.MonkeyPatch
) -> None:
    con_perfil_y_destino(entorno, monkeypatch, "C:\\backups\\XE")
    normal = recuperacion.plan(entorno.ajustes, "XE", "total-noarchivelog", abrir=instancia())
    assert (normal.script or "").startswith("STARTUP FORCE MOUNT;\nRESTORE DATABASE;")
    forzado = recuperacion.plan(entorno.ajustes, "XE", "total-noarchivelog", "controlfile", abrir=instancia())
    assert (forzado.script or "").startswith("STARTUP FORCE NOMOUNT;")


def test_con_la_instancia_caida_y_sin_destino_de_autobackup_el_plan_total_no_se_genera(
    entorno: Entorno, monkeypatch: pytest.MonkeyPatch
) -> None:
    con_perfil_y_destino(entorno, monkeypatch, None)
    procedimiento = recuperacion.plan(entorno.ajustes, "XE", "total-noarchivelog", abrir=caida)
    assert not procedimiento.posible
    assert procedimiento.script is None and procedimiento.id is None
    assert "autobackup" in procedimiento.motivo


def test_sin_perfil_ni_dbid_la_perdida_total_con_la_instancia_caida_se_explica(entorno: Entorno) -> None:
    procedimiento = recuperacion.plan(entorno.ajustes, "XE", "total-noarchivelog", abrir=caida)
    assert not procedimiento.posible
    assert "DBID" in procedimiento.motivo


def test_los_escenarios_con_resetlogs_recuerdan_el_respaldo_completo() -> None:
    correcta = ResultadoRman(codigo_salida=0, agotado=False, duracion_segundos=1)
    analizado = analizar(LOG_CORRECTO)
    esperados = {
        Escenario.CONTROLFILE,
        Escenario.GRUPO_REDOLOG_ACTUAL,
        Escenario.TOTAL_NOARCHIVELOG,
        Escenario.PUNTO_EN_TIEMPO,
    }
    assert esperados == ESCENARIOS_CON_RESETLOGS
    for escenario in Escenario:
        resultado, mensaje = clasificar(correcta, analizado, None, None, escenario)
        assert resultado is ResultadoRecuperacion.EJECUTADO_OK
        assert (RECORDATORIO_RESETLOGS in mensaje) is (escenario in ESCENARIOS_CON_RESETLOGS), escenario
        assert (RECORDATORIO_ARCHIVELOG in mensaje) is (escenario is Escenario.TOTAL_NOARCHIVELOG), escenario
    assert RECORDATORIO_RESETLOGS == "Se abrió con RESETLOGS: haga un respaldo completo ahora."
    sin_escenario = clasificar(correcta, analizado, None)[1]
    assert RECORDATORIO_RESETLOGS not in sin_escenario


def test_el_recordatorio_no_aparece_si_la_recuperacion_falla() -> None:
    correcta = ResultadoRman(codigo_salida=0, agotado=False, duracion_segundos=1)
    resultado, mensaje = clasificar(correcta, analizar(LOG_CON_ERROR), None, None, Escenario.CONTROLFILE)
    assert resultado is ResultadoRecuperacion.EJECUTADO_CON_ERRORES
    assert RECORDATORIO_RESETLOGS not in mensaje
    cerrada = ResultadoApertura(abierta=False, detalle="La base de datos está en modo MOUNTED.")
    _, sin_abrir = clasificar(correcta, analizar(LOG_CORRECTO), cerrada, None, Escenario.TOTAL_NOARCHIVELOG)
    assert RECORDATORIO_RESETLOGS not in sin_abrir


def test_la_ejecucion_de_la_perdida_total_recuerda_el_respaldo_y_volver_a_archivelog(
    entorno: Entorno, monkeypatch: pytest.MonkeyPatch
) -> None:
    con_perfil_y_destino(entorno, monkeypatch, "C:\\backups\\XE")
    procedimiento = recuperacion.plan(entorno.ajustes, "XE", "total-noarchivelog", abrir=caida)
    assert procedimiento.id is not None
    recuperacion.aprobar(entorno.ajustes, "XE", procedimiento.id, "Ana DBA", True)

    def comprobar(base: BaseDestino) -> EstadoApertura:
        return EstadoApertura(True, "La base de datos y sus PDB están abiertas en lectura y escritura.")

    vista = recuperacion.ejecutar(entorno.ajustes, "XE", procedimiento.id, True, entorno.lanzador(), comprobar)
    assert vista.registro.resultado is ResultadoRecuperacion.EJECUTADO_OK
    mensaje = vista.registro.mensaje or ""
    assert RECORDATORIO_RESETLOGS in mensaje and RECORDATORIO_ARCHIVELOG in mensaje
