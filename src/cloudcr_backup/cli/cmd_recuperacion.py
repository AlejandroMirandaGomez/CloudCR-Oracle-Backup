import getpass
from datetime import datetime
from typing import Annotated

import typer
from rich.syntax import Syntax
from rich.table import Table

from cloudcr_backup.cli.comun import terminar_con_error
from cloudcr_backup.cli.comun_monitoreo import ajustes, llamar
from cloudcr_backup.domain.recuperacion import Escenario, ResultadoRecuperacion, VistaRecuperacion
from cloudcr_backup.presentacion.formato import formato_bytes
from cloudcr_backup.presentacion.operaciones import ETIQUETA_ESCENARIO
from cloudcr_backup.presentacion.terminal import consola
from cloudcr_backup.services import recuperacion as servicio_recuperacion

app = typer.Typer(
    add_completion=False,
    help=(
        "Puntos de recuperación, diagnóstico y procedimientos por escenario. Un procedimiento nunca se ejecuta "
        "solo: hay que aprobarlo y confirmar, y solo se ejecuta en bases de ambiente PRUEBAS."
    ),
)

Bd = Annotated[str, typer.Argument(help="Base de datos registrada, por ejemplo XE.")]
Json = Annotated[bool, typer.Option("--json", help="Salida en JSON.")]
ProcedimientoId = Annotated[int, typer.Argument(help="Número del procedimiento que mostró 'plan'.", min=1)]
Confirmo = Annotated[bool, typer.Option("--confirmo", help="Confirma explícitamente la operación.")]
FORMATOS_HASTA = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M")


@app.command(help="Lista los respaldos correctos desde los que se puede recuperar la base.")
def puntos(bd: Bd, json_: Json = False) -> None:
    configuracion = ajustes()
    resultado = llamar(lambda: servicio_recuperacion.puntos(configuracion, bd))
    if json_:
        print(resultado.model_dump_json(indent=2))
        return
    salida = consola()
    modo = resultado.log_mode.value if resultado.log_mode else "modo desconocido"
    salida.print(f"[bold]Puntos de recuperación de {resultado.bd}[/] · {modo}", markup=True)
    if resultado.puntos:
        tabla = Table()
        for columna in ("Ejecución", "Completado (UTC)", "Estrategia", "Tarea", "Tipo", "Alcance", "Pruebas", "Tamaño"):
            tabla.add_column(columna)
        for punto in resultado.puntos:
            tabla.add_row(
                str(punto.ejecucion_id),
                f"{punto.completado_en:%Y-%m-%d %H:%M}" if punto.completado_en else "—",
                punto.estrategia,
                punto.tarea,
                punto.tipo_respaldo.value,
                "Base completa" if punto.base_completa else ", ".join(punto.alcance),
                punto.estado_prueba.value,
                formato_bytes(punto.tamano_bytes),
            )
        salida.print(tabla)
    for aviso in resultado.avisos:
        salida.print(aviso, style="yellow", highlight=False)


@app.command(
    help=(
        "Consulta V$RECOVER_FILE, V$DATAFILE, V$DATABASE_BLOCK_CORRUPTION y V$LOGFILE para decir qué falta o está "
        "dañado y sugerir el escenario. Si hay falla, la anota en el calendario y abre una alerta."
    )
)
def diagnostico(bd: Bd, json_: Json = False) -> None:
    configuracion = ajustes()
    resultado = llamar(lambda: servicio_recuperacion.diagnostico(configuracion, bd))
    if json_:
        print(resultado.model_dump_json(indent=2))
        return
    salida = consola()
    salida.print(
        f"[bold]Diagnóstico de {resultado.bd}[/] · {resultado.open_mode or '—'} · "
        f"{resultado.log_mode.value if resultado.log_mode else '—'}",
        markup=True,
    )
    if resultado.archivos:
        tabla = Table()
        for columna in ("file#", "Tablespace", "Estado", "Error", "Origen", "Archivo"):
            tabla.add_column(columna)
        for archivo in resultado.archivos:
            tabla.add_row(
                str(archivo.file_id),
                archivo.identificador_tablespace or "—",
                archivo.estado,
                archivo.error or "—",
                archivo.origen,
                archivo.ruta,
            )
        salida.print(tabla)
    if resultado.bloques:
        tabla = Table(title="Bloques corruptos")
        for columna in ("file#", "Bloque", "Bloques", "Tipo", "Tablespace"):
            tabla.add_column(columna)
        for bloque in resultado.bloques:
            tabla.add_row(
                str(bloque.file_id),
                str(bloque.bloque),
                str(bloque.bloques),
                bloque.tipo or "—",
                bloque.tablespace or "—",
            )
        salida.print(tabla)
    if resultado.miembros_redo:
        tabla = Table(title="Miembros de redo log inválidos")
        for columna in ("Grupo", "Miembro", "Estado del grupo", "Grupo perdido"):
            tabla.add_column(columna)
        for miembro in resultado.miembros_redo:
            tabla.add_row(
                str(miembro.grupo), miembro.miembro, miembro.estado_grupo, "sí" if miembro.grupo_perdido else "no"
            )
        salida.print(tabla)
    for aviso in resultado.avisos:
        salida.print(aviso, style="yellow", highlight=False)
    for escenario in resultado.sugeridos:
        salida.print(f"Escenario sugerido: {escenario.value} ({ETIQUETA_ESCENARIO[escenario]})", highlight=False)


def _hasta(texto: str | None) -> datetime | None:
    if texto is None:
        return None
    for formato in FORMATOS_HASTA:
        try:
            return datetime.strptime(texto, formato)
        except ValueError:
            continue
    terminar_con_error(f"'{texto}' no es una fecha válida.", "Use el formato 'AAAA-MM-DD HH:MM'.")


@app.command(
    help=(
        "Genera el procedimiento de recuperación de un escenario. No lo ejecuta: ejecutarlo requiere aprobarlo "
        "('aprobar') y confirmar ('ejecutar'), y solo se permite en ambiente PRUEBAS."
    )
)
def plan(
    bd: Bd,
    escenario: Annotated[Escenario, typer.Argument(help="Escenario de falla.")],
    objetivo: Annotated[
        str | None,
        typer.Option(
            "--objetivo",
            help="PDB, tablespace (PDB:TS), file#, GRUPO:RUTA, secuencia o FILE#:BLOQUE. Se deduce si se omite.",
        ),
    ] = None,
    hasta: Annotated[str | None, typer.Option("--hasta", help="Momento objetivo 'AAAA-MM-DD HH:MM'.")] = None,
    json_: Json = False,
) -> None:
    configuracion = ajustes()
    momento = _hasta(hasta)
    resultado = llamar(lambda: servicio_recuperacion.plan(configuracion, bd, escenario.value, objetivo, momento))
    if json_:
        print(resultado.model_dump_json(indent=2))
        return
    salida = consola()
    salida.print(f"[bold]Recuperación {resultado.escenario.value} en {resultado.bd}[/]", markup=True)
    if not resultado.posible:
        salida.print(f"[bold red]No es posible:[/] {resultado.motivo}", markup=True)
        raise typer.Exit(1)
    if resultado.objetivo:
        salida.print(f"Objetivo: {resultado.objetivo}", highlight=False)
    for numero, paso in enumerate(resultado.pasos, start=1):
        salida.print(f"  {numero}. {paso}", highlight=False)
    if resultado.script:
        salida.print(Syntax(resultado.script, "sql", theme="ansi_dark", line_numbers=True))
    if resultado.archivo:
        salida.print(f"Guardado en {resultado.archivo} (no se ejecutó).", highlight=False)
    if resultado.id is not None:
        salida.print(
            f"Registrado como procedimiento {resultado.id}. Revíselo y apruébelo con "
            f"'cloudcr recuperacion aprobar {resultado.bd} {resultado.id} --confirmo'.",
            highlight=False,
        )
    for aviso in resultado.avisos:
        salida.print(aviso, style="yellow", highlight=False)


def mostrar_procedimiento(vista: VistaRecuperacion) -> None:
    salida = consola()
    registro = vista.registro
    estado = registro.estado.value + (f" · {registro.resultado.value}" if registro.resultado else "")
    salida.print(
        f"[bold]Procedimiento {registro.id}[/] · {registro.escenario.value} en {vista.bd} · {estado}", markup=True
    )
    if registro.aprobado_por:
        salida.print(f"Aprobado por {registro.aprobado_por}.", highlight=False)
    if registro.mensaje:
        salida.print(registro.mensaje, highlight=False)
    if vista.log_rman and registro.resultado is not None:
        salida.print(vista.log_rman, highlight=False, markup=False)
    if vista.bloqueo and registro.resultado is None:
        salida.print(vista.bloqueo, style="yellow", highlight=False)


@app.command(help="Aprueba un procedimiento generado: fija su huella SHA-256. No lo ejecuta.")
def aprobar(
    bd: Bd,
    procedimiento_id: ProcedimientoId,
    confirmo: Confirmo = False,
    por: Annotated[str | None, typer.Option("--por", help="Quién aprueba (por defecto el usuario actual).")] = None,
) -> None:
    configuracion = ajustes()
    aprobado_por = por or getpass.getuser()
    vista = llamar(lambda: servicio_recuperacion.aprobar(configuracion, bd, procedimiento_id, aprobado_por, confirmo))
    mostrar_procedimiento(vista)
    if vista.puede_ejecutar:
        consola().print(
            f"Ejecútelo con 'cloudcr recuperacion ejecutar {vista.bd} {procedimiento_id} --confirmo'.", highlight=False
        )


@app.command(
    help=(
        "Ejecuta con RMAN un procedimiento aprobado. Solo en bases de ambiente PRUEBAS, con el script intacto y "
        "--confirmo: modifica la base de datos y no se puede deshacer."
    )
)
def ejecutar(bd: Bd, procedimiento_id: ProcedimientoId, confirmo: Confirmo = False) -> None:
    configuracion = ajustes()
    vista = llamar(lambda: servicio_recuperacion.ejecutar(configuracion, bd, procedimiento_id, confirmo))
    mostrar_procedimiento(vista)
    if vista.registro.resultado is not ResultadoRecuperacion.EJECUTADO_OK:
        raise typer.Exit(1)
