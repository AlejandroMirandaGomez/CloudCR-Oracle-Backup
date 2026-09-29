from typing import NoReturn

import typer

from cloudcr_backup.presentacion.terminal import consola


def terminar_con_error(mensaje: str, sugerencia: str | None = None, codigo: int = 2) -> NoReturn:
    salida = consola()
    salida.print(f"[bold red]Error:[/] {mensaje}", markup=True)
    if sugerencia:
        salida.print(f"[yellow]Sugerencia:[/] {sugerencia}", markup=True)
    raise typer.Exit(codigo)
