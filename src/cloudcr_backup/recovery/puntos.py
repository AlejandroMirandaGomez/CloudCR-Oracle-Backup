from collections.abc import Iterable

from cloudcr_backup.domain.enums import EstadoEjecucion, EstadoPrueba, LogMode, TipoObjeto, TipoRespaldo
from cloudcr_backup.domain.estrategia import Estrategia
from cloudcr_backup.domain.recuperacion import PuntoRecuperacion, PuntosRecuperacion
from cloudcr_backup.repository.ejecuciones import EjecucionDetallada
from cloudcr_backup.repository.piezas import PiezaRegistrada

ESTADOS_RESTAURABLES = (EstadoEjecucion.EXITOSA, EstadoEjecucion.CON_ADVERTENCIAS)
TIPOS_BASE = (TipoRespaldo.COMPLETO, TipoRespaldo.INCREMENTAL_N0)
MARCA_CONTROLFILE = "C-"


def _alcance(estrategia: Estrategia | None) -> list[str]:
    if estrategia is None:
        return []
    return [o.identificador or o.tipo.value for o in estrategia.alcance]


def _base_completa(estrategia: Estrategia | None) -> bool:
    return estrategia is not None and any(o.tipo is TipoObjeto.BASE_DATOS for o in estrategia.alcance)


def _pieza_controlfile(piezas: list[PiezaRegistrada], estrategia: Estrategia | None) -> str | None:
    tipos = (TipoObjeto.CONTROLFILE, TipoObjeto.BASE_DATOS)
    if estrategia is None or not any(o.tipo in tipos for o in estrategia.alcance):
        return None
    autobackups = [p.nombre_archivo for p in piezas if _nombre(p.nombre_archivo).startswith(MARCA_CONTROLFILE)]
    return autobackups[0] if autobackups else None


def _nombre(ruta: str) -> str:
    return ruta.replace("\\", "/").rsplit("/", 1)[-1].upper()


def construir(
    bd: str,
    log_mode: LogMode | None,
    ejecuciones: Iterable[EjecucionDetallada],
    piezas: Iterable[PiezaRegistrada],
    estrategias: dict[str, Estrategia],
) -> PuntosRecuperacion:
    por_ejecucion: dict[int, list[PiezaRegistrada]] = {}
    for pieza in piezas:
        if not pieza.obsoleta:
            por_ejecucion.setdefault(pieza.ejecucion_id, []).append(pieza)
    puntos = []
    for ejecucion in ejecuciones:
        propias = por_ejecucion.get(ejecucion.id, [])
        if ejecucion.estado not in ESTADOS_RESTAURABLES or not propias:
            continue
        estrategia = estrategias.get(ejecucion.estrategia_codigo)
        puntos.append(
            PuntoRecuperacion(
                ejecucion_id=ejecucion.id,
                estrategia=ejecucion.estrategia_codigo,
                tarea=ejecucion.tarea_codigo,
                tipo_respaldo=TipoRespaldo(ejecucion.tipo_respaldo),
                completado_en=ejecucion.fin,
                alcance=_alcance(estrategia),
                base_completa=_base_completa(estrategia),
                estado_prueba=ejecucion.estado_prueba,
                piezas=len(propias),
                tamano_bytes=sum(p.tamano_bytes or 0 for p in propias),
                tag=next((p.tag for p in propias if p.tag), None),
                controlfile=_pieza_controlfile(propias, estrategia),
            )
        )
    puntos.sort(key=lambda p: (p.completado_en is None, p.completado_en), reverse=True)
    avisos = []
    if not puntos:
        avisos.append("No hay respaldos correctos con piezas disponibles: hoy no existe ningún punto de recuperación.")
    elif not any(p.estado_prueba is EstadoPrueba.OK for p in puntos):
        avisos.append("Ningún punto está verificado (Pruebas en OK): no hay garantía de que se pueda restaurar.")
    bases = [
        p for p in puntos if p.base_completa and p.tipo_respaldo in TIPOS_BASE and p.completado_en is not None
    ]
    desde = min((p.completado_en for p in bases if p.completado_en is not None), default=None)
    if log_mode is LogMode.ARCHIVELOG and desde is not None:
        avisos.append(
            f"Con ARCHIVELOG continuo se puede recuperar a cualquier momento posterior a {desde:%Y-%m-%d %H:%M} UTC."
        )
    elif log_mode is LogMode.NOARCHIVELOG:
        avisos.append("En NOARCHIVELOG solo se puede volver exactamente a un respaldo consistente, sin aplicar redo.")
    return PuntosRecuperacion(bd=bd, log_mode=log_mode, puntos=puntos, recuperable_desde=desde, avisos=avisos)
