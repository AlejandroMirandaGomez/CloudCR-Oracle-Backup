from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import oracledb

from cloudcr_backup.domain.perfil_bd import PerfilBD
from cloudcr_backup.execution.correlator import Consulta
from cloudcr_backup.oracle.connection import ParametrosConexionLocal, conectar_local
from cloudcr_backup.oracle.inspector import inspeccionar

MODO_ABIERTA = "READ WRITE"
SQL_APERTURA_BD = "SELECT open_mode FROM v$database"
SQL_APERTURA_PDB = "SELECT name, open_mode FROM v$pdbs WHERE name <> 'PDB$SEED'"


@dataclass(frozen=True)
class BaseDestino:
    oracle_home: Path
    sid: str


@dataclass(frozen=True)
class EstadoApertura:
    abierta: bool
    detalle: str


@contextmanager
def conexion_destino(base: BaseDestino) -> Iterator[oracledb.Connection]:
    conexion = conectar_local(ParametrosConexionLocal(oracle_home=base.oracle_home, sid=base.sid))
    try:
        yield conexion
    finally:
        with suppress(oracledb.Error):
            conexion.close()


def consulta_de(conexion: oracledb.Connection) -> Consulta:
    def consultar(sql: str, parametros: dict[str, Any]) -> list[tuple[Any, ...]]:
        cursor = conexion.cursor()
        try:
            cursor.execute(sql, **parametros)
            return list(cursor.fetchall())
        finally:
            cursor.close()

    return consultar


@contextmanager
def consulta_destino(base: BaseDestino) -> Iterator[Consulta]:
    with conexion_destino(base) as conexion:
        yield consulta_de(conexion)


def perfil_actual(base: BaseDestino) -> PerfilBD:
    with conexion_destino(base) as conexion:
        return inspeccionar(conexion, str(base.oracle_home))


def estado_apertura(consulta: Consulta) -> EstadoApertura:
    filas = consulta(SQL_APERTURA_BD, {})
    modo_bd = str(filas[0][0]) if filas else "DESCONOCIDO"
    if modo_bd != MODO_ABIERTA:
        return EstadoApertura(False, f"La base de datos está en modo {modo_bd}.")
    cerradas = [f"{nombre} ({modo})" for nombre, modo in consulta(SQL_APERTURA_PDB, {}) if str(modo) != MODO_ABIERTA]
    if cerradas:
        return EstadoApertura(False, "PDB sin abrir en lectura y escritura: " + ", ".join(cerradas) + ".")
    return EstadoApertura(True, "La base de datos y sus PDB están abiertas en lectura y escritura.")


def estado_apertura_destino(base: BaseDestino) -> EstadoApertura:
    with consulta_destino(base) as consulta:
        return estado_apertura(consulta)
