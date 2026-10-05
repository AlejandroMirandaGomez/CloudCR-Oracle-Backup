import importlib
import inspect
import logging
import socket
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import ModuleType

from cloudcr_backup import __version__
from cloudcr_backup.agent import latido
from cloudcr_backup.agent.bucle import Agente, ConfiguracionAgente, ParametrosAgente
from cloudcr_backup.agent.puertos import EjecutorRespaldo
from cloudcr_backup.alerts.motor import Notificador
from cloudcr_backup.alerts.notificadores.seleccion import construir_notificadores
from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.domain.enums import EstadoEjecucion, EstadoPrueba
from cloudcr_backup.domain.errores import PipelineNoDisponible, RepositorioNoDisponible
from cloudcr_backup.domain.monitoreo import EstadoAgente
from cloudcr_backup.repository import ejecuciones as repositorio_ejecuciones
from cloudcr_backup.scheduling.reloj import Reloj, RelojSistema, utc_ingenuo
from cloudcr_backup.services.cliente_oracle import preparar_cliente_oracle
from cloudcr_backup.services.fuente_oracle import FuenteOracle
from cloudcr_backup.services.sesion import conexion_repositorio

REGISTRO = logging.getLogger("cloudcr.agente")

MODULO_PIPELINE = "cloudcr_backup.execution.pipeline"
MODULO_BUZON = "cloudcr_backup.execution.buzon"
MENSAJE_SIMULACION = "SIMULACION: ejecución de prueba del agente; no se ejecutó RMAN ni se generó ningún respaldo."
ARCHIVO_LOG = "cloudcr.log"
TAMANO_MAXIMO_LOG = 5 * 1024 * 1024
COPIAS_LOG = 5
FORMATO_LOG = "%(asctime)s %(levelname)s %(name)s [%(threadName)s] %(message)s"


def nombre_agente() -> str:
    return socket.gethostname()


def _importar_opcional(nombre: str) -> ModuleType | None:
    try:
        return importlib.import_module(nombre)
    except ModuleNotFoundError as error:
        if error.name is not None and nombre.startswith(error.name):
            return None
        raise


def pipeline_disponible() -> ModuleType | None:
    return _importar_opcional(MODULO_PIPELINE)


class EjecutorSimulado:
    def __init__(self, ajustes: Ajustes, agente: str, reloj: Reloj | None = None) -> None:
        self._ajustes = ajustes
        self._agente = agente
        self._reloj = reloj or RelojSistema()

    def ejecutar(self, ejecucion_id: int) -> None:
        with conexion_repositorio(self._ajustes) as conexion:
            repositorio_ejecuciones.marcar_en_curso(conexion, ejecucion_id, self._agente)
            repositorio_ejecuciones.registrar_resultado(
                conexion,
                ejecucion_id,
                {
                    "estado": EstadoEjecucion.EXITOSA,
                    "estado_prueba": EstadoPrueba.NO_APLICA,
                    "mensaje_rman": MENSAJE_SIMULACION,
                    "fin": utc_ingenuo(self._reloj.ahora()),
                    "duracion_segundos": 0,
                    "archivos_generados": 0,
                    "tamano_bytes": 0,
                },
            )

    def asegurar_apertura(self, ejecucion_id: int) -> None:
        REGISTRO.info("Simulación: no hay base que reabrir tras la ejecución %s", ejecucion_id)


class EjecutorPipeline:
    def __init__(self, modulo: ModuleType, ajustes: Ajustes) -> None:
        self._modulo = modulo
        self._ajustes = ajustes

    def _llamar(self, nombre: str, ejecucion_id: int) -> None:
        funcion: Callable[..., object] | None = getattr(self._modulo, nombre, None)
        if funcion is None:
            raise PipelineNoDisponible(f"El módulo {self._modulo.__name__} no tiene la función {nombre}().")
        if "ajustes" in inspect.signature(funcion).parameters:
            funcion(ejecucion_id, ajustes=self._ajustes)
        else:
            funcion(ejecucion_id)

    def ejecutar(self, ejecucion_id: int) -> None:
        self._llamar("ejecutar", ejecucion_id)

    def asegurar_apertura(self, ejecucion_id: int) -> None:
        if getattr(self._modulo, "asegurar_apertura", None) is not None:
            self._llamar("asegurar_apertura", ejecucion_id)


def crear_ejecutor(ajustes: Ajustes, agente: str, simulado: bool) -> EjecutorRespaldo:
    if simulado:
        return EjecutorSimulado(ajustes, agente)
    modulo = pipeline_disponible()
    if modulo is None:
        raise PipelineNoDisponible(
            "El agente no puede ejecutar respaldos reales: todavía no existe el pipeline de ejecución "
            f"({MODULO_PIPELINE}).",
            "Para probar el agente sin RMAN use --simulado: cada ejecución queda rotulada como SIMULACION.",
        )
    return EjecutorPipeline(modulo, ajustes)


def sincronizador_buzon(ajustes: Ajustes) -> Callable[[], None] | None:
    modulo = _importar_opcional(MODULO_BUZON)
    sincronizar = getattr(modulo, "sincronizar", None) if modulo is not None else None
    if sincronizar is None:
        return None

    def ejecutar() -> None:
        if "ajustes" in inspect.signature(sincronizar).parameters:
            sincronizar(ajustes=ajustes)
        else:
            sincronizar()

    return ejecutar


@contextmanager
def sesion_agente(ajustes: Ajustes) -> Iterator[FuenteOracle]:
    with conexion_repositorio(ajustes) as conexion:
        yield FuenteOracle(conexion)


def configurar_registro(ajustes: Ajustes) -> Path:
    ajustes.rutas.logs.mkdir(parents=True, exist_ok=True)
    ruta = ajustes.rutas.logs / ARCHIVO_LOG
    raiz = logging.getLogger("cloudcr")
    if not any(isinstance(h, RotatingFileHandler) and Path(h.baseFilename) == ruta for h in raiz.handlers):
        manejador = RotatingFileHandler(ruta, maxBytes=TAMANO_MAXIMO_LOG, backupCount=COPIAS_LOG, encoding="utf-8")
        manejador.setFormatter(logging.Formatter(FORMATO_LOG))
        raiz.addHandler(manejador)
    raiz.setLevel(logging.INFO)
    return ruta


def construir_agente(ajustes: Ajustes, simulado: bool, avisar: Callable[[str], None]) -> Agente:
    agente = nombre_agente()
    ejecutor = crear_ejecutor(ajustes, agente, simulado)
    ajustes.rutas.asegurar()
    configurar_registro(ajustes)
    preparar_cliente_oracle()

    def notificadores(parametros: dict[str, str]) -> Sequence[Notificador]:
        elegidos, problemas = construir_notificadores(parametros, avisar)
        for problema in problemas:
            REGISTRO.warning(problema)
            avisar(problema)
        return elegidos

    return Agente(
        fabrica_sesion=lambda: sesion_agente(ajustes),
        ejecutor=ejecutor,
        configuracion=ConfiguracionAgente(
            hostname=agente, carpeta_latido=ajustes.rutas.agente, version=__version__, simulado=simulado
        ),
        fabrica_notificadores=notificadores,
        sincronizar_buzon=sincronizador_buzon(ajustes),
        avisar=avisar,
    )


def tick_segundos(ajustes: Ajustes) -> int:
    try:
        with sesion_agente(ajustes) as fuente:
            return ParametrosAgente.desde(fuente.parametros()).tick_segundos
    except RepositorioNoDisponible:
        return ParametrosAgente().tick_segundos


def estado_agentes(ajustes: Ajustes, ahora: datetime | None = None, tick: int | None = None) -> list[EstadoAgente]:
    momento = ahora or RelojSistema().ahora()
    segundos = tick if tick is not None else tick_segundos(ajustes)
    anfitrion = nombre_agente()
    registros = latido.leer_todos(ajustes.rutas.agente)
    return [latido.estado_de(registro, momento, segundos, anfitrion) for registro in registros]
