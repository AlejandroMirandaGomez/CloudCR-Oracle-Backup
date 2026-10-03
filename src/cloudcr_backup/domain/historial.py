from datetime import datetime

from pydantic import BaseModel

from cloudcr_backup.domain.enums import EstadoEjecucion, EstadoPrueba, ModoRespaldo, TipoRespaldo

ESTADOS_TERMINALES = (
    EstadoEjecucion.EXITOSA,
    EstadoEjecucion.CON_ADVERTENCIAS,
    EstadoEjecucion.FALLIDA,
    EstadoEjecucion.NO_EJECUTADA,
    EstadoEjecucion.BLOQUEADA,
    EstadoEjecucion.CANCELADA,
)

ESTADOS_CORRECTOS = (EstadoEjecucion.EXITOSA, EstadoEjecucion.CON_ADVERTENCIAS)


class FilaHistorial(BaseModel):
    ejecucion_id: int
    bd: str
    bd_id: int
    estrategia: str
    estrategia_id: int
    estrategia_nombre: str
    tarea: str
    tarea_id: int
    tipo_respaldo: TipoRespaldo
    modo_respaldo: ModoRespaldo | None = None
    estado: EstadoEjecucion
    estado_prueba: EstadoPrueba
    programada_para: datetime
    inicio: datetime | None = None
    fin: datetime | None = None
    duracion_segundos: int | None = None
    tamano_bytes: int | None = None
    archivos_generados: int | None = None
    ubicacion: str | None = None
    zona_horaria: str
    mensaje: str | None = None
    agente: str | None = None

    @property
    def terminal(self) -> bool:
        return self.estado in ESTADOS_TERMINALES

    @property
    def concluyente(self) -> bool:
        if not self.terminal:
            return False
        return not (self.estado in ESTADOS_CORRECTOS and self.estado_prueba is EstadoPrueba.PENDIENTE)


class PiezaRespaldo(BaseModel):
    nombre_archivo: str
    tamano_bytes: int | None = None
    tag: str | None = None
    vence_en: datetime | None = None
    obsoleta: bool = False


class VerificacionEjecucion(BaseModel):
    tipo_prueba: str
    resultado: EstadoPrueba
    detalle: str | None = None
    ejecutada_en: datetime | None = None


class LogRman(BaseModel):
    ruta: str
    existe: bool
    primeras_lineas: list[str] = []
    ultimas_lineas: list[str] = []


class DetalleEjecucion(BaseModel):
    fila: FilaHistorial
    script_id: int | None = None
    script_version: int | None = None
    script_hash: str | None = None
    script_aprobado_por: str | None = None
    script_aprobado_en: datetime | None = None
    errores: str | None = None
    advertencias: str | None = None
    piezas: list[PiezaRespaldo] = []
    verificaciones: list[VerificacionEjecucion] = []
    evidencia: dict[str, object] | None = None
    ruta_evidencia: str | None = None
    log_rman: LogRman | None = None
    avisos: list[str] = []
