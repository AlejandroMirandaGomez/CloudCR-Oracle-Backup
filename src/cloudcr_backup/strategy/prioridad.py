from dataclasses import dataclass

from cloudcr_backup.domain.enums import Prioridad


@dataclass(frozen=True)
class CriterioPrioridad:
    prioridad: Prioridad
    rpo_horas: float
    rto_horas: float
    recencia_maxima_horas: float
    esquema_sugerido: str
    descripcion: str


_CRITERIOS: dict[Prioridad, CriterioPrioridad] = {
    Prioridad.ALTA: CriterioPrioridad(
        prioridad=Prioridad.ALTA,
        rpo_horas=1.0,
        rto_horas=4.0,
        recencia_maxima_horas=24.0,
        esquema_sugerido="Incremental nivel 0 semanal + nivel 1 acumulativo diario + archived logs cada 4 horas",
        descripcion=(
            "Información cuya pérdida puede detener o afectar significativamente la operación institucional "
            "(enunciado §1.1). Exige respaldos frecuentes y procedimientos de recuperación claramente definidos."
        ),
    ),
    Prioridad.MEDIA: CriterioPrioridad(
        prioridad=Prioridad.MEDIA,
        rpo_horas=24.0,
        rto_horas=24.0,
        recencia_maxima_horas=72.0,
        esquema_sugerido="Incremental nivel 0 semanal + nivel 1 diferencial diario",
        descripcion=(
            "Información importante para la operación, pero cuya pérdida temporal puede ser tolerable bajo "
            "determinadas condiciones (enunciado §1.1)."
        ),
    ),
    Prioridad.BAJA: CriterioPrioridad(
        prioridad=Prioridad.BAJA,
        rpo_horas=168.0,
        rto_horas=72.0,
        recencia_maxima_horas=192.0,
        esquema_sugerido="Respaldo completo semanal",
        descripcion=(
            "Información que puede ser reconstruida, recuperada por otros medios o cuya pérdida tiene un "
            "impacto menor sobre la operación (enunciado §1.1)."
        ),
    ),
}


def criterio_de(prioridad: Prioridad) -> CriterioPrioridad:
    return _CRITERIOS[prioridad]


def todos_los_criterios() -> list[CriterioPrioridad]:
    return [_CRITERIOS[p] for p in (Prioridad.ALTA, Prioridad.MEDIA, Prioridad.BAJA)]
