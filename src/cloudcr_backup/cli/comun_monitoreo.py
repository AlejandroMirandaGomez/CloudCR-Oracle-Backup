from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import TypeVar

from cloudcr_backup.cli.comun import terminar_con_error
from cloudcr_backup.config.ajustes import Ajustes, cargar_ajustes
from cloudcr_backup.domain.errores import ErrorServicio, RecursoNoEncontrado
from cloudcr_backup.domain.historial import ArchivoExportado
from cloudcr_backup.presentacion.terminal import consola

T = TypeVar("T")


def ajustes() -> Ajustes:
    return cargar_ajustes()


def llamar(funcion: Callable[[], T]) -> T:
    try:
        return funcion()
    except RecursoNoEncontrado as error:
        terminar_con_error(error.mensaje, error.sugerencia, codigo=1)
    except ErrorServicio as error:
        terminar_con_error(error.mensaje, error.sugerencia)


def fecha(texto: str | None, opcion: str) -> date | None:
    if texto is None:
        return None
    try:
        return date.fromisoformat(texto)
    except ValueError:
        terminar_con_error(f"{opcion} '{texto}' no es una fecha válida. Use el formato AAAA-MM-DD.")


def guardar_o_mostrar(archivo_exportado: ArchivoExportado, destino: Path | None) -> None:
    if destino is None:
        print(archivo_exportado.contenido.decode("utf-8").removeprefix("﻿"), end="")
        return
    ruta = destino / archivo_exportado.nombre if destino.is_dir() else destino
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(archivo_exportado.contenido)
    consola().print(f"Exportado a [bold]{ruta}[/]", markup=True)
