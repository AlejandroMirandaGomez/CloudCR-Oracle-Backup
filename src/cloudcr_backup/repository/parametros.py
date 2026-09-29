import oracledb


def obtener(conexion: oracledb.Connection, clave: str) -> str | None:
    raise NotImplementedError


def listar(conexion: oracledb.Connection) -> dict[str, str]:
    raise NotImplementedError


def asignar(conexion: oracledb.Connection, clave: str, valor: str) -> None:
    raise NotImplementedError
