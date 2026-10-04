from datetime import UTC, datetime

from pydantic import BaseModel, Field

from cloudcr_backup.domain.enums import EstadoEjecucion, EstadoPrueba, ModoRespaldo, TipoRespaldo

LARGO_MAXIMO_MENSAJE = 4000
VERSION_FORMATO_EVIDENCIA = 1


def utc_ingenuo(momento: datetime | None) -> datetime | None:
    if momento is None or momento.tzinfo is None:
        return momento
    return momento.astimezone(UTC).replace(tzinfo=None)


class PiezaEvidencia(BaseModel):
    ruta: str
    tamano_bytes: int | None = None
    existe: bool = False
    tag: str | None = None
    conjunto: int | None = None
    vence_en: datetime | None = None


class PruebaEvidencia(BaseModel):
    tipo: str
    resultado: EstadoPrueba
    detalle: str | None = None
    ejecutada_en: datetime | None = None


class Evidencia(BaseModel):
    version_formato: int = VERSION_FORMATO_EVIDENCIA
    ejecucion_id: int
    bd: str
    bd_id: int
    estrategia: str
    estrategia_nombre: str
    tarea: str
    tarea_id: int
    tipo_respaldo: TipoRespaldo
    modo_respaldo: ModoRespaldo
    programada_para: datetime | None = None
    inicio: datetime | None = None
    fin: datetime | None = None
    duracion_segundos: int | None = None
    estado: EstadoEjecucion
    estado_prueba: EstadoPrueba = EstadoPrueba.PENDIENTE
    motivos: list[str] = Field(default_factory=list)
    mensaje_rman: str | None = None
    errores: list[str] = Field(default_factory=list)
    advertencias: list[str] = Field(default_factory=list)
    script_id: int | None = None
    script_version: int | None = None
    script_hash: str | None = None
    script_ruta: str | None = None
    log_rman: str | None = None
    log_verificacion: str | None = None
    tag: str | None = None
    command_id: str | None = None
    codigo_salida: int | None = None
    agente: str | None = None
    ubicacion: str | None = None
    piezas: list[PiezaEvidencia] = Field(default_factory=list)
    estado_job_rman: str | None = None
    reapertura_correcta: bool | None = None
    pruebas: list[PruebaEvidencia] = Field(default_factory=list)
    generado_en: datetime | None = None

    @property
    def archivos_generados(self) -> int:
        return len(self.piezas)

    @property
    def tamano_bytes(self) -> int:
        return sum(p.tamano_bytes or 0 for p in self.piezas)

    def resultado_repositorio(self) -> dict[str, object]:
        return {
            "estado": self.estado,
            "estado_prueba": self.estado_prueba,
            "fin": utc_ingenuo(self.fin),
            "ubicacion": self.ubicacion,
            "archivos_generados": self.archivos_generados,
            "tamano_bytes": self.tamano_bytes,
            "duracion_segundos": self.duracion_segundos,
            "mensaje_rman": (self.mensaje_rman or "")[:LARGO_MAXIMO_MENSAJE] or None,
            "errores": "\n".join(self.errores) or None,
            "advertencias": "\n".join(self.advertencias) or None,
        }


class ResultadoEjecucion(BaseModel):
    ejecucion_id: int
    estado: EstadoEjecucion
    estado_prueba: EstadoPrueba
    motivos: list[str] = Field(default_factory=list)
    carpeta: str | None = None
    evidencia: str | None = None
    en_buzon: bool = False
    piezas: list[PiezaEvidencia] = Field(default_factory=list)
    avisos: list[str] = Field(default_factory=list)
