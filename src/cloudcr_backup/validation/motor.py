from collections.abc import Callable

from cloudcr_backup.domain.enums import Severidad
from cloudcr_backup.domain.hallazgos import Hallazgo, ordenar_por_severidad
from cloudcr_backup.validation.contexto import ContextoValidacion

ReglaValidacion = Callable[[ContextoValidacion], list[Hallazgo]]

_reglas: dict[str, ReglaValidacion] = {}


def regla(codigo: str) -> Callable[[ReglaValidacion], ReglaValidacion]:
    def decorador(funcion: ReglaValidacion) -> ReglaValidacion:
        if codigo in _reglas:
            raise ValueError(f"La regla {codigo} ya está registrada.")
        _reglas[codigo] = funcion
        return funcion

    return decorador


def reglas_registradas() -> list[str]:
    return sorted(_reglas)


def validar(contexto: ContextoValidacion) -> list[Hallazgo]:
    hallazgos: list[Hallazgo] = []
    for funcion in _reglas.values():
        hallazgos.extend(funcion(contexto))
    return ordenar_por_severidad(hallazgos)


def hay_bloqueantes(hallazgos: list[Hallazgo]) -> bool:
    return any(hallazgo.severidad is Severidad.ERROR for hallazgo in hallazgos)
