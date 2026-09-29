from dataclasses import dataclass

import oracledb


@dataclass(frozen=True)
class EstadoEsquema:
    instalado: bool
    tablas: dict[str, int]


def instalar(conexion: oracledb.Connection) -> None:
    raise NotImplementedError


def estado(conexion: oracledb.Connection) -> EstadoEsquema:
    raise NotImplementedError
