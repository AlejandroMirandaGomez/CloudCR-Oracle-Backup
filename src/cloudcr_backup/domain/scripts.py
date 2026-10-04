from datetime import datetime

from pydantic import BaseModel, Field

from cloudcr_backup.domain.enums import EstadoScript, ModoRespaldo
from cloudcr_backup.domain.hallazgos import Hallazgo


class FilaExplicacion(BaseModel):
    campo: str
    clausula: str


class VistaScript(BaseModel):
    bd: str
    estrategia: str
    tarea: str
    tarea_id: int
    script_id: int
    version: int
    estado: EstadoScript
    hash_sha256: str
    contenido: str
    modo: ModoRespaldo
    acepto_caida: bool = False
    aprobado_por: str | None = None
    aprobado_en: datetime | None = None
    creado_en: datetime | None = None
    motivo_rechazo: str | None = None
    archivo: str | None = None
    archivo_intacto: bool | None = None
    nueva: bool = False
    explicacion: list[FilaExplicacion] = Field(default_factory=list)
    hallazgos: list[Hallazgo] = Field(default_factory=list)
    avisos: list[str] = Field(default_factory=list)

    @property
    def requiere_caida(self) -> bool:
        return self.modo is ModoRespaldo.CONSISTENTE


class SimulacionEjecucion(BaseModel):
    bd: str
    estrategia: str
    tarea: str
    script_id: int
    version: int
    archivo: str
    contenido: str
    comando: str
    tag: str
    command_id: str
    aprobado: bool
    problemas: list[str] = Field(default_factory=list)
