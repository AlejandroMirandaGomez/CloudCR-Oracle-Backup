from dataclasses import dataclass, field
from datetime import datetime

from cloudcr_backup.domain.enums import LogMode, ModoRespaldo, Prioridad, TipoRespaldo
from cloudcr_backup.domain.estrategia import Programacion
from cloudcr_backup.domain.historial import FilaHistorial
from cloudcr_backup.domain.perfil_bd import PerfilBD


@dataclass(frozen=True)
class UsoDisco:
    total_bytes: int
    usados_bytes: int
    libres_bytes: int

    @property
    def porcentaje_uso(self) -> float:
        return self.usados_bytes / self.total_bytes * 100 if self.total_bytes else 0.0


@dataclass(frozen=True)
class BaseMonitoreada:
    bd_id: int
    nombre: str
    perfil: PerfilBD | None


@dataclass(frozen=True)
class ScriptVigente:
    script_id: int
    aprobado_en: datetime | None
    log_mode_al_crear: LogMode | None


@dataclass(frozen=True)
class TareaMonitoreada:
    tarea_id: int
    codigo: str
    tipo_respaldo: TipoRespaldo
    modo_respaldo: ModoRespaldo
    programacion: Programacion
    destino_ruta: str
    script: ScriptVigente | None
    ultimas: list[FilaHistorial] = field(default_factory=list)
    tamano_ultimo_exito: int | None = None
    ocurrencias_perdidas: list[datetime] = field(default_factory=list)

    @property
    def ultima_terminal(self) -> FilaHistorial | None:
        return next((fila for fila in self.ultimas if fila.terminal), None)

    @property
    def ultima_concluyente(self) -> FilaHistorial | None:
        return next((fila for fila in self.ultimas if fila.concluyente), None)


@dataclass(frozen=True)
class EstrategiaMonitoreada:
    estrategia_id: int
    bd_id: int
    bd_nombre: str
    codigo: str
    nombre: str
    prioridad: Prioridad
    alcance: list[str]
    purga_automatica: bool
    tareas: list[TareaMonitoreada]
    ultimo_exito: datetime | None = None
    piezas_vencidas: int = 0

    def sujeto(self, tarea: TareaMonitoreada | None = None) -> str:
        base = f"{self.bd_nombre}/{self.codigo}"
        return f"{base}/{tarea.codigo}" if tarea is not None else base


@dataclass(frozen=True)
class Instantanea:
    ahora: datetime
    bases: list[BaseMonitoreada]
    estrategias: list[EstrategiaMonitoreada]
    parametros: dict[str, str] = field(default_factory=dict)
    uso_disco: dict[str, UsoDisco | None] = field(default_factory=dict)

    def base(self, bd_id: int) -> BaseMonitoreada | None:
        return next((b for b in self.bases if b.bd_id == bd_id), None)
