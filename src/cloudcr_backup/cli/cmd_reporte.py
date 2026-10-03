from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from cloudcr_backup.cli.cmd_historial import Bd, CodigoEstrategia, Desde, Estado, Hasta, consulta_desde_opciones
from cloudcr_backup.cli.comun_monitoreo import ajustes, guardar_o_mostrar, llamar
from cloudcr_backup.services import historial as servicio_historial

app = typer.Typer(add_completion=False, help="Exporta el historial y la evidencia de ejecuciones.")


class FormatoReporte(StrEnum):
    CSV = "csv"
    MD = "md"
    HTML = "html"


class FormatoEvidencia(StrEnum):
    MD = "md"
    HTML = "html"


Archivo = Annotated[
    Path | None,
    typer.Option("--archivo", help="Archivo o carpeta destino. Si se omite, se imprime en la terminal."),
]


@app.command(help="Exporta el historial filtrado a CSV, Markdown o HTML autocontenido (evidencia E8).")
def historial(
    formato: Annotated[FormatoReporte, typer.Option("--formato", help="csv, md o html.")] = FormatoReporte.HTML,
    archivo: Archivo = None,
    bd: Bd = None,
    estrategia: CodigoEstrategia = None,
    estado: Estado = None,
    desde: Desde = None,
    hasta: Hasta = None,
) -> None:
    configuracion = ajustes()
    consulta = consulta_desde_opciones(bd, estrategia, estado, desde, hasta)
    exportado = llamar(lambda: servicio_historial.exportar(configuracion, consulta, formato.value))
    guardar_o_mostrar(exportado, archivo)


@app.command(help="Exporta la evidencia de una ejecución (script, log, piezas, verificaciones).")
def evidencia(
    ejecucion_id: Annotated[int, typer.Argument(help="Id de la ejecución.")],
    formato: Annotated[FormatoEvidencia, typer.Option("--formato", help="md o html.")] = FormatoEvidencia.MD,
    archivo: Archivo = None,
) -> None:
    configuracion = ajustes()
    exportado = llamar(lambda: servicio_historial.exportar_evidencia(configuracion, ejecucion_id, formato.value))
    guardar_o_mostrar(exportado, archivo)
