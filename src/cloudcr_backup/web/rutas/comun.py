from typing import Any
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from cloudcr_backup.domain.enums import EstadoEstrategia
from cloudcr_backup.domain.errores import ErrorServicio
from cloudcr_backup.domain.monitoreo import ResumenEstrategia
from cloudcr_backup.oracle.connection import ErrorConexionOracle
from cloudcr_backup.oracle.explorador import InstanciaNoEncontrada

ErroresRepositorio = (ErrorServicio, NotImplementedError)
ErroresExploracion = (ErrorConexionOracle, InstanciaNoEncontrada)


def es_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def plantillas(request: Request) -> Jinja2Templates:
    motor: Jinja2Templates = request.app.state.plantillas
    return motor


def estrategia_lista(resumen: ResumenEstrategia) -> bool:
    return (
        resumen.estado == EstadoEstrategia.ACTIVA and resumen.tareas > 0 and resumen.tareas_con_script >= resumen.tareas
    )


def avance_del_flujo(resumenes: list[ResumenEstrategia]) -> dict[str, Any]:
    pendiente = next((r for r in resumenes if not estrategia_lista(r)), None)
    return {
        "n_estrategias": len(resumenes),
        "n_listas": sum(1 for r in resumenes if estrategia_lista(r)),
        "pendiente": (
            {
                "codigo": pendiente.codigo,
                "ruta": f"/estrategias/{quote(pendiente.bd, safe='')}/{quote(pendiente.codigo, safe='')}",
            }
            if pendiente
            else None
        ),
    }


def avance_de_la_app(request: Request) -> dict[str, Any]:
    try:
        return avance_del_flujo(request.app.state.monitoreo.estrategias())
    except ErroresRepositorio:
        return {"n_estrategias": None, "n_listas": None, "pendiente": None}


def renderizar(request: Request, plantilla: str, contexto: dict[str, Any], estado: int = 200) -> HTMLResponse:
    if "seccion" in contexto and "n_estrategias" not in contexto and not es_htmx(request):
        contexto = {**avance_de_la_app(request), **contexto}
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
