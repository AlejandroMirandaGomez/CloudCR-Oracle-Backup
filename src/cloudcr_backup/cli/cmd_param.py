from typing import Annotated

import oracledb
import typer
from rich.table import Table

from cloudcr_backup.cli.cmd_repo import PARAMETROS_INICIALES
from cloudcr_backup.cli.comun import terminar_con_error
from cloudcr_backup.config.ajustes import cargar_ajustes
from cloudcr_backup.oracle.connection import ErrorConexionOracle
from cloudcr_backup.presentacion.terminal import consola
from cloudcr_backup.repository import parametros as repositorio_parametros
from cloudcr_backup.repository.conexion import RepositorioNoConfigurado, abrir_repositorio

app = typer.Typer(add_completion=False, help="Consulta y modifica los parámetros globales del repositorio.")


def _conectar() -> oracledb.Connection:
    try:
        return abrir_repositorio(cargar_ajustes())
    except RepositorioNoConfigurado as error:
        terminar_con_error(str(error), "Configure CLOUDCR_REPOSITORIO_DSN y CLOUDCR_REPO_CLAVE (vea .env.example).")
    except ErrorConexionOracle as error:
        terminar_con_error(str(error), error.sugerencia)


@app.command(help="Lista todos los parámetros guardados en el repositorio.")
def listar() -> None:
    conexion = _conectar()
    parametros = repositorio_parametros.listar(conexion)
    if not parametros:
        consola().print("No hay parámetros guardados. Ejecute 'cloudcr repo instalar' primero.", style="dim")
        return
    tabla = Table(title="Parámetros del repositorio")
    tabla.add_column("Clave", style="bold")
    tabla.add_column("Valor")
    for clave, valor in sorted(parametros.items()):
        tabla.add_row(clave, valor)
    consola().print(tabla)


@app.command(help="Muestra el valor de un parámetro.")
def obtener(clave: Annotated[str, typer.Argument(help="Clave del parámetro.")]) -> None:
    conexion = _conectar()
    valor = repositorio_parametros.obtener(conexion, clave)
    if valor is None:
        terminar_con_error(f"No existe el parámetro {clave}.")
    consola().print(valor)


@app.command(name="set", help="Asigna el valor de un parámetro (lo crea si no existe).")
def asignar(
    clave: Annotated[str, typer.Argument(help="Clave del parámetro.")],
    valor: Annotated[str, typer.Argument(help="Nuevo valor.")],
) -> None:
    conexion = _conectar()
    repositorio_parametros.asignar(conexion, clave, valor)
    consola().print(f"Parámetro [bold]{clave}[/] actualizado.", markup=True)


@app.command(help="Restablece un parámetro a su valor inicial de instalación.")
def restablecer(clave: Annotated[str, typer.Argument(help="Clave del parámetro.")]) -> None:
    if clave not in PARAMETROS_INICIALES:
        terminar_con_error(f"{clave} no es uno de los parámetros iniciales conocidos.")
    conexion = _conectar()
    repositorio_parametros.asignar(conexion, clave, PARAMETROS_INICIALES[clave])
    consola().print(f"Parámetro [bold]{clave}[/] restablecido a su valor inicial.", markup=True)
