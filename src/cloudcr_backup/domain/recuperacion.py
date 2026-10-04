from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from cloudcr_backup.domain.enums import EstadoPrueba, LogMode, TipoRespaldo


class Escenario(StrEnum):
    PDB = "pdb"
    TABLESPACE = "tablespace"
    DATAFILE = "datafile"
    CONTROLFILE = "controlfile"
    TOTAL_NOARCHIVELOG = "total-noarchivelog"
    PUNTO_EN_TIEMPO = "punto-en-tiempo"


class ArchivoDanado(BaseModel):
    file_id: int
    ruta: str
    tablespace: str | None = None
    contenedor: str | None = None
    estado: str
    error: str | None = None
    cambio: int | None = None
    origen: str

    @property
    def identificador_tablespace(self) -> str | None:
        if self.tablespace is None:
            return None
        if self.contenedor in (None, "", "CDB$ROOT"):
            return self.tablespace
        return f"{self.contenedor}:{self.tablespace}"

    @property
    def pdb(self) -> str | None:
        return None if self.contenedor in (None, "", "CDB$ROOT") else self.contenedor


class Diagnostico(BaseModel):
    bd: str
    generado_en: datetime
    log_mode: LogMode | None = None
    open_mode: str | None = None
    archivos: list[ArchivoDanado] = Field(default_factory=list)
    avisos: list[str] = Field(default_factory=list)

    @property
    def sin_danos(self) -> bool:
        return not self.archivos


class PuntoRecuperacion(BaseModel):
    ejecucion_id: int
    estrategia: str
    tarea: str
    tipo_respaldo: TipoRespaldo
    completado_en: datetime | None = None
    alcance: list[str] = Field(default_factory=list)
    base_completa: bool = False
    estado_prueba: EstadoPrueba = EstadoPrueba.PENDIENTE
    piezas: int = 0
    tamano_bytes: int = 0
    tag: str | None = None
    controlfile: str | None = None


class PuntosRecuperacion(BaseModel):
    bd: str
    log_mode: LogMode | None = None
    puntos: list[PuntoRecuperacion] = Field(default_factory=list)
    recuperable_desde: datetime | None = None
    avisos: list[str] = Field(default_factory=list)


class Procedimiento(BaseModel):
    bd: str
    escenario: Escenario
    posible: bool
    motivo: str
    objetivo: str | None = None
    pasos: list[str] = Field(default_factory=list)
    script: str | None = None
    archivo: str | None = None
    avisos: list[str] = Field(default_factory=list)
