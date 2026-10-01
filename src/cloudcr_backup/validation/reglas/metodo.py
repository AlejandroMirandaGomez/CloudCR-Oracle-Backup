from cloudcr_backup.domain.enums import Severidad, TipoRespaldo
from cloudcr_backup.domain.hallazgos import Hallazgo
from cloudcr_backup.oracle.capacidades import capacidades_de
from cloudcr_backup.validation.contexto import ContextoValidacion
from cloudcr_backup.validation.motor import regla

_TIPOS_N1 = (TipoRespaldo.INCREMENTAL_N1_DIFERENCIAL, TipoRespaldo.INCREMENTAL_N1_ACUMULATIVO)


@regla("MET_001")
def met_001_n1_sin_n0_en_la_estrategia(contexto: ContextoValidacion) -> list[Hallazgo]:
    tareas = contexto.estrategia.tareas
    tiene_n0 = any(t.como.tipo_respaldo is TipoRespaldo.INCREMENTAL_N0 for t in tareas)
    if tiene_n0:
        return []
    return [
        Hallazgo(
            codigo="MET_001",
            severidad=Severidad.ADVERTENCIA,
            mensaje=(
                f"La tarea {tarea.codigo} es incremental de nivel 1, pero la estrategia no tiene "
                "ninguna tarea de nivel 0 que le sirva de base."
            ),
            sujeto=tarea.codigo,
            accion_sugerida="Agregue una tarea INCREMENTAL_N0 a la estrategia antes de aprobar los incrementales.",
        )
        for tarea in tareas
        if tarea.como.tipo_respaldo in _TIPOS_N1
    ]


@regla("MET_002")
def met_002_n1_con_base_completo(contexto: ContextoValidacion) -> list[Hallazgo]:
    tareas = contexto.estrategia.tareas
    tiene_n1 = any(t.como.tipo_respaldo in _TIPOS_N1 for t in tareas)
    tiene_completo = any(t.como.tipo_respaldo is TipoRespaldo.COMPLETO for t in tareas)
    tiene_n0 = any(t.como.tipo_respaldo is TipoRespaldo.INCREMENTAL_N0 for t in tareas)
    if not (tiene_n1 and tiene_completo and not tiene_n0):
        return []
    return [
        Hallazgo(
            codigo="MET_002",
            severidad=Severidad.ADVERTENCIA,
            mensaje=(
                "La estrategia tiene tareas incrementales de nivel 1, pero su respaldo base es COMPLETO: "
                "un respaldo completo no sirve de base para incrementales en RMAN."
            ),
            sujeto=contexto.estrategia.codigo,
            accion_sugerida="Cambie la tarea base a INCREMENTAL_N0 en lugar de COMPLETO.",
        )
    ]


@regla("MET_003")
def met_003_compresion_no_soportada(contexto: ContextoValidacion) -> list[Hallazgo]:
    capacidades = capacidades_de(contexto.perfil.edicion)
    return [
        Hallazgo(
            codigo="MET_003",
            severidad=Severidad.ERROR,
            mensaje=(
                f"La tarea {tarea.codigo} usa compresión {tarea.como.opciones.compresion}, no soportada por la "
                f"edición {contexto.perfil.edicion} de Oracle."
            ),
            sujeto=tarea.codigo,
            accion_sugerida="Use una compresión soportada por esta edición (NINGUNA o BASIC en XE).",
        )
        for tarea in contexto.estrategia.tareas
        if tarea.como.opciones.compresion not in capacidades.compresiones_soportadas
    ]


@regla("MET_004")
def met_004_mas_canales_de_los_soportados(contexto: ContextoValidacion) -> list[Hallazgo]:
    capacidades = capacidades_de(contexto.perfil.edicion)
    return [
        Hallazgo(
            codigo="MET_004",
            severidad=Severidad.ERROR,
            mensaje=(
                f"La tarea {tarea.codigo} pide {tarea.como.opciones.canales} canales, pero la edición "
                f"{contexto.perfil.edicion} admite como máximo {capacidades.canales_maximos}."
            ),
            sujeto=tarea.codigo,
            accion_sugerida=f"Reduzca los canales a {capacidades.canales_maximos} o menos.",
        )
        for tarea in contexto.estrategia.tareas
        if tarea.como.opciones.canales > capacidades.canales_maximos
    ]
