from dataclasses import dataclass
from datetime import datetime

from cloudcr_backup.domain.enums import ModoRespaldo, TipoRespaldo
from cloudcr_backup.domain.estrategia import Programacion


@dataclass(frozen=True)
class TareaProgramable:
    tarea_id: int
    bd_id: int
    bd_nombre: str
    estrategia_id: int
    estrategia_codigo: str
    tarea_codigo: str
    tipo_respaldo: TipoRespaldo
    modo_respaldo: ModoRespaldo
    programacion: Programacion
    script_id: int
    aprobado_en: datetime | None

    @property
    def etiqueta(self) -> str:
        return f"{self.bd_nombre} {self.estrategia_codigo}/{self.tarea_codigo}"


@dataclass(frozen=True)
class EjecucionReclamada:
    ejecucion_id: int
    tarea_id: int
    programada_para: datetime
    tardia: bool = False


@dataclass(frozen=True)
class EjecucionPendiente:
    ejecucion_id: int
    tarea_id: int
    programada_para: datetime


@dataclass(frozen=True)
class OcurrenciaPerdida:
    tarea_id: int
    programada_para: datetime
    motivo: str


@dataclass(frozen=True)
class ResultadoPlanificacion:
    reclamadas: list[EjecucionReclamada]
    no_ejecutadas: list[OcurrenciaPerdida]
    huerfanas: list[EjecucionPendiente]
    errores: list[str]
