from typing import Annotated

import typer
from rich.table import Table

from cloudcr_backup.cli.comun_monitoreo import ajustes, llamar
from cloudcr_backup.presentacion.formato import formato_bytes
from cloudcr_backup.presentacion.terminal import consola
from cloudcr_backup.services import retencion as servicio_retencion

app = typer.Typer(add_completion=False, help="Política de retención: informe de respaldos obsoletos y purga.")

Bd = Annotated[str, typer.Argument(help="Base de datos registrada, por ejemplo XE.")]


@app.command(help="Lista los respaldos obsoletos según la retención de cada estrategia, sin borrar nada.")
def informe(
    bd: Bd,
    rman: Annotated[
        bool, typer.Option("--rman", help="Además consulta REPORT OBSOLETE en RMAN (solo informa).")
    ] = False,
    json_: Annotated[bool, typer.Option("--json", help="Salida en JSON.")] = False,
) -> None:
    configuracion = ajustes()
    resultado = llamar(lambda: servicio_retencion.informe(configuracion, bd, rman))
    if json_:
        print(resultado.model_dump_json(indent=2))
        return
    salida = consola()
    salida.print(f"[bold]Retención de {resultado.bd}[/] · nada se borra con este comando.", markup=True)
    tabla = Table()
    for columna in ("Estrategia", "Política", "Piezas", "Obsoletas", "Espacio a liberar", "Purga automática"):
        tabla.add_column(columna)
    for estrategia in resultado.estrategias:
        tabla.add_row(
            estrategia.estrategia,
            estrategia.politica or "sin política",
            str(estrategia.piezas_total),
            str(len(estrategia.vencidas)),
            formato_bytes(estrategia.bytes_vencidos),
            "sí" if estrategia.purga_automatica else "no",
        )
    salida.print(tabla)
    for estrategia in resultado.estrategias:
        salida.print(f"{estrategia.estrategia}: {estrategia.descripcion}", highlight=False)
        for pieza in estrategia.vencidas:
            vence = f" · venció {pieza.vence_en:%Y-%m-%d}" if pieza.vence_en else ""
            rman_marca = " · RMAN la informa obsoleta" if pieza.obsoleta_rman else ""
            salida.print(f"  · {pieza.ruta} ({formato_bytes(pieza.tamano_bytes)}){vence}{rman_marca}", highlight=False)
        if estrategia.script:
            salida.print("  Script sugerido: " + estrategia.script.replace("\n", " "), style="dim", highlight=False)
        for aviso in estrategia.avisos:
            salida.print(f"  {aviso}", style="yellow", highlight=False)
    if resultado.archivelogs_sin_respaldo is not None:
        salida.print(f"Archived logs sin respaldar: {resultado.archivelogs_sin_respaldo}", highlight=False)
    if resultado.consulto_rman and resultado.obsoletas_rman:
        salida.print(f"RMAN informa {len(resultado.obsoletas_rman)} archivo(s) obsoleto(s) en total.", highlight=False)
    for aviso in resultado.avisos:
        salida.print(aviso, style="yellow", highlight=False)


@app.command(help="Borra los respaldos obsoletos de una estrategia. Exige --purgar y purga_automatica activa.")
def purgar(
    bd: Bd,
    codigo: Annotated[str, typer.Argument(help="Código de la estrategia.")],
    confirmar: Annotated[
        bool, typer.Option("--purgar", help="Confirma que se borren los respaldos obsoletos.")
    ] = False,
) -> None:
    configuracion = ajustes()
    resultado = llamar(lambda: servicio_retencion.purgar(configuracion, bd, codigo, confirmar))
    salida = consola()
    salida.print(resultado.script, highlight=False)
    if resultado.errores:
        salida.print("[bold red]RMAN informó errores durante la purga:[/]", markup=True)
        for error in resultado.errores:
            salida.print(f"  · {error}", highlight=False)
        raise typer.Exit(1)
    salida.print(
        f"[bold green]Purga terminada.[/] {len(resultado.borradas)} pieza(s) borradas por RMAN; "
        f"{resultado.piezas_marcadas} marcadas como obsoletas en el repositorio. Log: {resultado.log}",
        markup=True,
    )
