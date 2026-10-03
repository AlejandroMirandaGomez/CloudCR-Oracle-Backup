import logging
import os
import signal
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path
from types import FrameType
from typing import Any

from cloudcr_backup.agent import latido
from cloudcr_backup.agent.puertos import EjecutorRespaldo, FabricaSesion, SesionAgente
from cloudcr_backup.alerts.motor import MotorAlertas, Notificador
from cloudcr_backup.domain.alertas import ResumenEvaluacion
from cloudcr_backup.domain.enums import ModoRespaldo
from cloudcr_backup.domain.monitoreo import EstadoLatido, Latido
from cloudcr_backup.domain.planificacion import EjecucionPendiente, EjecucionReclamada, OcurrenciaPerdida
from cloudcr_backup.scheduling.planificador import Planificador
from cloudcr_backup.scheduling.reloj import Reloj, RelojSistema

REGISTRO = logging.getLogger("cloudcr.agente")

PARAMETRO_TICK = "agente.tick_segundos"
PARAMETRO_GRACIA = "agente.gracia_omision_min"
PARAMETRO_EVALUACION = "alertas.eval_minutos"
PARAMETRO_PARALELO = "agente.max_paralelo_host"
PARAMETRO_HORIZONTE = "agente.horizonte_perdidas_horas"
TICK_POR_DEFECTO = 30
GRACIA_POR_DEFECTO_MIN = 15
EVALUACION_POR_DEFECTO_MIN = 5
PARALELO_POR_DEFECTO = 1
HORIZONTE_POR_DEFECTO_HORAS = 24
MOTIVO_INTERRUMPIDA = "Interrumpida: el agente se detuvo durante la ejecución."
SENALES_DE_PARADA = ("SIGINT", "SIGTERM", "SIGBREAK")


def _positivo(parametros: dict[str, str], clave: str, defecto: int) -> int:
    try:
        valor = int(parametros[clave])
    except (KeyError, ValueError):
        return defecto
    return valor if valor > 0 else defecto


@dataclass(frozen=True)
class ParametrosAgente:
    tick_segundos: int = TICK_POR_DEFECTO
    gracia: timedelta = timedelta(minutes=GRACIA_POR_DEFECTO_MIN)
    evaluacion_alertas: timedelta = timedelta(minutes=EVALUACION_POR_DEFECTO_MIN)
    max_paralelo: int = PARALELO_POR_DEFECTO
    horizonte: timedelta = timedelta(hours=HORIZONTE_POR_DEFECTO_HORAS)

    @classmethod
    def desde(cls, parametros: dict[str, str]) -> "ParametrosAgente":
        return cls(
            tick_segundos=_positivo(parametros, PARAMETRO_TICK, TICK_POR_DEFECTO),
            gracia=timedelta(minutes=_positivo(parametros, PARAMETRO_GRACIA, GRACIA_POR_DEFECTO_MIN)),
            evaluacion_alertas=timedelta(
                minutes=_positivo(parametros, PARAMETRO_EVALUACION, EVALUACION_POR_DEFECTO_MIN)
            ),
            max_paralelo=_positivo(parametros, PARAMETRO_PARALELO, PARALELO_POR_DEFECTO),
            horizonte=timedelta(hours=_positivo(parametros, PARAMETRO_HORIZONTE, HORIZONTE_POR_DEFECTO_HORAS)),
        )


@dataclass(frozen=True)
class ConfiguracionAgente:
    hostname: str
    carpeta_latido: Path
    version: str
    simulado: bool = False


@dataclass
class ResultadoTick:
    momento: datetime
    reclamadas: list[EjecucionReclamada] = field(default_factory=list)
    no_ejecutadas: list[OcurrenciaPerdida] = field(default_factory=list)
    huerfanas: list[EjecucionPendiente] = field(default_factory=list)
    interrumpidas: list[int] = field(default_factory=list)
    evaluacion: ResumenEvaluacion | None = None
    errores: list[str] = field(default_factory=list)


FabricaNotificadores = Callable[[dict[str, str]], Sequence[Notificador]]


def _sin_notificadores(_: dict[str, str]) -> Sequence[Notificador]:
    return []


def _sin_aviso(_: str) -> None:
    return None


class Agente:
    def __init__(
        self,
        fabrica_sesion: FabricaSesion,
        ejecutor: EjecutorRespaldo,
        configuracion: ConfiguracionAgente,
        reloj: Reloj | None = None,
        fabrica_notificadores: FabricaNotificadores = _sin_notificadores,
        sincronizar_buzon: Callable[[], None] | None = None,
        avisar: Callable[[str], None] = _sin_aviso,
    ) -> None:
        self._fabrica_sesion = fabrica_sesion
        self._ejecutor = ejecutor
        self._configuracion = configuracion
        self._reloj = reloj or RelojSistema()
        self._fabrica_notificadores = fabrica_notificadores
        self._sincronizar_buzon = sincronizar_buzon
        self._avisar = avisar
        self.parametros = ParametrosAgente()
        self._iniciado_en = self._reloj.ahora()
        self._detener = threading.Event()
        self._candado = threading.Lock()
        self._en_cola: set[int] = set()
        self._pools: list[ThreadPoolExecutor] = []
        self._pool: ThreadPoolExecutor | None = None
        self._paralelo_del_pool = 0
        self._ultima_evaluacion: datetime | None = None
        self._evaluar_pronto = False
        self._recuperacion_pendiente = True

    @property
    def en_cola(self) -> set[int]:
        with self._candado:
            return set(self._en_cola)

    def escribir_latido(self, estado: EstadoLatido, momento: datetime | None = None) -> None:
        registro = Latido(
            hostname=self._configuracion.hostname,
            pid=os.getpid(),
            iniciado_en=self._iniciado_en,
            ultimo_tick=momento or self._reloj.ahora(),
            estado=estado,
            version=self._configuracion.version,
            simulado=self._configuracion.simulado,
        )
        try:
            latido.escribir(self._configuracion.carpeta_latido, registro)
        except OSError:
            REGISTRO.exception("No se pudo escribir el latido en %s", self._configuracion.carpeta_latido)

    def recuperar_interrumpidas(self, sesion: SesionAgente) -> list[int]:
        interrumpidas = []
        for en_curso in sesion.en_curso_de_agente(self._configuracion.hostname):
            if not sesion.marcar_interrumpida(en_curso.ejecucion_id, MOTIVO_INTERRUMPIDA):
                continue
            interrumpidas.append(en_curso.ejecucion_id)
            self._avisar(f"La ejecución {en_curso.ejecucion_id} quedó interrumpida y se marcó como FALLIDA.")
            if en_curso.modo_respaldo is ModoRespaldo.CONSISTENTE:
                try:
                    self._ejecutor.asegurar_apertura(en_curso.ejecucion_id)
                except Exception:
                    REGISTRO.exception("No se pudo asegurar la apertura tras la ejecución %s", en_curso.ejecucion_id)
        return interrumpidas

    def tick(self) -> ResultadoTick:
        ahora = self._reloj.ahora()
        resultado = ResultadoTick(momento=ahora)
        self.escribir_latido(EstadoLatido.ACTIVO, ahora)
        self._sincronizar(resultado)
        try:
            with self._fabrica_sesion() as sesion:
                crudos = sesion.parametros()
                self.parametros = ParametrosAgente.desde(crudos)
                if self._recuperacion_pendiente:
                    resultado.interrumpidas = self.recuperar_interrumpidas(sesion)
                    self._recuperacion_pendiente = False
                planificador = Planificador(sesion, self.parametros.gracia, self.parametros.horizonte)
                plan = planificador.reclamar_vencidas(ahora, excluir=self.en_cola)
                resultado.reclamadas = plan.reclamadas
                resultado.no_ejecutadas = plan.no_ejecutadas
                resultado.huerfanas = plan.huerfanas
                resultado.errores.extend(plan.errores)
                for reclamada in plan.reclamadas:
                    self._despachar(reclamada)
                if self._toca_evaluar(ahora):
                    resultado.evaluacion = self._evaluar(sesion, crudos, ahora)
        except Exception as error:
            REGISTRO.exception("El tick del agente falló; se reintenta en el siguiente")
            resultado.errores.append(f"{type(error).__name__}: {error}")
        for mensaje in resultado.errores:
            REGISTRO.warning(mensaje)
        return resultado

    def ejecutar(self, una_vez: bool = False) -> int:
        anteriores = self._instalar_senales()
        self.escribir_latido(EstadoLatido.INICIANDO)
        try:
            while not self._detener.is_set():
                self._informar(self.tick())
                if una_vez:
                    break
                self._detener.wait(self.parametros.tick_segundos)
        finally:
            self.escribir_latido(EstadoLatido.DETENIENDO)
            self.esperar_ejecuciones()
            self._evaluacion_final()
            self.escribir_latido(EstadoLatido.DETENIDO)
            self._restaurar_senales(anteriores)
        return 0

    def detener(self) -> None:
        self._detener.set()

    def esperar_ejecuciones(self) -> None:
        for pool in self._pools:
            pool.shutdown(wait=True)
        self._pools.clear()
        self._pool = None

    def _sincronizar(self, resultado: ResultadoTick) -> None:
        if self._sincronizar_buzon is None:
            return
        try:
            self._sincronizar_buzon()
        except Exception as error:
            REGISTRO.exception("No se pudo sincronizar el buzón")
            resultado.errores.append(f"Buzón: {error}")

    def _toca_evaluar(self, ahora: datetime) -> bool:
        if self._evaluar_pronto or self._ultima_evaluacion is None:
            return True
        return ahora - self._ultima_evaluacion >= self.parametros.evaluacion_alertas

    def _evaluar(self, sesion: SesionAgente, crudos: dict[str, str], ahora: datetime) -> ResumenEvaluacion:
        self._evaluar_pronto = False
        self._ultima_evaluacion = ahora
        motor = MotorAlertas(sesion, self._fabrica_notificadores(crudos))
        return motor.evaluar(ahora)

    def _evaluacion_final(self) -> None:
        if not self._evaluar_pronto:
            return
        try:
            with self._fabrica_sesion() as sesion:
                self._informar_evaluacion(self._evaluar(sesion, sesion.parametros(), self._reloj.ahora()))
        except Exception:
            REGISTRO.exception("No se pudieron evaluar las alertas al detener el agente")

    def _pool_actual(self) -> ThreadPoolExecutor:
        if self._pool is None or self._paralelo_del_pool != self.parametros.max_paralelo:
            if self._pool is not None:
                self._pool.shutdown(wait=False)
            self._pool = ThreadPoolExecutor(
                max_workers=self.parametros.max_paralelo, thread_name_prefix="cloudcr-respaldo"
            )
            self._paralelo_del_pool = self.parametros.max_paralelo
            self._pools.append(self._pool)
        return self._pool

    def _despachar(self, reclamada: EjecucionReclamada) -> None:
        with self._candado:
            self._en_cola.add(reclamada.ejecucion_id)
        futuro = self._pool_actual().submit(self._ejecutor.ejecutar, reclamada.ejecucion_id)
        futuro.add_done_callback(partial(self._al_terminar, reclamada.ejecucion_id))

    def _al_terminar(self, ejecucion_id: int, futuro: "Future[None]") -> None:
        with self._candado:
            self._en_cola.discard(ejecucion_id)
        self._evaluar_pronto = True
        if futuro.cancelled():
            return
        error = futuro.exception()
        if error is not None:
            REGISTRO.error("La ejecución %s terminó con una excepción: %s", ejecucion_id, error, exc_info=error)
            self._avisar(f"La ejecución {ejecucion_id} terminó con error: {error}")
        else:
            self._avisar(f"La ejecución {ejecucion_id} terminó.")

    def _informar(self, resultado: ResultadoTick) -> None:
        etiqueta = " [SIMULACIÓN]" if self._configuracion.simulado else ""
        for reclamada in resultado.reclamadas:
            tarde = " (tarde)" if reclamada.tardia else ""
            self._avisar(
                f"Ejecución {reclamada.ejecucion_id} reclamada para {reclamada.programada_para:%Y-%m-%d %H:%M %Z}"
                f"{tarde}{etiqueta}"
            )
        for perdida in resultado.no_ejecutadas:
            self._avisar(f"Tarea {perdida.tarea_id} {perdida.programada_para:%Y-%m-%d %H:%M %Z}: {perdida.motivo}")
        for huerfana in resultado.huerfanas:
            self._avisar(f"Ejecución {huerfana.ejecucion_id} quedó huérfana y se marcó NO_EJECUTADA.")
        if resultado.evaluacion is not None:
            self._informar_evaluacion(resultado.evaluacion)
        for error in resultado.errores:
            self._avisar(f"Error: {error}")

    def _informar_evaluacion(self, evaluacion: ResumenEvaluacion) -> None:
        if evaluacion.abiertas or evaluacion.resueltas:
            self._avisar(
                f"Alertas: {len(evaluacion.abiertas)} nuevas, {len(evaluacion.actualizadas)} vigentes, "
                f"{len(evaluacion.resueltas)} resueltas."
            )

    def _instalar_senales(self) -> dict[int, Any]:
        anteriores: dict[int, Any] = {}
        if threading.current_thread() is not threading.main_thread():
            return anteriores
        for nombre in SENALES_DE_PARADA:
            senal = getattr(signal, nombre, None)
            if senal is None:
                continue
            anteriores[int(senal)] = signal.signal(senal, self._al_recibir_senal)
        return anteriores

    def _restaurar_senales(self, anteriores: dict[int, Any]) -> None:
        for numero, manejador in anteriores.items():
            signal.signal(numero, manejador)

    def _al_recibir_senal(self, numero: int, marco: FrameType | None) -> None:
        self._avisar("Deteniendo el agente: se espera a que terminen las ejecuciones en curso…")
        self._detener.set()
