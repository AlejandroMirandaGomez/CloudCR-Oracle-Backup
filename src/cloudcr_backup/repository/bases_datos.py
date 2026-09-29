from dataclasses import dataclass
from enum import StrEnum

import oracledb

from cloudcr_backup.domain.perfil_bd import PerfilBD


class Ambiente(StrEnum):
    PRODUCCION = "PRODUCCION"
    PRUEBAS = "PRUEBAS"
    DESARROLLO = "DESARROLLO"


@dataclass(frozen=True)
class BaseDatosRegistrada:
    id: int
    nombre: str
    oracle_home: str
    ambiente: Ambiente
    activa: bool


def registrar(
    conexion: oracledb.Connection, nombre: str, oracle_home: str, ambiente: Ambiente
) -> BaseDatosRegistrada:
    raise NotImplementedError


def listar(conexion: oracledb.Connection) -> list[BaseDatosRegistrada]:
    raise NotImplementedError


def obtener(conexion: oracledb.Connection, nombre: str) -> BaseDatosRegistrada | None:
    raise NotImplementedError


def guardar_perfil(conexion: oracledb.Connection, bd_id: int, perfil: PerfilBD) -> None:
    raise NotImplementedError
