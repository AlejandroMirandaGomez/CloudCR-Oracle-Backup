from contextlib import AbstractContextManager

import oracledb

from cloudcr_backup.config.ajustes import Ajustes


def abrir_repositorio(ajustes: Ajustes) -> oracledb.Connection:
    raise NotImplementedError


def transaccion(conexion: oracledb.Connection) -> AbstractContextManager[oracledb.Cursor]:
    raise NotImplementedError
