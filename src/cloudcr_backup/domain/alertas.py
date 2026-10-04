from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel

from cloudcr_backup.domain.enums import EstadoAlerta

LARGO_MAXIMO_CLAVE_DEDUP = 200


class SeveridadAlerta(StrEnum):
    ALERTA = "ALERTA"
    ADVERTENCIA = "ADVERTENCIA"
    RECOMENDACION = "RECOMENDACION"


ORDEN_SEVERIDAD_ALERTA = [SeveridadAlerta.ALERTA, SeveridadAlerta.ADVERTENCIA, SeveridadAlerta.RECOMENDACION]

ESTADOS_VIGENTES = (EstadoAlerta.ABIERTA, EstadoAlerta.RECONOCIDA)


def alcanza(severidad: SeveridadAlerta, minima: SeveridadAlerta) -> bool:
    return ORDEN_SEVERIDAD_ALERTA.index(severidad) <= ORDEN_SEVERIDAD_ALERTA.index(minima)


class CodigoAlerta(StrEnum):
    BD_NOARCHIVELOG = "BD_NOARCHIVELOG"
    ESTRATEGIA_SIN_PROGRAMACION = "ESTRATEGIA_SIN_PROGRAMACION"
    RESPALDO_NO_EJECUTADO = "RESPALDO_NO_EJECUTADO"
    EJECUCION_FALLIDA = "EJECUCION_FALLIDA"
    EJECUCION_BLOQUEADA = "EJECUCION_BLOQUEADA"
    VERIFICACION_FALLIDA = "VERIFICACION_FALLIDA"
    ESPACIO_INSUFICIENTE = "ESPACIO_INSUFICIENTE"
    SIN_RESPALDO_RECIENTE = "SIN_RESPALDO_RECIENTE"
    MODO_ARCHIVADO_CAMBIO = "MODO_ARCHIVADO_CAMBIO"
    RETENCION_VENCIDA = "RETENCION_VENCIDA"
    ARCHIVELOG_ACUMULADO = "ARCHIVELOG_ACUMULADO"
    SCRIPT_ALTERADO = "SCRIPT_ALTERADO"
    BASE_NO_REABIERTA = "BASE_NO_REABIERTA"


class Condicion(BaseModel):
    codigo_regla: str
    sujeto: str
    severidad: SeveridadAlerta
    mensaje: str
    accion_sugerida: str | None = None
    bd_id: int | None = None
    estrategia_id: int | None = None
    tarea_id: int | None = None
    ejecucion_id: int | None = None
    alcance: list[str] = []

    @property
    def clave_dedup(self) -> str:
        return f"{self.codigo_regla}:{self.sujeto}"[:LARGO_MAXIMO_CLAVE_DEDUP]


class VistaAlerta(BaseModel):
    id: int
    codigo: str
    clave_dedup: str
    severidad: SeveridadAlerta
    estado: EstadoAlerta
    mensaje: str
    accion_sugerida: str | None = None
    bd: str | None = None
    estrategia: str | None = None
    tarea: str | None = None
    bd_id: int | None = None
    estrategia_id: int | None = None
    tarea_id: int | None = None
    ejecucion_id: int | None = None
    abierta_en: datetime | None = None
    resuelta_en: datetime | None = None

    @property
    def vigente(self) -> bool:
        return self.estado in ESTADOS_VIGENTES


class ResumenEvaluacion(BaseModel):
    evaluada_en: datetime
    abiertas: list[str] = []
    actualizadas: list[str] = []
    resueltas: list[str] = []
    notificadas: list[str] = []
    errores: list[str] = []


class EstadoCorreo(BaseModel):
    canal_activo: bool
    configurado: bool
    servidor: str | None = None
    puerto: int | None = None
    remitente: str | None = None
    destinatarios: list[str] = []
    severidad_minima: str | None = None
    clave_definida: bool = False
    problema: str | None = None


class ResultadoPruebaCorreo(BaseModel):
    enviado_en: datetime
    servidor: str
    destinatarios: list[str]


class ResultadoConfiguracionCorreo(BaseModel):
    archivo: str
    aplicados: list[str] = []
    conservados: list[str] = []
