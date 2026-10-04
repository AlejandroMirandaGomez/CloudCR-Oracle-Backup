import logging
import os
import threading
from collections import deque
from collections.abc import Callable
from datetime import datetime

from cloudcr_backup.agent.bucle import Agente
from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.domain.administracion import EstadoControlAgente, MensajeAgente
from cloudcr_backup.domain.errores import OperacionNoPermitida
from cloudcr_backup.domain.monitoreo import EstadoAgente
from cloudcr_backup.scheduling.reloj import Reloj, RelojSistema
from cloudcr_backup.services import agente as servicio_agente

REGISTRO = logging.getLogger("cloudcr.web.agente")
MAXIMO_MENSAJES = 60
NOMBRE_HILO = "cloudcr-agente-web"

ConstruirAgente = Callable[[Ajustes, bool, Callable[[str], None]], Agente]
LeerAgentes = Callable[[Ajustes], list[EstadoAgente]]


class ControlAgente:
    def __init__(
        self,
        ajustes: Callable[[], Ajustes],
        construir: ConstruirAgente = servicio_agente.construir_agente,
        leer_agentes: LeerAgentes = servicio_agente.estado_agentes,
        reloj: Reloj | None = None,
    ) -> None:
        self._ajustes = ajustes
        self._construir = construir
        self._leer_agentes = leer_agentes
        self._reloj = reloj or RelojSistema()
        self._candado = threading.Lock()
        self._agente: Agente | None = None
        self._hilo: threading.Thread | None = None
        self._ciclo: threading.Thread | None = None
        self._simulado = False
        self._iniciado_en: datetime | None = None
        self._mensajes: deque[MensajeAgente] = deque(maxlen=MAXIMO_MENSAJES)

    def avisar(self, texto: str) -> None:
        self._mensajes.appendleft(MensajeAgente(momento=self._reloj.ahora(), texto=texto))

    def _corriendo(self) -> bool:
        return self._agente is not None and self._hilo is not None and self._hilo.is_alive()

    def _ciclo_en_curso(self) -> bool:
        return self._ciclo is not None and self._ciclo.is_alive()

    def estado(self) -> EstadoControlAgente:
        with self._candado:
            corriendo = self._corriendo()
            return EstadoControlAgente(
                corriendo=corriendo,
                simulado=self._simulado,
                iniciado_en=self._iniciado_en if corriendo else None,
                ciclo_en_curso=self._ciclo_en_curso(),
                mensajes=list(self._mensajes),
            )

    def _otro_agente_vivo(self, ajustes: Ajustes) -> EstadoAgente | None:
        return next((a for a in self._leer_agentes(ajustes) if a.vivo and a.latido.pid != os.getpid()), None)

    def iniciar(self, simulado: bool) -> EstadoControlAgente:
        with self._candado:
            if self._corriendo():
                raise OperacionNoPermitida("El agente ya está corriendo desde esta interfaz web.")
            if self._ciclo_en_curso():
                raise OperacionNoPermitida(
                    "Hay un ciclo del agente en curso.", "Espere a que termine y vuelva a intentarlo."
                )
            ajustes = self._ajustes()
            otro = self._otro_agente_vivo(ajustes)
            if otro is not None:
                raise OperacionNoPermitida(
                    f"Ya hay un agente activo en {otro.latido.hostname} (PID {otro.latido.pid}).",
                    "Deténgalo (Ctrl+C en su terminal) antes de iniciar otro desde la web.",
                )
            nuevo = self._construir(ajustes, simulado, self.avisar)
            hilo = threading.Thread(target=self._correr, args=(nuevo,), name=NOMBRE_HILO, daemon=True)
            self._agente = nuevo
            self._hilo = hilo
            self._simulado = simulado
            self._iniciado_en = self._reloj.ahora()
            hilo.start()
        etiqueta = " en modo SIMULACIÓN (no ejecuta RMAN)" if simulado else " con el pipeline real de RMAN"
        self.avisar(f"Agente iniciado desde la web{etiqueta}.")
        return self.estado()

    def _correr(self, agente: Agente) -> None:
        try:
            agente.ejecutar()
        except Exception as error:
            REGISTRO.exception("El agente iniciado desde la web se detuvo por un error")
            self.avisar(f"El agente se detuvo por un error: {type(error).__name__}: {error}")
        finally:
            with self._candado:
                if self._agente is agente:
                    self._agente = None
            self.avisar("Agente detenido.")

    def detener(self, esperar_segundos: float = 0) -> EstadoControlAgente:
        with self._candado:
            agente = self._agente
            hilo = self._hilo
        if agente is None or hilo is None or not hilo.is_alive():
            raise OperacionNoPermitida("El agente de la web no está corriendo.")
        agente.detener()
        self.avisar("Deteniendo el agente: se espera a que terminen las ejecuciones en curso…")
        if esperar_segundos > 0:
            hilo.join(esperar_segundos)
        return self.estado()

    def un_ciclo(self, simulado: bool) -> EstadoControlAgente:
        with self._candado:
            if self._corriendo():
                raise OperacionNoPermitida(
                    "El agente ya está corriendo: los ciclos se ejecutan solos.", "Deténgalo si quiere un ciclo manual."
                )
            if self._ciclo_en_curso():
                raise OperacionNoPermitida("Ya hay un ciclo del agente en curso.")
            nuevo = self._construir(self._ajustes(), simulado, self.avisar)
            hilo = threading.Thread(target=self._correr_ciclo, args=(nuevo,), name=f"{NOMBRE_HILO}-ciclo", daemon=True)
            self._ciclo = hilo
            hilo.start()
        self.avisar("Se lanzó un ciclo del agente" + (" en modo SIMULACIÓN." if simulado else "."))
        return self.estado()

    def _correr_ciclo(self, agente: Agente) -> None:
        try:
            agente.ejecutar(una_vez=True)
            self.avisar("El ciclo del agente terminó.")
        except Exception as error:
            REGISTRO.exception("El ciclo del agente lanzado desde la web falló")
            self.avisar(f"El ciclo del agente falló: {type(error).__name__}: {error}")

    def apagar(self, esperar_segundos: float) -> None:
        with self._candado:
            agente = self._agente
            hilo = self._hilo
        if agente is not None and hilo is not None and hilo.is_alive():
            agente.detener()
            hilo.join(esperar_segundos)
