from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel

from cloudcr_backup.domain.alertas import VistaAlerta
from cloudcr_backup.domain.enums import EstadoEstrategia, ModoRespaldo, Prioridad, TipoRespaldo
from cloudcr_backup.domain.estrategia import Estrategia, Programacion
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


class ScriptResumen(BaseModel):
    script_id: int
    version: int
    aprobado_por: str | None = None
    aprobado_en: datetime | None = None


class TareaDetalle(BaseModel):
    codigo: str
    tarea_id: int | None = None
    tipo_respaldo: TipoRespaldo
    etiqueta_tipo: str
    termino_clase: str
    modo_respaldo: ModoRespaldo
    programacion: Programacion
    descripcion_programacion: str
    destino: str
    script: ScriptResumen | None = None
    proximas: list[datetime] = []
    error_programacion: str | None = None


class ResumenEstrategia(BaseModel):
    bd: str
    bd_id: int
    estrategia_id: int | None = None
    codigo: str
    nombre: str
    prioridad: Prioridad
    estado: EstadoEstrategia
    version: int
    tareas: int
    tareas_con_script: int
    color: ColorSemaforo = ColorSemaforo.SIN_DATOS
    proxima_ejecucion: datetime | None = None


class DetalleEstrategia(BaseModel):
    resumen: ResumenEstrategia
    estrategia: Estrategia
    rpo_horas: float
    rto_horas: float
    recencia_maxima_horas: float
    tareas: list[TareaDetalle] = []
    retencion: str
    alcance: list[str] = []
