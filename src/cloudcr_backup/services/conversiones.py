import shutil
from datetime import datetime
from pathlib import Path

from cloudcr_backup.alerts.instantanea import UsoDisco
from cloudcr_backup.alerts.reglas import descripcion
from cloudcr_backup.domain.alertas import SeveridadAlerta, VistaAlerta
from cloudcr_backup.domain.enums import ModoRespaldo, TipoRespaldo
from cloudcr_backup.domain.estrategia import ObjetoAlcance
from cloudcr_backup.domain.historial import FilaHistorial
from cloudcr_backup.repository.alertas import AlertaDetallada
from cloudcr_backup.repository.ejecuciones import EjecucionDetallada
from cloudcr_backup.scheduling.reloj import utc_consciente


def momento_utc(valor: datetime | None) -> datetime | None:
    return None if valor is None else utc_consciente(valor)


def _modo(valor: str) -> ModoRespaldo | None:
    try:
        return ModoRespaldo(valor)
    except ValueError:
        return None


def fila_historial(ejecucion: EjecucionDetallada) -> FilaHistorial:
    return FilaHistorial(
        ejecucion_id=ejecucion.id,
        bd=ejecucion.bd_nombre,
        bd_id=ejecucion.bd_id,
        estrategia=ejecucion.estrategia_codigo,
        estrategia_id=ejecucion.estrategia_id,
        estrategia_nombre=ejecucion.estrategia_nombre,
        tarea=ejecucion.tarea_codigo,
        tarea_id=ejecucion.tarea_id,
        tipo_respaldo=TipoRespaldo(ejecucion.tipo_respaldo),
        modo_respaldo=_modo(ejecucion.modo_respaldo),
        estado=ejecucion.estado,
        estado_prueba=ejecucion.estado_prueba,
        programada_para=utc_consciente(ejecucion.programada_para),
        inicio=momento_utc(ejecucion.inicio),
        fin=momento_utc(ejecucion.fin),
        duracion_segundos=ejecucion.duracion_segundos,
        tamano_bytes=ejecucion.tamano_bytes,
        archivos_generados=ejecucion.archivos_generados,
        ubicacion=ejecucion.ubicacion,
        zona_horaria=ejecucion.zona_horaria,
        mensaje=ejecucion.mensaje_rman,
        agente=ejecucion.agente,
    )


def _severidad(valor: str) -> SeveridadAlerta:
    try:
        return SeveridadAlerta(valor)
    except ValueError:
        return SeveridadAlerta.ADVERTENCIA


def vista_alerta(alerta: AlertaDetallada) -> VistaAlerta:
    catalogo = descripcion(alerta.codigo)
    return VistaAlerta(
        id=alerta.id,
        codigo=alerta.codigo,
        clave_dedup=alerta.clave_dedup,
        severidad=_severidad(alerta.severidad),
        estado=alerta.estado,
        mensaje=alerta.mensaje,
        accion_sugerida=catalogo.accion if catalogo else None,
        bd=alerta.bd_nombre,
        estrategia=alerta.estrategia_codigo,
        tarea=alerta.tarea_codigo,
        bd_id=alerta.bd_id,
        estrategia_id=alerta.estrategia_id,
        tarea_id=alerta.tarea_id,
        ejecucion_id=alerta.ejecucion_id,
        abierta_en=momento_utc(alerta.abierta_en),
        resuelta_en=momento_utc(alerta.resuelta_en),
    )


def etiquetas_alcance(alcance: list[ObjetoAlcance]) -> list[str]:
    return [objeto.identificador or objeto.tipo.value for objeto in alcance]


def uso_disco(ruta: str) -> UsoDisco | None:
    camino = Path(ruta)
    if not camino.is_absolute():
        return None
    for candidato in (camino, *camino.parents):
        if not candidato.exists():
            continue
        try:
            uso = shutil.disk_usage(candidato)
        except OSError:
            return None
        return UsoDisco(total_bytes=uso.total, usados_bytes=uso.used, libres_bytes=uso.free)
    return None
