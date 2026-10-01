from collections.abc import Iterator
from contextlib import contextmanager

import oracledb

from cloudcr_backup.config.ajustes import Ajustes, obtener_clave_repositorio
from cloudcr_backup.oracle.connection import ParametrosConexionRemota, conectar_remota


class RepositorioNoConfigurado(RuntimeError):
    pass


def _manejador_tipos_salida(cursor: oracledb.Cursor, metadatos: oracledb.FetchInfo) -> oracledb.Var | None:
    if metadatos.type_code is oracledb.DB_TYPE_CLOB:
        return cursor.var(oracledb.DB_TYPE_LONG, arraysize=cursor.arraysize)
    return None


def abrir_repositorio(ajustes: Ajustes) -> oracledb.Connection:
    if not ajustes.repositorio_dsn:
        raise RepositorioNoConfigurado(
            "No hay un DSN configurado para el repositorio (variable CLOUDCR_REPOSITORIO_DSN o cloudcr.yaml)."
        )
    clave = obtener_clave_repositorio()
    if not clave:
        raise RepositorioNoConfigurado(
            "No hay clave configurada para el repositorio (variable CLOUDCR_REPO_CLAVE)."
        )
    conexion = conectar_remota(
        ParametrosConexionRemota(
            dsn=ajustes.repositorio_dsn,
            usuario=ajustes.repositorio_usuario,
            clave=clave,
            como_sysdba=False,
        )
    )
    conexion.outputtypehandler = _manejador_tipos_salida
    return conexion


@contextmanager
def transaccion(conexion: oracledb.Connection) -> Iterator[oracledb.Cursor]:
    cursor = conexion.cursor()
    try:
        yield cursor
        conexion.commit()
    except BaseException:
        conexion.rollback()
        raise
    finally:
        cursor.close()
