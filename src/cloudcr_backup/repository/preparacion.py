import re
from dataclasses import dataclass

from cloudcr_backup.config.ajustes import Ajustes, obtener_credenciales_admin_mysql
from cloudcr_backup.repository.conexion import (
    Conexion,
    ErrorConexionRepositorio,
    ErrorRepositorio,
    ParametrosMySql,
    RepositorioNoConfigurado,
    conectar,
    parametros_repositorio,
)

PATRON_NOMBRE_BASE = re.compile(r"[A-Za-z0-9_]{1,64}")
PATRON_NOMBRE_USUARIO = re.compile(r"[A-Za-z0-9_]{1,32}")
HOSTS_LOCALES = frozenset({"localhost", "127.0.0.1", "::1"})
PRIVILEGIOS = "SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, ALTER, INDEX, REFERENCES"
SUGERENCIA_ADMINISTRADOR = (
    "Defina CLOUDCR_MYSQL_ADMIN_CLAVE (y CLOUDCR_MYSQL_ADMIN_USUARIO si no es root) en .env.local, "
    "o cree la base y el usuario a mano (vea COMO_EJECUTAR.md)."
)


@dataclass(frozen=True)
class ResultadoPreparacion:
    base: str
    usuario: str
    ya_preparado: bool


def _validar_nombres(parametros: ParametrosMySql) -> str:
    if parametros.base is None or PATRON_NOMBRE_BASE.fullmatch(parametros.base) is None:
        raise ErrorConexionRepositorio(
            f"El nombre de la base {parametros.base!r} no es válido.",
            "Use solo letras, números y guion bajo (hasta 64 caracteres) en CLOUDCR_REPOSITORIO_BASE.",
        )
    if PATRON_NOMBRE_USUARIO.fullmatch(parametros.usuario) is None:
        raise ErrorConexionRepositorio(
            f"El nombre de usuario {parametros.usuario!r} no es válido.",
            "Use solo letras, números y guion bajo (hasta 32 caracteres) en CLOUDCR_REPOSITORIO_USUARIO.",
        )
    return parametros.base


def _repositorio_accesible(parametros: ParametrosMySql) -> bool:
    try:
        conexion = conectar(parametros)
    except ErrorConexionRepositorio:
        return False
    conexion.close()
    return True


def _crear_base_y_usuario(administrador: Conexion, parametros: ParametrosMySql, base: str) -> None:
    host_cliente = "localhost" if parametros.host in HOSTS_LOCALES else "%"
    identidad = {"usuario": parametros.usuario, "host": host_cliente, "clave": parametros.clave}
    base_para_privilegios = base.replace("_", "\\_")
    cursor = administrador.cursor()
    try:
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{base}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin")
        cursor.execute("CREATE USER IF NOT EXISTS :usuario@:host IDENTIFIED BY :clave", **identidad)
        cursor.execute("ALTER USER :usuario@:host IDENTIFIED BY :clave", **identidad)
        cursor.execute(
            f"GRANT {PRIVILEGIOS} ON `{base_para_privilegios}`.* TO :usuario@:host",
            usuario=parametros.usuario,
            host=host_cliente,
        )
        administrador.commit()
    finally:
        cursor.close()


def preparar(ajustes: Ajustes) -> ResultadoPreparacion:
    try:
        parametros = parametros_repositorio(ajustes)
    except RepositorioNoConfigurado as error:
        raise ErrorConexionRepositorio(str(error), "Defina CLOUDCR_REPO_CLAVE en el archivo .env.") from error
    base = _validar_nombres(parametros)
    if _repositorio_accesible(parametros):
        return ResultadoPreparacion(base=base, usuario=parametros.usuario, ya_preparado=True)
    usuario_admin, clave_admin = obtener_credenciales_admin_mysql()
    if not clave_admin:
        raise ErrorConexionRepositorio(
            "La base o el usuario del repositorio no existen y falta la clave del administrador de MySQL "
            "para crearlos.",
            SUGERENCIA_ADMINISTRADOR,
        )
    administrador = conectar(
        ParametrosMySql(
            host=parametros.host, puerto=parametros.puerto, base=None, usuario=usuario_admin, clave=clave_admin
        )
    )
    try:
        _crear_base_y_usuario(administrador, parametros, base)
    except ErrorRepositorio as error:
        raise ErrorConexionRepositorio(
            f"MySQL no permitió crear la base o el usuario del repositorio: {error}",
            "Verifique que el usuario administrador tenga privilegios para crear bases y usuarios.",
        ) from error
    finally:
        administrador.close()
    if not _repositorio_accesible(parametros):
        raise ErrorConexionRepositorio(
            f"Se creó la base {base}, pero el usuario {parametros.usuario} no pudo conectarse.",
            "Revise CLOUDCR_REPOSITORIO_USUARIO y CLOUDCR_REPO_CLAVE.",
        )
    return ResultadoPreparacion(base=base, usuario=parametros.usuario, ya_preparado=False)
