from datetime import UTC, datetime, time
from pathlib import Path
from typing import Any

import pytest

from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.domain.enums import (
    EstadoAlerta,
    EstadoEjecucion,
    EstadoEstrategia,
    EstadoPrueba,
    EstadoScript,
    LogMode,
    ModoRespaldo,
    Prioridad,
    TipoFrecuencia,
    TipoObjeto,
    TipoRespaldo,
)
from cloudcr_backup.domain.errores import OperacionNoPermitida, RecursoNoEncontrado, RepositorioNoDisponible
from cloudcr_backup.domain.estrategia import Como, Destino, Estrategia, ObjetoAlcance, Programacion, Tarea
from cloudcr_backup.domain.perfil_bd import PerfilBD
from cloudcr_backup.oracle.connection import ErrorConexionOracle
from cloudcr_backup.repository import alertas as repositorio_alertas
from cloudcr_backup.repository import bases_datos as repositorio_bases_datos
from cloudcr_backup.repository import conexion as repositorio_conexion
from cloudcr_backup.repository import ejecuciones as repositorio_ejecuciones
from cloudcr_backup.repository import estrategias as repositorio_estrategias
from cloudcr_backup.repository import parametros as repositorio_parametros
from cloudcr_backup.repository import scripts as repositorio_scripts
from cloudcr_backup.repository.alertas import AlertaDetallada
from cloudcr_backup.repository.bases_datos import Ambiente, BaseDatosRegistrada
from cloudcr_backup.repository.conexion import RepositorioNoConfigurado
from cloudcr_backup.repository.ejecuciones import Ejecucion, EjecucionDetallada, EjecucionInterrumpida
from cloudcr_backup.repository.scripts import ScriptRman
from cloudcr_backup.services import alertas as servicio_alertas
from cloudcr_backup.services.fuente_oracle import FuenteOracle
from cloudcr_backup.services.sesion import conexion_repositorio
from tests.unit.oracle_falso import ConexionFalsa

APROBADO = datetime(2026, 10, 1, 18, 0)
PROGRAMADA = datetime(2026, 10, 3, 19, 0)


def _estrategia(estado: EstadoEstrategia = EstadoEstrategia.ACTIVA) -> Estrategia:
    return Estrategia(
        id=2,
        bd_id=1,
        codigo="EST001",
        nombre="Producción diaria",
        prioridad=Prioridad.ALTA,
        estado=estado,
        creada_por="luis",
        alcance=[
            ObjetoAlcance(tipo=TipoObjeto.TABLESPACE, identificador="XEPDB1:VENTAS", prioridad=Prioridad.ALTA),
            ObjetoAlcance(tipo=TipoObjeto.CONTROLFILE, identificador="", prioridad=Prioridad.ALTA),
        ],
        tareas=[
            Tarea(
                codigo="T1",
                como=Como(tipo_respaldo=TipoRespaldo.COMPLETO, modo_respaldo=ModoRespaldo.EN_LINEA),
                programacion=Programacion(tipo_frecuencia=TipoFrecuencia.DIARIA, horas=[time(13, 0)]),
                destino=Destino(ruta=r"C:\backups\XE"),
            ),
            Tarea(
                codigo="T2",
                como=Como(tipo_respaldo=TipoRespaldo.ARCHIVELOG),
                programacion=Programacion(tipo_frecuencia=TipoFrecuencia.INTERVALO, intervalo_minutos=60),
                destino=Destino(ruta=r"C:\backups\XE"),
            ),
        ],
    )


def _detallada(estado: EstadoEjecucion = EstadoEjecucion.FALLIDA) -> EjecucionDetallada:
    return EjecucionDetallada(
        id=40, bd_id=1, bd_nombre="XE", estrategia_id=2, estrategia_codigo="EST001",
        estrategia_nombre="Producción diaria", tarea_id=3, tarea_codigo="T1", tipo_respaldo="COMPLETO",
        modo_respaldo="EN_LINEA", estado=estado, estado_prueba=EstadoPrueba.PENDIENTE, programada_para=PROGRAMADA,
        inicio=PROGRAMADA, fin=None, duracion_segundos=None, tamano_bytes=None, archivos_generados=None,
        ubicacion=None, zona_horaria="America/Costa_Rica", mensaje_rman="RMAN-03009", agente="SERVIDOR", script_id=9,
    )


@pytest.fixture
def repositorio(monkeypatch: pytest.MonkeyPatch, perfil_xe: PerfilBD) -> dict[str, Any]:
    estado: dict[str, Any] = {"reclamadas": [], "estrategia": _estrategia()}
    bd = BaseDatosRegistrada(id=1, nombre="XE", oracle_home=r"C:\oracle", ambiente=Ambiente.PRUEBAS, activa=True)
    script = ScriptRman(9, 3, 1, "", "abc", EstadoScript.APROBADO, "ale", APROBADO, APROBADO)
    monkeypatch.setattr(repositorio_parametros, "listar", lambda c: {"agente.gracia_omision_min": "15"})
    monkeypatch.setattr(repositorio_bases_datos, "listar", lambda c: [bd])
    monkeypatch.setattr(repositorio_bases_datos, "ultimo_perfil", lambda c, bd_id: perfil_xe)
    monkeypatch.setattr(repositorio_bases_datos, "log_mode_al_crear_script", lambda c, b, s: LogMode.ARCHIVELOG)
    monkeypatch.setattr(repositorio_estrategias, "listar", lambda c, bd_id: [estado["estrategia"]])
    monkeypatch.setattr(repositorio_estrategias, "ids_de_tareas", lambda c, e: {"T1": 3, "T2": 4})
    monkeypatch.setattr(repositorio_scripts, "vigentes_por_tarea", lambda c: {3: script})
    monkeypatch.setattr(repositorio_ejecuciones, "ultima_programada_por_tarea", lambda c: {3: PROGRAMADA})
    monkeypatch.setattr(repositorio_ejecuciones, "ultimas_por_tarea", lambda c, n: {3: [_detallada()]})
    monkeypatch.setattr(repositorio_ejecuciones, "ultimo_exito_por_estrategia", lambda c: {})
    monkeypatch.setattr(repositorio_ejecuciones, "tamano_ultimo_exito_por_tarea", lambda c: {3: 1024})
    monkeypatch.setattr(repositorio_ejecuciones, "piezas_vencidas_por_estrategia", lambda c, a: {2: 1})

    def reclamar(c: Any, tarea_id: int, momento: datetime) -> Ejecucion:
        estado["reclamadas"].append(momento)
        return Ejecucion(41, tarea_id, 9, EstadoEjecucion.PROGRAMADA, momento, None, None)

    monkeypatch.setattr(repositorio_ejecuciones, "reclamar", reclamar)
    monkeypatch.setattr(
        repositorio_ejecuciones,
        "en_curso_de_agente",
        lambda c, a: [EjecucionInterrumpida(7, 3, PROGRAMADA, "CONSISTENTE")],
    )
    return estado


def test_tareas_programables_solo_con_script_aprobado(repositorio: dict[str, Any]) -> None:
    tareas = FuenteOracle(ConexionFalsa()).tareas_programables()  # type: ignore[arg-type]
    assert [t.tarea_codigo for t in tareas] == ["T1"]
    assert tareas[0].aprobado_en == APROBADO.replace(tzinfo=UTC)
    assert tareas[0].etiqueta == "XE EST001/T1"


def test_estrategias_inactivas_no_se_programan(repositorio: dict[str, Any]) -> None:
    repositorio["estrategia"] = _estrategia(EstadoEstrategia.INACTIVA)
    assert FuenteOracle(ConexionFalsa()).tareas_programables() == []  # type: ignore[arg-type]


def test_las_horas_cruzan_la_frontera_en_utc_sin_zona(repositorio: dict[str, Any]) -> None:
    fuente = FuenteOracle(ConexionFalsa())  # type: ignore[arg-type]
    assert fuente.ultima_programada_por_tarea() == {3: PROGRAMADA.replace(tzinfo=UTC)}
    local = datetime(2026, 10, 3, 13, 0).astimezone(UTC)
    assert fuente.reclamar(3, datetime(2026, 10, 4, 1, 0, tzinfo=UTC)) == 41
    assert repositorio["reclamadas"][0].tzinfo is None
    assert local.tzinfo is not None


def test_en_curso_convierte_el_modo(repositorio: dict[str, Any]) -> None:
    [en_curso] = FuenteOracle(ConexionFalsa()).en_curso_de_agente("SERVIDOR")  # type: ignore[arg-type]
    assert en_curso.modo_respaldo is ModoRespaldo.CONSISTENTE
    assert en_curso.programada_para.tzinfo is not None


def test_instantanea_reune_todo_lo_que_usan_las_reglas(repositorio: dict[str, Any]) -> None:
    medidas: list[str] = []
    fuente = FuenteOracle(ConexionFalsa(), medir_disco=lambda r: medidas.append(r) or None)  # type: ignore[arg-type, func-returns-value]
    instantanea = fuente.instantanea(datetime(2026, 10, 3, 20, 0, tzinfo=UTC))
    [estrategia] = instantanea.estrategias
    assert estrategia.alcance == ["XEPDB1:VENTAS", "CONTROLFILE"]
    assert estrategia.piezas_vencidas == 1
    t1, t2 = estrategia.tareas
    assert t1.script is not None and t1.script.log_mode_al_crear is LogMode.ARCHIVELOG
    assert t1.ultimas[0].estado is EstadoEjecucion.FALLIDA
    assert t1.tamano_ultimo_exito == 1024
    assert t2.script is None
    assert medidas == [r"C:\backups\XE"]
    assert instantanea.bases[0].perfil is not None


def _alerta(estado: EstadoAlerta) -> AlertaDetallada:
    return AlertaDetallada(
        7, "EJECUCION_FALLIDA", "EJECUCION_FALLIDA:XE/EST001/T1", "ALERTA", estado, "Falló", 1, 2, 3, 40,
        PROGRAMADA, None, "XE", "EST001", "T1",
    )


@pytest.fixture
def ajustes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Ajustes:
    monkeypatch.setattr(repositorio_conexion, "abrir_repositorio", lambda a: ConexionFalsa())
    return Ajustes(work_dir=tmp_path)


def test_reconocer_una_alerta_abierta(ajustes: Ajustes, monkeypatch: pytest.MonkeyPatch) -> None:
    estados = iter([EstadoAlerta.ABIERTA, EstadoAlerta.RECONOCIDA])
    monkeypatch.setattr(repositorio_alertas, "obtener", lambda c, i: _alerta(next(estados)))
    monkeypatch.setattr(repositorio_alertas, "reconocer_abierta", lambda c, i: True)
    vista = servicio_alertas.reconocer(ajustes, 7)
    assert vista.estado is EstadoAlerta.RECONOCIDA
    assert vista.accion_sugerida is not None
    assert vista.abierta_en is not None and vista.abierta_en.tzinfo is not None


def test_reconocer_una_alerta_resuelta_no_se_permite(ajustes: Ajustes, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repositorio_alertas, "obtener", lambda c, i: _alerta(EstadoAlerta.RESUELTA))
    monkeypatch.setattr(repositorio_alertas, "reconocer_abierta", lambda c, i: False)
    with pytest.raises(OperacionNoPermitida, match="RESUELTA"):
        servicio_alertas.reconocer(ajustes, 7)


def test_resolver_una_alerta_inexistente(ajustes: Ajustes, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repositorio_alertas, "obtener", lambda c, i: None)
    with pytest.raises(RecursoNoEncontrado):
        servicio_alertas.resolver(ajustes, 99)


def test_filtros_de_listado(ajustes: Ajustes, monkeypatch: pytest.MonkeyPatch) -> None:
    llamadas: list[tuple[Any, ...]] = []
    def listar(c: Any, e: Any, s: Any, limite: int) -> list[AlertaDetallada]:
        llamadas.append((e, s, limite))
        return [_alerta(EstadoAlerta.ABIERTA)]

    monkeypatch.setattr(repositorio_alertas, "listar", listar)
    assert len(servicio_alertas.listar(ajustes)) == 1
    servicio_alertas.listar(ajustes, "todas", "alerta", 10)
    assert llamadas[0][0] == [EstadoAlerta.ABIERTA, EstadoAlerta.RECONOCIDA]
    assert llamadas[1] == (None, "ALERTA", 10)
    with pytest.raises(OperacionNoPermitida):
        servicio_alertas.listar(ajustes, "inventado")
    with pytest.raises(OperacionNoPermitida):
        servicio_alertas.listar(ajustes, severidad="grave")


def test_repositorio_sin_configurar_da_error_con_sugerencia(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def sin_configurar(a: Ajustes) -> None:
        raise RepositorioNoConfigurado("No hay un DSN configurado.")

    monkeypatch.setattr(repositorio_conexion, "abrir_repositorio", sin_configurar)
    with pytest.raises(RepositorioNoDisponible) as error, conexion_repositorio(Ajustes(work_dir=tmp_path)):
        pass
    assert "CLOUDCR_REPOSITORIO_DSN" in (error.value.sugerencia or "")


def test_repositorio_caido_da_error_con_sugerencia(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def caido(a: Ajustes) -> None:
        raise ErrorConexionOracle("No se pudo llegar a localhost (ORA-12541).", "Verifique el listener.")

    monkeypatch.setattr(repositorio_conexion, "abrir_repositorio", caido)
    with pytest.raises(RepositorioNoDisponible) as error, conexion_repositorio(Ajustes(work_dir=tmp_path)):
        pass
    assert error.value.sugerencia == "Verifique el listener."


def test_error_de_oracle_en_una_consulta_se_traduce(ajustes: Ajustes) -> None:
    import oracledb

    with pytest.raises(RepositorioNoDisponible) as error, conexion_repositorio(ajustes):
        raise oracledb.DatabaseError("ORA-00942: table or view does not exist")
    assert "repo instalar" in (error.value.sugerencia or "")
