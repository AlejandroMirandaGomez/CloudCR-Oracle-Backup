from dataclasses import dataclass, field

from cloudcr_backup.domain.enums import EstadoEjecucion
from cloudcr_backup.execution.parser import LogAnalizado

ESTADOS_JOB_FALLIDOS = frozenset({"FAILED", "COMPLETED WITH ERRORS", "RUNNING WITH ERRORS"})
ESTADOS_JOB_CON_ADVERTENCIAS = frozenset({"COMPLETED WITH WARNINGS", "RUNNING WITH WARNINGS"})
ESTADO_JOB_COMPLETO = "COMPLETED"


@dataclass(frozen=True)
class PiezaVerificada:
    ruta: str
    existe: bool
    tamano_bytes: int | None

    @property
    def valida(self) -> bool:
        return self.existe and bool(self.tamano_bytes)


@dataclass(frozen=True)
class EntradaClasificacion:
    codigo_salida: int | None
    agotado: bool
    log: LogAnalizado
    estado_job: str | None
    catalogo_consultado: bool
    piezas: list[PiezaVerificada] = field(default_factory=list)
    reapertura_correcta: bool | None = None
    error_lanzamiento: str | None = None


@dataclass(frozen=True)
class Clasificacion:
    estado: EstadoEjecucion
    motivos: list[str]

    @property
    def correcta(self) -> bool:
        return self.estado in (EstadoEjecucion.EXITOSA, EstadoEjecucion.CON_ADVERTENCIAS)


def _motivos_de_fallo(entrada: EntradaClasificacion) -> list[str]:
    motivos = []
    log = entrada.log
    if entrada.error_lanzamiento:
        motivos.append(entrada.error_lanzamiento)
    if entrada.agotado:
        motivos.append("RMAN superó el tiempo máximo de ejecución y se detuvo.")
    if entrada.codigo_salida not in (0, None):
        motivos.append(f"RMAN terminó con código de salida {entrada.codigo_salida}.")
    if log.errores:
        principal = log.primer_error
        texto = str(principal).rstrip(".")
        motivos.append(f"El log de RMAN contiene {len(log.errores)} error(es); el principal: {texto}.")
    if log.tiene_pila_error and not log.errores:
        motivos.append("El log de RMAN contiene una pila de errores (ERROR MESSAGE STACK FOLLOWS).")
    if not log.completo and not entrada.agotado and entrada.error_lanzamiento is None:
        motivos.append("El log no llega a 'Recovery Manager complete.': RMAN no terminó normalmente.")
    if entrada.estado_job in ESTADOS_JOB_FALLIDOS:
        motivos.append(f"V$RMAN_BACKUP_JOB_DETAILS informa el trabajo como {entrada.estado_job}.")
    if not entrada.piezas and not log.piezas:
        motivos.append("No se generó ninguna pieza de respaldo.")
    faltantes = [p.ruta for p in entrada.piezas if not p.valida]
    if faltantes:
        motivos.append(f"{len(faltantes)} pieza(s) no existen en disco o están vacías: {', '.join(faltantes)}.")
    return motivos


def _motivos_de_advertencia(entrada: EntradaClasificacion) -> list[str]:
    motivos = []
    if entrada.log.advertencias:
        motivos.append(
            f"El log de RMAN contiene {len(entrada.log.advertencias)} advertencia(s): "
            f"{str(entrada.log.advertencias[0]).rstrip('.')}."
        )
    if entrada.estado_job in ESTADOS_JOB_CON_ADVERTENCIAS:
        motivos.append(f"V$RMAN_BACKUP_JOB_DETAILS informa el trabajo como {entrada.estado_job}.")
    if not entrada.catalogo_consultado:
        motivos.append("No se pudo confirmar el resultado en V$RMAN_BACKUP_JOB_DETAILS ni V$BACKUP_PIECE_DETAILS.")
    elif entrada.estado_job is None:
        motivos.append("El trabajo no aparece en V$RMAN_BACKUP_JOB_DETAILS con su COMMAND ID.")
    if entrada.reapertura_correcta is False:
        motivos.append("El respaldo terminó, pero la base de datos no quedó abierta después del respaldo consistente.")
    return motivos


def clasificar(entrada: EntradaClasificacion) -> Clasificacion:
    fallos = _motivos_de_fallo(entrada)
    if fallos:
        if entrada.log.completo and entrada.codigo_salida == 0:
            fallos.append("El código de salida 0 y 'Recovery Manager complete.' no bastan para declarar éxito.")
        return Clasificacion(EstadoEjecucion.FALLIDA, fallos)
    advertencias = _motivos_de_advertencia(entrada)
    if advertencias:
        return Clasificacion(EstadoEjecucion.CON_ADVERTENCIAS, advertencias)
    return Clasificacion(
        EstadoEjecucion.EXITOSA,
        [
            "RMAN terminó sin errores, el trabajo figura como COMPLETED y todas las piezas existen en disco."
            if entrada.estado_job == ESTADO_JOB_COMPLETO
            else "RMAN terminó sin errores y todas las piezas existen en disco."
        ],
    )
