from typing import TYPE_CHECKING

import oracledb

if TYPE_CHECKING:
    from cloudcr_backup.domain.estrategia import Estrategia


def crear(conexion: oracledb.Connection, estrategia: "Estrategia") -> "Estrategia":
    raise NotImplementedError


def actualizar(conexion: oracledb.Connection, estrategia: "Estrategia") -> "Estrategia":
    raise NotImplementedError


def listar(conexion: oracledb.Connection, bd_id: int) -> list["Estrategia"]:
    raise NotImplementedError


def obtener(conexion: oracledb.Connection, bd_id: int, codigo: str) -> "Estrategia | None":
    raise NotImplementedError


def activar(conexion: oracledb.Connection, bd_id: int, codigo: str) -> None:
    raise NotImplementedError


def desactivar(conexion: oracledb.Connection, bd_id: int, codigo: str) -> None:
    raise NotImplementedError
