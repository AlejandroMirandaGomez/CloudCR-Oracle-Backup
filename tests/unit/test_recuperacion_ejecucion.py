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
from cloudcr_backup.domain.recuperacion import (
    Escenario,
    FallaDetectada,
    PuntoRecuperacion,
    RegistroRecuperacion,
    ResultadoRecuperacion,
)
from cloudcr_backup.execution.apertura import ResultadoApertura
from cloudcr_backup.execution.destino import BaseDestino, EstadoApertura
from cloudcr_backup.execution.parser import analizar
from cloudcr_backup.execution.runner import InvocacionRman, ResultadoRman
from cloudcr_backup.recovery import calendario
from cloudcr_backup.recovery.ejecucion import clasificar
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
from tests.unit.oracle_falso import ConexionFalsa

BD_PRUEBAS = BaseDatosRegistrada(id=1, nombre="XE", oracle_home=r"C:\oracle", ambiente=Ambiente.PRUEBAS, activa=True)
AVISO_NO_PRUEBAS = recuperacion.AVISO_AMBIENTE
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
    for nombre in ("registrar", "obtener", "aprobar", "marcar_en_curso", "registrar_resultado"):
        monkeypatch.setattr(repositorio_recuperaciones, nombre, getattr(datos.repositorio, nombre))
    monkeypatch.setattr(
        repositorio_alertas, "vigentes", lambda c: [SimpleNamespace(id=5, clave_dedup="CAIDA_DETECTADA:bd:1")]
    )
    monkeypatch.setattr(repositorio_alertas, "resolver_vigente", lambda c, i: datos.resueltas.append(i))
    return datos


def instancia(filas_recover: list[tuple[Any, ...]] | None = None) -> Callable[[BaseDestino], Any]:
    @contextmanager
    def abrir(base: BaseDestino) -> Iterator[Callable[[str, dict[str, Any]], list[tuple[Any, ...]]]]:
        def consulta(sql: str, parametros: dict[str, Any]) -> list[tuple[Any, ...]]:
            if "v$database" in sql and "corruption" not in sql:
                return [("ARCHIVELOG", "READ WRITE", 3114375768)]
            if "v$recover_file" in sql:
                return filas_recover or []
            return []

        yield consulta

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
    assert AVISO_NO_PRUEBAS not in procedimiento.avisos
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


def test_ejecutar_en_pruebas_aprobado_e_intacto(entorno: Entorno) -> None:
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


def test_ejecutar_se_bloquea_fuera_de_pruebas(entorno: Entorno) -> None:
    entorno.base = replace(BD_PRUEBAS, ambiente=Ambiente.DESARROLLO)
    procedimiento = recuperacion.plan(entorno.ajustes, "XE", "datafile", abrir=instancia(DATAFILE_7))
    assert AVISO_NO_PRUEBAS in procedimiento.avisos
    assert procedimiento.id is not None
    vista = recuperacion.aprobar(entorno.ajustes, "XE", procedimiento.id, "Ana", True)
    assert not vista.puede_ejecutar
    with pytest.raises(OperacionNoPermitida, match="PRUEBAS"):
        recuperacion.ejecutar(entorno.ajustes, "XE", procedimiento.id, True, entorno.lanzador())
    assert entorno.invocaciones == []


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
    assert "CREATE TABLE recuperacion_procedimiento" in nueva.sql(1)
    carrera = ConexionFalsa([(0,)])
    carrera.errores.extend([None, oracledb.DatabaseError(SimpleNamespace(code=955))])
    repositorio_recuperaciones.asegurar_tabla(carrera)  # type: ignore[arg-type]
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
    assert "SYSTIMESTAMP" not in conexion.sql(0)


def test_el_esquema_instala_la_tabla_de_recuperacion_sin_exigirla_en_repositorios_existentes() -> None:
    conexion = ConexionFalsa()
    esquema.instalar(conexion)  # type: ignore[arg-type]
    sentencias = [sql for sql, _ in conexion.ejecutados]
    assert sentencias[0].startswith("DROP TABLE RECUPERACION_PROCEDIMIENTO")
    assert sentencias[-1].startswith("CREATE TABLE recuperacion_procedimiento")
    assert "RECUPERACION_PROCEDIMIENTO" not in esquema.TABLAS
    desinstalada = ConexionFalsa()
    esquema.desinstalar(desinstalada)  # type: ignore[arg-type]
    assert desinstalada.sql(0).startswith("DROP TABLE RECUPERACION_PROCEDIMIENTO")


def test_una_falla_inesperada_no_deja_el_procedimiento_en_curso(entorno: Entorno) -> None:
    procedimiento_id = aprobado(entorno)

    def revienta(invocacion: InvocacionRman) -> ResultadoRman:
        raise RuntimeError("se cortó la luz")

    vista = recuperacion.ejecutar(entorno.ajustes, "XE", procedimiento_id, True, revienta)
    assert vista.registro.resultado is ResultadoRecuperacion.EJECUTADO_CON_ERRORES
    assert "se cortó la luz" in (vista.registro.mensaje or "")
