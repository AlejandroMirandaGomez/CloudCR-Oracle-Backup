import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Protocol

import pymysql
from pymysql.constants import CLIENT

from cloudcr_backup.config.ajustes import Ajustes, obtener_clave_repositorio

ErrorRepositorio = pymysql.MySQLError
ErrorIntegridad = pymysql.IntegrityError

MYSQL_ACCESO_DENEGADO = 1045
MYSQL_SIN_PERMISO_BASE = 1044
MYSQL_BASE_DESCONOCIDA = 1049
MYSQL_SIN_CONEXION_HOST = 2003
MYSQL_SIN_CONEXION_SOCKET = 2002
MYSQL_CONEXION_PERDIDA = 2013

SEGUNDOS_ESPERA_CONEXION = 10
SENTENCIA_AISLAMIENTO = "SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED"
SUGERENCIA_SERVICIO = (
    "Verifique que el servicio MySQL80 esté en ejecución (Get-Service MySQL80) y que host y puerto sean correctos."
)
SUGERENCIA_PREPARAR = "Ejecute 'cloudcr repo preparar' para crear la base y el usuario del repositorio."

PATRON_SQL = re.compile(r"('(?:[^']|'')*')|(?<![:\w]):([A-Za-z_]\w*)|(%)")


class RepositorioNoConfigurado(RuntimeError):
    pass


class ErrorConexionRepositorio(RuntimeError):
    def __init__(self, mensaje: str, sugerencia: str | None = None) -> None:
        super().__init__(mensaje)
        self.sugerencia = sugerencia


class Cursor(Protocol):
    @property
    def rowcount(self) -> int: ...

    @property
    def lastrowid(self) -> int: ...

    def execute(self, sql: str, **parametros: Any) -> None: ...

    def fetchone(self) -> Any: ...

    def fetchall(self) -> list[Any]: ...

    def close(self) -> None: ...


class Conexion(Protocol):
    def cursor(self) -> Cursor: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class ParametrosMySql:
    host: str
    puerto: int
    base: str | None
    usuario: str
    clave: str


def traducir_binds(sql: str) -> str:
    def sustituir(coincidencia: re.Match[str]) -> str:
        literal, bind, porcentaje = coincidencia.groups()
        if literal is not None:
            return literal.replace("%", "%%")
        if bind is not None:
            return f"%({bind})s"
        assert porcentaje is not None
        return "%%"

    return PATRON_SQL.sub(sustituir, sql)


class CursorMySql:
    def __init__(self, cursor: pymysql.cursors.Cursor) -> None:
        self._cursor = cursor

    @property
    def rowcount(self) -> int:
        return int(self._cursor.rowcount)

    @property
    def lastrowid(self) -> int:
        return int(self._cursor.lastrowid or 0)

    def execute(self, sql: str, **parametros: Any) -> None:
        self._cursor.execute(traducir_binds(sql), parametros)

    def fetchone(self) -> Any:
        return self._cursor.fetchone()

    def fetchall(self) -> list[Any]:
        return list(self._cursor.fetchall())

    def close(self) -> None:
        self._cursor.close()


class ConexionMySql:
    def __init__(self, conexion: pymysql.connections.Connection) -> None:
        self._conexion = conexion

    def cursor(self) -> CursorMySql:
        return CursorMySql(self._conexion.cursor())

    def commit(self) -> None:
        self._conexion.commit()

    def rollback(self) -> None:
        self._conexion.rollback()

    def close(self) -> None:
        self._conexion.close()


def _codigo_error(error: pymysql.MySQLError) -> int | None:
    codigo = error.args[0] if error.args else None
    return codigo if isinstance(codigo, int) else None


def _traducir_error(error: pymysql.MySQLError, parametros: ParametrosMySql) -> ErrorConexionRepositorio:
    destino = f"{parametros.host}:{parametros.puerto}"
    codigo = _codigo_error(error)
    if codigo == MYSQL_ACCESO_DENEGADO:
        return ErrorConexionRepositorio(
            f"MySQL rechazó el usuario {parametros.usuario} o su clave en {destino}.",
            "Revise CLOUDCR_REPOSITORIO_USUARIO y CLOUDCR_REPO_CLAVE en el archivo .env. "
            "Si el usuario aún no existe, ejecute 'cloudcr repo preparar'.",
        )
    if codigo == MYSQL_BASE_DESCONOCIDA:
        return ErrorConexionRepositorio(
            f"La base {parametros.base} no existe en {destino}.", SUGERENCIA_PREPARAR
        )
    if codigo == MYSQL_SIN_PERMISO_BASE:
        return ErrorConexionRepositorio(
            f"El usuario {parametros.usuario} no tiene permiso sobre la base {parametros.base}.",
            SUGERENCIA_PREPARAR,
        )
    if codigo in (MYSQL_SIN_CONEXION_HOST, MYSQL_SIN_CONEXION_SOCKET, MYSQL_CONEXION_PERDIDA):
        return ErrorConexionRepositorio(f"No se pudo llegar a MySQL en {destino}.", SUGERENCIA_SERVICIO)
    return ErrorConexionRepositorio(f"No se pudo conectar a MySQL en {destino}: {error}", SUGERENCIA_SERVICIO)


def conectar(parametros: ParametrosMySql) -> ConexionMySql:
    try:
        crudo = pymysql.connect(
            host=parametros.host,
            port=parametros.puerto,
            user=parametros.usuario,
            password=parametros.clave,
            database=parametros.base,
            charset="utf8mb4",
            autocommit=False,
            client_flag=CLIENT.FOUND_ROWS,
            init_command=SENTENCIA_AISLAMIENTO,
            connect_timeout=SEGUNDOS_ESPERA_CONEXION,
        )
    except pymysql.MySQLError as error:
        raise _traducir_error(error, parametros) from error
    return ConexionMySql(crudo)


def parametros_repositorio(ajustes: Ajustes) -> ParametrosMySql:
    clave = obtener_clave_repositorio()
    if not clave:
        raise RepositorioNoConfigurado("No hay clave configurada para el repositorio (variable CLOUDCR_REPO_CLAVE).")
    return ParametrosMySql(
        host=ajustes.repositorio_host,
        puerto=ajustes.repositorio_puerto,
        base=ajustes.repositorio_base,
        usuario=ajustes.repositorio_usuario,
        clave=clave,
    )


def abrir_repositorio(ajustes: Ajustes) -> Conexion:
    return conectar(parametros_repositorio(ajustes))


@contextmanager
def transaccion(conexion: Conexion) -> Iterator[Cursor]:
    cursor = conexion.cursor()
    try:
        yield cursor
        conexion.commit()
    except BaseException:
        conexion.rollback()
        raise
    finally:
        cursor.close()
