from cloudcr_backup.domain.recuperacion import Escenario, ResultadoRecuperacion
from cloudcr_backup.execution.apertura import ResultadoApertura
from cloudcr_backup.execution.parser import LogAnalizado
from cloudcr_backup.execution.runner import ResultadoRman
from cloudcr_backup.recovery.en_linea import ResultadoEnLinea

ESCENARIOS_CON_REINICIO = frozenset(
    {
        Escenario.DATAFILE_CRITICO,
        Escenario.CONTROLFILE,
        Escenario.GRUPO_REDOLOG_ACTUAL,
        Escenario.SPFILE,
        Escenario.TOTAL_NOARCHIVELOG,
        Escenario.PUNTO_EN_TIEMPO,
    }
)
ESCENARIOS_CON_RESETLOGS = frozenset(
    {
        Escenario.CONTROLFILE,
        Escenario.GRUPO_REDOLOG_ACTUAL,
        Escenario.TOTAL_NOARCHIVELOG,
        Escenario.PUNTO_EN_TIEMPO,
    }
)
RECORDATORIO_RESETLOGS = "Se abrió con RESETLOGS: haga un respaldo completo ahora."
RECORDATORIO_ARCHIVELOG = "Conviene volver a poner la base en ARCHIVELOG."


def motivos_de_fallo(resultado: ResultadoRman, log: LogAnalizado) -> list[str]:
    motivos = []
    if resultado.error_lanzamiento:
        motivos.append(resultado.error_lanzamiento)
        return motivos
    if resultado.agotado:
        motivos.append("RMAN superó el tiempo máximo de ejecución y se detuvo.")
    if resultado.codigo_salida not in (0, None):
        motivos.append(f"RMAN terminó con código de salida {resultado.codigo_salida}.")
    if log.errores:
        principal = str(log.primer_error).rstrip(".")
        motivos.append(f"El log de RMAN contiene {len(log.errores)} error(es); el principal: {principal}.")
    if log.tiene_pila_error and not log.errores:
        motivos.append("El log de RMAN contiene una pila de errores (ERROR MESSAGE STACK FOLLOWS).")
    if not log.completo and not resultado.agotado:
        motivos.append("El log no llega a 'Recovery Manager complete.': RMAN no terminó normalmente.")
    return motivos


def clasificar(
    resultado: ResultadoRman,
    log: LogAnalizado,
    apertura: ResultadoApertura | None,
    en_linea: ResultadoEnLinea | None = None,
    escenario: Escenario | None = None,
) -> tuple[ResultadoRecuperacion, str]:
    if resultado.error_lanzamiento:
        return ResultadoRecuperacion.NO_LANZADO, resultado.error_lanzamiento
    motivos = motivos_de_fallo(resultado, log)
    if apertura is not None and not apertura.abierta:
        motivos.append(f"La base no quedó abierta después de la recuperación: {apertura.detalle}")
    if en_linea is not None:
        motivos += en_linea.errores
    if motivos:
        return ResultadoRecuperacion.EJECUTADO_CON_ERRORES, " ".join(motivos)
    mensaje = "RMAN terminó sin errores."
    if log.advertencias:
        mensaje += f" Advertencias: {log.resumen_advertencias()}"
    if apertura is not None:
        mensaje += f" {apertura.detalle}"
    if en_linea is not None and en_linea.detalle:
        mensaje += f" {en_linea.detalle}"
    if escenario in ESCENARIOS_CON_RESETLOGS:
        mensaje += f" {RECORDATORIO_RESETLOGS}"
    if escenario is Escenario.TOTAL_NOARCHIVELOG:
        mensaje += f" {RECORDATORIO_ARCHIVELOG}"
    return ResultadoRecuperacion.EJECUTADO_OK, mensaje
