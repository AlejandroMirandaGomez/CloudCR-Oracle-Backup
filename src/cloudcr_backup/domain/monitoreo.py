from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel

from cloudcr_backup.domain.alertas import VistaAlerta
from cloudcr_backup.domain.enums import EstadoEstrategia, Prioridad
from cloudcr_backup.domain.historial import FilaHistorial


class ColorSemaforo(StrEnum):
    VERDE = "VERDE"
    AMARILLO = "AMARILLO"
    ROJO = "ROJO"
    SIN_DATOS = "SIN_DATOS"


class EstadoLatido(StrEnum):
    INICIANDO = "iniciando"
    ACTIVO = "activo"
    DETENIENDO = "deteniendo"
    DETENIDO = "detenido"


class Latido(BaseModel):
    hostname: str
    pid: int
    iniciado_en: datetime
    ultimo_tick: datetime
    estado: EstadoLatido
    version: str
    simulado: bool = False


class EstadoAgente(BaseModel):
    latido: Latido
    vivo: bool
    segundos_desde_tick: int


class SemaforoEstrategia(BaseModel):
    bd: str
    bd_id: int
    estrategia: str
    estrategia_id: int
    nombre: str
    prioridad: Prioridad
    estado: EstadoEstrategia
    color: ColorSemaforo
    motivos: list[str] = []
    ultimas: list[FilaHistorial] = []
    proxima_ejecucion: datetime | None = None
    alertas_vigentes: int = 0


class EstadoGeneral(BaseModel):
    generado_en: datetime
    semaforos: list[SemaforoEstrategia] = []
    en_curso: list[FilaHistorial] = []
    alertas: list[VistaAlerta] = []
    agentes: list[EstadoAgente] = []
    tick_segundos: int
