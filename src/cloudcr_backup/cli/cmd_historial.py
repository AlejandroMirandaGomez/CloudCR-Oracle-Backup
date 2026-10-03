from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from rich.text import Text

from cloudcr_backup.cli.comun_monitoreo import ajustes, fecha, guardar_o_mostrar, llamar
from cloudcr_backup.domain.enums import EstadoEjecucion
from cloudcr_backup.domain.historial import ConsultaHistorial
from cloudcr_backup.presentacion.detalle import secciones
from cloudcr_backup.presentacion.historial import construir_tabla
from cloudcr_backup.presentacion.terminal import consola
from cloudcr_backup.presentacion.terminal_monitoreo import leyenda_simbolos, tabla_historial
from cloudcr_backup.services import historial as servicio_historial

app = typer.Typer(add_completion=False, help="Historial de ejecuciones de respaldo y su detalle.")


class SalidaHistorial(StrEnum):
    TABLA = "tabla"
    JSON = "json"
    CSV = "csv"
    MD = "md"
    HTML = "html"


Bd = Annotated[str | None, typer.Option("--bd", help="Nombre de la base de datos registrada.")]
CodigoEstrategia = Annotated[str | None, typer.Option("--estrategia", help="Código de la estrategia.")]
Estado = Annotated[EstadoEjecucion | None, typer.Option("--estado", help="Solo ejecuciones en este estado.")]
Desde = Annotated[str | None, typer.Option("--desde", help="Fecha inicial AAAA-MM-DD (incluida).")]
Hasta = Annotated[str | None, typer.Option("--hasta", help="Fecha final AAAA-MM-DD (incluida).")]


def consulta_desde_opciones(
    bd: str | None,
    estrategia: str | None,
    estado: EstadoEjecucion | None,
    desde: str | None,
    hasta: str | None,
    limite: int = 50,
    pagina: int = 1,
) -> ConsultaHistorial:
    return ConsultaHistorial(
        bd=bd,
        estrategia=estrategia,
        estado=estado,
        desde=fecha(desde, "--desde"),
        hasta=fecha(hasta, "--hasta"),
        limite=limite,
        pagina=pagina,
    )


@app.callback(invoke_without_command=True)
def historial(
    ctx: typer.Context,
    bd: Bd = None,
    estrategia: CodigoEstrategia = None,
    estado: Estado = None,
    desde: Desde = None,
    hasta: Hasta = None,
    limite: Annotated[int, typer.Option("--limite", min=1, max=500, help="Filas por página.")] = 50,
    pagina: Annotated[int, typer.Option("--pagina", min=1, help="Página a mostrar.")] = 1,
    salida: Annotated[SalidaHistorial, typer.Option("--salida", help="Formato de salida.")] = SalidaHistorial.TABLA,
    archivo: Annotated[Path | None, typer.Option("--archivo", help="Guarda csv, md o html en este archivo.")] = None,
) -> None:
    if ctx.invoked_subcommand is not None:
        return
    configuracion = ajustes()
    consulta = consulta_desde_opciones(bd, estrategia, estado, desde, hasta, limite, pagina)
    if salida in (SalidaHistorial.CSV, SalidaHistorial.MD, SalidaHistorial.HTML):
        exportado = llamar(lambda: servicio_historial.exportar(configuracion, consulta, salida.value))
        guardar_o_mostrar(exportado, archivo)
        return
    resultado = llamar(lambda: servicio_historial.consultar(configuracion, consulta))
    if salida is SalidaHistorial.JSON:
        print(resultado.model_dump_json(indent=2))
        return
    tabla = construir_tabla(resultado.filas)
    terminal = consola()
    if not tabla.filas:
        terminal.print("No hay ejecuciones para esos filtros.", style="dim")
        return
    terminal.print(tabla_historial(tabla))
    terminal.print(
        f"Página {resultado.pagina} de {resultado.paginas} · {resultado.total} ejecuciones · "
        "horas en la zona de cada tarea.",
        style="dim",
    )
    terminal.print(leyenda_simbolos(), style="dim")
    for nota in tabla.notas:
        terminal.print(nota, style="yellow")


@app.command(help="Muestra el detalle de una ejecución: script, log de RMAN, piezas y verificaciones.")
def mostrar(
    ejecucion_id: Annotated[int, typer.Argument(help="Id de la ejecución (columna Id del historial).")],
    json_: Annotated[bool, typer.Option("--json", help="Salida en JSON (la misma que /api/historial/{id}).")] = False,
) -> None:
    configuracion = ajustes()
    detalle = llamar(lambda: servicio_historial.detalle(configuracion, ejecucion_id))
    if json_:
        print(detalle.model_dump_json(indent=2))
        return
    terminal = consola()
    for titulo, lineas in secciones(detalle):
        terminal.print(Text(titulo, style="bold"))
        for linea in lineas:
            terminal.print(f"  {linea}", markup=False, highlight=False)
        terminal.print()
