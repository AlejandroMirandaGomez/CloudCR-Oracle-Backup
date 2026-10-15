from collections.abc import Iterator
from contextlib import contextmanager, suppress

from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.domain.errores import RepositorioNoDisponible
from cloudcr_backup.repository import conexion as repositorio_conexion
from cloudcr_backup.repository.conexion import (
    Conexion,
    ErrorConexionRepositorio,
    ErrorRepositorio,
    RepositorioNoConfigurado,
)

SUGERENCIA_CONFIGURACION = "Configure CLOUDCR_REPO_CLAVE en el archivo .env (vea .env.example)."
SUGERENCIA_ESQUEMA = "Verifique que el repositorio esté instalado ('cloudcr repo estado' / 'cloudcr repo instalar')."


@contextmanager
def conexion_repositorio(ajustes: Ajustes) -> Iterator[Conexion]:
    try:
        conexion = repositorio_conexion.abrir_repositorio(ajustes)
    except RepositorioNoConfigurado as error:
        raise RepositorioNoDisponible(str(error), SUGERENCIA_CONFIGURACION) from error
    except ErrorConexionRepositorio as error:
        raise RepositorioNoDisponible(str(error), error.sugerencia) from error
    try:
        yield conexion
    except ErrorRepositorio as error:
        raise RepositorioNoDisponible(f"Error al consultar el repositorio: {error}", SUGERENCIA_ESQUEMA) from error
    finally:
        with suppress(ErrorRepositorio):
            conexion.close()
