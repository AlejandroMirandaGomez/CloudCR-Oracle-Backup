from typing import Annotated

import typer

from cloudcr_backup import __version__
from cloudcr_backup.cli import cmd_explorar
from cloudcr_backup.presentacion.terminal import consola

app = typer.Typer(
    help="CloudCR Oracle Backup — Gestión de Estrategias de Respaldo de Bases de Datos Oracle (RMAN).",
    add_completion=False,
    no_args_is_help=False,
    rich_markup_mode="rich",
)

app.registered_commands.extend(cmd_explorar.app.registered_commands)


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
    cmd_explorar.flujo_por_defecto()


def main() -> None:
    app()
