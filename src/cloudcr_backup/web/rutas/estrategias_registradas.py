from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from cloudcr_backup.domain.monitoreo import DetalleEstrategia
from cloudcr_backup.presentacion.estado import ETIQUETA_COLOR, SIMBOLO_COLOR, TONO_COLOR
from cloudcr_backup.web.monitoreo import ProveedorMonitoreo, obtener_monitoreo
from cloudcr_backup.web.rutas.comun import es_htmx, renderizar
from cloudcr_backup.web.seguridad import exigir_origen_confiable

router = APIRouter()

Monitoreo = Annotated[ProveedorMonitoreo, Depends(obtener_monitoreo)]
Cantidad = Annotated[int, Query(ge=1, le=100)]


def ruta_detalle(bd: str, codigo: str) -> str:
    return f"/estrategias/{quote(bd, safe='')}/{quote(codigo, safe='')}"


def contexto_detalle(detalle: DetalleEstrategia, zona: str, aviso: str | None = None) -> dict[str, Any]:
    color = detalle.resumen.color
    return {
        "seccion": "estrategias",
        "detalle": detalle,
        "resumen": detalle.resumen,
        "zona": zona,
        "color": {"etiqueta": ETIQUETA_COLOR[color], "simbolo": SIMBOLO_COLOR[color], "tono": TONO_COLOR[color].value},
        "ruta": ruta_detalle(detalle.resumen.bd, detalle.resumen.codigo),
        "aviso": aviso,
    }


@router.get("/estrategias", response_class=HTMLResponse)
def pagina_estrategias(request: Request, monitoreo: Monitoreo) -> HTMLResponse:
    resumenes = monitoreo.estrategias()
    filas = [
        {
            "resumen": r,
            "ruta": ruta_detalle(r.bd, r.codigo),
            "etiqueta": ETIQUETA_COLOR[r.color],
            "simbolo": SIMBOLO_COLOR[r.color],
            "tono": TONO_COLOR[r.color].value,
        }
        for r in resumenes
    ]
    bases = sorted({r.bd for r in resumenes})
    contexto = {"seccion": "estrategias", "filas": filas, "bases": bases, "zona": monitoreo.zona_horaria}
    return renderizar(request, "estrategias.html", contexto)


@router.get("/estrategias/{bd}/{codigo}", response_class=HTMLResponse)
def pagina_estrategia(
    request: Request,
    bd: str,
    codigo: str,
    monitoreo: Monitoreo,
    n: Cantidad = 5,
    aviso: Annotated[str | None, Query(max_length=600)] = None,
) -> HTMLResponse:
    detalle = monitoreo.estrategia(bd, codigo, n)
    return renderizar(request, "estrategia_detalle.html", contexto_detalle(detalle, monitoreo.zona_horaria, aviso))


def _cambiar(request: Request, bd: str, codigo: str, monitoreo: ProveedorMonitoreo, activa: bool) -> Response:
    resumen = monitoreo.cambiar_estado_estrategia(bd, codigo, activa)
    if not es_htmx(request):
        return RedirectResponse(ruta_detalle(resumen.bd, resumen.codigo), status_code=303)
    detalle = monitoreo.estrategia(bd, codigo, 5)
    aviso = f"Estrategia {resumen.codigo} {'activada' if activa else 'desactivada'}."
    contexto = contexto_detalle(detalle, monitoreo.zona_horaria, aviso)
    return renderizar(request, "parciales/_estrategia_detalle.html", contexto)


@router.post(
    "/estrategias/{bd}/{codigo}/activar", response_model=None, dependencies=[Depends(exigir_origen_confiable)]
)
def activar(request: Request, bd: str, codigo: str, monitoreo: Monitoreo) -> Response:
    return _cambiar(request, bd, codigo, monitoreo, True)


@router.post(
    "/estrategias/{bd}/{codigo}/desactivar", response_model=None, dependencies=[Depends(exigir_origen_confiable)]
)
def desactivar(request: Request, bd: str, codigo: str, monitoreo: Monitoreo) -> Response:
    return _cambiar(request, bd, codigo, monitoreo, False)


@router.get("/api/estrategias")
def api_estrategias(monitoreo: Monitoreo) -> list[dict[str, Any]]:
    return [r.model_dump(mode="json") for r in monitoreo.estrategias()]


@router.get("/api/estrategias/{bd}/{codigo}")
def api_estrategia(bd: str, codigo: str, monitoreo: Monitoreo, n: Cantidad = 5) -> dict[str, Any]:
    return monitoreo.estrategia(bd, codigo, n).model_dump(mode="json")


@router.get("/api/estrategias/{bd}/{codigo}/tareas/{tarea}/proximas")
def api_proximas(bd: str, codigo: str, tarea: str, monitoreo: Monitoreo, n: Cantidad = 5) -> dict[str, Any]:
    momentos = monitoreo.proximas(bd, codigo, tarea, n)
    return {
        "bd": bd.upper(),
        "estrategia": codigo.upper(),
        "tarea": tarea.upper(),
        "proximas": [m.isoformat() for m in momentos],
    }


@router.post("/api/estrategias/{bd}/{codigo}/activar", dependencies=[Depends(exigir_origen_confiable)])
def api_activar(bd: str, codigo: str, monitoreo: Monitoreo) -> dict[str, Any]:
    return monitoreo.cambiar_estado_estrategia(bd, codigo, True).model_dump(mode="json")


@router.post("/api/estrategias/{bd}/{codigo}/desactivar", dependencies=[Depends(exigir_origen_confiable)])
def api_desactivar(bd: str, codigo: str, monitoreo: Monitoreo) -> dict[str, Any]:
    return monitoreo.cambiar_estado_estrategia(bd, codigo, False).model_dump(mode="json")
