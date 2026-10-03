from typing import Annotated

import typer

from cloudcr_backup.cli.comun_monitoreo import ajustes, llamar
from cloudcr_backup.presentacion.estado import REGLA_SEMAFORO
from cloudcr_backup.presentacion.historial import construir_tabla
from cloudcr_backup.presentacion.terminal import consola
from cloudcr_backup.presentacion.terminal_monitoreo import (
    tabla_agentes,
    tabla_alertas,
    tabla_historial,
    tabla_semaforos,
)
from cloudcr_backup.services import monitoreo

app = typer.Typer(add_completion=False)


@app.command(name="estado", help="Semáforo por estrategia, ejecuciones en curso, alertas vigentes y estado del agente.")
def estado(
    bd: Annotated[str | None, typer.Option("--bd", help="Solo esta base de datos registrada.")] = None,
    json_: Annotated[bool, typer.Option("--json", help="Salida en JSON (la misma que /api/estado).")] = False,
) -> None:
    configuracion = ajustes()
    general = llamar(lambda: monitoreo.estado_general(configuracion, bd))
    if json_:
        print(general.model_dump_json(indent=2))
        return
    salida = consola()
    zona = configuracion.zona_horaria
    if general.semaforos:
        salida.print(tabla_semaforos(general, zona))
    else:
        salida.print("No hay estrategias registradas en el repositorio.", style="dim")
    salida.print(REGLA_SEMAFORO, style="dim")
    if general.en_curso:
        salida.print(tabla_historial(construir_tabla(general.en_curso), "Ejecuciones en curso o por iniciar"))
    if general.alertas:
        salida.print(tabla_alertas(general.alertas, zona, "Alertas vigentes"))
    else:
        salida.print("Sin alertas vigentes.", style="green")
    if general.agentes:
        salida.print(tabla_agentes(general.agentes, zona))
    else:
        salida.print("[bold red]El agente no ha corrido nunca con esta carpeta de trabajo.[/]", markup=True)
