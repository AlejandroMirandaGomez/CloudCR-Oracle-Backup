from typing import Annotated

import typer

from cloudcr_backup.cli.comun_monitoreo import ajustes, llamar
from cloudcr_backup.presentacion.terminal import consola
from cloudcr_backup.presentacion.terminal_monitoreo import tabla_alertas
from cloudcr_backup.services import alertas as servicio_alertas

app = typer.Typer(add_completion=False, help="Consulta, reconoce, resuelve y evalúa alertas.")

Estado = Annotated[
    str, typer.Option("--estado", help="vigentes (abiertas y reconocidas), todas, ABIERTA, RECONOCIDA o RESUELTA.")
]
Severidad = Annotated[str | None, typer.Option("--severidad", help="ALERTA, ADVERTENCIA o RECOMENDACION.")]
Json = Annotated[bool, typer.Option("--json", help="Salida en JSON (la misma que /api/alertas).")]


def _listar(estado: str, severidad: str | None, json_: bool) -> None:
    configuracion = ajustes()
    alertas = llamar(lambda: servicio_alertas.listar(configuracion, estado, severidad))
    if json_:
        print("[" + ",".join(a.model_dump_json() for a in alertas) + "]")
        return
    if not alertas:
        consola().print("No hay alertas para ese filtro.", style="green")
        return
    consola().print(tabla_alertas(alertas, configuracion.zona_horaria))


@app.callback(invoke_without_command=True)
def alertas(ctx: typer.Context, estado: Estado = "vigentes", severidad: Severidad = None, json_: Json = False) -> None:
    if ctx.invoked_subcommand is None:
        _listar(estado, severidad, json_)


@app.command(help="Lista las alertas (por defecto, las vigentes).")
def listar(estado: Estado = "vigentes", severidad: Severidad = None, json_: Json = False) -> None:
    _listar(estado, severidad, json_)


@app.command(help="Marca una alerta abierta como reconocida (sigue vigente hasta que se resuelva).")
def reconocer(alerta_id: Annotated[int, typer.Argument(help="Id de la alerta.")]) -> None:
    configuracion = ajustes()
    alerta = llamar(lambda: servicio_alertas.reconocer(configuracion, alerta_id))
    consola().print(f"Alerta [bold]{alerta.id}[/] ({alerta.codigo}) reconocida.", markup=True)


@app.command(help="Resuelve manualmente una alerta vigente (si la condición sigue, se volverá a abrir).")
def resolver(alerta_id: Annotated[int, typer.Argument(help="Id de la alerta.")]) -> None:
    configuracion = ajustes()
    alerta = llamar(lambda: servicio_alertas.resolver(configuracion, alerta_id))
    consola().print(f"Alerta [bold]{alerta.id}[/] ({alerta.codigo}) resuelta.", markup=True)


@app.command(help="Evalúa ahora todas las reglas de alerta (abre, actualiza y resuelve).")
def evaluar(
    sin_notificar: Annotated[bool, typer.Option("--sin-notificar", help="No envía notificaciones.")] = False,
) -> None:
    configuracion = ajustes()
    salida = consola()
    resumen = llamar(
        lambda: servicio_alertas.evaluar(
            configuracion, notificar=not sin_notificar, escribir=lambda t: salida.print(t, markup=False)
        )
    )
    salida.print(
        f"Evaluación terminada: {len(resumen.abiertas)} nuevas, {len(resumen.actualizadas)} siguen vigentes, "
        f"{len(resumen.resueltas)} resueltas."
    )
    for error in resumen.errores:
        salida.print(f"[yellow]Aviso:[/] {error}", markup=True)


@app.command("probar-correo", help="Envía un correo de prueba con la configuración de notificacion.email.*.")
def probar_correo() -> None:
    configuracion = ajustes()
    resultado = llamar(lambda: servicio_alertas.probar_correo(configuracion))
    consola().print(
        f"Correo de prueba enviado por {resultado.servidor} a {', '.join(resultado.destinatarios)}.", style="green"
    )


@app.command(
    "configurar-correo",
    help="Carga la configuración de correo del equipo (config/notificaciones.yaml) en el repositorio.",
)
def configurar_correo(
    sobrescribir: Annotated[
        bool, typer.Option("--sobrescribir", help="Reemplaza también los valores que ya fueron cambiados a mano.")
    ] = False,
) -> None:
    configuracion = ajustes()
    resultado = llamar(lambda: servicio_alertas.cargar_configuracion_del_equipo(configuracion, sobrescribir))
    salida = consola()
    salida.print(f"Configuración de correo cargada desde {resultado.archivo}.", style="green")
    salida.print(f"Aplicados: {', '.join(resultado.aplicados) or 'ninguno'}.")
    if resultado.conservados:
        salida.print(
            f"Conservados (ya tenían otro valor; use --sobrescribir para reemplazarlos): "
            f"{', '.join(resultado.conservados)}.",
            style="yellow",
        )
