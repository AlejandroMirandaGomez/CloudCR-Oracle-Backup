import getpass
from typing import Annotated

import typer
from rich.syntax import Syntax
from rich.table import Table

from cloudcr_backup.cli.comun_monitoreo import ajustes, llamar
from cloudcr_backup.domain.scripts import VistaScript
from cloudcr_backup.presentacion.terminal import consola, tabla_hallazgos
from cloudcr_backup.services import scripts as servicio_scripts

app = typer.Typer(add_completion=False, help="Genera, muestra, aprueba y rechaza los scripts RMAN de cada tarea.")

Codigo = Annotated[str, typer.Argument(help="Código de la estrategia, por ejemplo EST001.")]
CodigoTarea = Annotated[str, typer.Argument(help="Código de la tarea, por ejemplo T1.")]
Bd = Annotated[str | None, typer.Option("--bd", help="Base de datos registrada (si el código existe en varias).")]
Version = Annotated[int | None, typer.Option("--version", min=1, help="Versión concreta del script.")]
Json = Annotated[bool, typer.Option("--json", help="Salida en JSON.")]


def _encabezado(vista: VistaScript) -> str:
    caida = " · [bold red]CONSISTENTE: apaga la base[/]" if vista.requiere_caida else ""
    return (
        f"[bold]{vista.bd} · {vista.estrategia}/{vista.tarea}[/] · versión {vista.version} · {vista.estado.value}"
        f" · modo {vista.modo.value}{caida}"
    )


def mostrar_vista(vista: VistaScript, con_contenido: bool = True) -> None:
    salida = consola()
    salida.print(_encabezado(vista), markup=True)
    salida.print(f"SHA-256: {vista.hash_sha256}", highlight=False)
    if vista.archivo:
        estado = {True: "intacto", False: "[bold red]MODIFICADO[/]", None: "no existe todavía"}[vista.archivo_intacto]
        salida.print(f"Archivo: {vista.archivo} ({estado})", markup=True, highlight=False)
    if vista.aprobado_por:
        cuando = f" el {vista.aprobado_en:%Y-%m-%d %H:%M} UTC" if vista.aprobado_en else ""
        aceptada = " · caída aceptada" if vista.acepto_caida else ""
        salida.print(f"Aprobado por {vista.aprobado_por}{cuando}{aceptada}", highlight=False)
    if vista.motivo_rechazo:
        salida.print(f"Rechazado: {vista.motivo_rechazo}", style="red", highlight=False)
    if con_contenido:
        salida.print(Syntax(vista.contenido, "sql", theme="ansi_dark", line_numbers=True, word_wrap=True))
    if vista.explicacion:
        tabla = Table(title="De la estrategia al script (campo -> cláusula RMAN)", title_justify="left")
        tabla.add_column("Campo", style="bold")
        tabla.add_column("Cláusula RMAN")
        for fila in vista.explicacion:
            tabla.add_row(fila.campo, fila.clausula)
        salida.print(tabla)
    if vista.hallazgos:
        salida.print(tabla_hallazgos(vista.hallazgos))
    for aviso in vista.avisos:
        salida.print(aviso, style="yellow", highlight=False)


@app.command(help="Genera el script RMAN (borrador) de una tarea, o de todas las tareas de la estrategia.")
def generar(
    codigo: Codigo,
    tarea: Annotated[str | None, typer.Option("--tarea", help="Solo esta tarea.")] = None,
    bd: Bd = None,
    json_: Json = False,
) -> None:
    configuracion = ajustes()
    vistas = llamar(lambda: servicio_scripts.generar(configuracion, bd, codigo, tarea))
    if json_:
        print("[" + ",".join(v.model_dump_json() for v in vistas) + "]")
        return
    for vista in vistas:
        mostrar_vista(vista)
        estado = "Nueva versión generada" if vista.nueva else "Sin cambios"
        consola().print(
            f"{estado}. Revísela y apruébela con 'cloudcr script aprobar {vista.estrategia} {vista.tarea}'."
        )
        consola().print()


@app.command(help="Muestra el script de una tarea (por defecto el borrador vigente o el aprobado).")
def ver(codigo: Codigo, tarea: CodigoTarea, bd: Bd = None, version: Version = None, json_: Json = False) -> None:
    configuracion = ajustes()
    vista = llamar(lambda: servicio_scripts.ver(configuracion, bd, codigo, tarea, version))
    if json_:
        print(vista.model_dump_json(indent=2))
        return
    mostrar_vista(vista)


@app.command(help="Lista las versiones de los scripts de una estrategia.")
def listar(codigo: Codigo, bd: Bd = None) -> None:
    configuracion = ajustes()
    vistas = llamar(lambda: servicio_scripts.listar(configuracion, bd, codigo))
    if not vistas:
        consola().print("No hay scripts generados para esa estrategia.", style="dim")
        return
    tabla = Table()
    for columna in ("BD", "Estrategia", "Tarea", "Versión", "Estado", "Modo", "SHA-256", "Aprobado por"):
        tabla.add_column(columna)
    for vista in vistas:
        tabla.add_row(
            vista.bd,
            vista.estrategia,
            vista.tarea,
            str(vista.version),
            vista.estado.value,
            vista.modo.value,
            vista.hash_sha256[:12] + "…",
            vista.aprobado_por or "—",
        )
    consola().print(tabla)


@app.command(help="Aprueba el script de una tarea. Un respaldo CONSISTENTE exige --acepto-caida.")
def aprobar(
    codigo: Codigo,
    tarea: CodigoTarea,
    bd: Bd = None,
    acepto_caida: Annotated[
        bool, typer.Option("--acepto-caida", help="Acepta que el respaldo consistente apague la base.")
    ] = False,
    por: Annotated[str | None, typer.Option("--por", help="Quién aprueba (por defecto el usuario actual).")] = None,
    version: Version = None,
) -> None:
    configuracion = ajustes()
    aprobado_por = por or getpass.getuser()
    vista = llamar(
        lambda: servicio_scripts.aprobar(configuracion, bd, codigo, tarea, aprobado_por, acepto_caida, version)
    )
    mostrar_vista(vista, con_contenido=False)
    consola().print(
        f"[bold green]Script aprobado.[/] Ejecútelo con 'cloudcr ejecutar {codigo} {tarea} --ahora'.", markup=True
    )


@app.command(help="Rechaza el script borrador de una tarea indicando el motivo.")
def rechazar(
    codigo: Codigo,
    tarea: CodigoTarea,
    motivo: Annotated[str, typer.Option("--motivo", help="Por qué se rechaza.")],
    bd: Bd = None,
    version: Version = None,
) -> None:
    configuracion = ajustes()
    vista = llamar(lambda: servicio_scripts.rechazar(configuracion, bd, codigo, tarea, motivo, version))
    mostrar_vista(vista, con_contenido=False)
