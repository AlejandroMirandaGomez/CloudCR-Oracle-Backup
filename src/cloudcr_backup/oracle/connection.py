import os
import sys
from dataclasses import dataclass
from pathlib import Path

import oracledb

ORA_PRIVILEGIOS_INSUFICIENTES = 1031
ORA_INSTANCIA_NO_DISPONIBLE = 1034
ORA_ADAPTADOR_PROTOCOLO = 12560
ORA_USUARIO_CLAVE_INVALIDOS = 1017
ORA_SIN_LISTENER = 12541
ORA_SERVICIO_DESCONOCIDO = 12514

_cliente_thick_iniciado: Path | None = None


class ErrorConexionOracle(RuntimeError):
    def __init__(self, mensaje: str, sugerencia: str | None = None) -> None:
        super().__init__(mensaje)
        self.sugerencia = sugerencia


@dataclass(frozen=True)
class ParametrosConexionLocal:
    oracle_home: Path
    sid: str


@dataclass(frozen=True)
class ParametrosConexionRemota:
    dsn: str
    usuario: str
    clave: str
    como_sysdba: bool


def directorio_bibliotecas(oracle_home: Path) -> Path | None:
    if sys.platform == "win32":
        return oracle_home / "bin"
    if sys.platform == "darwin":
        return oracle_home / "lib"
    return None


def iniciar_cliente_thick(oracle_home: Path) -> None:
    global _cliente_thick_iniciado
    if _cliente_thick_iniciado is not None:
        if _cliente_thick_iniciado != oracle_home:
            raise ErrorConexionOracle(
                f"El cliente Oracle ya se inició con {_cliente_thick_iniciado}; no se puede cambiar a {oracle_home}",
                "Ejecute el comando de nuevo indicando solo una instancia por proceso.",
            )
        return
    os.environ["ORACLE_HOME"] = str(oracle_home)
    biblioteca = directorio_bibliotecas(oracle_home)
    try:
        if biblioteca is None:
            oracledb.init_oracle_client()
        else:
            oracledb.init_oracle_client(lib_dir=str(biblioteca))
    except oracledb.Error as error:
        raise ErrorConexionOracle(
            f"No se pudieron cargar las bibliotecas del cliente Oracle desde {oracle_home}: {error}",
            "Verifique que la ruta sea un ORACLE_HOME válido (debe contener bin/ y lib/).",
        ) from error
    _cliente_thick_iniciado = oracle_home


def conectar_local(parametros: ParametrosConexionLocal) -> oracledb.Connection:
    iniciar_cliente_thick(parametros.oracle_home)
    os.environ["ORACLE_SID"] = parametros.sid
    try:
        return oracledb.connect(mode=oracledb.AUTH_MODE_SYSDBA)
    except oracledb.Error as error:
        raise _traducir_error(error, parametros.sid) from error


def conectar_remota(parametros: ParametrosConexionRemota) -> oracledb.Connection:
    modo = oracledb.AUTH_MODE_SYSDBA if parametros.como_sysdba else oracledb.AUTH_MODE_DEFAULT
    try:
        return oracledb.connect(user=parametros.usuario, password=parametros.clave, dsn=parametros.dsn, mode=modo)
    except oracledb.Error as error:
        raise _traducir_error(error, parametros.dsn) from error


def _codigo_error(error: oracledb.Error) -> int | None:
    detalle = error.args[0] if error.args else None
    codigo = getattr(detalle, "code", None)
    return codigo if isinstance(codigo, int) else None


def _traducir_error(error: oracledb.Error, destino: str) -> ErrorConexionOracle:
    codigo = _codigo_error(error)
    if codigo == ORA_PRIVILEGIOS_INSUFICIENTES:
        return ErrorConexionOracle(
            f"El usuario del sistema operativo no tiene privilegios de administrador sobre {destino} (ORA-01031).",
            "En Windows agregue su usuario al grupo local ORA_DBA; en Linux, al grupo dba. "
            "Luego cierre sesión y vuelva a entrar.",
        )
    if codigo in (ORA_INSTANCIA_NO_DISPONIBLE, ORA_ADAPTADOR_PROTOCOLO):
        return ErrorConexionOracle(
            f"La instancia {destino} no está disponible (ORA-{codigo:05d}).",
            "Verifique que el servicio o la instancia estén iniciados y que el SID sea correcto.",
        )
    if codigo == ORA_USUARIO_CLAVE_INVALIDOS:
        return ErrorConexionOracle("Usuario o contraseña inválidos (ORA-01017).")
    if codigo in (ORA_SIN_LISTENER, ORA_SERVICIO_DESCONOCIDO):
        return ErrorConexionOracle(
            f"No se pudo llegar a {destino} (ORA-{codigo:05d}).",
            "Verifique host, puerto y nombre de servicio del DSN, y que el listener esté activo.",
        )
    return ErrorConexionOracle(f"No se pudo conectar a {destino}: {error}")
