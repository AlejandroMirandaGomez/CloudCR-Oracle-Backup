from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.domain.enums import Compresion, EstadoScript, LogMode
from cloudcr_backup.domain.errores import FiltroInvalido, OperacionNoPermitida, RecursoNoEncontrado
from cloudcr_backup.domain.estrategia import Estrategia
from cloudcr_backup.domain.perfil_bd import PerfilBD
from cloudcr_backup.execution.destino import BaseDestino
from cloudcr_backup.execution.pipeline import EstadoCarpeta
from cloudcr_backup.repository import bases_datos as repositorio_bases_datos
from cloudcr_backup.repository import conexion as repositorio_conexion
from cloudcr_backup.repository import ejecuciones as repositorio_ejecuciones
from cloudcr_backup.repository import estrategias as repositorio_estrategias
from cloudcr_backup.repository import parametros as repositorio_parametros
from cloudcr_backup.repository import piezas as repositorio_piezas
from cloudcr_backup.repository import scripts as repositorio_scripts
from cloudcr_backup.repository.bases_datos import Ambiente, BaseDatosRegistrada
from cloudcr_backup.repository.ejecuciones import Ejecucion
from cloudcr_backup.repository.piezas import PiezaRegistrada
from cloudcr_backup.repository.scripts import ScriptRman
from cloudcr_backup.rman.aprobacion import calcular_hash
from cloudcr_backup.services import ejecucion, recuperacion, retencion, scripts
from cloudcr_backup.strategy.yaml_io import cargar_estrategia_yaml
from tests.unit.oracle_falso import ConexionFalsa

RAIZ = Path(__file__).resolve().parents[2]
PERFIL = RAIZ / "tests" / "fixtures" / "perfiles_bd" / "xe_noarchivelog.json"
BD = BaseDatosRegistrada(id=1, nombre="XE", oracle_home=r"C:\oracle", ambiente=Ambiente.DESARROLLO, activa=True)


def cargar(codigo: str, id_: int) -> Estrategia:
    return cargar_estrategia_yaml(RAIZ / "config" / "estrategias" / f"{codigo.lower()}.yaml").model_copy(
        update={"id": id_}
    )


class Almacen:
    def __init__(self, log_mode: LogMode) -> None:
        self.perfil = PerfilBD.model_validate_json(PERFIL.read_text(encoding="utf-8")).model_copy(
            update={"log_mode": log_mode}
        )
        self.estrategias = {"EST001": cargar("EST001", 1), "EST002": cargar("EST002", 2), "EST004": cargar("EST004", 4)}
        self.scripts: list[ScriptRman] = []
        self.perfiles_guardados = 0
        self.reclamadas: list[datetime] = []
        self.piezas: list[PiezaRegistrada] = []
        self.obsoletas: list[int] = []

    def tarea_id(self, estrategia_id: int, codigo: str) -> int:
        return estrategia_id * 10 + int(codigo[1:])

    def guardar_borrador(self, c: Any, tarea_id: int, contenido: str) -> ScriptRman:
        version = 1 + max((s.version for s in self.scripts if s.tarea_id == tarea_id), default=0)
        nuevo = ScriptRman(
            len(self.scripts) + 1, tarea_id, version, contenido, calcular_hash(contenido), EstadoScript.BORRADOR
        )
        self.scripts.append(nuevo)
        return nuevo

    def cambiar(self, script_id: int, **cambios: Any) -> None:
        from dataclasses import replace

        self.scripts = [replace(s, **cambios) if s.id == script_id else s for s in self.scripts]


@pytest.fixture
def almacen(monkeypatch: pytest.MonkeyPatch) -> Almacen:
    datos = Almacen(LogMode.ARCHIVELOG)
    monkeypatch.setattr(repositorio_conexion, "abrir_repositorio", lambda a: ConexionFalsa())
    monkeypatch.setattr("cloudcr_backup.services.cliente_oracle.preparar_cliente_oracle", lambda: None)
    for modulo in (scripts, ejecucion, retencion, recuperacion):
        monkeypatch.setattr(modulo, "preparar_cliente_oracle", lambda: None)
    monkeypatch.setattr(repositorio_bases_datos, "obtener", lambda c, n: BD if n == "XE" else None)
    monkeypatch.setattr(repositorio_bases_datos, "listar", lambda c: [BD])
    monkeypatch.setattr(repositorio_bases_datos, "ultimo_perfil", lambda c, i: datos.perfil)

    def guardar_perfil(c: Any, i: int, p: PerfilBD) -> None:
        datos.perfiles_guardados += 1

    monkeypatch.setattr(repositorio_bases_datos, "guardar_perfil", guardar_perfil)
    monkeypatch.setattr(repositorio_bases_datos, "log_mode_al_crear_script", lambda c, b, s: datos.perfil.log_mode)
    monkeypatch.setattr(repositorio_estrategias, "obtener", lambda c, b, codigo: datos.estrategias.get(codigo))
    monkeypatch.setattr(repositorio_estrategias, "listar", lambda c, b: list(datos.estrategias.values()))
    monkeypatch.setattr(
        repositorio_estrategias,
        "ids_de_tareas",
        lambda c, e: {
            t.codigo: datos.tarea_id(e, t.codigo)
            for est in datos.estrategias.values()
            if est.id == e
            for t in est.tareas
        },
    )
    monkeypatch.setattr(repositorio_parametros, "listar", lambda c: {})
    monkeypatch.setattr(repositorio_scripts, "guardar_borrador", datos.guardar_borrador)
    monkeypatch.setattr(
        repositorio_scripts,
        "listar",
        lambda c, t: sorted((s for s in datos.scripts if s.tarea_id == t), key=lambda s: -s.version),
    )
    monkeypatch.setattr(
        repositorio_scripts, "obtener", lambda c, i: next((s for s in datos.scripts if s.id == i), None)
    )
    monkeypatch.setattr(
        repositorio_scripts,
        "obtener_vigente",
        lambda c, t: next((s for s in datos.scripts if s.tarea_id == t and s.estado is EstadoScript.APROBADO), None),
    )
    monkeypatch.setattr(
        repositorio_scripts, "marcar_obsoleto", lambda c, i: datos.cambiar(i, estado=EstadoScript.OBSOLETO)
    )
    monkeypatch.setattr(
        repositorio_scripts,
        "aprobar",
        lambda c, i, por, acepto=False: datos.cambiar(
            i, estado=EstadoScript.APROBADO, aprobado_por=por, acepto_caida=acepto
        ),
    )
    monkeypatch.setattr(
        repositorio_scripts,
        "rechazar",
        lambda c, i, motivo: datos.cambiar(i, estado=EstadoScript.RECHAZADO, motivo_rechazo=motivo),
    )

    def reclamar(c: Any, tarea_id: int, momento: datetime) -> Ejecucion:
        datos.reclamadas.append(momento)
        return Ejecucion(77, tarea_id, 1, repositorio_ejecuciones.EstadoEjecucion.PROGRAMADA, momento, None, None)

    monkeypatch.setattr(repositorio_ejecuciones, "reclamar", reclamar)
    monkeypatch.setattr(repositorio_ejecuciones, "historial_detallado", lambda c, f, limite=200, d=0: [])
    monkeypatch.setattr(repositorio_piezas, "de_base", lambda c, b: datos.piezas)
    return datos


def perfil_vivo(almacen: Almacen):  # type: ignore[no-untyped-def]
    def obtener(base: BaseDestino) -> PerfilBD:
        return almacen.perfil

    return obtener


def ajustes(tmp_path: Path) -> Ajustes:
    return Ajustes(work_dir=tmp_path, repositorio_dsn="x")


def test_generar_crea_borrador_archivo_y_guarda_el_perfil(tmp_path: Path, almacen: Almacen) -> None:
    vistas = scripts.generar(ajustes(tmp_path), "XE", "EST001", obtener_perfil=perfil_vivo(almacen))
    assert len(vistas) == 1
    vista = vistas[0]
    assert vista.nueva
    assert vista.estado is EstadoScript.BORRADOR
    assert vista.version == 1
    assert vista.archivo_intacto is True
    assert Path(vista.archivo or "").read_bytes() == vista.contenido.encode("ascii")
    assert almacen.perfiles_guardados == 1
    assert any(f.campo == "Tipo de respaldo" for f in vista.explicacion)


def test_generar_dos_veces_sin_cambios_no_crea_otra_version(tmp_path: Path, almacen: Almacen) -> None:
    scripts.generar(ajustes(tmp_path), "XE", "EST001", obtener_perfil=perfil_vivo(almacen))
    segunda = scripts.generar(ajustes(tmp_path), "XE", "EST001", obtener_perfil=perfil_vivo(almacen))[0]
    assert not segunda.nueva
    assert len(almacen.scripts) == 1


def test_generar_todas_las_tareas_de_una_estrategia(tmp_path: Path, almacen: Almacen) -> None:
    vistas = scripts.generar(ajustes(tmp_path), None, "EST004", obtener_perfil=perfil_vivo(almacen))
    assert [v.tarea for v in vistas] == ["T1", "T2", "T3"]


def test_si_la_base_no_responde_usa_el_ultimo_perfil(tmp_path: Path, almacen: Almacen) -> None:
    def caida(base: BaseDestino) -> PerfilBD:
        raise RuntimeError("ORA-01034")

    vista = scripts.generar(ajustes(tmp_path), "XE", "EST001", obtener_perfil=caida)[0]
    assert any("último perfil" in aviso for aviso in vista.avisos)


def test_aprobar_consistente_sin_aceptar_la_caida_falla_con_mensaje_claro(tmp_path: Path, almacen: Almacen) -> None:
    almacen.perfil = almacen.perfil.model_copy(update={"log_mode": LogMode.NOARCHIVELOG})
    scripts.generar(ajustes(tmp_path), "XE", "EST002", obtener_perfil=perfil_vivo(almacen))
    with pytest.raises(OperacionNoPermitida) as error:
        scripts.aprobar(ajustes(tmp_path), "XE", "EST002", "T1", "juan")
    assert "SHUTDOWN IMMEDIATE" in error.value.mensaje
    assert "--acepto-caida" in (error.value.sugerencia or "")
    aprobada = scripts.aprobar(ajustes(tmp_path), "XE", "EST002", "T1", "juan", acepto_caida=True)
    assert aprobada.estado is EstadoScript.APROBADO
    assert aprobada.acepto_caida


def test_no_se_aprueba_un_archivo_modificado(tmp_path: Path, almacen: Almacen) -> None:
    vista = scripts.generar(ajustes(tmp_path), "XE", "EST001", obtener_perfil=perfil_vivo(almacen))[0]
    Path(vista.archivo or "").write_bytes(b"RUN { BACKUP DATABASE; }\n")
    with pytest.raises(OperacionNoPermitida, match="modificado"):
        scripts.aprobar(ajustes(tmp_path), "XE", "EST001", "T1", "juan")


def test_aprobar_con_errores_de_validacion_falla(tmp_path: Path, almacen: Almacen) -> None:
    scripts.generar(ajustes(tmp_path), "XE", "EST001", obtener_perfil=perfil_vivo(almacen))
    almacen.perfil = almacen.perfil.model_copy(update={"log_mode": LogMode.NOARCHIVELOG})
    with pytest.raises(OperacionNoPermitida, match="ARCH_005"):
        scripts.aprobar(ajustes(tmp_path), "XE", "EST001", "T1", "juan")


def test_aprobar_una_version_nueva_deja_obsoleta_la_anterior(tmp_path: Path, almacen: Almacen) -> None:
    configuracion = ajustes(tmp_path)
    scripts.generar(configuracion, "XE", "EST004", "T2", obtener_perfil=perfil_vivo(almacen))
    scripts.aprobar(configuracion, "XE", "EST004", "T2", "juan")
    tarea = almacen.estrategias["EST004"].tareas[1]
    opciones = tarea.como.opciones.model_copy(update={"compresion": Compresion.BASIC})
    nueva = tarea.model_copy(update={"como": tarea.como.model_copy(update={"opciones": opciones})})
    almacen.estrategias["EST004"] = almacen.estrategias["EST004"].model_copy(
        update={"tareas": [almacen.estrategias["EST004"].tareas[0], nueva, almacen.estrategias["EST004"].tareas[2]]}
    )
    segunda = scripts.generar(configuracion, "XE", "EST004", "T2", obtener_perfil=perfil_vivo(almacen))[0]
    assert segunda.version == 2
    scripts.aprobar(configuracion, "XE", "EST004", "T2", "juan")
    estados = {s.version: s.estado for s in almacen.scripts}
    assert estados == {1: EstadoScript.OBSOLETO, 2: EstadoScript.APROBADO}


def test_rechazar_y_ver(tmp_path: Path, almacen: Almacen) -> None:
    scripts.generar(ajustes(tmp_path), "XE", "EST001", obtener_perfil=perfil_vivo(almacen))
    with pytest.raises(OperacionNoPermitida):
        scripts.rechazar(ajustes(tmp_path), "XE", "EST001", "T1", " ")
    rechazado = scripts.rechazar(ajustes(tmp_path), "XE", "EST001", "T1", "falta el SPFILE")
    assert rechazado.estado is EstadoScript.RECHAZADO
    assert scripts.ver(ajustes(tmp_path), "XE", "EST001", "T1").motivo_rechazo == "falta el SPFILE"
    with pytest.raises(RecursoNoEncontrado):
        scripts.ver(ajustes(tmp_path), "XE", "EST001", "T1", version=9)
    assert len(scripts.listar(ajustes(tmp_path), "XE", "EST001")) == 1


def test_estrategia_o_tarea_inexistente(tmp_path: Path, almacen: Almacen) -> None:
    with pytest.raises(RecursoNoEncontrado):
        scripts.ver(ajustes(tmp_path), "XE", "EST999", "T1")
    with pytest.raises(RecursoNoEncontrado):
        scripts.ver(ajustes(tmp_path), "XE", "EST001", "T9")
    with pytest.raises(RecursoNoEncontrado):
        scripts.ver(ajustes(tmp_path), "ORCL", "EST001", "T1")


def test_ejecutar_exige_script_aprobado(tmp_path: Path, almacen: Almacen) -> None:
    with pytest.raises(OperacionNoPermitida, match="APROBADO"):
        ejecucion.programar_ahora(ajustes(tmp_path), "XE", "EST004", "T2")
    scripts.generar(ajustes(tmp_path), "XE", "EST004", "T2", obtener_perfil=perfil_vivo(almacen))
    scripts.aprobar(ajustes(tmp_path), "XE", "EST004", "T2", "juan")
    assert ejecucion.programar_ahora(ajustes(tmp_path), "XE", "EST004", "T2") == 77
    assert almacen.reclamadas[0].microsecond == 0


def test_simular_muestra_comando_y_problemas(tmp_path: Path, almacen: Almacen, monkeypatch: pytest.MonkeyPatch) -> None:
    configuracion = ajustes(tmp_path)
    scripts.generar(configuracion, "XE", "EST004", "T2", obtener_perfil=perfil_vivo(almacen))
    vista = scripts.aprobar(configuracion, "XE", "EST004", "T2", "juan")
    monkeypatch.setattr(ejecucion, "perfil_actual", perfil_vivo(almacen))
    monkeypatch.setattr(ejecucion, "medir_carpeta", lambda ruta: EstadoCarpeta(False, None))
    simulacion = ejecucion.simular(configuracion, "XE", "EST004", "T2")
    assert "cmdfile=EST004.XE.T2.RMAN" in simulacion.comando
    assert "using EST004_T2_" in simulacion.comando
    assert any("DESTINO_NO_ESCRIBIBLE" in p for p in simulacion.problemas)
    Path(vista.archivo or "").write_bytes(b"alterado")
    assert any("SCRIPT_ALTERADO" in p for p in ejecucion.simular(configuracion, "XE", "EST004", "T2").problemas)


def test_escenario_invalido() -> None:
    with pytest.raises(FiltroInvalido):
        recuperacion.escenario_de("todo")
    assert recuperacion.escenario_de(" DataFile ").value == "datafile"


def consulta_danada():  # type: ignore[no-untyped-def]
    from contextlib import contextmanager

    @contextmanager
    def abrir(base: BaseDestino):  # type: ignore[no-untyped-def]
        def consulta(sql: str, parametros: dict[str, Any]) -> list[tuple[Any, ...]]:
            if "v$database" in sql:
                return [("ARCHIVELOG", "READ WRITE", 3114375768)]
            if "v$recover_file" in sql:
                return [(12, "C:\\ORADATA\\XEPDB1\\USERS01.DBF", "USERS", "XEPDB1", "OFFLINE", "FILE NOT FOUND", 9)]
            return []

        yield consulta

    return abrir


def test_plan_de_datafile_identifica_el_archivo_y_lo_guarda(tmp_path: Path, almacen: Almacen) -> None:
    procedimiento = recuperacion.plan(ajustes(tmp_path), "XE", "datafile", abrir=consulta_danada())
    assert procedimiento.posible
    assert (procedimiento.objetivo or "").startswith("12")
    assert procedimiento.archivo is not None
    assert Path(procedimiento.archivo).read_text(encoding="ascii") == procedimiento.script
    assert any("PRUEBAS" in aviso for aviso in procedimiento.avisos)


def test_diagnostico_sin_conexion_lo_avisa(tmp_path: Path, almacen: Almacen) -> None:
    from contextlib import contextmanager

    @contextmanager
    def caida(base: BaseDestino):  # type: ignore[no-untyped-def]
        raise RuntimeError("ORA-01034")
        yield

    diagnostico = recuperacion.diagnostico(ajustes(tmp_path), "XE", abrir=caida)
    assert diagnostico.archivos == []
    assert "ORA-01034" in diagnostico.avisos[0]


def test_informe_de_retencion_no_borra_nada(tmp_path: Path, almacen: Almacen) -> None:
    almacen.piezas = [
        PiezaRegistrada(
            1, 5, "C:\\b\\vieja.bkp", 10, "T", datetime(2026, 1, 1), False, 4, "EST004", "T1", datetime(2025, 12, 1)
        ),
        PiezaRegistrada(
            2, 6, "C:\\b\\nueva.bkp", 10, "T", datetime(2099, 1, 1), False, 4, "EST004", "T1", datetime(2026, 10, 1)
        ),
    ]
    informe = retencion.informe(ajustes(tmp_path), "XE")
    est004 = next(e for e in informe.estrategias if e.estrategia == "EST004")
    assert [p.ruta for p in est004.vencidas] == ["C:\\b\\vieja.bkp"]
    assert est004.politica == "RECOVERY WINDOW OF 30 DAYS"
    assert est004.script is not None
    assert "DELETE" not in est004.script
    est001 = next(e for e in informe.estrategias if e.estrategia == "EST001")
    assert est001.politica is None
    assert est001.avisos


def test_purga_exige_confirmacion_y_purga_automatica(tmp_path: Path, almacen: Almacen) -> None:
    with pytest.raises(OperacionNoPermitida, match="no se puede deshacer"):
        retencion.purgar(ajustes(tmp_path), "XE", "EST004", confirmado=False)
    with pytest.raises(OperacionNoPermitida, match="nunca los borra"):
        retencion.purgar(ajustes(tmp_path), "XE", "EST004", confirmado=True)
