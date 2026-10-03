import logging
from collections.abc import Callable
from pathlib import Path

from cloudcr_backup.oracle.connection import ErrorConexionOracle, iniciar_cliente_thick
from cloudcr_backup.oracle.discovery import InstanciaDescubierta, descubrir_instancias

REGISTRO = logging.getLogger("cloudcr.cliente_oracle")


def elegir_oracle_home(instancias: list[InstanciaDescubierta]) -> Path | None:
    candidatas = sorted(instancias, key=lambda i: (not i.en_ejecucion, i.sid))
    return next((i.oracle_home for i in candidatas if i.oracle_home is not None), None)


def preparar_cliente_oracle(
    descubrir: Callable[[], list[InstanciaDescubierta]] = descubrir_instancias,
    iniciar: Callable[[Path], None] = iniciar_cliente_thick,
) -> Path | None:
    try:
        home = elegir_oracle_home(descubrir())
    except Exception:
        REGISTRO.exception("No se pudieron descubrir instancias para iniciar el cliente Oracle")
        return None
    if home is None:
        return None
    try:
        iniciar(home)
    except ErrorConexionOracle:
        REGISTRO.exception("No se pudo iniciar el cliente Oracle thick desde %s; se usará el modo thin", home)
        return None
    return home
