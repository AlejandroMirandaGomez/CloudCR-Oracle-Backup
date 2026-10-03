from collections.abc import Iterator
from contextlib import contextmanager, suppress

import oracledb

from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.domain.errores import RepositorioNoDisponible
from cloudcr_backup.oracle.connection import ErrorConexionOracle
from cloudcr_backup.repository import conexion as repositorio_conexion
from cloudcr_backup.repository.conexion import RepositorioNoConfigurado

SUGERENCIA_CONFIGURACION = (
    "Configure CLOUDCR_REPOSITORIO_DSN y CLOUDCR_REPO_CLAVE en el archivo .env (vea .env.example)."
)
SUGERENCIA_ESQUEMA = "Verifique que el repositorio esté instalado ('cloudcr repo estado' / 'cloudcr repo instalar')."


@contextmanager
def conexion_repositorio(ajustes: Ajustes) -> Iterator[oracledb.Connection]:
    try:
        conexion = repositorio_conexion.abrir_repositorio(ajustes)
    except RepositorioNoConfigurado as error:
        raise RepositorioNoDisponible(str(error), SUGERENCIA_CONFIGURACION) from error
    except ErrorConexionOracle as error:
        raise RepositorioNoDisponible(str(error), error.sugerencia) from error
    try:
        yield conexion
    except oracledb.Error as error:
        raise RepositorioNoDisponible(f"Error al consultar el repositorio: {error}", SUGERENCIA_ESQUEMA) from error
    finally:
        with suppress(oracledb.Error):
            conexion.close()
