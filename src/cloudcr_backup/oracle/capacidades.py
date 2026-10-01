from dataclasses import dataclass

from cloudcr_backup.domain.enums import Compresion


@dataclass(frozen=True)
class CapacidadesEdicion:
    compresiones_soportadas: frozenset[Compresion]
    canales_maximos: int
    block_change_tracking: bool


_XE = CapacidadesEdicion(
    compresiones_soportadas=frozenset({Compresion.NINGUNA, Compresion.BASIC}),
    canales_maximos=1,
    block_change_tracking=False,
)

_SE = CapacidadesEdicion(
    compresiones_soportadas=frozenset({Compresion.NINGUNA, Compresion.BASIC}),
    canales_maximos=4,
    block_change_tracking=False,
)

_EE = CapacidadesEdicion(
    compresiones_soportadas=frozenset(Compresion),
    canales_maximos=255,
    block_change_tracking=True,
)

_CAPACIDADES_POR_EDICION = {
    "XE": _XE,
    "SE": _SE,
    "SE2": _SE,
    "PE": _EE,
    "EE": _EE,
}


def capacidades_de(codigo_edicion: str) -> CapacidadesEdicion:
    return _CAPACIDADES_POR_EDICION.get(codigo_edicion.upper(), _XE)
