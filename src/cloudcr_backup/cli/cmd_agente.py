from typing import Annotated

import typer

from cloudcr_backup.cli.comun import terminar_con_error
from cloudcr_backup.cli.comun_monitoreo import ajustes, llamar
from cloudcr_backup.domain.errores import ErrorServicio
from cloudcr_backup.presentacion.terminal import consola
from cloudcr_backup.presentacion.terminal_monitoreo import tabla_agentes
from cloudcr_backup.services import agente as servicio_agente

app = typer.Typer(add_completion=False, help="Ejecuta y consulta el agente que dispara los respaldos programados.")


@app.command(help="Corre el agente: reclama las ejecuciones vencidas, las despacha y evalúa alertas.")
def ejecutar(
    una_vez: Annotated[bool, typer.Option("--una-vez", help="Ejecuta un solo tick y termina.")] = False,
    simulado: Annotated[
        bool,
        typer.Option("--simulado", help="Usa el ejecutor de prueba (no ejecuta RMAN; queda rotulado SIMULACION)."),
    ] = False,
) -> None:
    configuracion = ajustes()
    salida = consola()

    def avisar(texto: str) -> None:
        salida.print(texto, markup=False, highlight=False)

    try:
        agente = servicio_agente.construir_agente(configuracion, simulado, avisar)
    except ErrorServicio as error:
        terminar_con_error(error.mensaje, error.sugerencia)
    if simulado:
        salida.print(
            "[bold yellow]MODO SIMULACIÓN:[/] las ejecuciones no corren RMAN; quedan rotuladas como SIMULACION "
            "en el historial y no cuentan como evidencia.",
            markup=True,
        )
    salida.print(
        f"Agente [bold]{servicio_agente.nombre_agente()}[/] iniciado · registro en "
        f"{configuracion.rutas.logs / servicio_agente.ARCHIVO_LOG}",
        markup=True,
    )
    if not una_vez:
        salida.print("Presione Ctrl+C para detenerlo (espera a que terminen las ejecuciones en curso).", style="dim")
    raise typer.Exit(agente.ejecutar(una_vez=una_vez))


@app.command(help="Muestra el último latido de cada agente que usa esta carpeta de trabajo.")
def estado(json_: Annotated[bool, typer.Option("--json", help="Salida en JSON.")] = False) -> None:
    configuracion = ajustes()
    agentes = llamar(lambda: servicio_agente.estado_agentes(configuracion))
    if json_:
        print("[" + ",".join(a.model_dump_json() for a in agentes) + "]")
        return
    if not agentes:
        terminar_con_error(
            f"No hay latidos en {configuracion.rutas.agente}: el agente nunca corrió con esta carpeta de trabajo.",
            "Inícielo con 'cloudcr agente ejecutar' (o '--simulado' para probar sin RMAN).",
            codigo=1,
        )
    consola().print(tabla_agentes(agentes, configuracion.zona_horaria))
    if not any(a.vivo for a in agentes):
        raise typer.Exit(1)
