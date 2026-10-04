from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from fastapi import FastAPI, Request

from cloudcr_backup.config.ajustes import Ajustes, cargar_ajustes
from cloudcr_backup.domain.alertas import ResumenEvaluacion, VistaAlerta
from cloudcr_backup.domain.historial import ArchivoExportado, ConsultaHistorial, DetalleEjecucion, PaginaHistorial
from cloudcr_backup.domain.monitoreo import DetalleEstrategia, EstadoAgente, EstadoGeneral, ResumenEstrategia
from cloudcr_backup.services import agente, alertas, consulta_estrategias, historial, monitoreo


class ProveedorMonitoreo(Protocol):
    @property
    def zona_horaria(self) -> str: ...

    def estado(self, bd: str | None) -> EstadoGeneral: ...

    def agentes(self) -> list[EstadoAgente]: ...

    def estrategias(self) -> list[ResumenEstrategia]: ...

    def estrategia(self, bd: str, codigo: str, cantidad: int) -> DetalleEstrategia: ...

    def proximas(self, bd: str, codigo: str, tarea: str, cantidad: int) -> list[datetime]: ...

    def cambiar_estado_estrategia(self, bd: str, codigo: str, activa: bool) -> ResumenEstrategia: ...

    def historial(self, consulta: ConsultaHistorial) -> PaginaHistorial: ...

    def detalle_ejecucion(self, ejecucion_id: int) -> DetalleEjecucion: ...

    def exportar_historial(self, consulta: ConsultaHistorial, formato: str) -> ArchivoExportado: ...

    def exportar_evidencia(self, ejecucion_id: int, formato: str) -> ArchivoExportado: ...

    def alertas(self, estado: str | None, severidad: str | None) -> list[VistaAlerta]: ...

    def reconocer_alerta(self, alerta_id: int) -> VistaAlerta: ...

    def resolver_alerta(self, alerta_id: int) -> VistaAlerta: ...

    def evaluar_alertas(self) -> ResumenEvaluacion: ...


class ServicioMonitoreo:
    def __init__(self, ajustes: Callable[[], Ajustes]) -> None:
        self._ajustes = ajustes

    @property
    def zona_horaria(self) -> str:
        return self._ajustes().zona_horaria

    def estado(self, bd: str | None) -> EstadoGeneral:
        return monitoreo.estado_general(self._ajustes(), bd)

    def agentes(self) -> list[EstadoAgente]:
        return agente.estado_agentes(self._ajustes())

    def estrategias(self) -> list[ResumenEstrategia]:
        return consulta_estrategias.listar(self._ajustes())

    def estrategia(self, bd: str, codigo: str, cantidad: int) -> DetalleEstrategia:
        return consulta_estrategias.detalle(self._ajustes(), bd, codigo, cantidad)

    def proximas(self, bd: str, codigo: str, tarea: str, cantidad: int) -> list[datetime]:
        return consulta_estrategias.proximas_de_tarea(self._ajustes(), bd, codigo, tarea, cantidad)

    def cambiar_estado_estrategia(self, bd: str, codigo: str, activa: bool) -> ResumenEstrategia:
        return consulta_estrategias.cambiar_estado(self._ajustes(), bd, codigo, activa)

    def historial(self, consulta: ConsultaHistorial) -> PaginaHistorial:
        return historial.consultar(self._ajustes(), consulta)

    def detalle_ejecucion(self, ejecucion_id: int) -> DetalleEjecucion:
        return historial.detalle(self._ajustes(), ejecucion_id)

    def exportar_historial(self, consulta: ConsultaHistorial, formato: str) -> ArchivoExportado:
        return historial.exportar(self._ajustes(), consulta, formato)

    def exportar_evidencia(self, ejecucion_id: int, formato: str) -> ArchivoExportado:
        return historial.exportar_evidencia(self._ajustes(), ejecucion_id, formato)

    def alertas(self, estado: str | None, severidad: str | None) -> list[VistaAlerta]:
        return alertas.listar(self._ajustes(), estado, severidad)

    def reconocer_alerta(self, alerta_id: int) -> VistaAlerta:
        return alertas.reconocer(self._ajustes(), alerta_id)

    def resolver_alerta(self, alerta_id: int) -> VistaAlerta:
        return alertas.resolver(self._ajustes(), alerta_id)

    def evaluar_alertas(self) -> ResumenEvaluacion:
        return alertas.evaluar(self._ajustes())


def ajustes_de_la_app(app: FastAPI) -> Callable[[], Ajustes]:
    def obtener() -> Ajustes:
        ajustes: Ajustes | None = app.state.ajustes
        if ajustes is None:
            ajustes = cargar_ajustes()
            app.state.ajustes = ajustes
        return ajustes

    return obtener


def obtener_monitoreo(request: Request) -> ProveedorMonitoreo:
    proveedor: ProveedorMonitoreo = request.app.state.monitoreo
    return proveedor
