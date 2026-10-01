from typing import Annotated

import typer

from cloudcr_backup import __version__
from cloudcr_backup.cli import cmd_db, cmd_doctor, cmd_estrategia, cmd_explorar, cmd_param, cmd_repo, cmd_tarea
from cloudcr_backup.presentacion.terminal import consola

app = typer.Typer(
    help="CloudCR Oracle Backup — Gestión de Estrategias de Respaldo de Bases de Datos Oracle (RMAN).",
    add_completion=False,
    no_args_is_help=False,
    rich_markup_mode="rich",
)

app.registered_commands.extend(cmd_explorar.app.registered_commands)
app.registered_commands.extend(cmd_doctor.app.registered_commands)
app.add_typer(cmd_estrategia.app, name="estrategia", help="Crear, validar, activar y consultar estrategias.")
app.add_typer(cmd_tarea.app, name="tarea", help="Agregar, editar o eliminar tareas dentro de una estrategia.")
app.add_typer(cmd_repo.app, name="repo", help="Instala y administra el esquema del repositorio en BKPCAT.")
app.add_typer(cmd_db.app, name="db", help="Registra e inspecciona bases de datos Oracle en el repositorio.")
app.add_typer(cmd_param.app, name="param", help="Consulta y modifica los parámetros globales del repositorio.")


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
