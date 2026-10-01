from pathlib import Path
from typing import Annotated

import oracledb
import typer
from rich.table import Table

from cloudcr_backup.cli import asistente_estrategia
from cloudcr_backup.cli.comun import terminar_con_error
from cloudcr_backup.config.ajustes import cargar_ajustes
from cloudcr_backup.domain.enums import TipoObjeto
from cloudcr_backup.domain.estrategia import Estrategia, ObjetoAlcance
from cloudcr_backup.domain.perfil_bd import PerfilBD
from cloudcr_backup.oracle.connection import ErrorConexionOracle
from cloudcr_backup.oracle.discovery import descubrir_instancias
from cloudcr_backup.oracle.explorador import InstanciaNoEncontrada, explorar_local, resolver_instancia
from cloudcr_backup.presentacion.terminal import consola, tabla_hallazgos
from cloudcr_backup.repository import bases_datos as repositorio_bases_datos
from cloudcr_backup.repository import conexion as repositorio_conexion
from cloudcr_backup.repository.conexion import RepositorioNoConfigurado
from cloudcr_backup.strategy import servicio
from cloudcr_backup.strategy.prioridad import criterio_de
from cloudcr_backup.strategy.vocabulario import etiqueta_doble
from cloudcr_backup.strategy.yaml_io import (
    EstrategiaYamlInvalida,
    cargar_estrategia_yaml,
    guardar_estrategia_yaml,
)
from cloudcr_backup.validation import motor, reglas  # noqa: F401
from cloudcr_backup.validation.contexto import ContextoValidacion

app = typer.Typer(add_completion=False, help="Administra estrategias de respaldo: qué, cómo, cuándo y su validación.")


def _conectar_repositorio() -> oracledb.Connection:
    try:
        return repositorio_conexion.abrir_repositorio(cargar_ajustes())
    except RepositorioNoConfigurado as error:
        terminar_con_error(str(error), "Configure CLOUDCR_REPOSITORIO_DSN y CLOUDCR_REPO_CLAVE (vea .env.example).")
    except ErrorConexionOracle as error:
        terminar_con_error(str(error), error.sugerencia)


def _bd_id_de(conexion: oracledb.Connection, nombre: str) -> int:
    bd = repositorio_bases_datos.obtener(conexion, nombre)
    if bd is None:
        terminar_con_error(
            f"No hay ninguna base de datos registrada con el nombre {nombre}.",
            "Use 'cloudcr db agregar' para registrarla primero.",
        )
    return bd.id


def _perfil_local(sid: str | None) -> PerfilBD:
    try:
        instancia = resolver_instancia(descubrir_instancias(), sid, None)
    except InstanciaNoEncontrada as error:
        terminar_con_error(str(error), "Ejecute 'cloudcr descubrir' para ver las instancias disponibles.")
    try:
        return explorar_local(instancia).perfil
    except ErrorConexionOracle as error:
        terminar_con_error(str(error), error.sugerencia)


def _cargar_desde_archivo(archivo: Path) -> Estrategia:
    try:
        return cargar_estrategia_yaml(archivo)
    except EstrategiaYamlInvalida as error:
        terminar_con_error(str(error))


def _obtener_o_fallar(conexion: oracledb.Connection, bd_id: int, bd: str, codigo: str) -> Estrategia:
    estrategia = servicio.obtener(conexion, bd_id, codigo)
    if estrategia is None:
        terminar_con_error(f"No existe la estrategia {codigo} en {bd}.")
    return estrategia


@app.command(help="Abre el asistente interactivo para crear una estrategia paso a paso.")
def crear(
    sid: Annotated[str | None, typer.Option("--sid", help="SID de la instancia local. Se detecta si se omite.")] = None,
) -> None:
    asistente_estrategia.ejecutar(sid)


@app.command(help="Valida una estrategia (de un archivo YAML, o ya guardada) contra el perfil real de la base.")
def validar(
    archivo: Annotated[
        Path | None, typer.Option("--archivo", help="Estrategia en YAML a validar, sin guardarla.")
    ] = None,
    bd: Annotated[str | None, typer.Option("--bd", help="Nombre de la base de datos registrada.")] = None,
    codigo: Annotated[str | None, typer.Option("--codigo", help="Código de la estrategia ya guardada.")] = None,
    sid: Annotated[str | None, typer.Option("--sid", help="SID de la instancia local. Se detecta si se omite.")] = None,
) -> None:
    if archivo is not None:
        estrategia = _cargar_desde_archivo(archivo)
    else:
        if bd is None or codigo is None:
            terminar_con_error("Indique --archivo, o --bd y --codigo juntos.")
        conexion = _conectar_repositorio()
        estrategia = _obtener_o_fallar(conexion, _bd_id_de(conexion, bd), bd, codigo)

    contexto = ContextoValidacion(estrategia=estrategia, perfil=_perfil_local(sid))
    hallazgos = motor.validar(contexto)
    salida = consola()
    salida.print(f"\nValidación de [bold]{estrategia.codigo}[/] — {estrategia.nombre}", markup=True)
    if not hallazgos:
        salida.print("Sin observaciones.", style="green")
    else:
        salida.print(tabla_hallazgos(hallazgos))
    if motor.hay_bloqueantes(hallazgos):
        salida.print("\n[bold red]Hay errores que bloquean la aprobación de esta estrategia.[/]", markup=True)
        raise typer.Exit(code=1)
    salida.print("\n[bold green]Sin errores bloqueantes.[/]", markup=True)


@app.command(help="Muestra el detalle de una estrategia: qué, cómo, cuándo y su retención.")
def mostrar(
    archivo: Annotated[Path | None, typer.Option("--archivo", help="Estrategia en YAML a mostrar.")] = None,
    bd: Annotated[str | None, typer.Option("--bd", help="Nombre de la base de datos registrada.")] = None,
    codigo: Annotated[str | None, typer.Option("--codigo", help="Código de la estrategia ya guardada.")] = None,
) -> None:
    if archivo is not None:
        estrategia = _cargar_desde_archivo(archivo)
    else:
        if bd is None or codigo is None:
            terminar_con_error("Indique --archivo, o --bd y --codigo juntos.")
        conexion = _conectar_repositorio()
        estrategia = _obtener_o_fallar(conexion, _bd_id_de(conexion, bd), bd, codigo)

    criterio = criterio_de(estrategia.prioridad)
    salida = consola()
    salida.print(
        f"\n[bold]{estrategia.codigo}[/] — {estrategia.nombre}  ·  prioridad {estrategia.prioridad}  ·  "
        f"{estrategia.estado}  ·  versión {estrategia.version}",
        markup=True,
    )
    if estrategia.descripcion:
        salida.print(estrategia.descripcion, style="dim")
    salida.print(
        f"RPO <= {criterio.rpo_horas:.0f} h  ·  RTO <= {criterio.rto_horas:.0f} h  ·  "
        f"respaldar al menos cada {criterio.recencia_maxima_horas:.0f} h",
        style="dim",
    )

    salida.print("\n[bold]Qué (alcance)[/]", markup=True)
    for objeto in estrategia.alcance:
        identificador = objeto.identificador or "(toda la base)"
        salida.print(f"  - {objeto.tipo}: {identificador}  ·  prioridad {objeto.prioridad}")

    salida.print("\n[bold]Tareas (cómo y cuándo)[/]", markup=True)
    for tarea in estrategia.tareas:
        salida.print(
            f"  [bold]{tarea.codigo}[/] — {etiqueta_doble(tarea.como.tipo_respaldo)}  ·  "
            f"modo {tarea.como.modo_respaldo}",
            markup=True,
        )
        salida.print(
            f"      frecuencia {tarea.programacion.tipo_frecuencia}  ·  destino {tarea.destino.ruta}", style="dim"
        )

    retencion = estrategia.retencion
    salida.print("\n[bold]Retención[/]", markup=True)
    if retencion.ventana_dias is not None:
        salida.print(f"  ventana de {retencion.ventana_dias} días")
    elif retencion.redundancia is not None:
        salida.print(f"  redundancia de {retencion.redundancia} copias")
    else:
        salida.print("  sin política definida", style="yellow")


@app.command(help="Importa una estrategia desde un archivo YAML y la guarda en el repositorio.")
def importar(
    archivo: Annotated[Path, typer.Argument(help="Archivo YAML con la estrategia.")],
    bd: Annotated[str, typer.Option("--bd", help="Nombre de la base de datos registrada.")],
) -> None:
    estrategia = _cargar_desde_archivo(archivo)
    conexion = _conectar_repositorio()
    nueva = estrategia.model_copy(update={"bd_id": _bd_id_de(conexion, bd)})
    try:
        creada = servicio.crear(conexion, nueva)
    except servicio.EstrategiaYaExiste as error:
        terminar_con_error(str(error))
    consola().print(f"Estrategia [bold]{creada.codigo}[/] creada (versión {creada.version}).", markup=True)


@app.command(help="Reemplaza una estrategia guardada por el contenido de un archivo YAML (incrementa versión).")
def editar(
    archivo: Annotated[Path, typer.Argument(help="Archivo YAML con la estrategia actualizada.")],
    bd: Annotated[str, typer.Option("--bd", help="Nombre de la base de datos registrada.")],
) -> None:
    estrategia = _cargar_desde_archivo(archivo)
    conexion = _conectar_repositorio()
    actualizada = estrategia.model_copy(update={"bd_id": _bd_id_de(conexion, bd)})
    try:
        editada = servicio.editar(conexion, actualizada)
    except servicio.EstrategiaNoEncontrada as error:
        terminar_con_error(str(error))
    consola().print(f"Estrategia [bold]{editada.codigo}[/] actualizada a la versión {editada.version}.", markup=True)


@app.command(help="Exporta una estrategia guardada a un archivo YAML.")
def exportar(
    codigo: Annotated[str, typer.Argument(help="Código de la estrategia.")],
    bd: Annotated[str, typer.Option("--bd", help="Nombre de la base de datos registrada.")],
    archivo: Annotated[Path, typer.Option("--archivo", help="Dónde guardar el YAML.")],
) -> None:
    conexion = _conectar_repositorio()
    estrategia = _obtener_o_fallar(conexion, _bd_id_de(conexion, bd), bd, codigo)
    guardar_estrategia_yaml(estrategia, archivo)
    consola().print(f"Exportado a [bold]{archivo}[/]", markup=True)


@app.command(help="Lista las estrategias registradas para una base de datos.")
def listar(bd: Annotated[str, typer.Option("--bd", help="Nombre de la base de datos registrada.")]) -> None:
    conexion = _conectar_repositorio()
    estrategias = servicio.listar(conexion, _bd_id_de(conexion, bd))
    if not estrategias:
        consola().print("No hay estrategias registradas para esta base de datos.", style="dim")
        return
    tabla = Table(title=f"Estrategias de {bd}")
    tabla.add_column("Código")
    tabla.add_column("Nombre")
    tabla.add_column("Prioridad")
    tabla.add_column("Estado")
    tabla.add_column("Versión")
    for estrategia in estrategias:
        tabla.add_row(
            estrategia.codigo, estrategia.nombre, estrategia.prioridad, estrategia.estado, str(estrategia.version)
        )
    consola().print(tabla)


@app.command(help="Activa una estrategia para que el agente la tenga en cuenta.")
def activar(
    codigo: Annotated[str, typer.Argument(help="Código de la estrategia.")],
    bd: Annotated[str, typer.Option("--bd", help="Nombre de la base de datos registrada.")],
) -> None:
    conexion = _conectar_repositorio()
    servicio.activar(conexion, _bd_id_de(conexion, bd), codigo)
    consola().print(f"Estrategia [bold]{codigo}[/] activada.", markup=True)


@app.command(help="Desactiva una estrategia.")
def desactivar(
    codigo: Annotated[str, typer.Argument(help="Código de la estrategia.")],
    bd: Annotated[str, typer.Option("--bd", help="Nombre de la base de datos registrada.")],
) -> None:
    conexion = _conectar_repositorio()
    servicio.desactivar(conexion, _bd_id_de(conexion, bd), codigo)
    consola().print(f"Estrategia [bold]{codigo}[/] desactivada.", markup=True)


@app.command(help="Elimina lógicamente una estrategia (equivale a desactivarla).")
def eliminar(
    codigo: Annotated[str, typer.Argument(help="Código de la estrategia.")],
    bd: Annotated[str, typer.Option("--bd", help="Nombre de la base de datos registrada.")],
) -> None:
    conexion = _conectar_repositorio()
    servicio.eliminar(conexion, _bd_id_de(conexion, bd), codigo)
    consola().print(f"Estrategia [bold]{codigo}[/] eliminada (desactivada).", markup=True)


@app.command(name="aplicar-recomendacion", help="Aplica automáticamente una recomendación del validador.")
def aplicar_recomendacion(
    codigo: Annotated[str, typer.Argument(help="Código de la estrategia.")],
    recomendacion: Annotated[str, typer.Argument(help="Código de la recomendación, por ejemplo ARCH_002.")],
    bd: Annotated[str, typer.Option("--bd", help="Nombre de la base de datos registrada.")],
) -> None:
    if recomendacion != "ARCH_002":
        terminar_con_error(
            f"La recomendación {recomendacion} todavía no se puede aplicar automáticamente.",
            "Por ahora solo ARCH_002 (agregar archived logs al alcance) está implementada.",
        )
    conexion = _conectar_repositorio()
    estrategia = _obtener_o_fallar(conexion, _bd_id_de(conexion, bd), bd, codigo)
    if any(objeto.tipo is TipoObjeto.ARCHIVELOG for objeto in estrategia.alcance):
        consola().print("La estrategia ya incluye los archived logs en su alcance.", style="dim")
        return
    nuevo_objeto = ObjetoAlcance(tipo=TipoObjeto.ARCHIVELOG, identificador="", prioridad=estrategia.prioridad)
    actualizada = estrategia.model_copy(update={"alcance": [*estrategia.alcance, nuevo_objeto]})
    editada = servicio.editar(conexion, actualizada)
    consola().print(
        f"Se agregó ARCHIVELOG al alcance de [bold]{editada.codigo}[/] (versión {editada.version}).", markup=True
    )
