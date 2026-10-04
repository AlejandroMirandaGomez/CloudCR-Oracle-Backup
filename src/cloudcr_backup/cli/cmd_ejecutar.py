from typing import Annotated

import typer
from rich.syntax import Syntax

from cloudcr_backup.cli.comun import terminar_con_error
from cloudcr_backup.cli.comun_monitoreo import ajustes, llamar
from cloudcr_backup.domain.ejecucion import ResultadoEjecucion
from cloudcr_backup.domain.enums import EstadoEjecucion, EstadoPrueba
from cloudcr_backup.presentacion.formato import formato_bytes
from cloudcr_backup.presentacion.terminal import consola
from cloudcr_backup.services import ejecucion as servicio_ejecucion

app = typer.Typer(add_completion=False)

ESTILO_ESTADO = {
    EstadoEjecucion.EXITOSA: "bold green",
    EstadoEjecucion.CON_ADVERTENCIAS: "bold yellow",
    EstadoEjecucion.FALLIDA: "bold red",
    EstadoEjecucion.BLOQUEADA: "bold red",
}


def mostrar_resultado(resultado: ResultadoEjecucion) -> None:
    salida = consola()
    estilo = ESTILO_ESTADO.get(resultado.estado, "bold")
    salida.print(
        f"Ejecución {resultado.ejecucion_id}: [{estilo}]{resultado.estado.value}[/] · "
        f"Pruebas: [bold]{resultado.estado_prueba.value}[/]",
        markup=True,
    )
    for motivo in resultado.motivos:
        salida.print(f"  · {motivo}", highlight=False)
    for pieza in resultado.piezas:
        marca = "OK   " if pieza.existe else "FALTA"
        salida.print(f"  {marca} {pieza.ruta} ({formato_bytes(pieza.tamano_bytes)})", highlight=False)
    if resultado.evidencia:
        salida.print(f"Evidencia: {resultado.evidencia}", highlight=False)
    if resultado.en_buzon:
        salida.print(
            "El repositorio no estaba disponible: la evidencia quedó en el buzón y el agente la sincronizará.",
            style="yellow",
        )
    for aviso in resultado.avisos:
        salida.print(aviso, style="yellow", highlight=False)


def codigo_de_salida(resultado: ResultadoEjecucion) -> int:
    if resultado.estado in (EstadoEjecucion.FALLIDA, EstadoEjecucion.BLOQUEADA):
        return 1
    return 1 if resultado.estado_prueba is EstadoPrueba.FALLIDA else 0


@app.command(help="Ejecuta ahora el script aprobado de una tarea: 'ejecutar EST001 T1 --ahora'.")
def ejecutar(
    codigo: Annotated[str, typer.Argument(help="Código de la estrategia.")],
    tarea: Annotated[str, typer.Argument(help="Código de la tarea.")],
    ahora: Annotated[bool, typer.Option("--ahora", help="Ejecuta el respaldo de inmediato.")] = False,
    simular: Annotated[
        bool, typer.Option("--simular", help="Revisa el preflight y muestra el comando, sin ejecutar RMAN.")
    ] = False,
    bd: Annotated[str | None, typer.Option("--bd", help="Base de datos registrada.")] = None,
) -> None:
    configuracion = ajustes()
    if simular:
        simulacion = llamar(lambda: servicio_ejecucion.simular(configuracion, bd, codigo, tarea))
        salida = consola()
        salida.print(
            f"[bold]{simulacion.bd} · {simulacion.estrategia}/{simulacion.tarea}[/] · script versión "
            f"{simulacion.version} ({simulacion.archivo})",
            markup=True,
        )
        salida.print(Syntax(simulacion.contenido, "sql", theme="ansi_dark", line_numbers=True))
        salida.print(f"Comando: {simulacion.comando}", highlight=False)
        if simulacion.aprobado:
            salida.print("[bold green]Preflight sin problemas.[/] No se ejecutó RMAN (--simular).", markup=True)
            return
        salida.print("[bold red]El preflight bloquearía la ejecución:[/]", markup=True)
        for problema in simulacion.problemas:
            salida.print(f"  · {problema}", highlight=False)
        raise typer.Exit(1)
    if not ahora:
        terminar_con_error(
            "Indique --ahora para ejecutar el respaldo de inmediato, o --simular para revisarlo sin ejecutar.",
            "Las ejecuciones programadas las dispara el agente ('cloudcr agente ejecutar').",
        )
    consola().print(f"Ejecutando {codigo.upper()}/{tarea.upper()} con RMAN…", style="dim")
    resultado = llamar(lambda: servicio_ejecucion.ejecutar_ahora(configuracion, bd, codigo, tarea))
    mostrar_resultado(resultado)
    raise typer.Exit(codigo_de_salida(resultado))


@app.command(help="Vuelve a verificar un respaldo ya hecho (CROSSCHECK + existencia + VALIDATE).")
def verificar(
    ejecucion_id: Annotated[int, typer.Argument(help="Id de la ejecución (columna Id del historial).")],
) -> None:
    configuracion = ajustes()
    resultado = llamar(lambda: servicio_ejecucion.verificar(configuracion, ejecucion_id))
    mostrar_resultado(resultado)
    raise typer.Exit(codigo_de_salida(resultado))
