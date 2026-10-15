from typing import Annotated

import typer
from rich.table import Table

from cloudcr_backup.cli.comun import terminar_con_error
from cloudcr_backup.config.ajustes import cargar_ajustes, obtener_origen_oracle
from cloudcr_backup.oracle.connection import ErrorConexionOracle, ParametrosConexionRemota, conectar_remota
from cloudcr_backup.presentacion.terminal import consola
from cloudcr_backup.repository import esquema as repositorio_esquema
from cloudcr_backup.repository import parametros as repositorio_parametros
from cloudcr_backup.repository.conexion import (
    Conexion,
    ErrorConexionRepositorio,
    RepositorioNoConfigurado,
    abrir_repositorio,
)
from cloudcr_backup.repository.migracion_oracle import (
    DestinoConDatos,
    DestinoSinEsquema,
    MigracionIncompleta,
)
from cloudcr_backup.repository.migracion_oracle import migrar as migrar_desde_oracle
from cloudcr_backup.repository.preparacion import preparar as preparar_repositorio
from cloudcr_backup.services.administracion import PARAMETROS_INICIALES

app = typer.Typer(add_completion=False, help="Instala y administra el esquema del repositorio en MySQL.")


def _conectar() -> Conexion:
    try:
        return abrir_repositorio(cargar_ajustes())
    except RepositorioNoConfigurado as error:
        terminar_con_error(str(error), "Configure CLOUDCR_REPO_CLAVE (vea .env.example).")
    except ErrorConexionRepositorio as error:
        terminar_con_error(str(error), error.sugerencia)


@app.command(
    help=(
        "Crea las 12 tablas del repositorio (más la de procedimientos de recuperación) y carga los parámetros "
        "iniciales. Si las tablas ya existían, las elimina primero junto con sus datos."
    )
)
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


@app.command(help="Elimina las tablas del repositorio y todos sus datos.")
def desinstalar(
    confirmar: Annotated[
        bool, typer.Option("--confirmar", help="Confirma la eliminación sin preguntar.")
    ] = False,
) -> None:
    if not confirmar and not typer.confirm(
        "Esto elimina las tablas del repositorio y todos sus datos. ¿Continuar?"
    ):
        raise typer.Exit(1)
    conexion = _conectar()
    repositorio_esquema.desinstalar(conexion)
    consola().print("Repositorio desinstalado.", style="yellow")


@app.command(
    help=(
        "Crea en MySQL la base y el usuario del repositorio si no existen, usando el administrador de "
        "CLOUDCR_MYSQL_ADMIN_USUARIO / CLOUDCR_MYSQL_ADMIN_CLAVE. Si el repositorio ya es accesible no hace nada."
    )
)
def preparar() -> None:
    try:
        resultado = preparar_repositorio(cargar_ajustes())
    except ErrorConexionRepositorio as error:
        terminar_con_error(str(error), error.sugerencia)
    if resultado.ya_preparado:
        consola().print(f"La base {resultado.base} y el usuario {resultado.usuario} ya existen.", style="green")
        return
    consola().print(
        f"Base [bold]{resultado.base}[/] y usuario [bold]{resultado.usuario}[/] creados.", markup=True
    )


@app.command(
    "migrar-oracle",
    help=(
        "Copia a MySQL los datos del repositorio que estaba en Oracle (PDB BKPCAT). El destino debe tener el "
        "esquema instalado y vacío, salvo que use --reemplazar."
    ),
)
def migrar_oracle(
    dsn: Annotated[
        str | None,
        typer.Option(
            "--dsn", help="DSN del repositorio Oracle (host:puerto/servicio). Por defecto CLOUDCR_ORIGEN_DSN."
        ),
    ] = None,
    usuario: Annotated[
        str | None,
        typer.Option("--usuario", help="Usuario del repositorio Oracle. Por defecto CLOUDCR_ORIGEN_USUARIO."),
    ] = None,
    reemplazar: Annotated[
        bool, typer.Option("--reemplazar", help="Borra los datos que ya tenga MySQL antes de copiar.")
    ] = False,
) -> None:
    dsn_entorno, usuario_entorno, clave_entorno = obtener_origen_oracle()
    dsn_origen = dsn or dsn_entorno
    if not dsn_origen:
        terminar_con_error(
            "Falta el DSN del repositorio Oracle de origen.",
            "Indíquelo con --dsn (por ejemplo localhost:1521/BKPCAT) o en CLOUDCR_ORIGEN_DSN.",
        )
    clave_origen = clave_entorno or typer.prompt("Clave del usuario del repositorio Oracle", hide_input=True)
    try:
        origen = conectar_remota(
            ParametrosConexionRemota(
                dsn=dsn_origen, usuario=usuario or usuario_entorno, clave=clave_origen, como_sysdba=False
            )
        )
    except ErrorConexionOracle as error:
        terminar_con_error(str(error), error.sugerencia)
    destino = _conectar()
    try:
        resultado = migrar_desde_oracle(origen, destino, reemplazar=reemplazar)
    except (DestinoConDatos, DestinoSinEsquema, MigracionIncompleta) as error:
        sugerencia = (
            "Use --reemplazar para sobrescribir los datos de MySQL." if isinstance(error, DestinoConDatos) else None
        )
        terminar_con_error(str(error), sugerencia)
    finally:
        origen.close()
        destino.close()
    tabla = Table(title="Datos migrados de Oracle a MySQL")
    tabla.add_column("Tabla")
    tabla.add_column("Filas", justify="right")
    for nombre, filas in resultado.filas.items():
        tabla.add_row(nombre, str(filas))
    consola().print(tabla)
    consola().print(f"[bold green]Migración completa:[/] {resultado.total} filas.", markup=True)
