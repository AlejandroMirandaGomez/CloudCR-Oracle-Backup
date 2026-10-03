from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from cloudcr_backup.domain.alertas import ResumenEvaluacion, SeveridadAlerta, VistaAlerta
from cloudcr_backup.presentacion.estado import ETIQUETA_SEVERIDAD_ALERTA, fila_alerta
from cloudcr_backup.web.monitoreo import ProveedorMonitoreo, obtener_monitoreo
from cloudcr_backup.web.rutas.comun import es_htmx, renderizar
from cloudcr_backup.web.seguridad import exigir_origen_confiable

router = APIRouter()

Monitoreo = Annotated[ProveedorMonitoreo, Depends(obtener_monitoreo)]
FiltroEstado = Annotated[str, Query(max_length=20)]
FiltroSeveridad = Annotated[str | None, Query(max_length=20)]
ESTADOS_FILTRO = (
    ("vigentes", "Vigentes (abiertas y reconocidas)"),
    ("ABIERTA", "Abiertas"),
    ("RECONOCIDA", "Reconocidas"),
    ("RESUELTA", "Resueltas"),
    ("todas", "Todas"),
)


def _contexto(
    monitoreo: ProveedorMonitoreo,
    estado: str,
    severidad: str | None,
    aviso: str | None = None,
) -> dict[str, Any]:
    alertas = monitoreo.alertas(estado, severidad or None)
    zona = monitoreo.zona_horaria
    return {
        "seccion": "alertas",
        "alertas": [(alerta, fila_alerta(alerta, zona)) for alerta in alertas],
        "estado": estado,
        "severidad": severidad or "",
        "estados": ESTADOS_FILTRO,
        "severidades": [(s.value, ETIQUETA_SEVERIDAD_ALERTA[s]) for s in SeveridadAlerta],
        "aviso": aviso,
    }


def _texto_evaluacion(resumen: ResumenEvaluacion) -> str:
    return (
        f"Evaluación terminada: {len(resumen.abiertas)} nuevas, {len(resumen.actualizadas)} siguen vigentes, "
        f"{len(resumen.resueltas)} resueltas."
    )


@router.get("/alertas", response_class=HTMLResponse)
def pagina_alertas(
    request: Request, monitoreo: Monitoreo, estado: FiltroEstado = "vigentes", severidad: FiltroSeveridad = None
) -> HTMLResponse:
    plantilla = "parciales/_alertas.html" if es_htmx(request) else "alertas.html"
    return renderizar(request, plantilla, _contexto(monitoreo, estado, severidad))


def _accion(request: Request, monitoreo: Monitoreo, estado: str, severidad: str | None, aviso: str) -> Response:
    if not es_htmx(request):
        consulta = urlencode({"estado": estado, "severidad": severidad or ""})
        return RedirectResponse(f"/alertas?{consulta}", status_code=303)
    return renderizar(request, "parciales/_alertas.html", _contexto(monitoreo, estado, severidad, aviso))


@router.post(
    "/alertas/{alerta_id}/reconocer", response_model=None, dependencies=[Depends(exigir_origen_confiable)]
)
def reconocer(
    request: Request,
    alerta_id: int,
    monitoreo: Monitoreo,
    estado: FiltroEstado = "vigentes",
    severidad: FiltroSeveridad = None,
) -> Response:
    alerta = monitoreo.reconocer_alerta(alerta_id)
    return _accion(request, monitoreo, estado, severidad, f"Alerta {alerta.id} ({alerta.codigo}) reconocida.")


@router.post(
    "/alertas/{alerta_id}/resolver", response_model=None, dependencies=[Depends(exigir_origen_confiable)]
)
def resolver(
    request: Request,
    alerta_id: int,
    monitoreo: Monitoreo,
    estado: FiltroEstado = "vigentes",
    severidad: FiltroSeveridad = None,
) -> Response:
    alerta = monitoreo.resolver_alerta(alerta_id)
    return _accion(request, monitoreo, estado, severidad, f"Alerta {alerta.id} ({alerta.codigo}) resuelta.")


@router.post("/alertas/evaluar", response_model=None, dependencies=[Depends(exigir_origen_confiable)])
def evaluar(
    request: Request, monitoreo: Monitoreo, estado: FiltroEstado = "vigentes", severidad: FiltroSeveridad = None
) -> Response:
    resumen = monitoreo.evaluar_alertas()
    return _accion(request, monitoreo, estado, severidad, _texto_evaluacion(resumen))


def _json(alerta: VistaAlerta) -> dict[str, Any]:
    return alerta.model_dump(mode="json")


@router.get("/api/alertas")
def api_alertas(
    monitoreo: Monitoreo, estado: FiltroEstado = "vigentes", severidad: FiltroSeveridad = None
) -> list[dict[str, Any]]:
    return [_json(alerta) for alerta in monitoreo.alertas(estado, severidad or None)]


@router.post("/api/alertas/evaluar", dependencies=[Depends(exigir_origen_confiable)])
def api_evaluar(monitoreo: Monitoreo) -> dict[str, Any]:
    return monitoreo.evaluar_alertas().model_dump(mode="json")


@router.post("/api/alertas/{alerta_id}/reconocer", dependencies=[Depends(exigir_origen_confiable)])
def api_reconocer(alerta_id: int, monitoreo: Monitoreo) -> dict[str, Any]:
    return _json(monitoreo.reconocer_alerta(alerta_id))


@router.post("/api/alertas/{alerta_id}/resolver", dependencies=[Depends(exigir_origen_confiable)])
def api_resolver(alerta_id: int, monitoreo: Monitoreo) -> dict[str, Any]:
    return _json(monitoreo.resolver_alerta(alerta_id))
