from datetime import date, time
from pathlib import Path
from typing import Annotated, TypeVar

import typer
from rich.table import Table

from cloudcr_backup.cli.comun import terminar_con_error
from cloudcr_backup.cli.comun_monitoreo import ajustes, llamar
from cloudcr_backup.domain.enums import (
    Compresion,
    DiaSemana,
    ModoRespaldo,
    PoliticaOmision,
    TipoFrecuencia,
    TipoRespaldo,
)
from cloudcr_backup.domain.estrategia import Como, Destino, Estrategia, OpcionesRespaldo, Programacion, Tarea, Ventana
from cloudcr_backup.presentacion.estrategias import describir_programacion
from cloudcr_backup.presentacion.terminal import consola
from cloudcr_backup.services import consulta_estrategias
from cloudcr_backup.strategy.yaml_io import EstrategiaYamlInvalida, cargar_estrategia_yaml, guardar_estrategia_yaml

app = typer.Typer(add_completion=False, help="Agrega, edita o elimina tareas dentro de una estrategia.")

T = TypeVar("T")


def _coalesce(nuevo: T | None, actual: T) -> T:
    return actual if nuevo is None else nuevo


def _cargar(archivo: Path) -> Estrategia:
    try:
        return cargar_estrategia_yaml(archivo)
    except EstrategiaYamlInvalida as error:
        terminar_con_error(str(error))


def _hora(texto: str) -> time:
    try:
        return time.fromisoformat(texto)
    except ValueError:
        terminar_con_error(f"'{texto}' no es una hora válida. Use el formato HH:MM.")


def _fecha(texto: str) -> date:
    try:
        return date.fromisoformat(texto)
    except ValueError:
        terminar_con_error(f"'{texto}' no es una fecha válida. Use el formato AAAA-MM-DD.")


def _reemplazar_tarea(estrategia: Estrategia, tarea: Tarea) -> Estrategia:
    tareas = [tarea if t.codigo == tarea.codigo else t for t in estrategia.tareas]
    return estrategia.model_copy(update={"tareas": tareas})


@app.command(help="Agrega una tarea nueva a una estrategia guardada en un archivo YAML.")
def agregar(
    archivo: Annotated[Path, typer.Argument(help="Archivo YAML de la estrategia.")],
    codigo: Annotated[str, typer.Argument(help="Código de la tarea, por ejemplo T1.")],
    tipo_respaldo: Annotated[TipoRespaldo, typer.Option("--tipo-respaldo")],
    destino: Annotated[str, typer.Option("--destino", help="Ruta donde se guardan las piezas del respaldo.")],
    tipo_frecuencia: Annotated[TipoFrecuencia, typer.Option("--frecuencia")] = TipoFrecuencia.DIARIA,
    modo_respaldo: Annotated[ModoRespaldo, typer.Option("--modo-respaldo")] = ModoRespaldo.AUTO,
    compresion: Annotated[Compresion, typer.Option("--compresion")] = Compresion.NINGUNA,
    canales: Annotated[int, typer.Option("--canales")] = 1,
    omitir_solo_lectura: Annotated[bool, typer.Option("--omitir-solo-lectura")] = False,
    hora: Annotated[list[str] | None, typer.Option("--hora", help="Hora HH:MM. Se puede repetir.")] = None,
    dia: Annotated[list[DiaSemana] | None, typer.Option("--dia", help="Día de la semana. Se puede repetir.")] = None,
    intervalo_minutos: Annotated[int | None, typer.Option("--intervalo-minutos")] = None,
    fecha_inicio: Annotated[str | None, typer.Option("--fecha-inicio", help="AAAA-MM-DD.")] = None,
    ventana_inicio: Annotated[str | None, typer.Option("--ventana-inicio", help="HH:MM.")] = None,
    ventana_fin: Annotated[str | None, typer.Option("--ventana-fin", help="HH:MM.")] = None,
    politica_omision: Annotated[
        PoliticaOmision, typer.Option("--politica-omision")
    ] = PoliticaOmision.EJECUTAR_EN_VENTANA,
    etiqueta: Annotated[str | None, typer.Option("--etiqueta")] = None,
) -> None:
    estrategia = _cargar(archivo)
    if estrategia.tarea(codigo) is not None:
        terminar_con_error(f"La tarea {codigo} ya existe en {estrategia.codigo}.")

    ventana = None
    if ventana_inicio is not None or ventana_fin is not None:
        if ventana_inicio is None or ventana_fin is None:
            terminar_con_error("La ventana necesita --ventana-inicio y --ventana-fin juntos.")
        ventana = Ventana(inicio=_hora(ventana_inicio), fin=_hora(ventana_fin))

    nueva = Tarea(
        codigo=codigo,
        como=Como(
            tipo_respaldo=tipo_respaldo,
            modo_respaldo=modo_respaldo,
            opciones=OpcionesRespaldo(
                compresion=compresion, canales=canales, omitir_solo_lectura=omitir_solo_lectura
            ),
        ),
        programacion=Programacion(
            tipo_frecuencia=tipo_frecuencia,
            horas=[_hora(h) for h in (hora or [])],
            dias_semana=dia or [],
            intervalo_minutos=intervalo_minutos,
            fecha_inicio=_fecha(fecha_inicio) if fecha_inicio else None,
            ventana=ventana,
            politica_omision=politica_omision,
        ),
        destino=Destino(ruta=destino, etiqueta=etiqueta),
    )
    actualizada = estrategia.model_copy(update={"tareas": [*estrategia.tareas, nueva]})
    guardar_estrategia_yaml(actualizada, archivo)
    consola().print(f"Tarea [bold]{codigo}[/] agregada a {estrategia.codigo}.", markup=True)


@app.command(help="Modifica una tarea existente de una estrategia guardada en un archivo YAML.")
def editar(
    archivo: Annotated[Path, typer.Argument(help="Archivo YAML de la estrategia.")],
    codigo: Annotated[str, typer.Argument(help="Código de la tarea a modificar.")],
    tipo_respaldo: Annotated[TipoRespaldo | None, typer.Option("--tipo-respaldo")] = None,
    modo_respaldo: Annotated[ModoRespaldo | None, typer.Option("--modo-respaldo")] = None,
    compresion: Annotated[Compresion | None, typer.Option("--compresion")] = None,
    canales: Annotated[int | None, typer.Option("--canales")] = None,
    omitir_solo_lectura: Annotated[
        bool | None, typer.Option("--omitir-solo-lectura/--no-omitir-solo-lectura")
    ] = None,
    tipo_frecuencia: Annotated[TipoFrecuencia | None, typer.Option("--frecuencia")] = None,
    hora: Annotated[list[str] | None, typer.Option("--hora", help="Reemplaza todas las horas.")] = None,
    dia: Annotated[list[DiaSemana] | None, typer.Option("--dia", help="Reemplaza todos los días.")] = None,
    intervalo_minutos: Annotated[int | None, typer.Option("--intervalo-minutos")] = None,
    fecha_inicio: Annotated[str | None, typer.Option("--fecha-inicio", help="AAAA-MM-DD.")] = None,
    ventana_inicio: Annotated[str | None, typer.Option("--ventana-inicio", help="HH:MM.")] = None,
    ventana_fin: Annotated[str | None, typer.Option("--ventana-fin", help="HH:MM.")] = None,
    politica_omision: Annotated[PoliticaOmision | None, typer.Option("--politica-omision")] = None,
    destino: Annotated[str | None, typer.Option("--destino")] = None,
    etiqueta: Annotated[str | None, typer.Option("--etiqueta")] = None,
) -> None:
    estrategia = _cargar(archivo)
    actual = estrategia.tarea(codigo)
    if actual is None:
        terminar_con_error(f"No existe la tarea {codigo} en {estrategia.codigo}.")

    ventana = actual.programacion.ventana
    if ventana_inicio is not None or ventana_fin is not None:
        inicio = _hora(ventana_inicio) if ventana_inicio is not None else (ventana.inicio if ventana else None)
        fin = _hora(ventana_fin) if ventana_fin is not None else (ventana.fin if ventana else None)
        if inicio is None or fin is None:
            terminar_con_error("La ventana necesita --ventana-inicio y --ventana-fin (o que la tarea ya tenga una).")
        ventana = Ventana(inicio=inicio, fin=fin)

    nueva = Tarea(
        codigo=codigo,
        como=Como(
            tipo_respaldo=_coalesce(tipo_respaldo, actual.como.tipo_respaldo),
            modo_respaldo=_coalesce(modo_respaldo, actual.como.modo_respaldo),
            opciones=OpcionesRespaldo(
                compresion=_coalesce(compresion, actual.como.opciones.compresion),
                canales=_coalesce(canales, actual.como.opciones.canales),
                omitir_solo_lectura=_coalesce(omitir_solo_lectura, actual.como.opciones.omitir_solo_lectura),
            ),
        ),
        programacion=Programacion(
            tipo_frecuencia=_coalesce(tipo_frecuencia, actual.programacion.tipo_frecuencia),
            horas=[_hora(h) for h in hora] if hora is not None else actual.programacion.horas,
            dias_semana=dia if dia is not None else actual.programacion.dias_semana,
            intervalo_minutos=_coalesce(intervalo_minutos, actual.programacion.intervalo_minutos),
            fecha_inicio=_fecha(fecha_inicio) if fecha_inicio is not None else actual.programacion.fecha_inicio,
            ventana=ventana,
            politica_omision=_coalesce(politica_omision, actual.programacion.politica_omision),
        ),
        destino=Destino(
            ruta=_coalesce(destino, actual.destino.ruta),
            etiqueta=_coalesce(etiqueta, actual.destino.etiqueta),
        ),
    )
    guardar_estrategia_yaml(_reemplazar_tarea(estrategia, nueva), archivo)
    consola().print(f"Tarea [bold]{codigo}[/] actualizada en {estrategia.codigo}.", markup=True)


@app.command(help="Elimina una tarea de una estrategia guardada en un archivo YAML.")
def eliminar(
    archivo: Annotated[Path, typer.Argument(help="Archivo YAML de la estrategia.")],
    codigo: Annotated[str, typer.Argument(help="Código de la tarea a eliminar.")],
) -> None:
    estrategia = _cargar(archivo)
    if estrategia.tarea(codigo) is None:
        terminar_con_error(f"No existe la tarea {codigo} en {estrategia.codigo}.")
    restantes = [t for t in estrategia.tareas if t.codigo != codigo]
    guardar_estrategia_yaml(estrategia.model_copy(update={"tareas": restantes}), archivo)
    consola().print(f"Tarea [bold]{codigo}[/] eliminada de {estrategia.codigo}.", markup=True)


DIAS_SEMANA = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


@app.command(
    help=(
        "Muestra las próximas ejecuciones de una tarea: 'proximas ESTRATEGIA TAREA [--bd XE]' desde el "
        "repositorio, o 'proximas TAREA --archivo ruta.yaml' desde un archivo."
    )
)
def proximas(
    primero: Annotated[str, typer.Argument(help="Código de la estrategia (o de la tarea si usa --archivo).")],
    segundo: Annotated[str | None, typer.Argument(help="Código de la tarea.")] = None,
    archivo: Annotated[Path | None, typer.Option("--archivo", help="Estrategia en YAML.")] = None,
    bd: Annotated[str | None, typer.Option("--bd", help="Base de datos registrada (si hay ambigüedad).")] = None,
    cantidad: Annotated[int, typer.Option("-n", "--cantidad", min=1, max=100, help="Cuántas mostrar.")] = 5,
) -> None:
    if archivo is not None:
        if segundo is not None:
            terminar_con_error("Con --archivo indique solo el código de la tarea.")
        estrategia = _cargar(archivo)
        tarea = estrategia.tarea(primero.upper())
        if tarea is None:
            terminar_con_error(f"No existe la tarea {primero.upper()} en {estrategia.codigo}.")
        programacion = tarea.programacion
        momentos = llamar(lambda: consulta_estrategias.proximas_de(programacion, cantidad))
        titulo = f"{estrategia.codigo}/{tarea.codigo}"
    else:
        if segundo is None:
            terminar_con_error("Indique ESTRATEGIA y TAREA, o use --archivo.")
        configuracion = ajustes()
        momentos = llamar(
            lambda: consulta_estrategias.proximas_de_tarea(configuracion, bd, primero, segundo, cantidad)
        )
        programacion = None
        titulo = f"{primero.upper()}/{segundo.upper()}"
    tabla = Table(title=f"Próximas ejecuciones de {titulo}")
    tabla.add_column("#", justify="right")
    tabla.add_column("Fecha")
    tabla.add_column("Día")
    tabla.add_column("Hora")
    for indice, momento in enumerate(momentos, start=1):
        tabla.add_row(
            str(indice), f"{momento:%Y-%m-%d}", DIAS_SEMANA[momento.weekday()], f"{momento:%H:%M} {momento:%Z}"
        )
    salida = consola()
    salida.print(tabla)
    if programacion is not None:
        salida.print(describir_programacion(programacion), style="dim")
