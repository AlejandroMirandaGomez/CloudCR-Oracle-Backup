from datetime import datetime
from typing import Annotated

import typer
from rich.syntax import Syntax
from rich.table import Table

from cloudcr_backup.cli.comun import terminar_con_error
from cloudcr_backup.cli.comun_monitoreo import ajustes, llamar
from cloudcr_backup.domain.recuperacion import Escenario
from cloudcr_backup.presentacion.formato import formato_bytes
from cloudcr_backup.presentacion.terminal import consola
from cloudcr_backup.services import recuperacion as servicio_recuperacion

app = typer.Typer(
    add_completion=False, help="Puntos de recuperación, diagnóstico y procedimientos por escenario (no se ejecutan)."
)

Bd = Annotated[str, typer.Argument(help="Base de datos registrada, por ejemplo XE.")]
Json = Annotated[bool, typer.Option("--json", help="Salida en JSON.")]
FORMATOS_HASTA = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M")


@app.command(help="Lista los respaldos correctos desde los que se puede recuperar la base.")
def puntos(bd: Bd, json_: Json = False) -> None:
    configuracion = ajustes()
    resultado = llamar(lambda: servicio_recuperacion.puntos(configuracion, bd))
    if json_:
        print(resultado.model_dump_json(indent=2))
        return
    salida = consola()
    modo = resultado.log_mode.value if resultado.log_mode else "modo desconocido"
    salida.print(f"[bold]Puntos de recuperación de {resultado.bd}[/] · {modo}", markup=True)
    if resultado.puntos:
        tabla = Table()
        for columna in ("Ejecución", "Completado (UTC)", "Estrategia", "Tarea", "Tipo", "Alcance", "Pruebas", "Tamaño"):
            tabla.add_column(columna)
        for punto in resultado.puntos:
            tabla.add_row(
                str(punto.ejecucion_id),
                f"{punto.completado_en:%Y-%m-%d %H:%M}" if punto.completado_en else "—",
                punto.estrategia,
                punto.tarea,
                punto.tipo_respaldo.value,
                "Base completa" if punto.base_completa else ", ".join(punto.alcance),
                punto.estado_prueba.value,
                formato_bytes(punto.tamano_bytes),
            )
        salida.print(tabla)
    for aviso in resultado.avisos:
        salida.print(aviso, style="yellow", highlight=False)


@app.command(help="Consulta V$RECOVER_FILE y V$DATAFILE para decir qué archivo falta o está dañado.")
def diagnostico(bd: Bd, json_: Json = False) -> None:
    configuracion = ajustes()
    resultado = llamar(lambda: servicio_recuperacion.diagnostico(configuracion, bd))
    if json_:
        print(resultado.model_dump_json(indent=2))
        return
    salida = consola()
    salida.print(
        f"[bold]Diagnóstico de {resultado.bd}[/] · {resultado.open_mode or '—'} · "
        f"{resultado.log_mode.value if resultado.log_mode else '—'}",
        markup=True,
    )
    if resultado.archivos:
        tabla = Table()
        for columna in ("file#", "Tablespace", "Estado", "Error", "Origen", "Archivo"):
            tabla.add_column(columna)
        for archivo in resultado.archivos:
            tabla.add_row(
                str(archivo.file_id),
                archivo.identificador_tablespace or "—",
                archivo.estado,
                archivo.error or "—",
                archivo.origen,
                archivo.ruta,
            )
        salida.print(tabla)
    for aviso in resultado.avisos:
        salida.print(aviso, style="yellow", highlight=False)


def _hasta(texto: str | None) -> datetime | None:
    if texto is None:
        return None
    for formato in FORMATOS_HASTA:
        try:
            return datetime.strptime(texto, formato)
        except ValueError:
            continue
    terminar_con_error(f"'{texto}' no es una fecha válida.", "Use el formato 'AAAA-MM-DD HH:MM'.")


@app.command(help="Genera el procedimiento de recuperación de un escenario; nunca lo ejecuta.")
def plan(
    bd: Bd,
    escenario: Annotated[Escenario, typer.Argument(help="Escenario de falla.")],
    objetivo: Annotated[
        str | None, typer.Option("--objetivo", help="PDB, tablespace (PDB:TS) o file#. Se deduce si se omite.")
    ] = None,
    hasta: Annotated[str | None, typer.Option("--hasta", help="Momento objetivo 'AAAA-MM-DD HH:MM'.")] = None,
    json_: Json = False,
) -> None:
    configuracion = ajustes()
    momento = _hasta(hasta)
    resultado = llamar(lambda: servicio_recuperacion.plan(configuracion, bd, escenario.value, objetivo, momento))
    if json_:
        print(resultado.model_dump_json(indent=2))
        return
    salida = consola()
    salida.print(f"[bold]Recuperación {resultado.escenario.value} en {resultado.bd}[/]", markup=True)
    if not resultado.posible:
        salida.print(f"[bold red]No es posible:[/] {resultado.motivo}", markup=True)
        raise typer.Exit(1)
    if resultado.objetivo:
        salida.print(f"Objetivo: {resultado.objetivo}", highlight=False)
    for numero, paso in enumerate(resultado.pasos, start=1):
        salida.print(f"  {numero}. {paso}", highlight=False)
    if resultado.script:
        salida.print(Syntax(resultado.script, "sql", theme="ansi_dark", line_numbers=True))
    if resultado.archivo:
        salida.print(f"Guardado en {resultado.archivo} (no se ejecutó).", highlight=False)
    for aviso in resultado.avisos:
        salida.print(aviso, style="yellow", highlight=False)
