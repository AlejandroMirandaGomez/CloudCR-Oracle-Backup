from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from cloudcr_backup.oracle.connection import ErrorConexionOracle
from cloudcr_backup.oracle.explorador import InstanciaNoEncontrada

ErroresExploracion = (ErrorConexionOracle, InstanciaNoEncontrada)


def es_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def plantillas(request: Request) -> Jinja2Templates:
    motor: Jinja2Templates = request.app.state.plantillas
    return motor


def renderizar(request: Request, plantilla: str, contexto: dict[str, Any], estado: int = 200) -> HTMLResponse:
    respuesta: HTMLResponse = plantillas(request).TemplateResponse(request, plantilla, contexto, status_code=estado)
    return respuesta


def renderizar_error(request: Request, error: Exception, sid: str | None) -> HTMLResponse:
    contexto = {
        "mensaje": str(error),
        "sugerencia": getattr(error, "sugerencia", None),
        "sid": sid,
    }
    if es_htmx(request):
        return renderizar(request, "parciales/_error.html", contexto)
    estado = 404 if isinstance(error, InstanciaNoEncontrada) else 502
    return renderizar(request, "error.html", contexto, estado)
