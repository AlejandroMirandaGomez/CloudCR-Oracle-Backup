from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from cloudcr_backup.domain.ejecucion import PruebaEvidencia
from cloudcr_backup.domain.enums import EstadoPrueba
from cloudcr_backup.execution.correlator import PiezaCatalogo
from cloudcr_backup.execution.destino import BaseDestino
from cloudcr_backup.execution.parser import analizar
from cloudcr_backup.execution.runner import InvocacionRman, Lanzador, escribir_script, leer_log
from cloudcr_backup.rman.render import renderizar

PLANTILLA_VERIFICACION = "verificacion.rman.j2"
ARCHIVO_SCRIPT = "verificacion.rman"
ARCHIVO_LOG = "verificacion.log"
PRUEBA_EXISTENCIA = "EXISTENCIA"
PRUEBA_CROSSCHECK = "CROSSCHECK"
PRUEBA_VALIDATE = "VALIDATE"
TIMEOUT_VERIFICACION_SEGUNDOS = 60 * 60

ConsultaPiezas = Callable[[str], list[PiezaCatalogo]]
MedirArchivo = Callable[[str], int | None]


@dataclass(frozen=True)
class ResultadoVerificacion:
    estado: EstadoPrueba
    pruebas: list[PruebaEvidencia] = field(default_factory=list)
    log: str | None = None


def tamano_en_disco(ruta: str) -> int | None:
    try:
        return Path(ruta).stat().st_size
    except OSError:
        return None


def script_verificacion(tag: str, conjuntos: list[int]) -> str:
    return renderizar(PLANTILLA_VERIFICACION, tag=tag, conjuntos=conjuntos)


def _prueba(tipo: str, correcta: bool, detalle: str, momento: datetime) -> PruebaEvidencia:
    resultado = EstadoPrueba.OK if correcta else EstadoPrueba.FALLIDA
    return PruebaEvidencia(tipo=tipo, resultado=resultado, detalle=detalle, ejecutada_en=momento)


def _existencia(piezas: list[PiezaCatalogo], medir: MedirArchivo, momento: datetime) -> PruebaEvidencia:
    faltantes = [p.handle for p in piezas if not medir(p.handle)]
    if faltantes:
        return _prueba(PRUEBA_EXISTENCIA, False, "Faltan o están vacías: " + ", ".join(faltantes), momento)
    return _prueba(PRUEBA_EXISTENCIA, True, f"Las {len(piezas)} pieza(s) existen en disco.", momento)


def _crosscheck(antes: list[PiezaCatalogo], despues: list[PiezaCatalogo], momento: datetime) -> PruebaEvidencia:
    disponibles = {p.handle.upper() for p in despues if p.disponible}
    expiradas = [p.handle for p in antes if p.handle.upper() not in disponibles]
    if expiradas:
        return _prueba(
            PRUEBA_CROSSCHECK, False, "CROSSCHECK las marcó EXPIRED o no disponibles: " + ", ".join(expiradas), momento
        )
    return _prueba(PRUEBA_CROSSCHECK, True, "CROSSCHECK: todas las piezas AVAILABLE.", momento)


def verificar(
    base: BaseDestino,
    tag: str,
    carpeta: Path,
    consultar_piezas: ConsultaPiezas,
    lanzar: Lanzador,
    nls_lang: str,
    medir: MedirArchivo = tamano_en_disco,
    ahora: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ResultadoVerificacion:
    momento = ahora()
    piezas = consultar_piezas(tag)
    if not piezas:
        return ResultadoVerificacion(
            EstadoPrueba.FALLIDA,
            [_prueba(PRUEBA_EXISTENCIA, False, f"No hay piezas con el tag {tag} en el catálogo de RMAN.", momento)],
        )
    existencia = _existencia(piezas, medir, momento)
    script = carpeta / ARCHIVO_SCRIPT
    log = carpeta / ARCHIVO_LOG
    escribir_script(script, script_verificacion(tag, sorted({p.conjunto for p in piezas if p.conjunto is not None})))
    resultado = lanzar(
        InvocacionRman(
            oracle_home=base.oracle_home,
            sid=base.sid,
            script=script,
            log=log,
            timeout_segundos=TIMEOUT_VERIFICACION_SEGUNDOS,
            nls_lang=nls_lang,
        )
    )
    analizado = analizar(leer_log(log))
    despues = consultar_piezas(tag)
    crosscheck = _crosscheck(piezas, despues, momento)
    validate_ok = resultado.error_lanzamiento is None and not analizado.errores and analizado.completo
    detalle_validate = (
        "VALIDATE BACKUPSET leyó todas las piezas sin errores."
        if validate_ok
        else resultado.error_lanzamiento or analizado.resumen_errores() or "RMAN no terminó la validación."
    )
    pruebas = [existencia, crosscheck, _prueba(PRUEBA_VALIDATE, validate_ok, detalle_validate, momento)]
    estado = EstadoPrueba.OK if all(p.resultado is EstadoPrueba.OK for p in pruebas) else EstadoPrueba.FALLIDA
    return ResultadoVerificacion(estado, pruebas, str(log))
