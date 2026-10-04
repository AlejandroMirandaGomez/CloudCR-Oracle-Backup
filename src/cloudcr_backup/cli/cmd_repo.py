from typing import Annotated

import oracledb
import typer
from rich.table import Table

from cloudcr_backup.cli.comun import terminar_con_error
from cloudcr_backup.config.ajustes import cargar_ajustes
from cloudcr_backup.oracle.connection import ErrorConexionOracle
from cloudcr_backup.presentacion.terminal import consola
from cloudcr_backup.repository import esquema as repositorio_esquema
from cloudcr_backup.repository import parametros as repositorio_parametros
from cloudcr_backup.repository.conexion import RepositorioNoConfigurado, abrir_repositorio
from cloudcr_backup.services.administracion import PARAMETROS_INICIALES

app = typer.Typer(add_completion=False, help="Instala y administra el esquema del repositorio en BKPCAT.")


def _conectar() -> oracledb.Connection:
    try:
        return abrir_repositorio(cargar_ajustes())
    except RepositorioNoConfigurado as error:
        terminar_con_error(str(error), "Configure CLOUDCR_REPOSITORIO_DSN y CLOUDCR_REPO_CLAVE (vea .env.example).")
    except ErrorConexionOracle as error:
        terminar_con_error(str(error), error.sugerencia)


@app.command(help="Crea las 12 tablas del repositorio y carga los parámetros iniciales. Es idempotente.")
def instalar() -> None:
    conexion = _conectar()
    repositorio_esquema.instalar(conexion)
    for clave, valor in PARAMETROS_INICIALES.items():
        if repositorio_parametros.obtener(conexion, clave) is None:
            repositorio_parametros.asignar(conexion, clave, valor)
    consola().print("[bold green]Repositorio instalado.[/]", markup=True)


@app.command(help="Muestra las tablas del repositorio y la cantidad de filas de cada una.")
def estado() -> None:
    conexion = _conectar()
    info = repositorio_esquema.estado(conexion)
    salida = consola()
    if not info.instalado:
        salida.print("[bold yellow]El repositorio no está instalado o está incompleto.[/]", markup=True)
        if info.tablas:
            salida.print(f"Tablas encontradas: {len(info.tablas)} de {len(repositorio_esquema.TABLAS)}")
        raise typer.Exit(1)
    tabla = Table(title="Estado del repositorio")
    tabla.add_column("Tabla")
    tabla.add_column("Filas", justify="right")
    for nombre, filas in sorted(info.tablas.items()):
        tabla.add_row(nombre, str(filas))
    salida.print(tabla)


@app.command(help="Elimina las 12 tablas del repositorio y todos sus datos.")
def desinstalar(
    confirmar: Annotated[
        bool, typer.Option("--confirmar", help="Confirma la eliminación sin preguntar.")
    ] = False,
) -> None:
    if not confirmar and not typer.confirm(
        "Esto elimina las 12 tablas del repositorio y todos sus datos. ¿Continuar?"
    ):
        raise typer.Exit(1)
    conexion = _conectar()
    repositorio_esquema.desinstalar(conexion)
    consola().print("Repositorio desinstalado.", style="yellow")
