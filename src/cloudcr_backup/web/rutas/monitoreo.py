from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse

from cloudcr_backup.presentacion.estado import (
    REGLA_SEMAFORO,
    fila_agente,
    fila_alerta,
    fila_semaforo,
    resumen_colores,
)
from cloudcr_backup.presentacion.historial import construir_tabla
from cloudcr_backup.web.monitoreo import ProveedorMonitoreo, obtener_monitoreo
from cloudcr_backup.web.rutas.comun import es_htmx, renderizar

router = APIRouter()

Monitoreo = Annotated[ProveedorMonitoreo, Depends(obtener_monitoreo)]
FiltroBd = Annotated[str | None, Query(max_length=30)]


@router.get("/estado", response_class=HTMLResponse)
def pagina_estado(request: Request, monitoreo: Monitoreo, bd: FiltroBd = None) -> HTMLResponse:
    general = monitoreo.estado(bd or None)
    zona = monitoreo.zona_horaria
    contexto: dict[str, Any] = {
        "seccion": "estado",
        "general": general,
        "bd": bd or "",
        "zona": zona,
        "semaforos": [fila_semaforo(s, zona) for s in general.semaforos],
        "resumen": resumen_colores(general),
        "en_curso": construir_tabla(general.en_curso),
        "alertas": [fila_alerta(a, zona) for a in general.alertas],
        "agentes": [fila_agente(a, zona) for a in general.agentes],
        "regla": REGLA_SEMAFORO,
        "observaciones_redo": general.observaciones_redo,
    }
    plantilla = "parciales/_estado.html" if es_htmx(request) else "estado.html"
    return renderizar(request, plantilla, contexto)


@router.get("/api/estado")
def api_estado(monitoreo: Monitoreo, bd: FiltroBd = None) -> dict[str, Any]:
    return monitoreo.estado(bd or None).model_dump(mode="json")


@router.get("/api/agente")
def api_agente(monitoreo: Monitoreo) -> list[dict[str, Any]]:
    return [agente.model_dump(mode="json") for agente in monitoreo.agentes()]
