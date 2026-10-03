from datetime import datetime

from cloudcr_backup.agent.bucle import ParametrosAgente
from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.domain.enums import EstadoEstrategia
from cloudcr_backup.domain.errores import OperacionNoPermitida, RecursoNoEncontrado
from cloudcr_backup.domain.estrategia import Programacion
from cloudcr_backup.domain.monitoreo import (
    ColorSemaforo,
    DetalleEstrategia,
    ResumenEstrategia,
    ScriptResumen,
    TareaDetalle,
)
from cloudcr_backup.presentacion.estrategias import describir_programacion, describir_retencion
from cloudcr_backup.repository import estrategias as repositorio_estrategias
from cloudcr_backup.scheduling.recurrencia import ProgramacionInvalida, construir_regla
from cloudcr_backup.scheduling.reloj import RelojSistema, utc_consciente
from cloudcr_backup.services.agente import sesion_agente
from cloudcr_backup.services.conversiones import etiquetas_alcance, momento_utc
from cloudcr_backup.services.fuente_oracle import EstrategiaRegistrada, FuenteOracle
from cloudcr_backup.services.monitoreo import estado_general
from cloudcr_backup.strategy.prioridad import criterio_de
from cloudcr_backup.strategy.vocabulario import equivalencia_de, etiqueta_doble

PROXIMAS_POR_DEFECTO = 5
PROXIMAS_MAXIMO = 100


def proximas_de(programacion: Programacion, cantidad: int, despues_de: datetime | None = None) -> list[datetime]:
    if not 1 <= cantidad <= PROXIMAS_MAXIMO:
        raise OperacionNoPermitida(f"La cantidad debe estar entre 1 y {PROXIMAS_MAXIMO}.")
    try:
        regla = construir_regla(programacion)
    except ProgramacionInvalida as error:
        raise OperacionNoPermitida(str(error), "Complete la programación de la tarea.") from error
    return regla.proximas(utc_consciente(despues_de or RelojSistema().ahora()), cantidad)


def _buscar(fuente: FuenteOracle, bd: str | None, codigo: str) -> EstrategiaRegistrada:
    candidatas = [
        r
        for r in fuente.estrategias_registradas()
        if r.estrategia.codigo == codigo.strip().upper() and (bd is None or r.base.nombre.upper() == bd.strip().upper())
    ]
    if len(candidatas) == 1:
        return candidatas[0]
    if not candidatas:
        lugar = f" en la base {bd.upper()}" if bd else ""
        raise RecursoNoEncontrado(
            f"No existe la estrategia {codigo.upper()}{lugar}.",
            "Use 'cloudcr estrategia listar --bd <BD>' para ver las registradas.",
        )
    bases = ", ".join(r.base.nombre for r in candidatas)
    raise OperacionNoPermitida(f"La estrategia {codigo.upper()} existe en varias bases ({bases}).", "Indique --bd.")


def _resumen(registrada: EstrategiaRegistrada, con_script: int) -> ResumenEstrategia:
    estrategia = registrada.estrategia
    return ResumenEstrategia(
        bd=registrada.base.nombre,
        bd_id=registrada.base.id,
        estrategia_id=estrategia.id,
        codigo=estrategia.codigo,
        nombre=estrategia.nombre,
        prioridad=estrategia.prioridad,
        estado=estrategia.estado,
        version=estrategia.version,
        tareas=len(estrategia.tareas),
        tareas_con_script=con_script,
    )


def listar(ajustes: Ajustes) -> list[ResumenEstrategia]:
    general = estado_general(ajustes)
    colores = {(s.bd, s.estrategia): s for s in general.semaforos}
    with sesion_agente(ajustes) as fuente:
        scripts = fuente.scripts_vigentes()
        resumenes = []
        for registrada in fuente.estrategias_registradas():
            con_script = sum(1 for tarea_id in registrada.ids_tareas.values() if tarea_id in scripts)
            resumen = _resumen(registrada, con_script)
            semaforo = colores.get((resumen.bd, resumen.codigo))
            if semaforo is not None:
                resumen = resumen.model_copy(
                    update={"color": semaforo.color, "proxima_ejecucion": semaforo.proxima_ejecucion}
                )
            resumenes.append(resumen)
    return resumenes


def detalle(ajustes: Ajustes, bd: str | None, codigo: str, cantidad: int = PROXIMAS_POR_DEFECTO) -> DetalleEstrategia:
    ahora = RelojSistema().ahora()
    with sesion_agente(ajustes) as fuente:
        registrada = _buscar(fuente, bd, codigo)
        scripts = fuente.scripts_vigentes()
    estrategia = registrada.estrategia
    tareas = []
    for tarea in estrategia.tareas:
        tarea_id = registrada.ids_tareas.get(tarea.codigo)
        script = scripts.get(tarea_id) if tarea_id is not None else None
        equivalencia = equivalencia_de(tarea.como.tipo_respaldo)
        proximas: list[datetime] = []
        error = None
        try:
            proximas = proximas_de(tarea.programacion, cantidad, ahora)
        except OperacionNoPermitida as problema:
            error = problema.mensaje
        tareas.append(
            TareaDetalle(
                codigo=tarea.codigo,
                tarea_id=tarea_id,
                tipo_respaldo=tarea.como.tipo_respaldo,
                etiqueta_tipo=etiqueta_doble(tarea.como.tipo_respaldo),
                termino_clase=equivalencia.termino_clase,
                modo_respaldo=tarea.como.modo_respaldo,
                programacion=tarea.programacion,
                descripcion_programacion=describir_programacion(tarea.programacion),
                destino=tarea.destino.ruta,
                script=(
                    ScriptResumen(
                        script_id=script.id,
                        version=script.version,
                        aprobado_por=script.aprobado_por,
                        aprobado_en=momento_utc(script.aprobado_en),
                    )
                    if script is not None
                    else None
                ),
                proximas=proximas,
                error_programacion=error,
            )
        )
    criterio = criterio_de(estrategia.prioridad)
    activa = estrategia.estado is EstadoEstrategia.ACTIVA
    proximas_todas = [p for t in tareas if t.script is not None for p in t.proximas]
    resumen = _resumen(registrada, sum(1 for t in tareas if t.script is not None)).model_copy(
        update={"proxima_ejecucion": min(proximas_todas) if proximas_todas and activa else None}
    )
    return DetalleEstrategia(
        resumen=resumen,
        estrategia=estrategia,
        rpo_horas=criterio.rpo_horas,
        rto_horas=criterio.rto_horas,
        recencia_maxima_horas=criterio.recencia_maxima_horas,
        tareas=tareas,
        retencion=describir_retencion(estrategia.retencion),
        alcance=etiquetas_alcance(estrategia.alcance),
    )


def proximas_de_tarea(ajustes: Ajustes, bd: str | None, codigo: str, tarea: str, cantidad: int) -> list[datetime]:
    with sesion_agente(ajustes) as fuente:
        registrada = _buscar(fuente, bd, codigo)
    encontrada = registrada.estrategia.tarea(tarea.upper())
    if encontrada is None:
        raise RecursoNoEncontrado(f"No existe la tarea {tarea.upper()} en la estrategia {codigo.upper()}.")
    return proximas_de(encontrada.programacion, cantidad)


def cambiar_estado(ajustes: Ajustes, bd: str | None, codigo: str, activa: bool) -> ResumenEstrategia:
    with sesion_agente(ajustes) as fuente:
        registrada = _buscar(fuente, bd, codigo)
        if activa:
            repositorio_estrategias.activar(fuente.conexion, registrada.base.id, registrada.estrategia.codigo)
        else:
            repositorio_estrategias.desactivar(fuente.conexion, registrada.base.id, registrada.estrategia.codigo)
        scripts = fuente.scripts_vigentes()
    estado = EstadoEstrategia.ACTIVA if activa else EstadoEstrategia.INACTIVA
    actualizada = EstrategiaRegistrada(
        registrada.base, registrada.estrategia.model_copy(update={"estado": estado}), registrada.ids_tareas
    )
    con_script = sum(1 for tarea_id in registrada.ids_tareas.values() if tarea_id in scripts)
    return _resumen(actualizada, con_script).model_copy(
        update={"color": ColorSemaforo.SIN_DATOS if not activa else ColorSemaforo.VERDE}
    )


def tick_y_gracia(ajustes: Ajustes) -> ParametrosAgente:
    with sesion_agente(ajustes) as fuente:
        return ParametrosAgente.desde(fuente.parametros())
