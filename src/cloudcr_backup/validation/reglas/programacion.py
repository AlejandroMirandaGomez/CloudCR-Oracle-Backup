from cloudcr_backup.domain.enums import EstadoEstrategia, Severidad, TipoFrecuencia
from cloudcr_backup.domain.estrategia import Programacion
from cloudcr_backup.domain.hallazgos import Hallazgo
from cloudcr_backup.scheduling.recurrencia import ProgramacionInvalida, proximas
from cloudcr_backup.strategy.prioridad import criterio_de
from cloudcr_backup.validation.contexto import ContextoValidacion
from cloudcr_backup.validation.motor import regla

CANTIDAD_VISTA_PREVIA = 5
DIAS_CORTOS = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")

_HORAS_POR_FRECUENCIA = {
    TipoFrecuencia.DIARIA: 24.0,
    TipoFrecuencia.SEMANAL: 24.0 * 7,
    TipoFrecuencia.MENSUAL: 24.0 * 30,
}


def _programacion_vacia(programacion: Programacion) -> bool:
    return (
        not programacion.horas
        and not programacion.dias_semana
        and programacion.intervalo_minutos is None
        and programacion.fecha_inicio is None
    )


def _campos_faltantes(programacion: Programacion) -> list[str]:
    faltantes = []
    tipos_con_horas = (TipoFrecuencia.DIARIA, TipoFrecuencia.SEMANAL, TipoFrecuencia.MENSUAL)
    if programacion.tipo_frecuencia in tipos_con_horas and not programacion.horas:
        faltantes.append("horas")
    if programacion.tipo_frecuencia is TipoFrecuencia.SEMANAL and not programacion.dias_semana:
        faltantes.append("dias_semana")
    if programacion.tipo_frecuencia is TipoFrecuencia.INTERVALO and programacion.intervalo_minutos is None:
        faltantes.append("intervalo_minutos")
    if programacion.tipo_frecuencia is TipoFrecuencia.UNA_VEZ and programacion.fecha_inicio is None:
        faltantes.append("fecha_inicio")
    return faltantes


def _intervalo_horas(programacion: Programacion) -> float | None:
    if programacion.tipo_frecuencia is TipoFrecuencia.INTERVALO:
        if programacion.intervalo_minutos is None:
            return None
        return programacion.intervalo_minutos / 60
    if programacion.tipo_frecuencia is TipoFrecuencia.DIARIA and len(programacion.horas) > 1:
        return 24.0 / len(programacion.horas)
    if programacion.tipo_frecuencia is TipoFrecuencia.SEMANAL and programacion.dias_semana:
        return (24.0 * 7) / len(programacion.dias_semana)
    return _HORAS_POR_FRECUENCIA.get(programacion.tipo_frecuencia)


@regla("PRG_001")
def prg_001_tarea_activa_sin_programacion(contexto: ContextoValidacion) -> list[Hallazgo]:
    if contexto.estrategia.estado is not EstadoEstrategia.ACTIVA:
        return []
    return [
        Hallazgo(
            codigo="PRG_001",
            severidad=Severidad.ERROR,
            mensaje=f"La tarea {tarea.codigo} está en una estrategia activa pero no tiene ninguna programación.",
            sujeto=tarea.codigo,
            accion_sugerida="Defina al menos una hora, día o intervalo de ejecución para la tarea.",
        )
        for tarea in contexto.estrategia.tareas
        if _programacion_vacia(tarea.programacion)
    ]


@regla("PRG_002")
def prg_002_programacion_incompleta(contexto: ContextoValidacion) -> list[Hallazgo]:
    hallazgos = []
    for tarea in contexto.estrategia.tareas:
        faltantes = _campos_faltantes(tarea.programacion)
        if not faltantes:
            continue
        hallazgos.append(
            Hallazgo(
                codigo="PRG_002",
                severidad=Severidad.ERROR,
                mensaje=(
                    f"La programación de la tarea {tarea.codigo} está incompleta para su frecuencia "
                    f"{tarea.programacion.tipo_frecuencia}: falta {', '.join(faltantes)}."
                ),
                sujeto=tarea.codigo,
                accion_sugerida="Complete los campos que exige el tipo de frecuencia elegido.",
            )
        )
    return hallazgos


@regla("PRG_003")
def prg_003_hora_fuera_de_la_ventana(contexto: ContextoValidacion) -> list[Hallazgo]:
    hallazgos = []
    for tarea in contexto.estrategia.tareas:
        ventana = tarea.programacion.ventana
        if ventana is None:
            continue
        for hora in tarea.programacion.horas:
            if ventana.contiene(hora):
                continue
            hallazgos.append(
                Hallazgo(
                    codigo="PRG_003",
                    severidad=Severidad.ADVERTENCIA,
                    mensaje=(
                        f"La tarea {tarea.codigo} tiene una ejecución a las {hora} fuera de su ventana "
                        f"de respaldo ({ventana.inicio}-{ventana.fin})."
                    ),
                    sujeto=tarea.codigo,
                    accion_sugerida="Ajuste la hora o amplíe la ventana de respaldo.",
                )
            )
    return hallazgos


@regla("PRG_005")
def prg_005_frecuencia_insuficiente_para_la_prioridad(contexto: ContextoValidacion) -> list[Hallazgo]:
    maximo = criterio_de(contexto.estrategia.prioridad).recencia_maxima_horas
    hallazgos = []
    for tarea in contexto.estrategia.tareas:
        intervalo = _intervalo_horas(tarea.programacion)
        if intervalo is None or intervalo <= maximo:
            continue
        hallazgos.append(
            Hallazgo(
                codigo="PRG_005",
                severidad=Severidad.ADVERTENCIA,
                mensaje=(
                    f"La tarea {tarea.codigo} se ejecuta cada ~{intervalo:.1f} h, pero una estrategia de "
                    f"prioridad {contexto.estrategia.prioridad} debería respaldar al menos cada {maximo:.0f} h."
                ),
                sujeto=tarea.codigo,
                accion_sugerida="Aumente la frecuencia de la tarea o reduzca la prioridad de la estrategia.",
            )
        )
    return hallazgos


@regla("PRG_007")
def prg_007_vista_previa_de_proximas_ejecuciones(contexto: ContextoValidacion) -> list[Hallazgo]:
    hallazgos = []
    for tarea in contexto.estrategia.tareas:
        try:
            ocurrencias = proximas(tarea.programacion, contexto.ahora, CANTIDAD_VISTA_PREVIA)
        except ProgramacionInvalida:
            continue
        if not ocurrencias:
            continue
        listado = ", ".join(f"{DIAS_CORTOS[o.weekday()]} {o:%d/%m %H:%M}" for o in ocurrencias)
        hallazgos.append(
            Hallazgo(
                codigo="PRG_007",
                severidad=Severidad.INFORMATIVA,
                mensaje=(
                    f"Próximas ejecuciones de {tarea.codigo} ({tarea.programacion.zona_horaria}): {listado}."
                ),
                sujeto=tarea.codigo,
            )
        )
    return hallazgos
