from pathlib import Path
from typing import Annotated

import oracledb
import typer
from rich.table import Table

from cloudcr_backup.cli.comun import terminar_con_error
from cloudcr_backup.config.ajustes import cargar_ajustes
from cloudcr_backup.oracle.connection import ErrorConexionOracle
from cloudcr_backup.oracle.discovery import descubrir_instancias
from cloudcr_backup.oracle.explorador import InstanciaNoEncontrada, explorar_local, resolver_instancia
from cloudcr_backup.presentacion.terminal import consola
from cloudcr_backup.repository import bases_datos as repositorio_bases_datos
from cloudcr_backup.repository.bases_datos import Ambiente, BaseDatosRegistrada
from cloudcr_backup.repository.conexion import RepositorioNoConfigurado, abrir_repositorio

app = typer.Typer(add_completion=False, help="Registra e inspecciona bases de datos Oracle en el repositorio.")


def _conectar() -> oracledb.Connection:
    try:
        return abrir_repositorio(cargar_ajustes())
    except RepositorioNoConfigurado as error:
        terminar_con_error(str(error), "Configure CLOUDCR_REPOSITORIO_DSN y CLOUDCR_REPO_CLAVE (vea .env.example).")
    except ErrorConexionOracle as error:
        terminar_con_error(str(error), error.sugerencia)


def _obtener_o_fallar(conexion: oracledb.Connection, nombre: str) -> BaseDatosRegistrada:
    bd = repositorio_bases_datos.obtener(conexion, nombre)
    if bd is None:
        terminar_con_error(
            f"No hay ninguna base de datos registrada con el nombre {nombre}.",
            "Use 'cloudcr db agregar' para registrarla primero.",
        )
    return bd


@app.command(help="Lista las instancias Oracle encontradas en esta máquina (igual que 'cloudcr descubrir').")
def descubrir() -> None:
    instancias = descubrir_instancias()
    if not instancias:
        terminar_con_error("No se encontró ninguna instancia Oracle en esta máquina.", codigo=1)
    tabla = Table(title="Instancias Oracle encontradas en esta máquina")
    tabla.add_column("SID", style="bold")
    tabla.add_column("Estado")
    tabla.add_column("ORACLE_HOME")
    for instancia in instancias:
        tabla.add_row(
            instancia.sid,
            "[green]en ejecución[/]" if instancia.en_ejecucion else "[yellow]detenida o desconocido[/]",
            str(instancia.oracle_home) if instancia.oracle_home else "[dim]desconocido[/]",
        )
    consola().print(tabla)


@app.command(help="Registra una base de datos Oracle en el repositorio.")
def agregar(
    sid: Annotated[str | None, typer.Argument(help="SID de la instancia. Si se omite, se detecta sola.")] = None,
    oracle_home: Annotated[
        Path | None, typer.Option("--oracle-home", help="ORACLE_HOME, si no se detecta solo.")
    ] = None,
    ambiente: Annotated[Ambiente, typer.Option("--ambiente", help="Ambiente de la base de datos.")] = (
        Ambiente.DESARROLLO
    ),
) -> None:
    try:
        instancia = resolver_instancia(descubrir_instancias(), sid, oracle_home)
    except InstanciaNoEncontrada as error:
        terminar_con_error(str(error), "Ejecute 'cloudcr descubrir' para ver las instancias disponibles.")
    if instancia.oracle_home is None:
        terminar_con_error(f"No se detectó el ORACLE_HOME de {instancia.sid}.", "Indíquelo con --oracle-home.")
    conexion = _conectar()
    try:
        registrada = repositorio_bases_datos.registrar(conexion, instancia.sid, str(instancia.oracle_home), ambiente)
    except repositorio_bases_datos.BaseDatosYaRegistrada as error:
        terminar_con_error(str(error))
    consola().print(f"Base de datos [bold]{registrada.nombre}[/] registrada (id {registrada.id}).", markup=True)


@app.command(help="Lista las bases de datos registradas en el repositorio.")
def listar() -> None:
    conexion = _conectar()
    registradas = repositorio_bases_datos.listar(conexion)
    if not registradas:
        consola().print("No hay bases de datos registradas.", style="dim")
        return
    tabla = Table(title="Bases de datos registradas")
    tabla.add_column("Nombre", style="bold")
    tabla.add_column("Ambiente")
    tabla.add_column("ORACLE_HOME")
    tabla.add_column("Activa")
    for bd in registradas:
        tabla.add_row(bd.nombre, bd.ambiente, bd.oracle_home, "Sí" if bd.activa else "No")
    consola().print(tabla)


@app.command(help="Muestra el detalle de una base de datos registrada.")
def mostrar(nombre: Annotated[str, typer.Argument(help="Nombre de la base de datos registrada.")]) -> None:
    conexion = _conectar()
    bd = _obtener_o_fallar(conexion, nombre)
    salida = consola()
    salida.print(f"\n[bold]{bd.nombre}[/]  ·  id {bd.id}", markup=True)
    salida.print(f"  Ambiente: {bd.ambiente}")
    salida.print(f"  ORACLE_HOME: {bd.oracle_home}")
    salida.print(f"  Activa: {'sí' if bd.activa else 'no'}")


@app.command(help="Inspecciona la base de datos registrada y guarda su perfil en el repositorio.")
def inspeccionar(nombre: Annotated[str, typer.Argument(help="Nombre de la base de datos registrada.")]) -> None:
    try:
        instancia = resolver_instancia(descubrir_instancias(), nombre, None)
    except InstanciaNoEncontrada as error:
        terminar_con_error(str(error), "Ejecute 'cloudcr descubrir' para ver las instancias disponibles.")
    try:
        with consola().status(f"Conectando a {nombre} e inspeccionando la instancia..."):
            exploracion = explorar_local(instancia)
    except ErrorConexionOracle as error:
        terminar_con_error(str(error), error.sugerencia)
    conexion = _conectar()
    bd = _obtener_o_fallar(conexion, nombre)
    repositorio_bases_datos.guardar_perfil(conexion, bd.id, exploracion.perfil)
    consola().print(f"Perfil de [bold]{bd.nombre}[/] guardado ({exploracion.perfil.capturado_en}).", markup=True)


@app.command(help="Desactiva una base de datos registrada (no la elimina).")
def desactivar(nombre: Annotated[str, typer.Argument(help="Nombre de la base de datos registrada.")]) -> None:
    conexion = _conectar()
    _obtener_o_fallar(conexion, nombre)
    repositorio_bases_datos.desactivar(conexion, nombre)
    consola().print(f"Base de datos [bold]{nombre}[/] desactivada.", markup=True)
