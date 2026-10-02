from datetime import time
from pathlib import Path
from typing import cast

import questionary
import typer

from cloudcr_backup.cli.comun import terminar_con_error
from cloudcr_backup.config.ajustes import cargar_ajustes
from cloudcr_backup.domain.enums import (
    ContenidoTablespace,
    DiaSemana,
    LogMode,
    ModoRespaldo,
    Prioridad,
    TipoFrecuencia,
    TipoObjeto,
    TipoRespaldo,
)
from cloudcr_backup.domain.estrategia import (
    Como,
    Destino,
    Estrategia,
    ObjetoAlcance,
    Programacion,
    Retencion,
    Tarea,
)
from cloudcr_backup.domain.hallazgos import Hallazgo
from cloudcr_backup.domain.perfil_bd import PerfilBD
from cloudcr_backup.oracle.connection import ErrorConexionOracle
from cloudcr_backup.oracle.discovery import descubrir_instancias
from cloudcr_backup.oracle.explorador import InstanciaNoEncontrada, explorar_local, resolver_instancia
from cloudcr_backup.presentacion.terminal import consola, tabla_hallazgos
from cloudcr_backup.repository import bases_datos as repositorio_bases_datos
from cloudcr_backup.repository import conexion as repositorio_conexion
from cloudcr_backup.repository.conexion import RepositorioNoConfigurado
from cloudcr_backup.strategy import servicio
from cloudcr_backup.strategy.alcance import identificador_tablespace
from cloudcr_backup.strategy.codigos import siguiente_codigo_sugerido
from cloudcr_backup.strategy.plantillas_esquema import ParametrosEsquema, tareas_de, todos_los_esquemas
from cloudcr_backup.strategy.prioridad import criterio_de
from cloudcr_backup.strategy.yaml_io import estrategia_a_yaml, guardar_estrategia_yaml
from cloudcr_backup.validation import motor, reglas  # noqa: F401
from cloudcr_backup.validation.contexto import ContextoValidacion


def construir_opciones_alcance(perfil: PerfilBD) -> list[tuple[str, TipoObjeto, str]]:
    opciones: list[tuple[str, TipoObjeto, str]] = [("Toda la base de datos", TipoObjeto.BASE_DATOS, "")]
    for contenedor in perfil.contenedores:
        if contenedor.es_semilla:
            continue
        for tablespace in perfil.tablespaces_de(contenedor.con_id):
            if tablespace.contenido is ContenidoTablespace.TEMPORAL:
                continue
            identificador = identificador_tablespace(contenedor, tablespace.nombre)
            opciones.append((f"Tablespace {identificador}", TipoObjeto.TABLESPACE, identificador))
    opciones.append(("Control file", TipoObjeto.CONTROLFILE, ""))
    opciones.append(("SPFILE", TipoObjeto.SPFILE, ""))
    if perfil.log_mode is LogMode.ARCHIVELOG:
        opciones.append(("Archived logs", TipoObjeto.ARCHIVELOG, ""))
    return opciones


def _preguntar_texto(mensaje: str, valor_por_defecto: str = "") -> str:
    respuesta = questionary.text(mensaje, default=valor_por_defecto).ask()
    if respuesta is None:
        terminar_con_error("Asistente cancelado.")
    return cast(str, respuesta)


def _preguntar_seleccion(mensaje: str, opciones: list[str], valor_por_defecto: str | None = None) -> str:
    respuesta = questionary.select(mensaje, choices=opciones, default=valor_por_defecto).ask()
    if respuesta is None:
        terminar_con_error("Asistente cancelado.")
    return cast(str, respuesta)


def _preguntar_multiple(mensaje: str, opciones: list[str]) -> list[int]:
    elegidas = questionary.checkbox(
        mensaje, choices=[questionary.Choice(opcion, value=i) for i, opcion in enumerate(opciones)]
    ).ask()
    return cast(list[int], elegidas) if elegidas else []


def _preguntar_confirmacion(mensaje: str, valor_por_defecto: bool = False) -> bool:
    respuesta = questionary.confirm(mensaje, default=valor_por_defecto).ask()
    if respuesta is None:
        terminar_con_error("Asistente cancelado.")
    return cast(bool, respuesta)


def _preguntar_hora(mensaje: str, por_defecto: time) -> time:
    while True:
        texto = _preguntar_texto(mensaje, por_defecto.strftime("%H:%M"))
        try:
            return time.fromisoformat(texto)
        except ValueError:
            consola().print(f"'{texto}' no es una hora válida (HH:MM).", style="red")


def _codigos_existentes(bd_nombre: str) -> list[str]:
    try:
        conexion = repositorio_conexion.abrir_repositorio(cargar_ajustes())
    except (RepositorioNoConfigurado, ErrorConexionOracle):
        return []
    bd = repositorio_bases_datos.obtener(conexion, bd_nombre)
    if bd is None:
        return []
    return [estrategia.codigo for estrategia in servicio.listar(conexion, bd.id)]


def _paso_general(bd_nombre: str, codigos_existentes: list[str]) -> tuple[str, str, str | None, Prioridad, str]:
    sugerido = siguiente_codigo_sugerido(codigos_existentes)
    codigo = _preguntar_texto("Código de la estrategia", sugerido)
    if codigo in codigos_existentes:
        terminar_con_error(f"Ya existe una estrategia con el código {codigo} en {bd_nombre}.")
    nombre = _preguntar_texto("Nombre de la estrategia")
    descripcion = _preguntar_texto("Descripción (opcional, Enter para omitir)") or None
    prioridad = Prioridad(_preguntar_seleccion("Prioridad", [p.value for p in Prioridad]))
    creada_por = _preguntar_texto("Responsable (su nombre)")
    return codigo, nombre, descripcion, prioridad, creada_por


def _paso_que(perfil: PerfilBD, prioridad_estrategia: Prioridad) -> list[ObjetoAlcance]:
    opciones = construir_opciones_alcance(perfil)
    etiquetas = [etiqueta for etiqueta, _, _ in opciones]
    indices = _preguntar_multiple("Qué desea respaldar", etiquetas)
    if not indices:
        terminar_con_error("Debe seleccionar al menos un objeto para el alcance.")
    alcance = []
    for i in indices:
        _, tipo, identificador = opciones[i]
        prioridad_objeto = Prioridad(
            _preguntar_seleccion(
                f"Prioridad de {etiquetas[i]}", [p.value for p in Prioridad], prioridad_estrategia.value
            )
        )
        alcance.append(ObjetoAlcance(tipo=tipo, identificador=identificador, prioridad=prioridad_objeto))
    return alcance


def _paso_destino_y_retencion() -> tuple[str, Retencion]:
    ruta = _preguntar_texto("Ruta de destino de los respaldos", r"C:\backups\XE")
    tipo = _preguntar_seleccion(
        "Política de retención",
        ["Ventana de días", "Redundancia (cantidad de copias)", "Sin definir (no recomendado)"],
    )
    if tipo == "Ventana de días":
        return ruta, Retencion(ventana_dias=int(_preguntar_texto("¿Cuántos días conservar?", "30")))
    if tipo == "Redundancia (cantidad de copias)":
        return ruta, Retencion(redundancia=int(_preguntar_texto("¿Cuántas copias conservar?", "2")))
    return ruta, Retencion()


def _tareas_personalizadas(destino_ruta: str) -> list[Tarea]:
    tareas: list[Tarea] = []
    numero = 1
    while True:
        tipo_respaldo = TipoRespaldo(_preguntar_seleccion("Tipo de respaldo", [t.value for t in TipoRespaldo]))
        modo_respaldo = ModoRespaldo(
            _preguntar_seleccion("Modo", [m.value for m in ModoRespaldo], ModoRespaldo.AUTO.value)
        )
        tipo_frecuencia = TipoFrecuencia(_preguntar_seleccion("Frecuencia", [f.value for f in TipoFrecuencia]))
        hora = _preguntar_hora("Hora de ejecución", time(2, 0))
        tareas.append(
            Tarea(
                codigo=f"T{numero}",
                como=Como(tipo_respaldo=tipo_respaldo, modo_respaldo=modo_respaldo),
                programacion=Programacion(tipo_frecuencia=tipo_frecuencia, horas=[hora]),
                destino=Destino(ruta=destino_ruta),
            )
        )
        numero += 1
        if not _preguntar_confirmacion("¿Agregar otra tarea?", False):
            break
    return tareas


def _paso_como_y_cuando(destino_ruta: str) -> list[Tarea]:
    if not _preguntar_confirmacion("¿Usar un esquema predefinido?", True):
        return _tareas_personalizadas(destino_ruta)
    descripciones = todos_los_esquemas()
    etiquetas = [f"{d.nombre} — {d.descripcion}" for d in descripciones]
    elegida = _preguntar_seleccion("Esquema", etiquetas)
    esquema = descripciones[etiquetas.index(elegida)].esquema
    dias_semana = [d.value for d in DiaSemana]
    dia_n0 = DiaSemana(_preguntar_seleccion("Día de la semana del nivel 0", dias_semana, DiaSemana.DOMINGO.value))
    hora_n0 = _preguntar_hora("Hora del nivel 0", time(2, 0))
    hora_n1 = _preguntar_hora("Hora del nivel 1 / diario", time(15, 0))
    parametros = ParametrosEsquema(destino=Destino(ruta=destino_ruta), dia_n0=dia_n0, hora_n0=hora_n0, hora_n1=hora_n1)
    return tareas_de(esquema, parametros)


def _paso_validacion(estrategia: Estrategia, perfil: PerfilBD) -> list[Hallazgo]:
    hallazgos = motor.validar(ContextoValidacion(estrategia=estrategia, perfil=perfil))
    salida = consola()
    if hallazgos:
        salida.print(tabla_hallazgos(hallazgos))
    else:
        salida.print("Sin observaciones.", style="green")
    if motor.hay_bloqueantes(hallazgos):
        salida.print(
            "\n[bold red]Hay errores que bloquean esta estrategia. Corríjalos y vuelva a intentar.[/]", markup=True
        )
        raise typer.Exit(code=1)
    return hallazgos


def _paso_script(estrategia: Estrategia) -> None:
    consola().print(
        "\n[dim]El generador de script RMAN todavía no está implementado. "
        "Esta es la estrategia tal como va a quedar guardada:[/]",
        markup=True,
    )
    consola().print(estrategia_a_yaml(estrategia))


def _confirmar_consistente_si_aplica(tareas: list[Tarea]) -> None:
    if not any(t.como.modo_respaldo is ModoRespaldo.CONSISTENTE for t in tareas):
        return
    acepta = _preguntar_confirmacion(
        "Una o más tareas usan modo CONSISTENTE y van a apagar la base de datos. ¿Acepta la caída del servicio?",
        False,
    )
    if not acepta:
        terminar_con_error("No se puede continuar sin aceptar la caída del servicio en modo CONSISTENTE.")


def _paso_guardar_y_activar(estrategia: Estrategia, bd_nombre: str) -> None:
    salida = consola()
    archivo_defecto = f"config/estrategias/{estrategia.codigo.lower()}.yaml"
    archivo = Path(_preguntar_texto("Archivo YAML donde guardar la estrategia", archivo_defecto))
    guardar_estrategia_yaml(estrategia, archivo)
    salida.print(f"Guardada en [bold]{archivo}[/]", markup=True)

    if not _preguntar_confirmacion("¿Intentar guardarla también en el repositorio?", False):
        return
    try:
        conexion = repositorio_conexion.abrir_repositorio(cargar_ajustes())
    except (RepositorioNoConfigurado, ErrorConexionOracle) as error:
        salida.print(
            f"No se pudo conectar al repositorio ({error}); quedó guardada solo en el archivo.", style="yellow"
        )
        return
    bd = repositorio_bases_datos.obtener(conexion, bd_nombre)
    if bd is None:
        salida.print(f"No hay ninguna base de datos registrada con el nombre {bd_nombre}.", style="red")
        return
    nueva = estrategia.model_copy(update={"bd_id": bd.id})
    try:
        creada = servicio.crear(conexion, nueva)
    except servicio.EstrategiaYaExiste as error:
        salida.print(str(error), style="red")
        return
    salida.print(f"Creada en el repositorio como [bold]{creada.codigo}[/] (versión {creada.version}).", markup=True)
    if _preguntar_confirmacion("¿Activar la estrategia ahora?", False):
        servicio.activar(conexion, bd.id, creada.codigo)
        salida.print("Estrategia activada.", style="green")


def ejecutar(sid: str | None = None) -> None:
    salida = consola()
    salida.print("\n[bold]Asistente de estrategias — CloudCR Oracle Backup[/]", markup=True)

    try:
        instancia = resolver_instancia(descubrir_instancias(), sid, None)
    except InstanciaNoEncontrada as error:
        terminar_con_error(str(error), "Ejecute 'cloudcr descubrir' para ver las instancias disponibles.")
    try:
        perfil = explorar_local(instancia).perfil
    except ErrorConexionOracle as error:
        terminar_con_error(str(error), error.sugerencia)

    bd_nombre = _preguntar_texto(
        "Nombre de la base de datos (como la registró con 'cloudcr db agregar')", perfil.nombre
    )
    codigos = _codigos_existentes(bd_nombre)

    salida.print("\n[bold]Paso 1 — General[/]", markup=True)
    codigo, nombre, descripcion, prioridad, creada_por = _paso_general(bd_nombre, codigos)

    criterio = criterio_de(prioridad)
    salida.print(
        f"RPO <= {criterio.rpo_horas:.0f} h  ·  RTO <= {criterio.rto_horas:.0f} h  ·  "
        f"esquema sugerido: {criterio.esquema_sugerido}",
        style="dim",
    )

    salida.print("\n[bold]Paso 2 — Qué (alcance)[/]", markup=True)
    alcance = _paso_que(perfil, prioridad)

    salida.print("\n[bold]Paso 5 — Destino y retención[/]", markup=True)
    destino_ruta, retencion = _paso_destino_y_retencion()

    salida.print("\n[bold]Pasos 3 y 4 — Cómo y cuándo[/]", markup=True)
    tareas = _paso_como_y_cuando(destino_ruta)

    estrategia = Estrategia(
        bd_id=0,
        codigo=codigo,
        nombre=nombre,
        descripcion=descripcion,
        prioridad=prioridad,
        creada_por=creada_por,
        alcance=alcance,
        tareas=tareas,
        retencion=retencion,
    )

    salida.print("\n[bold]Paso 6 — Validación[/]", markup=True)
    _paso_validacion(estrategia, perfil)

    salida.print("\n[bold]Paso 7 — Script (vista previa)[/]", markup=True)
    _paso_script(estrategia)

    salida.print("\n[bold]Paso 8 — Aprobación[/]", markup=True)
    _confirmar_consistente_si_aplica(tareas)

    salida.print("\n[bold]Paso 9 — Guardar y activar[/]", markup=True)
    _paso_guardar_y_activar(estrategia, bd_nombre)
