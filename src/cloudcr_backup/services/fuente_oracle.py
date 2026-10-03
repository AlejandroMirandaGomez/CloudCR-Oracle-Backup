from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import oracledb

from cloudcr_backup.agent.bucle import ParametrosAgente
from cloudcr_backup.alerts.instantanea import (
    BaseMonitoreada,
    EstrategiaMonitoreada,
    Instantanea,
    ScriptVigente,
    TareaMonitoreada,
    UsoDisco,
)
from cloudcr_backup.domain.alertas import Condicion, VistaAlerta
from cloudcr_backup.domain.enums import EstadoEstrategia, ModoRespaldo
from cloudcr_backup.domain.estrategia import Estrategia
from cloudcr_backup.domain.planificacion import EjecucionEnCurso, EjecucionPendiente, TareaProgramable
from cloudcr_backup.repository import alertas as repositorio_alertas
from cloudcr_backup.repository import bases_datos as repositorio_bases_datos
from cloudcr_backup.repository import ejecuciones as repositorio_ejecuciones
from cloudcr_backup.repository import estrategias as repositorio_estrategias
from cloudcr_backup.repository import parametros as repositorio_parametros
from cloudcr_backup.repository import scripts as repositorio_scripts
from cloudcr_backup.repository.bases_datos import BaseDatosRegistrada
from cloudcr_backup.repository.scripts import ScriptRman
from cloudcr_backup.scheduling.planificador import Planificador
from cloudcr_backup.scheduling.reloj import utc_consciente, utc_ingenuo
from cloudcr_backup.services.conversiones import (
    etiquetas_alcance,
    fila_historial,
    momento_utc,
    uso_disco,
    vista_alerta,
)

EJECUCIONES_POR_TAREA = 10


@dataclass(frozen=True)
class EstrategiaRegistrada:
    base: BaseDatosRegistrada
    estrategia: Estrategia
    ids_tareas: dict[str, int]

    @property
    def estrategia_id(self) -> int:
        assert self.estrategia.id is not None
        return self.estrategia.id


class FuenteOracle:
    def __init__(
        self, conexion: oracledb.Connection, medir_disco: Callable[[str], UsoDisco | None] = uso_disco
    ) -> None:
        self._conexion = conexion
        self._medir_disco = medir_disco
        self._parametros: dict[str, str] | None = None
        self._registradas: list[EstrategiaRegistrada] | None = None
        self._scripts: dict[int, ScriptRman] | None = None

    @property
    def conexion(self) -> oracledb.Connection:
        return self._conexion

    def parametros(self) -> dict[str, str]:
        if self._parametros is None:
            self._parametros = repositorio_parametros.listar(self._conexion)
        return dict(self._parametros)

    def bases_activas(self) -> list[BaseDatosRegistrada]:
        return [bd for bd in repositorio_bases_datos.listar(self._conexion) if bd.activa]

    def estrategias_registradas(self) -> list[EstrategiaRegistrada]:
        if self._registradas is None:
            registradas = []
            for bd in repositorio_bases_datos.listar(self._conexion):
                for estrategia in repositorio_estrategias.listar(self._conexion, bd.id):
                    assert estrategia.id is not None
                    ids = repositorio_estrategias.ids_de_tareas(self._conexion, estrategia.id)
                    registradas.append(EstrategiaRegistrada(bd, estrategia, ids))
            self._registradas = registradas
        return list(self._registradas)

    def estrategias_activas(self) -> list[EstrategiaRegistrada]:
        return [
            r
            for r in self.estrategias_registradas()
            if r.base.activa and r.estrategia.estado is EstadoEstrategia.ACTIVA
        ]

    def scripts_vigentes(self) -> dict[int, ScriptRman]:
        if self._scripts is None:
            self._scripts = repositorio_scripts.vigentes_por_tarea(self._conexion)
        return dict(self._scripts)

    def tareas_programables(self) -> list[TareaProgramable]:
        scripts = self.scripts_vigentes()
        programables = []
        for registrada in self.estrategias_activas():
            for tarea in registrada.estrategia.tareas:
                tarea_id = registrada.ids_tareas.get(tarea.codigo)
                script = scripts.get(tarea_id) if tarea_id is not None else None
                if tarea_id is None or script is None:
                    continue
                programables.append(
                    TareaProgramable(
                        tarea_id=tarea_id,
                        bd_id=registrada.base.id,
                        bd_nombre=registrada.base.nombre,
                        estrategia_id=registrada.estrategia_id,
                        estrategia_codigo=registrada.estrategia.codigo,
                        tarea_codigo=tarea.codigo,
                        tipo_respaldo=tarea.como.tipo_respaldo,
                        modo_respaldo=tarea.como.modo_respaldo,
                        programacion=tarea.programacion,
                        script_id=script.id,
                        aprobado_en=momento_utc(script.aprobado_en),
                    )
                )
        return programables

    def ultima_programada_por_tarea(self) -> dict[int, datetime]:
        return {
            tarea_id: utc_consciente(momento)
            for tarea_id, momento in repositorio_ejecuciones.ultima_programada_por_tarea(self._conexion).items()
        }

    def reclamar(self, tarea_id: int, programada_para: datetime) -> int | None:
        ejecucion = repositorio_ejecuciones.reclamar(self._conexion, tarea_id, utc_ingenuo(programada_para))
        return ejecucion.id if ejecucion is not None else None

    def registrar_no_ejecutada(self, tarea_id: int, programada_para: datetime, motivo: str) -> bool:
        registrada = repositorio_ejecuciones.registrar_no_ejecutada(
            self._conexion, tarea_id, utc_ingenuo(programada_para), motivo
        )
        return registrada is not None

    def programadas_sin_iniciar(self, antes_de: datetime) -> list[EjecucionPendiente]:
        return [
            EjecucionPendiente(e.id, e.tarea_id, utc_consciente(e.programada_para))
            for e in repositorio_ejecuciones.programadas_sin_iniciar(self._conexion, utc_ingenuo(antes_de))
        ]

    def marcar_no_ejecutada(self, ejecucion_id: int, motivo: str) -> bool:
        return repositorio_ejecuciones.marcar_no_ejecutada(self._conexion, ejecucion_id, motivo)

    def en_curso_de_agente(self, agente: str) -> list[EjecucionEnCurso]:
        return [
            EjecucionEnCurso(
                ejecucion_id=e.id,
                tarea_id=e.tarea_id,
                programada_para=utc_consciente(e.programada_para),
                modo_respaldo=ModoRespaldo(e.modo_respaldo),
            )
            for e in repositorio_ejecuciones.en_curso_de_agente(self._conexion, agente)
        ]

    def marcar_interrumpida(self, ejecucion_id: int, motivo: str) -> bool:
        return repositorio_ejecuciones.marcar_interrumpida(self._conexion, ejecucion_id, motivo)

    def vigentes(self) -> list[VistaAlerta]:
        return [vista_alerta(a) for a in repositorio_alertas.vigentes(self._conexion)]

    def abrir(self, condicion: Condicion) -> tuple[VistaAlerta, bool]:
        alerta, es_nueva = repositorio_alertas.abrir(self._conexion, condicion)
        return vista_alerta(alerta), es_nueva

    def resolver(self, alerta_id: int) -> bool:
        return repositorio_alertas.resolver_vigente(self._conexion, alerta_id)

    def instantanea(self, ahora: datetime) -> Instantanea:
        ahora = utc_consciente(ahora)
        parametros = self.parametros()
        ajustes_agente = ParametrosAgente.desde(parametros)
        perdidas: dict[int, list[datetime]] = {}
        planificador = Planificador(self, ajustes_agente.gracia, ajustes_agente.horizonte)
        for perdida in planificador.ocurrencias_perdidas(ahora):
            perdidas.setdefault(perdida.tarea_id, []).append(perdida.programada_para)
        ultimas = repositorio_ejecuciones.ultimas_por_tarea(self._conexion, EJECUCIONES_POR_TAREA)
        exitos = repositorio_ejecuciones.ultimo_exito_por_estrategia(self._conexion)
        tamanos = repositorio_ejecuciones.tamano_ultimo_exito_por_tarea(self._conexion)
        vencidas = repositorio_ejecuciones.piezas_vencidas_por_estrategia(self._conexion, utc_ingenuo(ahora))
        scripts = self.scripts_vigentes()
        bases = [
            BaseMonitoreada(bd.id, bd.nombre, repositorio_bases_datos.ultimo_perfil(self._conexion, bd.id))
            for bd in self.bases_activas()
        ]
        estrategias = []
        destinos: set[str] = set()
        for registrada in self.estrategias_activas():
            tareas = []
            for tarea in registrada.estrategia.tareas:
                tarea_id = registrada.ids_tareas.get(tarea.codigo)
                if tarea_id is None:
                    continue
                script = scripts.get(tarea_id)
                vigente = None
                if script is not None:
                    destinos.add(tarea.destino.ruta)
                    vigente = ScriptVigente(
                        script_id=script.id,
                        aprobado_en=momento_utc(script.aprobado_en),
                        log_mode_al_crear=repositorio_bases_datos.log_mode_al_crear_script(
                            self._conexion, registrada.base.id, script.id
                        ),
                    )
                tareas.append(
                    TareaMonitoreada(
                        tarea_id=tarea_id,
                        codigo=tarea.codigo,
                        tipo_respaldo=tarea.como.tipo_respaldo,
                        modo_respaldo=tarea.como.modo_respaldo,
                        programacion=tarea.programacion,
                        destino_ruta=tarea.destino.ruta,
                        script=vigente,
                        ultimas=[fila_historial(e) for e in ultimas.get(tarea_id, [])],
                        tamano_ultimo_exito=tamanos.get(tarea_id),
                        ocurrencias_perdidas=perdidas.get(tarea_id, []),
                    )
                )
            estrategias.append(
                EstrategiaMonitoreada(
                    estrategia_id=registrada.estrategia_id,
                    bd_id=registrada.base.id,
                    bd_nombre=registrada.base.nombre,
                    codigo=registrada.estrategia.codigo,
                    nombre=registrada.estrategia.nombre,
                    prioridad=registrada.estrategia.prioridad,
                    alcance=etiquetas_alcance(registrada.estrategia.alcance),
                    purga_automatica=registrada.estrategia.retencion.purga_automatica,
                    tareas=tareas,
                    ultimo_exito=momento_utc(exitos.get(registrada.estrategia_id)),
                    piezas_vencidas=vencidas.get(registrada.estrategia_id, 0),
                )
            )
        return Instantanea(
            ahora=ahora,
            bases=bases,
            estrategias=estrategias,
            parametros=parametros,
            uso_disco={ruta: self._medir_disco(ruta) for ruta in sorted(destinos)},
        )
