from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.domain.enums import Severidad
from cloudcr_backup.services import bases_datos as servicio_bases
from cloudcr_backup.services import gestion_estrategias as servicio_gestion
from cloudcr_backup.web.formularios import Formulario, marcado, texto
from cloudcr_backup.web.monitoreo import ProveedorMonitoreo, ajustes_de_la_app, obtener_monitoreo
from cloudcr_backup.web.rutas.comun import es_htmx, renderizar
from cloudcr_backup.web.rutas.estrategias_registradas import contexto_detalle, ruta_detalle
from cloudcr_backup.web.seguridad import exigir_origen_confiable

router = APIRouter()

Monitoreo = Annotated[ProveedorMonitoreo, Depends(obtener_monitoreo)]
OrigenConfiable = [Depends(exigir_origen_confiable)]
Ejemplo = Annotated[str | None, Query(max_length=120)]
Base = Annotated[str | None, Query(max_length=30)]


def _ajustes(request: Request) -> Ajustes:
    return ajustes_de_la_app(request.app)()


@router.get("/estrategias/importar", response_class=HTMLResponse)
def pagina_importar(request: Request, ejemplo: Ejemplo = None, bd: Base = None) -> HTMLResponse:
    contenido = servicio_gestion.contenido_ejemplo(ejemplo) if ejemplo else ""
    if es_htmx(request):
        return renderizar(request, "parciales/_importar_contenido.html", {"contenido": contenido})
    contexto = {
        "seccion": "estrategias",
        "bases": servicio_bases.registradas(_ajustes(request)),
        "bd": (bd or "").upper(),
        "ejemplos": servicio_gestion.ejemplos(),
        "ejemplo": ejemplo or "",
        "contenido": contenido,
    }
    return renderizar(request, "estrategia_importar.html", contexto)


@router.post("/estrategias/importar", response_model=None, dependencies=OrigenConfiable)
def importar(request: Request, campos: Formulario) -> Response:
    contenido = campos.get("contenido", "")
    ejemplo = texto(campos, "ejemplo")
    if not contenido.strip() and ejemplo:
        contenido = servicio_gestion.contenido_ejemplo(ejemplo)
    importada = servicio_gestion.importar(
        _ajustes(request), texto(campos, "bd"), contenido, marcado(campos, "reemplazar")
    )
    ruta = ruta_detalle(importada.bd, importada.codigo)
    if not es_htmx(request):
        return RedirectResponse(ruta, status_code=303)
    return renderizar(request, "parciales/_importacion.html", {"importada": importada, "ruta": ruta})


@router.get("/estrategias/{bd}/{codigo}/validar", response_class=HTMLResponse)
def validar(request: Request, bd: str, codigo: str) -> HTMLResponse:
    resultado = servicio_gestion.validar(_ajustes(request), bd, codigo)
    contexto: dict[str, Any] = {
        "resultado": resultado,
        "ruta": ruta_detalle(resultado.bd, resultado.estrategia),
        "conteos": [(s, resultado.cantidad(s)) for s in Severidad if resultado.cantidad(s)],
        "aplicables": [c for c in servicio_gestion.RECOMENDACIONES_APLICABLES if resultado.tiene(c)],
    }
    return renderizar(request, "parciales/_validacion.html", contexto)


@router.post(
    "/estrategias/{bd}/{codigo}/recomendaciones/{recomendacion}/aplicar",
    response_model=None,
    dependencies=OrigenConfiable,
)
def aplicar_recomendacion(request: Request, bd: str, codigo: str, recomendacion: str, monitoreo: Monitoreo) -> Response:
    resultado = servicio_gestion.aplicar_recomendacion(_ajustes(request), bd, codigo, recomendacion)
    if not es_htmx(request):
        return RedirectResponse(ruta_detalle(resultado.bd, resultado.estrategia), status_code=303)
    detalle = monitoreo.estrategia(resultado.bd, resultado.estrategia, 5)
    contexto = contexto_detalle(detalle, monitoreo.zona_horaria, resultado.mensaje)
    return renderizar(request, "parciales/_estrategia_detalle.html", contexto)


@router.get("/estrategias/{bd}/{codigo}/exportar", response_model=None)
def exportar(request: Request, bd: str, codigo: str) -> Response:
    archivo = servicio_gestion.exportar(_ajustes(request), bd, codigo)
    return Response(
        content=archivo.contenido,
        media_type=archivo.tipo_contenido,
        headers={"Content-Disposition": f'attachment; filename="{archivo.nombre}"'},
    )
