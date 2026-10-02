from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.domain.enums import ModoRespaldo
from cloudcr_backup.domain.estrategia import Estrategia
from cloudcr_backup.domain.hallazgos import Hallazgo
from cloudcr_backup.domain.perfil_bd import PerfilBD
from cloudcr_backup.services import almacen_estrategias
from cloudcr_backup.services.almacen_estrategias import REPOSITORIO_OMITIDO, ResultadoRepositorio
from cloudcr_backup.services.destinos import inspeccionar_destino
from cloudcr_backup.services.solicitud_estrategia import SolicitudEstrategia, construir_estrategia
from cloudcr_backup.validation import motor, reglas  # noqa: F401
from cloudcr_backup.validation.contexto import ContextoValidacion
from cloudcr_backup.validation.reglas.archivado import modo_efectivo


class ErrorCreacion(Exception):
    def __init__(self, mensaje: str, tipo: str, hallazgos: list[Hallazgo] | None = None) -> None:
        super().__init__(mensaje)
        self.tipo = tipo
        self.hallazgos = hallazgos or []


@dataclass(frozen=True)
class ResultadoValidacion:
    estrategia: Estrategia
    hallazgos: list[Hallazgo]
    requiere_aceptar_caida: bool

    @property
    def bloqueante(self) -> bool:
        return motor.hay_bloqueantes(self.hallazgos)


@dataclass(frozen=True)
class ResultadoGuardado:
    estrategia: Estrategia
    hallazgos: list[Hallazgo]
    archivo: Path
    repositorio: ResultadoRepositorio


def _contexto(estrategia: Estrategia, perfil: PerfilBD, codigos_existentes: list[str]) -> ContextoValidacion:
    escribibles: dict[str, bool] = {}
    libres: dict[str, int] = {}
    totales: dict[str, int] = {}
    for ruta in {tarea.destino.ruta for tarea in estrategia.tareas}:
        estado = inspeccionar_destino(ruta)
        escribibles[ruta] = estado.escribible
        if estado.libre_bytes is not None and estado.total_bytes is not None:
            libres[ruta] = estado.libre_bytes
            totales[ruta] = estado.total_bytes
    return ContextoValidacion(
        estrategia=estrategia,
        perfil=perfil,
        codigos_estrategia_existentes=codigos_existentes,
        destinos_escribibles=escribibles,
        espacio_libre_destino_bytes=libres,
        espacio_total_destino_bytes=totales,
    )


def validar(solicitud: SolicitudEstrategia, perfil: PerfilBD, ajustes: Ajustes, sid: str) -> ResultadoValidacion:
    estrategia = construir_estrategia(solicitud)
    existentes = almacen_estrategias.codigos_existentes(ajustes, sid, perfil.nombre)
    hallazgos = motor.validar(_contexto(estrategia, perfil, existentes))
    requiere_caida = any(modo_efectivo(tarea.como, perfil) is ModoRespaldo.CONSISTENTE for tarea in estrategia.tareas)
    return ResultadoValidacion(estrategia=estrategia, hallazgos=hallazgos, requiere_aceptar_caida=requiere_caida)


def guardar(solicitud: SolicitudEstrategia, perfil: PerfilBD, ajustes: Ajustes, sid: str) -> ResultadoGuardado:
    resultado = validar(solicitud, perfil, ajustes, sid)
    if resultado.bloqueante:
        raise ErrorCreacion(
            "La estrategia tiene errores que impiden guardarla. Corríjalos y vuelva a validar.",
            "bloqueada",
            resultado.hallazgos,
        )
    if resultado.requiere_aceptar_caida and not solicitud.aceptar_caida:
        raise ErrorCreacion(
            "Una o más tareas se ejecutarán en modo consistente y apagarán la base de datos. "
            "Debe aceptar la caída del servicio para continuar.",
            "caida_no_aceptada",
            resultado.hallazgos,
        )
    estrategia = resultado.estrategia.model_copy(update={"creada_en": datetime.now(UTC)})
    try:
        archivo = almacen_estrategias.guardar_archivo(ajustes, sid, estrategia)
    except almacen_estrategias.EstrategiaYaGuardada as error:
        raise ErrorCreacion(str(error), "duplicada", resultado.hallazgos) from error
    repositorio = (
        almacen_estrategias.guardar_en_repositorio(ajustes, perfil.nombre, estrategia)
        if solicitud.guardar_en_repositorio
        else REPOSITORIO_OMITIDO
    )
    return ResultadoGuardado(
        estrategia=estrategia, hallazgos=resultado.hallazgos, archivo=archivo, repositorio=repositorio
    )
