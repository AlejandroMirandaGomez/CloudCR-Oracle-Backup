import re
from dataclasses import dataclass
from pathlib import Path

import oracledb

from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.domain.enums import EstadoEstrategia
from cloudcr_backup.domain.estrategia import Estrategia
from cloudcr_backup.domain.perfil_bd import PerfilBD
from cloudcr_backup.repository import bases_datos as repositorio_bases_datos
from cloudcr_backup.repository import conexion as repositorio_conexion
from cloudcr_backup.strategy import servicio
from cloudcr_backup.strategy.yaml_io import estrategia_a_yaml

PATRON_SID = re.compile(r"[A-Za-z0-9_$#-]{1,64}")
EXTENSION_ESTRATEGIA = ".yaml"


class EstrategiaYaGuardada(ValueError):
    pass


@dataclass(frozen=True)
class ResultadoRepositorio:
    estado: str
    mensaje: str


REPOSITORIO_OMITIDO = ResultadoRepositorio("omitida", "No se pidió guardarla en el repositorio.")


def _segmento_seguro(sid: str) -> str:
    if PATRON_SID.fullmatch(sid) is None:
        raise ValueError(f"El identificador de instancia {sid!r} no es válido.")
    return sid.upper()


def directorio_estrategias(ajustes: Ajustes, sid: str) -> Path:
    return ajustes.rutas.estrategias / _segmento_seguro(sid)


def ruta_estrategia(ajustes: Ajustes, sid: str, codigo: str) -> Path:
    return directorio_estrategias(ajustes, sid) / f"{codigo}{EXTENSION_ESTRATEGIA}"


def codigos_guardados(ajustes: Ajustes, sid: str) -> list[str]:
    directorio = directorio_estrategias(ajustes, sid)
    if not directorio.is_dir():
        return []
    return sorted(archivo.stem.upper() for archivo in directorio.glob(f"*{EXTENSION_ESTRATEGIA}") if archivo.is_file())


def codigos_en_repositorio(ajustes: Ajustes, nombre_bd: str) -> list[str]:
    try:
        conexion = repositorio_conexion.abrir_repositorio(ajustes)
    except Exception:
        return []
    try:
        bd = repositorio_bases_datos.obtener(conexion, nombre_bd)
        if bd is None:
            return []
        return [estrategia.codigo.upper() for estrategia in servicio.listar(conexion, bd.id)]
    except Exception:
        return []
    finally:
        conexion.close()


def codigos_existentes(ajustes: Ajustes, sid: str, nombre_bd: str) -> list[str]:
    return sorted({*codigos_guardados(ajustes, sid), *codigos_en_repositorio(ajustes, nombre_bd)})


def guardar_archivo(ajustes: Ajustes, sid: str, estrategia: Estrategia) -> Path:
    destino = ruta_estrategia(ajustes, sid, estrategia.codigo)
    destino.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destino.open("x", encoding="utf-8") as archivo:
            archivo.write(estrategia_a_yaml(estrategia))
    except FileExistsError as error:
        raise EstrategiaYaGuardada(f"Ya existe un archivo para la estrategia {estrategia.codigo}.") from error
    return destino


def _obtener_o_registrar(
    conexion: oracledb.Connection, perfil: PerfilBD
) -> tuple[repositorio_bases_datos.BaseDatosRegistrada | None, bool]:
    bd = repositorio_bases_datos.obtener(conexion, perfil.nombre)
    if bd is not None or perfil.oracle_home is None:
        return bd, False
    registrada = repositorio_bases_datos.registrar(
        conexion, perfil.nombre, perfil.oracle_home, repositorio_bases_datos.Ambiente.DESARROLLO
    )
    return registrada, True


def guardar_en_repositorio(ajustes: Ajustes, perfil: PerfilBD, estrategia: Estrategia) -> ResultadoRepositorio:
    try:
        conexion = repositorio_conexion.abrir_repositorio(ajustes)
    except NotImplementedError:
        return ResultadoRepositorio(
            "no_disponible", "El repositorio todavía no está disponible; la estrategia quedó guardada en el archivo."
        )
    except Exception as error:
        return ResultadoRepositorio("error", f"No se pudo conectar con el repositorio: {error}")
    try:
        bd, recien_registrada = _obtener_o_registrar(conexion, perfil)
        if bd is None:
            return ResultadoRepositorio(
                "no_registrada",
                f"La base {perfil.nombre} no está registrada en el repositorio y no se detectó su ORACLE_HOME "
                "(use 'cloudcr db agregar').",
            )
        creada = servicio.crear(
            conexion, estrategia.model_copy(update={"bd_id": bd.id, "estado": EstadoEstrategia.INACTIVA})
        )
        if estrategia.estado is EstadoEstrategia.ACTIVA:
            servicio.activar(conexion, bd.id, creada.codigo)
        sufijo = f" La base {bd.nombre} se registró automáticamente." if recien_registrada else ""
        return ResultadoRepositorio("guardada", f"Guardada en el repositorio como {creada.codigo}.{sufijo}")
    except Exception as error:
        return ResultadoRepositorio("error", f"No se pudo guardar en el repositorio: {error}")
    finally:
        conexion.close()
