from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

import oracledb

if TYPE_CHECKING:
    from cloudcr_backup.domain.enums import EstadoEjecucion


@dataclass(frozen=True)
class FiltrosHistorial:
    bd_id: int | None = None
    estrategia_codigo: str | None = None
    estado: "EstadoEjecucion | None" = None
    desde: datetime | None = None
    hasta: datetime | None = None


@dataclass(frozen=True)
class Ejecucion:
    id: int
    tarea_id: int
    script_id: int
    estado: "EstadoEjecucion"
    programada_para: datetime
    inicio: datetime | None
    fin: datetime | None


def reclamar(conexion: oracledb.Connection, tarea_id: int, programada_para: datetime) -> Ejecucion | None:
    raise NotImplementedError


def marcar_en_curso(conexion: oracledb.Connection, ejecucion_id: int, agente: str) -> None:
    raise NotImplementedError


def registrar_resultado(conexion: oracledb.Connection, ejecucion_id: int, resultado: dict[str, object]) -> None:
    raise NotImplementedError


def historial(conexion: oracledb.Connection, filtros: FiltrosHistorial) -> list[Ejecucion]:
    raise NotImplementedError


def ultimas(conexion: oracledb.Connection, tarea_id: int, n: int) -> list[Ejecucion]:
    raise NotImplementedError
