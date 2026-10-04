from dataclasses import dataclass, field
from enum import StrEnum

from cloudcr_backup.domain.enums import EstadoScript, LogMode, ModoRespaldo, Severidad
from cloudcr_backup.domain.hallazgos import Hallazgo
from cloudcr_backup.rman.aprobacion import hash_de_bytes


class CodigoPreflight(StrEnum):
    SCRIPT_NO_APROBADO = "SCRIPT_NO_APROBADO"
    SCRIPT_ALTERADO = "SCRIPT_ALTERADO"
    CAIDA_NO_ACEPTADA = "CAIDA_NO_ACEPTADA"
    BD_NO_DISPONIBLE = "BD_NO_DISPONIBLE"
    MODO_ARCHIVADO_CAMBIO = "MODO_ARCHIVADO_CAMBIO"
    DESTINO_NO_ESCRIBIBLE = "DESTINO_NO_ESCRIBIBLE"
    ESPACIO_INSUFICIENTE = "ESPACIO_INSUFICIENTE"
    VALIDACION = "VALIDACION"


@dataclass(frozen=True)
class EntradaPreflight:
    estado_script: EstadoScript
    hash_registrado: str
    contenido_registrado: str
    bytes_en_disco: bytes | None
    acepto_caida: bool
    modo: ModoRespaldo
    log_mode_actual: LogMode | None
    log_mode_al_generar: LogMode | None
    destino: str
    destino_escribible: bool
    libre_bytes: int | None = None
    estimado_bytes: int | None = None
    hallazgos: list[Hallazgo] = field(default_factory=list)
    error_conexion: str | None = None


@dataclass(frozen=True)
class ProblemaPreflight:
    codigo: CodigoPreflight
    mensaje: str
    sugerencia: str | None = None

    def __str__(self) -> str:
        return f"{self.codigo.value}: {self.mensaje}"


@dataclass(frozen=True)
class ResultadoPreflight:
    problemas: list[ProblemaPreflight]

    @property
    def aprobado(self) -> bool:
        return not self.problemas

    @property
    def script_alterado(self) -> bool:
        return any(p.codigo is CodigoPreflight.SCRIPT_ALTERADO for p in self.problemas)

    def codigos(self) -> list[CodigoPreflight]:
        return [p.codigo for p in self.problemas]


def _script(entrada: EntradaPreflight) -> list[ProblemaPreflight]:
    if entrada.estado_script is not EstadoScript.APROBADO:
        return [
            ProblemaPreflight(
                CodigoPreflight.SCRIPT_NO_APROBADO,
                f"El script de la ejecución está {entrada.estado_script.value}; solo se ejecuta un script APROBADO.",
                "Apruebe la versión vigente con 'cloudcr script aprobar'.",
            )
        ]
    problemas = []
    if hash_de_bytes(entrada.contenido_registrado.encode("utf-8")) != entrada.hash_registrado.lower():
        problemas.append(
            ProblemaPreflight(
                CodigoPreflight.SCRIPT_ALTERADO,
                "El contenido guardado en el repositorio no coincide con el hash SHA-256 aprobado.",
                "Genere y apruebe una versión nueva del script.",
            )
        )
    if entrada.bytes_en_disco is not None and hash_de_bytes(entrada.bytes_en_disco) != entrada.hash_registrado.lower():
        problemas.append(
            ProblemaPreflight(
                CodigoPreflight.SCRIPT_ALTERADO,
                "El archivo del script aprobado fue modificado después de aprobarse: su SHA-256 ya no coincide.",
                "No se ejecuta un script distinto del aprobado. Genere y apruebe una versión nueva.",
            )
        )
    if entrada.modo is ModoRespaldo.CONSISTENTE and not entrada.acepto_caida:
        problemas.append(
            ProblemaPreflight(
                CodigoPreflight.CAIDA_NO_ACEPTADA,
                "El script apaga la base de datos (respaldo CONSISTENTE) y nadie aceptó la caída del servicio.",
                "Apruebe el script con --acepto-caida.",
            )
        )
    return problemas


def _base(entrada: EntradaPreflight) -> list[ProblemaPreflight]:
    if entrada.error_conexion is not None:
        return [
            ProblemaPreflight(
                CodigoPreflight.BD_NO_DISPONIBLE,
                f"No se pudo revalidar la base de datos antes de respaldar: {entrada.error_conexion}",
                "Verifique que la instancia esté iniciada y que el usuario pertenezca a ORA_DBA.",
            )
        ]
    actual, al_generar = entrada.log_mode_actual, entrada.log_mode_al_generar
    if actual is not None and al_generar is not None and actual is not al_generar:
        return [
            ProblemaPreflight(
                CodigoPreflight.MODO_ARCHIVADO_CAMBIO,
                f"La base está en {actual.value} y el script se generó cuando estaba en {al_generar.value}.",
                "Regenere y apruebe el script con el modo de archivado actual.",
            )
        ]
    return []


def _destino(entrada: EntradaPreflight) -> list[ProblemaPreflight]:
    if not entrada.destino_escribible:
        return [
            ProblemaPreflight(
                CodigoPreflight.DESTINO_NO_ESCRIBIBLE,
                f"El destino {entrada.destino} no existe o no tiene permiso de escritura.",
                "Cree la carpeta y dé permiso de escritura a la cuenta que ejecuta RMAN.",
            )
        ]
    libre, estimado = entrada.libre_bytes, entrada.estimado_bytes
    if libre is not None and estimado is not None and estimado > libre:
        return [
            ProblemaPreflight(
                CodigoPreflight.ESPACIO_INSUFICIENTE,
                f"El respaldo necesita unos {estimado} bytes y el destino {entrada.destino} solo tiene {libre} libres.",
                "Libere espacio o cambie el destino de la tarea.",
            )
        ]
    return []


def _validacion(entrada: EntradaPreflight) -> list[ProblemaPreflight]:
    return [
        ProblemaPreflight(CodigoPreflight.VALIDACION, f"{h.codigo}: {h.mensaje}", h.accion_sugerida)
        for h in entrada.hallazgos
        if h.severidad is Severidad.ERROR
    ]


def evaluar(entrada: EntradaPreflight) -> ResultadoPreflight:
    problemas = _script(entrada)
    problemas += _base(entrada)
    if entrada.error_conexion is None:
        problemas += _validacion(entrada)
    problemas += _destino(entrada)
    vistos: set[str] = set()
    unicos = []
    for problema in problemas:
        if problema.mensaje not in vistos:
            vistos.add(problema.mensaje)
            unicos.append(problema)
    return ResultadoPreflight(unicos)
