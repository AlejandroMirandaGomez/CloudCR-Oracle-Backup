from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.domain.errores import FiltroInvalido
from cloudcr_backup.domain.recuperacion import Escenario
from cloudcr_backup.presentacion.operaciones import AYUDA_OBJETIVO, ETIQUETA_ESCENARIO
from cloudcr_backup.services import bases_datos as servicio_bases
from cloudcr_backup.services import recuperacion as servicio_recuperacion
from cloudcr_backup.web.monitoreo import ajustes_de_la_app
from cloudcr_backup.web.rutas.comun import es_htmx, renderizar
from cloudcr_backup.web.rutas.retencion import base_elegida

router = APIRouter()

FORMATOS_MOMENTO = ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S")
Texto = Annotated[str | None, Query(max_length=130)]


def _ajustes(request: Request) -> Ajustes:
    return ajustes_de_la_app(request.app)()


def momento_desde_texto(valor: str | None) -> datetime | None:
    texto = (valor or "").strip()
    if not texto:
        return None
    for formato in FORMATOS_MOMENTO:
        try:
            return datetime.strptime(texto, formato)
        except ValueError:
            continue
    raise FiltroInvalido(f"'{texto}' no es una fecha y hora válida.", "Use el formato AAAA-MM-DD HH:MM.")


def _escenarios() -> list[tuple[str, str, str]]:
    return [(e.value, ETIQUETA_ESCENARIO[e], AYUDA_OBJETIVO[e]) for e in Escenario]


@router.get("/recuperacion", response_class=HTMLResponse)
def pagina_recuperacion(request: Request, bd: Annotated[str | None, Query(max_length=30)] = None) -> HTMLResponse:
    ajustes = _ajustes(request)
    bases = servicio_bases.registradas(ajustes)
    elegida = base_elegida(bd, bases)
    puntos = servicio_recuperacion.puntos(ajustes, elegida) if elegida else None
    contexto: dict[str, Any] = {
        "seccion": "recuperacion",
        "bases": bases,
        "bd": elegida,
        "puntos": puntos,
        "escenarios": _escenarios(),
        "zona": ajustes.zona_horaria,
    }
    plantilla = "parciales/_recuperacion.html" if es_htmx(request) else "recuperacion.html"
    return renderizar(request, plantilla, contexto)


@router.get("/recuperacion/{bd}/diagnostico", response_class=HTMLResponse)
def diagnostico(request: Request, bd: str) -> HTMLResponse:
    ajustes = _ajustes(request)
    resultado = servicio_recuperacion.diagnostico(ajustes, bd)
    return renderizar(request, "parciales/_diagnostico.html", {"diagnostico": resultado, "zona": ajustes.zona_horaria})


@router.get("/recuperacion/{bd}/plan", response_class=HTMLResponse)
def plan(
    request: Request,
    bd: str,
    escenario: Annotated[str, Query(min_length=1, max_length=30)],
    objetivo: Texto = None,
    hasta: Annotated[str | None, Query(max_length=19)] = None,
) -> HTMLResponse:
    procedimiento = servicio_recuperacion.plan(
        _ajustes(request), bd, escenario, (objetivo or "").strip() or None, momento_desde_texto(hasta)
    )
    contexto = {"procedimiento": procedimiento, "etiqueta": ETIQUETA_ESCENARIO[procedimiento.escenario]}
    return renderizar(request, "parciales/_procedimiento.html", contexto)
