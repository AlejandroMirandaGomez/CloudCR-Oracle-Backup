from cloudcr_backup.domain.enums import Severidad, TipoFrecuencia, TipoRespaldo
from cloudcr_backup.domain.estrategia import Programacion, Tarea
from cloudcr_backup.domain.hallazgos import Hallazgo
from cloudcr_backup.validation.contexto import ContextoValidacion
from cloudcr_backup.validation.motor import regla

_DIAS_POR_FRECUENCIA = {
    TipoFrecuencia.DIARIA: 1.0,
    TipoFrecuencia.SEMANAL: 7.0,
    TipoFrecuencia.MENSUAL: 30.0,
}


def _intervalo_dias(programacion: Programacion) -> float | None:
    if programacion.tipo_frecuencia is TipoFrecuencia.INTERVALO:
        if programacion.intervalo_minutos is None:
            return None
        return programacion.intervalo_minutos / (60 * 24)
    return _DIAS_POR_FRECUENCIA.get(programacion.tipo_frecuencia)


def _es_tarea_nivel_0(tarea: Tarea) -> bool:
    return tarea.como.tipo_respaldo in (TipoRespaldo.COMPLETO, TipoRespaldo.INCREMENTAL_N0)


@regla("RET_001")
def ret_001_sin_politica_de_retencion(contexto: ContextoValidacion) -> list[Hallazgo]:
    retencion = contexto.estrategia.retencion
    if retencion.ventana_dias is not None or retencion.redundancia is not None:
        return []
    return [
        Hallazgo(
            codigo="RET_001",
            severidad=Severidad.ADVERTENCIA,
            mensaje="La estrategia no tiene una política de retención: los respaldos se acumularán sin límite.",
            sujeto=contexto.estrategia.codigo,
            accion_sugerida="Defina 'ventana_dias' o 'redundancia' en la retención de la estrategia.",
        )
    ]


@regla("RET_002")
def ret_002_ventana_y_redundancia_a_la_vez(contexto: ContextoValidacion) -> list[Hallazgo]:
    retencion = contexto.estrategia.retencion
    if retencion.ventana_dias is None or retencion.redundancia is None:
        return []
    return [
        Hallazgo(
            codigo="RET_002",
            severidad=Severidad.ERROR,
            mensaje="'ventana_dias' y 'redundancia' son excluyentes: no se pueden definir los dos a la vez.",
            sujeto=contexto.estrategia.codigo,
            accion_sugerida="Elija solo uno de los dos criterios de retención.",
        )
    ]


@regla("RET_003")
def ret_003_ventana_menor_que_el_intervalo_n0(contexto: ContextoValidacion) -> list[Hallazgo]:
    ventana_dias = contexto.estrategia.retencion.ventana_dias
    if ventana_dias is None:
        return []
    hallazgos = []
    for tarea in contexto.estrategia.tareas:
        if not _es_tarea_nivel_0(tarea):
            continue
        intervalo = _intervalo_dias(tarea.programacion)
        if intervalo is not None and ventana_dias < intervalo:
            hallazgos.append(
                Hallazgo(
                    codigo="RET_003",
                    severidad=Severidad.ADVERTENCIA,
                    mensaje=(
                        f"La ventana de retención ({ventana_dias} días) es menor que el intervalo entre "
                        f"respaldos de nivel 0 de la tarea {tarea.codigo} (~{intervalo:.1f} días): puede "
                        "quedar un período sin ningún respaldo válido."
                    ),
                    sujeto=tarea.codigo,
                    accion_sugerida="Aumente la ventana de retención o programe los N0 con más frecuencia.",
                )
            )
    return hallazgos


@regla("RET_004")
def ret_004_purga_automatica_activa(contexto: ContextoValidacion) -> list[Hallazgo]:
    if not contexto.estrategia.retencion.purga_automatica:
        return []
    return [
        Hallazgo(
            codigo="RET_004",
            severidad=Severidad.ADVERTENCIA,
            mensaje="La purga automática está activa: el sistema borrará respaldos obsoletos sin volver a preguntar.",
            sujeto=contexto.estrategia.codigo,
        )
    ]
