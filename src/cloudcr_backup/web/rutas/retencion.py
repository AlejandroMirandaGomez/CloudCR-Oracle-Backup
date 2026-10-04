from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.services import bases_datos as servicio_bases
from cloudcr_backup.services import retencion as servicio_retencion
from cloudcr_backup.web.formularios import Formulario, marcado
from cloudcr_backup.web.monitoreo import ajustes_de_la_app
from cloudcr_backup.web.rutas.comun import es_htmx, renderizar
from cloudcr_backup.web.seguridad import exigir_origen_confiable

router = APIRouter()

Base = Annotated[str | None, Query(max_length=30)]


def _ajustes(request: Request) -> Ajustes:
    return ajustes_de_la_app(request.app)()


def base_elegida(bd: str | None, bases: list[str]) -> str:
    if bd and bd.strip():
        return bd.strip().upper()
    return bases[0].upper() if len(bases) == 1 else ""


@router.get("/retencion", response_class=HTMLResponse)
def pagina_retencion(request: Request, bd: Base = None, rman: bool = False) -> HTMLResponse:
    ajustes = _ajustes(request)
    bases = servicio_bases.registradas(ajustes)
    elegida = base_elegida(bd, bases)
    informe = servicio_retencion.informe(ajustes, elegida, rman) if elegida else None
    contexto: dict[str, Any] = {
        "seccion": "retencion",
        "bases": bases,
        "bd": elegida,
        "rman": rman,
        "informe": informe,
        "zona": ajustes.zona_horaria,
    }
    plantilla = "parciales/_retencion.html" if es_htmx(request) else "retencion.html"
    return renderizar(request, plantilla, contexto)


@router.post("/retencion/{bd}/{codigo}/purgar", response_model=None, dependencies=[Depends(exigir_origen_confiable)])
def purgar(request: Request, bd: str, codigo: str, campos: Formulario) -> Response:
    resultado = servicio_retencion.purgar(_ajustes(request), bd, codigo, marcado(campos, "confirmar"))
    if not es_htmx(request):
        return RedirectResponse(f"/retencion?bd={resultado.bd}", status_code=303)
    return renderizar(request, "parciales/_purga.html", {"resultado": resultado})
