from dataclasses import dataclass

from cloudcr_backup.domain.alertas import SeveridadAlerta, VistaAlerta
from cloudcr_backup.domain.enums import EstadoAlerta
from cloudcr_backup.domain.monitoreo import ColorSemaforo, EstadoAgente, EstadoGeneral, SemaforoEstrategia
from cloudcr_backup.presentacion.formato import Tono
from cloudcr_backup.presentacion.historial import local

ETIQUETA_COLOR = {
    ColorSemaforo.VERDE: "Verde",
    ColorSemaforo.AMARILLO: "Amarillo",
    ColorSemaforo.ROJO: "Rojo",
    ColorSemaforo.SIN_DATOS: "Sin datos",
}

SIMBOLO_COLOR = {
    ColorSemaforo.VERDE: "●",
    ColorSemaforo.AMARILLO: "▲",
    ColorSemaforo.ROJO: "✕",
    ColorSemaforo.SIN_DATOS: "○",
}

TONO_COLOR = {
    ColorSemaforo.VERDE: Tono.EXITO,
    ColorSemaforo.AMARILLO: Tono.ADVERTENCIA,
    ColorSemaforo.ROJO: Tono.PELIGRO,
    ColorSemaforo.SIN_DATOS: Tono.ATENUADO,
}

ETIQUETA_SEVERIDAD_ALERTA = {
    SeveridadAlerta.ALERTA: "ALERTA",
    SeveridadAlerta.ADVERTENCIA: "ADVERTENCIA",
    SeveridadAlerta.RECOMENDACION: "RECOMENDACIÓN",
}

TONO_SEVERIDAD_ALERTA = {
    SeveridadAlerta.ALERTA: Tono.PELIGRO,
    SeveridadAlerta.ADVERTENCIA: Tono.ADVERTENCIA,
    SeveridadAlerta.RECOMENDACION: Tono.DATO,
}

ETIQUETA_ESTADO_ALERTA = {
    EstadoAlerta.ABIERTA: "Abierta",
    EstadoAlerta.RECONOCIDA: "Reconocida",
    EstadoAlerta.RESUELTA: "Resuelta",
}

REGLA_SEMAFORO = (
    "Rojo: hay una alerta de severidad ALERTA vigente de la estrategia, o la última ejecución de alguna tarea "
    "terminó con error, bloqueada o no se ejecutó. Amarillo: hay una ADVERTENCIA vigente, la última ejecución "
    "terminó con advertencias o sus pruebas están pendientes o fallidas. Verde: el resto. Sin datos: estrategia "
    "inactiva o sin ninguna tarea con script aprobado."
)


@dataclass(frozen=True)
class FilaSemaforo:
    bd: str
    estrategia: str
    nombre: str
    prioridad: str
    color: ColorSemaforo
    etiqueta: str
    simbolo: str
    tono: Tono
    motivos: list[str]
    ultima: str
    proxima: str
    alertas: int


@dataclass(frozen=True)
class FilaAgente:
    hostname: str
    pid: int
    estado: str
    vivo: bool
    ultimo_tick: str
    segundos_desde_tick: int
    simulado: bool


def fila_semaforo(semaforo: SemaforoEstrategia, zona_horaria: str) -> FilaSemaforo:
    ultima = semaforo.ultimas[0] if semaforo.ultimas else None
    texto_ultima = "—"
    if ultima is not None:
        texto_ultima = f"{local(ultima.programada_para, ultima.zona_horaria):%Y-%m-%d %H:%M} {ultima.tarea}"
    proxima = (
        f"{local(semaforo.proxima_ejecucion, zona_horaria):%Y-%m-%d %H:%M}" if semaforo.proxima_ejecucion else "—"
    )
    return FilaSemaforo(
        bd=semaforo.bd,
        estrategia=semaforo.estrategia,
        nombre=semaforo.nombre,
        prioridad=semaforo.prioridad.value,
        color=semaforo.color,
        etiqueta=ETIQUETA_COLOR[semaforo.color],
        simbolo=SIMBOLO_COLOR[semaforo.color],
        tono=TONO_COLOR[semaforo.color],
        motivos=semaforo.motivos,
        ultima=texto_ultima,
        proxima=proxima,
        alertas=semaforo.alertas_vigentes,
    )


def fila_agente(agente: EstadoAgente, zona_horaria: str) -> FilaAgente:
    return FilaAgente(
        hostname=agente.latido.hostname,
        pid=agente.latido.pid,
        estado="activo" if agente.vivo else f"detenido ({agente.latido.estado.value})",
        vivo=agente.vivo,
        ultimo_tick=f"{local(agente.latido.ultimo_tick, zona_horaria):%Y-%m-%d %H:%M:%S}",
        segundos_desde_tick=agente.segundos_desde_tick,
        simulado=agente.latido.simulado,
    )


def fila_alerta(alerta: VistaAlerta, zona_horaria: str) -> dict[str, str]:
    donde = " ".join(p for p in (alerta.bd, alerta.estrategia, alerta.tarea) if p)
    return {
        "id": str(alerta.id),
        "severidad": ETIQUETA_SEVERIDAD_ALERTA[alerta.severidad],
        "codigo": alerta.codigo,
        "estado": ETIQUETA_ESTADO_ALERTA[alerta.estado],
        "donde": donde or "—",
        "mensaje": alerta.mensaje,
        "abierta": f"{local(alerta.abierta_en, zona_horaria):%Y-%m-%d %H:%M}" if alerta.abierta_en else "—",
    }


def resumen_colores(estado: EstadoGeneral) -> dict[ColorSemaforo, int]:
    conteo = dict.fromkeys(ColorSemaforo, 0)
    for semaforo in estado.semaforos:
        conteo[semaforo.color] += 1
    return conteo
