from datetime import datetime
from typing import Any

from cloudcr_backup.agent.bucle import ParametrosAgente
from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.domain.alertas import SeveridadAlerta, VistaAlerta
from cloudcr_backup.domain.enums import EstadoEjecucion, EstadoEstrategia, EstadoPrueba
from cloudcr_backup.domain.historial import FilaHistorial
from cloudcr_backup.domain.monitoreo import ColorSemaforo, EstadoGeneral, ObservacionesBase, SemaforoEstrategia
from cloudcr_backup.oracle.observaciones import afinamiento_redo, redo_logs
from cloudcr_backup.presentacion.historial import TEXTO_PRUEBAS, TEXTO_RESULTADO
from cloudcr_backup.repository import bases_datos as repositorio_bases_datos
from cloudcr_backup.repository import ejecuciones as repositorio_ejecuciones
from cloudcr_backup.scheduling.planificador import Planificador
from cloudcr_backup.scheduling.reloj import RelojSistema, utc_consciente
from cloudcr_backup.services.agente import estado_agentes, sesion_agente
from cloudcr_backup.services.conversiones import fila_historial

EJECUCIONES_POR_TAREA = 3
ESTADOS_ROJOS = (EstadoEjecucion.FALLIDA, EstadoEjecucion.BLOQUEADA, EstadoEjecucion.NO_EJECUTADA)
PRUEBAS_AMARILLAS = (EstadoPrueba.PENDIENTE, EstadoPrueba.FALLIDA)


def color_semaforo(
    activa: bool,
    con_script: bool,
    ultimas_por_tarea: dict[str, FilaHistorial | None],
    alertas: list[VistaAlerta],
) -> tuple[ColorSemaforo, list[str]]:
    if not activa:
        return ColorSemaforo.SIN_DATOS, ["La estrategia está inactiva."]
    if not con_script:
        return ColorSemaforo.SIN_DATOS, ["Ninguna tarea tiene un script RMAN aprobado."]
    rojos: list[str] = []
    amarillos: list[str] = []
    for alerta in alertas:
        if not alerta.vigente:
            continue
        motivo = f"Alerta {alerta.codigo} ({alerta.severidad.value}) vigente."
        if alerta.severidad is SeveridadAlerta.ALERTA:
            rojos.append(motivo)
        elif alerta.severidad is SeveridadAlerta.ADVERTENCIA:
            amarillos.append(motivo)
    for tarea, ultima in ultimas_por_tarea.items():
        if ultima is None:
            continue
        resultado = TEXTO_RESULTADO[ultima.estado]
        if ultima.estado in ESTADOS_ROJOS:
            rojos.append(f"Última ejecución de {tarea}: {resultado}.")
        elif ultima.estado is EstadoEjecucion.CON_ADVERTENCIAS:
            amarillos.append(f"Última ejecución de {tarea}: {resultado}.")
        elif ultima.estado_prueba in PRUEBAS_AMARILLAS:
            amarillos.append(f"Pruebas de la última ejecución de {tarea}: {TEXTO_PRUEBAS[ultima.estado_prueba]}.")
    if rojos:
        return ColorSemaforo.ROJO, rojos + amarillos
    if amarillos:
        return ColorSemaforo.AMARILLO, amarillos
    if all(ultima is None for ultima in ultimas_por_tarea.values()):
        return ColorSemaforo.VERDE, ["Sin ejecuciones todavía."]
    return ColorSemaforo.VERDE, []


def _observaciones_de_redo(conexion: Any, filtro_bd: str | None) -> list[ObservacionesBase]:
    observaciones: list[ObservacionesBase] = []
    for base in repositorio_bases_datos.listar(conexion):
        if not base.activa or filtro_bd not in (None, base.nombre.upper()):
            continue
        perfil = repositorio_bases_datos.ultimo_perfil(conexion, base.id)
        if perfil is None:
            continue
        hallazgos = [*redo_logs(perfil), *afinamiento_redo(perfil)]
        observaciones.append(ObservacionesBase(bd=base.nombre, capturado_en=perfil.capturado_en, hallazgos=hallazgos))
    return observaciones


def estado_general(ajustes: Ajustes, bd: str | None = None, ahora: datetime | None = None) -> EstadoGeneral:
    momento = utc_consciente(ahora or RelojSistema().ahora())
    filtro_bd = bd.strip().upper() if bd else None
    with sesion_agente(ajustes) as fuente:
        parametros = ParametrosAgente.desde(fuente.parametros())
        planificador = Planificador(fuente, parametros.gracia, parametros.horizonte)
        programables = {t.tarea_id: t for t in fuente.tareas_programables()}
        scripts = fuente.scripts_vigentes()
        ultimas = repositorio_ejecuciones.ultimas_por_tarea(fuente.conexion, EJECUCIONES_POR_TAREA)
        alertas = fuente.vigentes()
        en_curso = [fila_historial(e) for e in repositorio_ejecuciones.en_curso(fuente.conexion)]
        observaciones_redo = _observaciones_de_redo(fuente.conexion, filtro_bd)
        registradas = [r for r in fuente.estrategias_registradas() if filtro_bd in (None, r.base.nombre.upper())]
        semaforos = []
        for registrada in registradas:
            estrategia = registrada.estrategia
            ids = registrada.ids_tareas
            filas_por_tarea: dict[str, FilaHistorial | None] = {}
            recientes: list[FilaHistorial] = []
            proximas: list[datetime] = []
            for tarea in estrategia.tareas:
                tarea_id = ids.get(tarea.codigo)
                filas = [fila_historial(e) for e in ultimas.get(tarea_id, [])] if tarea_id is not None else []
                recientes.extend(filas)
                filas_por_tarea[tarea.codigo] = next((f for f in filas if f.terminal), None)
                programable = programables.get(tarea_id) if tarea_id is not None else None
                if programable is not None:
                    proxima = planificador.proxima_ejecucion(programable, momento)
                    if proxima is not None:
                        proximas.append(proxima)
            propias = [a for a in alertas if a.estrategia_id == registrada.estrategia_id]
            activa = registrada.base.activa and estrategia.estado is EstadoEstrategia.ACTIVA
            con_script = any(ids.get(t.codigo) in scripts for t in estrategia.tareas)
            color, motivos = color_semaforo(activa, con_script, filas_por_tarea, propias)
            semaforos.append(
                SemaforoEstrategia(
                    bd=registrada.base.nombre,
                    bd_id=registrada.base.id,
                    estrategia=estrategia.codigo,
                    estrategia_id=registrada.estrategia_id,
                    nombre=estrategia.nombre,
                    prioridad=estrategia.prioridad,
                    estado=estrategia.estado,
                    color=color,
                    motivos=motivos,
                    ultimas=sorted(recientes, key=lambda f: f.programada_para, reverse=True)[:EJECUCIONES_POR_TAREA],
                    proxima_ejecucion=min(proximas) if proximas and activa else None,
                    alertas_vigentes=len(propias),
                )
            )
    if filtro_bd is not None:
        alertas = [a for a in alertas if a.bd is None or a.bd.upper() == filtro_bd]
        en_curso = [f for f in en_curso if f.bd.upper() == filtro_bd]
    return EstadoGeneral(
        generado_en=momento,
        semaforos=semaforos,
        en_curso=en_curso,
        alertas=alertas,
        agentes=estado_agentes(ajustes, momento, parametros.tick_segundos),
        observaciones_redo=observaciones_redo,
        tick_segundos=parametros.tick_segundos,
    )
