from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from cloudcr_backup.execution.destino import BaseDestino, EstadoApertura
from cloudcr_backup.execution.parser import analizar
from cloudcr_backup.execution.runner import InvocacionRman, Lanzador, escribir_script, leer_log
from cloudcr_backup.rman.render import renderizar

PLANTILLA_APERTURA = "asegurar_apertura.rman.j2"
CODIGOS_YA_ABIERTA = frozenset({"ORA-01531", "ORA-65019", "RMAN-03002"})
ARCHIVO_LOG_APERTURA = "asegurar_apertura.log"
TIMEOUT_APERTURA_SEGUNDOS = 30 * 60

ComprobadorApertura = Callable[[BaseDestino], EstadoApertura]


@dataclass(frozen=True)
class ResultadoApertura:
    abierta: bool
    detalle: str
    errores: list[str] = field(default_factory=list)
    log: str | None = None


def sentencias(es_cdb: bool) -> list[str]:
    return [linea for linea in renderizar(PLANTILLA_APERTURA, es_cdb=es_cdb).splitlines() if linea.strip()]


def asegurar(
    base: BaseDestino,
    carpeta: Path,
    es_cdb: bool,
    lanzar: Lanzador,
    comprobar: ComprobadorApertura,
    nls_lang: str,
) -> ResultadoApertura:
    log = carpeta / ARCHIVO_LOG_APERTURA
    errores: list[str] = []
    for numero, sentencia in enumerate(sentencias(es_cdb), start=1):
        script = carpeta / f"asegurar_apertura_{numero}.rman"
        escribir_script(script, sentencia)
        resultado = lanzar(
            InvocacionRman(
                oracle_home=base.oracle_home,
                sid=base.sid,
                script=script,
                log=log,
                timeout_segundos=TIMEOUT_APERTURA_SEGUNDOS,
                nls_lang=nls_lang,
                agregar_al_log=numero > 1,
            )
        )
        if resultado.error_lanzamiento:
            errores.append(resultado.error_lanzamiento)
            break
    analizado = analizar(leer_log(log))
    errores += [str(e) for e in analizado.errores if e.codigo not in CODIGOS_YA_ABIERTA]
    try:
        estado = comprobar(base)
    except Exception as error:
        detalle = f"No se pudo comprobar la apertura: {type(error).__name__}: {error}"
        return ResultadoApertura(abierta=False, detalle=detalle, errores=errores, log=str(log))
    return ResultadoApertura(abierta=estado.abierta, detalle=estado.detalle, errores=errores, log=str(log))
