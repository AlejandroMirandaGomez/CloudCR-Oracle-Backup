from typing import Annotated

import typer
from rich.table import Table

from cloudcr_backup.cli.comun_monitoreo import llamar
from cloudcr_backup.presentacion.terminal import consola
from cloudcr_backup.services import evidencias as servicio_evidencias

app = typer.Typer(add_completion=False)


@app.command(name="evidencias", help="Lista las evidencias E1 a E10 del proyecto y cuáles ya están capturadas.")
def evidencias(
    json_: Annotated[bool, typer.Option("--json", help="Salida en JSON (la misma que /api/evidencias).")] = False,
) -> None:
    catalogo = llamar(servicio_evidencias.catalogo)
    if json_:
        print(catalogo.model_dump_json(indent=2))
        return
    tabla = Table(title="Evidencias del proyecto", show_lines=True)
    tabla.add_column("Id", no_wrap=True)
    tabla.add_column("Evidencia")
    tabla.add_column("Responsable", no_wrap=True)
    tabla.add_column("Estado", no_wrap=True)
    tabla.add_column("Archivos", justify="right")
    for evidencia in catalogo.evidencias:
        estado = "[green]● Capturada[/]" if evidencia.disponible else "[yellow]○ Pendiente[/]"
        tabla.add_row(evidencia.id, evidencia.titulo, evidencia.responsable, estado, str(len(evidencia.archivos)))
    salida = consola()
    salida.print(tabla)
    salida.print(f"{catalogo.disponibles} de {len(catalogo.evidencias)} capturadas en {catalogo.carpeta or '—'}.")
