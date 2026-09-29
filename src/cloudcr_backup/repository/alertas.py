from dataclasses import dataclass
from typing import TYPE_CHECKING

import oracledb

if TYPE_CHECKING:
    from cloudcr_backup.domain.enums import EstadoAlerta


@dataclass(frozen=True)
class Alerta:
    id: int
    codigo: str
    clave_dedup: str
    estado: "EstadoAlerta"
    mensaje: str


def upsert_abierta(conexion: oracledb.Connection, codigo: str, clave_dedup: str, mensaje: str) -> Alerta:
    raise NotImplementedError


def abiertas(conexion: oracledb.Connection, codigos: list[str] | None = None) -> list[Alerta]:
    raise NotImplementedError


def resolver(conexion: oracledb.Connection, alerta_id: int) -> None:
    raise NotImplementedError


def reconocer(conexion: oracledb.Connection, alerta_id: int) -> None:
    raise NotImplementedError
