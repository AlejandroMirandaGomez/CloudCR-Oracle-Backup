from datetime import datetime, time

from cloudcr_backup.domain.enums import (
    DiaSemana,
    LogMode,
    ModoRespaldo,
    Prioridad,
    TipoFrecuencia,
    TipoObjeto,
    TipoRespaldo,
)
from cloudcr_backup.domain.estrategia import Destino, Estrategia, ObjetoAlcance
from cloudcr_backup.domain.perfil_bd import PerfilBD
from cloudcr_backup.strategy.plantillas_esquema import (
    EsquemaPredefinido,
    ParametrosEsquema,
    tareas_de,
    todos_los_esquemas,
)
from cloudcr_backup.validation import motor, reglas  # noqa: F401  registra todas las reglas
from cloudcr_backup.validation.contexto import ContextoValidacion


def _parametros() -> ParametrosEsquema:
    return ParametrosEsquema(
        destino=Destino(ruta=r"C:\backups\XE"),
        dia_n0=DiaSemana.DOMINGO,
        hora_n0=time(2, 0),
        hora_n1=time(23, 0),
    )


def test_completo_semanal_genera_una_sola_tarea() -> None:
    tareas = tareas_de(EsquemaPredefinido.COMPLETO_SEMANAL, _parametros())
    assert len(tareas) == 1
    assert tareas[0].como.tipo_respaldo is TipoRespaldo.COMPLETO
    assert tareas[0].programacion.tipo_frecuencia is TipoFrecuencia.SEMANAL


def test_n0_semanal_n1_diferencial_diario_genera_dos_tareas_coherentes() -> None:
    tareas = tareas_de(EsquemaPredefinido.N0_SEMANAL_N1_DIFERENCIAL_DIARIO, _parametros())
    assert [t.como.tipo_respaldo for t in tareas] == [
        TipoRespaldo.INCREMENTAL_N0,
        TipoRespaldo.INCREMENTAL_N1_DIFERENCIAL,
    ]
    assert tareas[1].programacion.tipo_frecuencia is TipoFrecuencia.DIARIA


def test_n0_semanal_n1_acumulativo_diario() -> None:
    tareas = tareas_de(EsquemaPredefinido.N0_SEMANAL_N1_ACUMULATIVO_DIARIO, _parametros())
    assert [t.como.tipo_respaldo for t in tareas] == [
        TipoRespaldo.INCREMENTAL_N0,
        TipoRespaldo.INCREMENTAL_N1_ACUMULATIVO,
    ]


def test_n0_n1_acumulativo_con_archivelogs_agrega_una_tercera_tarea() -> None:
    tareas = tareas_de(EsquemaPredefinido.N0_N1_ACUMULATIVO_CON_ARCHIVELOGS, _parametros())
    assert len(tareas) == 3
    assert tareas[2].como.tipo_respaldo is TipoRespaldo.ARCHIVELOG
    assert tareas[2].programacion.tipo_frecuencia is TipoFrecuencia.INTERVALO
    assert tareas[2].programacion.intervalo_minutos == 240


def test_consistente_para_noarchivelog_usa_el_modo_consistente() -> None:
    tareas = tareas_de(EsquemaPredefinido.CONSISTENTE_NOARCHIVELOG, _parametros())
    assert len(tareas) == 1
    assert tareas[0].como.modo_respaldo is ModoRespaldo.CONSISTENTE


def test_todos_los_esquemas_devuelve_los_cinco() -> None:
    assert {e.esquema for e in todos_los_esquemas()} == set(EsquemaPredefinido)


def test_cada_esquema_explica_que_hace_para_quien_es_y_que_tener_en_cuenta() -> None:
    for descripcion in todos_los_esquemas():
        assert descripcion.que_hace, descripcion.nombre
        assert descripcion.ideal_para, descripcion.nombre
        assert descripcion.nota, descripcion.nombre


def test_los_textos_de_los_esquemas_hablan_de_tipos_de_respaldo_y_no_de_tareas() -> None:
    for descripcion in todos_los_esquemas():
        textos = " ".join((descripcion.que_hace, descripcion.ideal_para, descripcion.nota)).lower()
        assert "tarea" not in textos, descripcion.nombre
        assert any(frase in descripcion.que_hace for frase in ("tipo de respaldo", "tipos de respaldo")), (
            descripcion.nombre
        )


def test_la_descripcion_corta_de_un_esquema_es_lo_que_hace() -> None:
    for descripcion in todos_los_esquemas():
        assert descripcion.descripcion == descripcion.que_hace


def test_los_rotulos_de_dia_y_hora_dependen_del_esquema() -> None:
    rotulos = {e.esquema: (e.rotulo_dia, e.rotulo_hora_principal, e.rotulo_hora_n1) for e in todos_los_esquemas()}
    assert rotulos == {
        EsquemaPredefinido.COMPLETO_SEMANAL: ("Día del respaldo completo", "Hora del respaldo completo", ""),
        EsquemaPredefinido.N0_SEMANAL_N1_DIFERENCIAL_DIARIO: (
            "Día del nivel 0",
            "Hora del nivel 0",
            "Hora del nivel 1 diferencial (diario)",
        ),
        EsquemaPredefinido.N0_SEMANAL_N1_ACUMULATIVO_DIARIO: (
            "Día del nivel 0",
            "Hora del nivel 0",
            "Hora del nivel 1 acumulativo (diario)",
        ),
        EsquemaPredefinido.N0_N1_ACUMULATIVO_CON_ARCHIVELOGS: (
            "Día del nivel 0",
            "Hora del nivel 0",
            "Hora del nivel 1 acumulativo (diario)",
        ),
        EsquemaPredefinido.CONSISTENTE_NOARCHIVELOG: (
            "Día del respaldo consistente",
            "Hora del respaldo consistente",
            "",
        ),
    }


def test_solo_los_esquemas_con_nivel_1_tienen_rotulo_para_su_hora() -> None:
    tipos_nivel_1 = {TipoRespaldo.INCREMENTAL_N1_DIFERENCIAL, TipoRespaldo.INCREMENTAL_N1_ACUMULATIVO}
    for descripcion in todos_los_esquemas():
        tareas = tareas_de(descripcion.esquema, _parametros())
        usa_nivel_1 = any(tarea.como.tipo_respaldo in tipos_nivel_1 for tarea in tareas)
        assert bool(descripcion.rotulo_hora_n1) is usa_nivel_1, descripcion.nombre


def _perfil_archivelog() -> PerfilBD:
    return PerfilBD(
        nombre="XE",
        nombre_instancia="XE",
        dbid=1,
        host="localhost",
        version="21.3.0.0.0",
        edicion="XE",
        es_cdb=False,
        log_mode=LogMode.ARCHIVELOG,
        open_mode="READ WRITE",
        estado_instancia="OPEN",
        oracle_home=None,
        diagnostic_dest=None,
        capturado_en=datetime.now(),
        contenedores=[],
        tablespaces=[],
        datafiles=[],
        tempfiles=[],
        controlfiles=[],
        redo_grupos=[],
        archivos_parametros=[],
        destinos_archivado=[],
        destino_archivado_configurado=False,
        area_recuperacion=None,
        archivelogs_sin_respaldo=0,
    )


def test_cada_esquema_no_produce_errores_de_metodo_en_el_motor_de_validacion() -> None:
    for descripcion in todos_los_esquemas():
        if descripcion.esquema is EsquemaPredefinido.CONSISTENTE_NOARCHIVELOG:
            continue
        estrategia = Estrategia(
            bd_id=1,
            codigo="EST_PLANTILLA",
            nombre=descripcion.nombre,
            prioridad=Prioridad.ALTA,
            creada_por="luis",
            alcance=[ObjetoAlcance(tipo=TipoObjeto.BASE_DATOS, identificador="", prioridad=Prioridad.ALTA)],
            tareas=tareas_de(descripcion.esquema, _parametros()),
        )
        contexto = ContextoValidacion(estrategia=estrategia, perfil=_perfil_archivelog())
        codigos = [h.codigo for h in motor.validar(contexto)]
        assert "MET_001" not in codigos, descripcion.nombre
        assert "MET_002" not in codigos, descripcion.nombre
        assert "PRG_002" not in codigos, descripcion.nombre
