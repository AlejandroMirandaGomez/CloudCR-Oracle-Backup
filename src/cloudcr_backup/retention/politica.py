import re
from collections.abc import Iterable
from datetime import datetime, timedelta

from cloudcr_backup.domain.estrategia import Retencion
from cloudcr_backup.domain.retencion import PiezaRetencion
from cloudcr_backup.repository.piezas import PiezaRegistrada
from cloudcr_backup.rman.render import renderizar

PLANTILLA_RETENCION = "retencion.rman.j2"
PLANTILLA_PURGA = "purga.rman.j2"
TIPOS_OBSOLETOS = ("Backup Piece", "Archive Log", "Datafile Copy", "Control File Copy")
PATRON_RUTA = re.compile(r"\s((?:[A-Za-z]:[\\/]|/|\+)\S.*)$")


class PoliticaNoDefinida(ValueError):
    pass


class PurgaNoPermitida(ValueError):
    pass


def clausula(retencion: Retencion) -> str | None:
    if retencion.ventana_dias is not None and retencion.redundancia is not None:
        raise PoliticaNoDefinida("La retención no puede tener ventana y redundancia a la vez (RET_002).")
    if retencion.ventana_dias is not None:
        return f"RECOVERY WINDOW OF {retencion.ventana_dias} DAYS"
    if retencion.redundancia is not None:
        return f"REDUNDANCY {retencion.redundancia}"
    return None


def describir(retencion: Retencion) -> str:
    if retencion.ventana_dias is not None:
        texto = f"Conservar {retencion.ventana_dias} días (ventana de recuperación)"
    elif retencion.redundancia is not None:
        texto = f"Conservar las últimas {retencion.redundancia} copias (redundancia)"
    else:
        texto = "Sin política de retención: los respaldos se acumulan sin límite"
    if retencion.archived_logs_dias is not None:
        texto += f"; archived logs ya respaldados: {retencion.archived_logs_dias} días"
    return texto + ("; purga automática activa" if retencion.purga_automatica else "; solo informe, nunca borra")


def script(retencion: Retencion, purgar: bool = False) -> str:
    politica = clausula(retencion)
    if politica is None:
        raise PoliticaNoDefinida("La estrategia no tiene ventana de recuperación ni redundancia definidas.")
    if purgar and not retencion.purga_automatica:
        raise PurgaNoPermitida(
            "La estrategia no tiene la purga automática activa: el sistema solo informa los respaldos obsoletos, "
            "nunca los borra."
        )
    return renderizar(
        PLANTILLA_RETENCION, purgar=purgar, politica=politica, archived_logs_dias=retencion.archived_logs_dias
    )


def _cadena_rman(ruta: str) -> str:
    if "'" in ruta:
        raise ValueError(f"La ruta {ruta} contiene una comilla simple y no se puede pasar a RMAN.")
    return f"'{ruta}'"


def script_purga(rutas: list[str], archived_logs_dias: int | None) -> str:
    if not rutas and archived_logs_dias is None:
        raise PoliticaNoDefinida("No hay piezas obsoletas ni archived logs que purgar.")
    return renderizar(
        PLANTILLA_PURGA, piezas=[_cadena_rman(r) for r in rutas], archived_logs_dias=archived_logs_dias
    )


def vence_en(fin: datetime, retencion: Retencion) -> datetime | None:
    if retencion.ventana_dias is None:
        return None
    return fin + timedelta(days=retencion.ventana_dias)


def obsoletas_de_reporte(texto: str) -> list[str]:
    rutas = []
    for linea in texto.splitlines():
        limpia = linea.strip()
        if not limpia.startswith(TIPOS_OBSOLETOS):
            continue
        ruta = PATRON_RUTA.search(limpia)
        if ruta is not None:
            rutas.append(ruta.group(1).strip())
    return list(dict.fromkeys(rutas))


def _como_pieza(pieza: PiezaRegistrada, vencida: bool, obsoletas: set[str]) -> PiezaRetencion:
    return PiezaRetencion(
        pieza_id=pieza.id,
        ruta=pieza.nombre_archivo,
        tamano_bytes=pieza.tamano_bytes,
        ejecucion_id=pieza.ejecucion_id,
        tarea=pieza.tarea_codigo,
        fin=pieza.fin,
        vence_en=pieza.vence_en,
        vencida=vencida,
        obsoleta_rman=pieza.nombre_archivo.upper() in obsoletas,
        marcada_obsoleta=pieza.obsoleta,
    )


def _ejecuciones_fuera_de_redundancia(piezas: list[PiezaRegistrada], redundancia: int) -> set[int]:
    por_tarea: dict[str, set[tuple[datetime, int]]] = {}
    for pieza in piezas:
        por_tarea.setdefault(pieza.tarea_codigo, set()).add((pieza.fin or datetime.min, pieza.ejecucion_id))
    fuera: set[int] = set()
    for ejecuciones in por_tarea.values():
        fuera |= {ejecucion_id for _, ejecucion_id in sorted(ejecuciones, reverse=True)[redundancia:]}
    return fuera


def vencidas(
    piezas: list[PiezaRegistrada], retencion: Retencion, ahora: datetime, obsoletas_rman: Iterable[str] = ()
) -> list[PiezaRetencion]:
    obsoletas = {ruta.upper() for ruta in obsoletas_rman}
    fuera = _ejecuciones_fuera_de_redundancia(piezas, retencion.redundancia) if retencion.redundancia else set()
    resultado = []
    for pieza in piezas:
        por_ventana = pieza.vence_en is not None and pieza.vence_en < ahora
        por_redundancia = pieza.ejecucion_id in fuera
        por_rman = pieza.nombre_archivo.upper() in obsoletas
        if por_ventana or por_redundancia or por_rman:
            resultado.append(_como_pieza(pieza, True, obsoletas))
    return resultado
