from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Protocol

from cloudcr_backup.alerts.motor import FuenteAlertas
from cloudcr_backup.domain.planificacion import EjecucionEnCurso
from cloudcr_backup.scheduling.planificador import FuentePlanificador


class EjecutorRespaldo(Protocol):
    def ejecutar(self, ejecucion_id: int) -> None: ...

    def asegurar_apertura(self, ejecucion_id: int) -> None: ...


class SesionAgente(FuentePlanificador, FuenteAlertas, Protocol):
    def parametros(self) -> dict[str, str]: ...

    def en_curso_de_agente(self, agente: str) -> list[EjecucionEnCurso]: ...

    def marcar_interrumpida(self, ejecucion_id: int, motivo: str) -> bool: ...


FabricaSesion = Callable[[], AbstractContextManager[SesionAgente]]
