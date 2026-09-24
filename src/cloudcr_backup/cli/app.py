import os
from enum import StrEnum
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from rich.table import Table

from cloudcr_backup import __version__
from cloudcr_backup.oracle.connection import ErrorConexionOracle, ParametrosConexionRemota
from cloudcr_backup.oracle.discovery import InstanciaDescubierta, descubrir_instancias
from cloudcr_backup.oracle.explorador import (
    Exploracion,
    InstanciaNoEncontrada,
    explorar_local,
    explorar_remota,
    resolver_instancia,
)
from cloudcr_backup.presentacion.arbol import OpcionesArbol, perfil_tiene_pdb
from cloudcr_backup.presentacion.terminal import consola, construir_arbol, tabla_hallazgos
from cloudcr_backup.reports.exportar_instancia import FormatoExportacion, exportar

VARIABLE_CLAVE = "CLOUDCR_ORACLE_CLAVE"


class FormatoSalida(StrEnum):
    ARBOL = "arbol"
    JSON = FormatoExportacion.JSON.value
    MD = FormatoExportacion.MD.value
    HTML = FormatoExportacion.HTML.value


app = typer.Typer(
    help="CloudCR Oracle Backup — Gestión de Estrategias de Respaldo de Bases de Datos Oracle (RMAN).",
    add_completion=False,
    no_args_is_help=False,
    rich_markup_mode="rich",
)


def _terminar_con_error(mensaje: str, sugerencia: str | None = None, codigo: int = 2) -> NoReturn:
    salida = consola()
    salida.print(f"[bold red]Error:[/] {mensaje}", markup=True)
    if sugerencia:
        salida.print(f"[yellow]Sugerencia:[/] {sugerencia}", markup=True)
    raise typer.Exit(codigo)


def _tabla_instancias(instancias: list[InstanciaDescubierta]) -> Table:
    tabla = Table(title="Instancias Oracle encontradas en esta máquina")
    tabla.add_column("#", justify="right")
    tabla.add_column("SID", style="bold")
    tabla.add_column("Estado")
    tabla.add_column("ORACLE_HOME")
    tabla.add_column("Detectada por", style="dim")
    for indice, instancia in enumerate(instancias, start=1):
        tabla.add_row(
            str(indice),
            instancia.sid,
            "[green]en ejecución[/]" if instancia.en_ejecucion else "[yellow]detenida o desconocido[/]",
            str(instancia.oracle_home) if instancia.oracle_home else "[dim]desconocido[/]",
            ", ".join(instancia.origenes),
        )
    return tabla


def _mostrar(exploracion: Exploracion, opciones: OpcionesArbol, formato: FormatoSalida, archivo: Path | None) -> None:
    if opciones.pdb and not perfil_tiene_pdb(exploracion.perfil, opciones.pdb):
        _terminar_con_error(f"La instancia no tiene un contenedor llamado {opciones.pdb}.")
    if formato is FormatoSalida.ARBOL:
        salida = consola()
        salida.print()
        salida.print(construir_arbol(exploracion, opciones))
        if exploracion.hallazgos:
            salida.print()
            salida.print(tabla_hallazgos(exploracion.hallazgos))
        return
    contenido = exportar(exploracion, opciones, FormatoExportacion(formato.value))
    if archivo is None:
        print(contenido)
        return
    archivo.parent.mkdir(parents=True, exist_ok=True)
    archivo.write_text(contenido, encoding="utf-8")
    consola().print(f"Exportado a [bold]{archivo}[/]", markup=True)


def _elegir_interactivamente(instancias: list[InstanciaDescubierta]) -> InstanciaDescubierta:
    consola().print(_tabla_instancias(instancias))
    numero = int(typer.prompt("Número de la instancia a explorar", type=int, default=1))
    if not 1 <= numero <= len(instancias):
        _terminar_con_error("Número fuera de rango.")
    return instancias[numero - 1]


def _explorar_local(instancia: InstanciaDescubierta) -> Exploracion:
    with consola().status(f"Conectando a {instancia.sid} e inspeccionando la instancia..."):
        return explorar_local(instancia)


@app.callback(invoke_without_command=True)
def principal(
    ctx: typer.Context,
    version: Annotated[bool, typer.Option("--version", help="Muestra la versión y termina.")] = False,
) -> None:
    if version:
        consola().print(f"cloudcr-oracle-backup {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is not None:
        return
    salida = consola()
    salida.print("[bold]CloudCR Oracle Backup[/] — buscando instancias Oracle en esta máquina...", markup=True)
    instancias = descubrir_instancias()
    if not instancias:
        _terminar_con_error(
            "No se encontró ninguna instancia Oracle.",
            "Use 'cloudcr explorar SID --oracle-home RUTA' "
            "o 'cloudcr explorar --dsn host:puerto/servicio --usuario U'.",
        )
    en_ejecucion = [i for i in instancias if i.en_ejecucion]
    elegida = en_ejecucion[0] if len(en_ejecucion) == 1 else _elegir_interactivamente(instancias)
    try:
        exploracion = _explorar_local(elegida)
    except ErrorConexionOracle as error:
        _terminar_con_error(str(error), error.sugerencia)
    _mostrar(exploracion, OpcionesArbol(), FormatoSalida.ARBOL, None)
    salida.print("\nMás opciones: [bold]cloudcr explorar --help[/]", markup=True)


@app.command(help="Lista las instancias Oracle encontradas en esta máquina.")
def descubrir() -> None:
    instancias = descubrir_instancias()
    if not instancias:
        _terminar_con_error("No se encontró ninguna instancia Oracle en esta máquina.", codigo=1)
    consola().print(_tabla_instancias(instancias))


@app.command(
    help=(
        "Muestra la estructura física de una instancia: "
        "archivos de la instancia y contenedores → tablespaces → datafiles."
    )
)
def explorar(
    sid: Annotated[str | None, typer.Argument(help="SID de la instancia local. Si se omite, se detecta.")] = None,
    oracle_home: Annotated[
        Path | None, typer.Option("--oracle-home", help="ORACLE_HOME de la instancia, si no se detecta solo.")
    ] = None,
    dsn: Annotated[
        str | None, typer.Option("--dsn", help="Conexión por red host:puerto/servicio (en lugar de local).")
    ] = None,
    usuario: Annotated[str | None, typer.Option("--usuario", help="Usuario para la conexión por red.")] = None,
    sysdba: Annotated[bool, typer.Option("--sysdba", help="Conectar por red AS SYSDBA.")] = False,
    pdb: Annotated[str | None, typer.Option("--pdb", help="Muestra solo ese contenedor.")] = None,
    sin_seed: Annotated[bool, typer.Option("--sin-seed", help="Oculta PDB$SEED.")] = False,
    rutas_completas: Annotated[
        bool, typer.Option("--rutas-completas", help="Muestra la ruta completa de cada archivo.")
    ] = False,
    salida: Annotated[FormatoSalida, typer.Option("--salida", help="Formato de salida.")] = FormatoSalida.ARBOL,
    archivo: Annotated[Path | None, typer.Option("--archivo", help="Guarda la exportación en este archivo.")] = None,
) -> None:
    opciones = OpcionesArbol(pdb=pdb, sin_seed=sin_seed, rutas_completas=rutas_completas)
    try:
        if dsn:
            if not usuario:
                _terminar_con_error("Con --dsn hay que indicar --usuario.")
            clave = os.environ.get(VARIABLE_CLAVE) or typer.prompt(f"Contraseña de {usuario}", hide_input=True)
            with consola().status(f"Conectando a {dsn}..."):
                exploracion = explorar_remota(
                    ParametrosConexionRemota(dsn=dsn, usuario=usuario, clave=clave, como_sysdba=sysdba)
                )
        else:
            try:
                instancia = resolver_instancia(descubrir_instancias(), sid, oracle_home)
            except InstanciaNoEncontrada as error:
                _terminar_con_error(str(error), "Ejecute 'cloudcr descubrir' para ver las instancias disponibles.")
            exploracion = _explorar_local(instancia)
    except ErrorConexionOracle as error:
        _terminar_con_error(str(error), error.sugerencia)
    _mostrar(exploracion, opciones, salida, archivo)


@app.command(help="Abre la interfaz web en el navegador (por defecto solo accesible desde este equipo).")
def web(
    host: Annotated[
        str, typer.Option("--host", envvar="CLOUDCR_WEB_HOST", help="Interfaz de red donde escuchar.")
    ] = "127.0.0.1",
    puerto: Annotated[
        int,
        typer.Option("--puerto", envvar="CLOUDCR_WEB_PUERTO", help="Puerto inicial; si está ocupado usa el siguiente."),
    ] = 8765,
    no_abrir: Annotated[bool, typer.Option("--no-abrir", help="No abre el navegador automáticamente.")] = False,
    token: Annotated[
        str | None,
        typer.Option("--token", envvar="CLOUDCR_WEB_TOKEN", help="Token de acceso (se genera si el host no es local)."),
    ] = None,
    cache: Annotated[
        int,
        typer.Option("--cache", envvar="CLOUDCR_WEB_CACHE", min=0, help="Segundos que se reutiliza una inspección."),
    ] = 60,
) -> None:
    from cloudcr_backup.web.config import ConfigWeb
    from cloudcr_backup.web.servidor import PuertoNoDisponible, iniciar_servidor

    config = ConfigWeb.desde_opciones(host=host, puerto=puerto, token=token, ttl_cache_segundos=cache)
    salida = consola()
    if not config.es_local:
        salida.print(
            "[bold yellow]Atención:[/] la interfaz queda accesible desde la red y se conecta a Oracle como SYSDBA. "
            "Comparta la URL con token solo con quien corresponda.",
            markup=True,
        )

    def avisar(url: str) -> None:
        salida.print(f"Interfaz web disponible en [bold]{url}[/]", markup=True)
        salida.print("Presione Ctrl+C para detenerla.", style="dim")

    try:
        iniciar_servidor(config, abrir_navegador=not no_abrir, avisar=avisar)
    except PuertoNoDisponible as error:
        _terminar_con_error(str(error), "Indique otro puerto con --puerto.")


def main() -> None:
    app()
