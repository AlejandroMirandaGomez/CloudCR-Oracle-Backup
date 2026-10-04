from collections.abc import Iterator
from contextlib import contextmanager, suppress

import oracledb

from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.domain.ejecucion import Evidencia, utc_ingenuo
from cloudcr_backup.domain.errores import RepositorioNoDisponible
from cloudcr_backup.oracle.connection import ErrorConexionOracle
from cloudcr_backup.repository import conexion as repositorio_conexion
from cloudcr_backup.repository import ejecuciones as repositorio_ejecuciones
from cloudcr_backup.repository import piezas as repositorio_piezas
from cloudcr_backup.repository.piezas import PiezaNueva, VerificacionNueva


@contextmanager
def repositorio(ajustes: Ajustes) -> Iterator[oracledb.Connection]:
    try:
        conexion = repositorio_conexion.abrir_repositorio(ajustes)
    except (repositorio_conexion.RepositorioNoConfigurado, ErrorConexionOracle) as error:
        raise RepositorioNoDisponible(f"No se pudo abrir el repositorio: {error}") from error
    try:
        yield conexion
    except oracledb.Error as error:
        raise RepositorioNoDisponible(f"Error al escribir en el repositorio: {error}") from error
    finally:
        with suppress(oracledb.Error):
            conexion.close()


def persistir(conexion: oracledb.Connection, evidencia: Evidencia) -> None:
    repositorio_ejecuciones.registrar_resultado(conexion, evidencia.ejecucion_id, evidencia.resultado_repositorio())
    repositorio_piezas.reemplazar(
        conexion,
        evidencia.ejecucion_id,
        [
            PiezaNueva(
                nombre_archivo=pieza.ruta,
                tamano_bytes=pieza.tamano_bytes,
                tag=pieza.tag,
                vence_en=utc_ingenuo(pieza.vence_en),
            )
            for pieza in evidencia.piezas
        ],
    )
    if evidencia.pruebas:
        repositorio_piezas.reemplazar_verificaciones(
            conexion,
            evidencia.ejecucion_id,
            [
                VerificacionNueva(tipo_prueba=prueba.tipo, resultado=prueba.resultado, detalle=prueba.detalle)
                for prueba in evidencia.pruebas
            ],
        )
