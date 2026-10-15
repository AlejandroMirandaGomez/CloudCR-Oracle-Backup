import pytest

from cloudcr_backup.config.ajustes import cargar_ajustes
from cloudcr_backup.repository.conexion import Conexion, abrir_repositorio

MARCAS_DE_BASE_DE_PRUEBA = ("prueba", "test")


def abrir_repositorio_de_prueba() -> Conexion:
    ajustes = cargar_ajustes()
    if not any(marca in ajustes.repositorio_base.lower() for marca in MARCAS_DE_BASE_DE_PRUEBA):
        pytest.skip(
            f"La base {ajustes.repositorio_base} no parece de prueba: use CLOUDCR_REPOSITORIO_BASE con "
            "'prueba' o 'test' en el nombre para no borrar el catálogo real."
        )
    return abrir_repositorio(ajustes)
