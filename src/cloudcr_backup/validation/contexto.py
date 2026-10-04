from datetime import UTC, datetime

from pydantic import BaseModel, Field

from cloudcr_backup.domain.estrategia import Estrategia
from cloudcr_backup.domain.perfil_bd import PerfilBD


class ContextoValidacion(BaseModel):
    estrategia: Estrategia
    perfil: PerfilBD
    ahora: datetime = Field(default_factory=lambda: datetime.now(UTC))
    parametros: dict[str, str] = Field(default_factory=dict)
    espacio_libre_destino_bytes: dict[str, int] = Field(default_factory=dict)
    espacio_total_destino_bytes: dict[str, int] = Field(default_factory=dict)
    espacio_estimado_bytes: dict[str, int] = Field(default_factory=dict)
    destinos_escribibles: dict[str, bool] = Field(default_factory=dict)
    ultimas_ejecuciones_exitosas: dict[str, datetime] = Field(default_factory=dict)
    codigos_estrategia_existentes: list[str] = Field(default_factory=list)
    repositorio_servicio: str | None = None


def servicio_de_dsn(dsn: str | None) -> str | None:
    if not dsn or "/" not in dsn:
        return None
    servicio = dsn.rsplit("/", 1)[1].strip()
    return servicio or None
