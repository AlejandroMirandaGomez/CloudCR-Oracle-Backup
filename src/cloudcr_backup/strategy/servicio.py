import oracledb

from cloudcr_backup.domain.estrategia import Estrategia
from cloudcr_backup.repository import estrategias as repositorio_estrategias


class EstrategiaYaExiste(ValueError):
    pass


class EstrategiaNoEncontrada(ValueError):
    pass


def crear(conexion: oracledb.Connection, estrategia: Estrategia) -> Estrategia:
    existentes = repositorio_estrategias.listar(conexion, estrategia.bd_id)
    if any(e.codigo == estrategia.codigo for e in existentes):
        raise EstrategiaYaExiste(f"Ya existe una estrategia con el código {estrategia.codigo} en esta base de datos.")
    nueva = estrategia.model_copy(update={"version": 1})
    return repositorio_estrategias.crear(conexion, nueva)


def editar(conexion: oracledb.Connection, estrategia_actualizada: Estrategia) -> Estrategia:
    actual = repositorio_estrategias.obtener(conexion, estrategia_actualizada.bd_id, estrategia_actualizada.codigo)
    if actual is None:
        raise EstrategiaNoEncontrada(f"No existe la estrategia {estrategia_actualizada.codigo} en esta base de datos.")
    nueva = estrategia_actualizada.model_copy(update={"version": actual.version + 1})
    return repositorio_estrategias.actualizar(conexion, nueva)


def activar(conexion: oracledb.Connection, bd_id: int, codigo: str) -> None:
    repositorio_estrategias.activar(conexion, bd_id, codigo)


def desactivar(conexion: oracledb.Connection, bd_id: int, codigo: str) -> None:
    repositorio_estrategias.desactivar(conexion, bd_id, codigo)


def eliminar(conexion: oracledb.Connection, bd_id: int, codigo: str) -> None:
    desactivar(conexion, bd_id, codigo)


def listar(conexion: oracledb.Connection, bd_id: int) -> list[Estrategia]:
    return repositorio_estrategias.listar(conexion, bd_id)


def obtener(conexion: oracledb.Connection, bd_id: int, codigo: str) -> Estrategia | None:
    return repositorio_estrategias.obtener(conexion, bd_id, codigo)
