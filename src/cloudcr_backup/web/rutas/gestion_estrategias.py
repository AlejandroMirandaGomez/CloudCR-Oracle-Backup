from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.domain.enums import (
    Compresion,
    DiaSemana,
    ModoRespaldo,
    PoliticaOmision,
    Prioridad,
    Severidad,
    TipoFrecuencia,
    TipoObjeto,
    TipoRespaldo,
)
from cloudcr_backup.services import bases_datos as servicio_bases
from cloudcr_backup.services import gestion_estrategias as servicio_gestion
from cloudcr_backup.web.formularios import Formulario, marcado, texto
from cloudcr_backup.web.monitoreo import ProveedorMonitoreo, ajustes_de_la_app, obtener_monitoreo
from cloudcr_backup.web.rutas.comun import es_htmx, renderizar
from cloudcr_backup.web.rutas.estrategias_registradas import contexto_detalle, ruta_detalle, tareas_con_borrador
from cloudcr_backup.web.seguridad import exigir_origen_confiable

router = APIRouter()

Monitoreo = Annotated[ProveedorMonitoreo, Depends(obtener_monitoreo)]
OrigenConfiable = [Depends(exigir_origen_confiable)]
Ejemplo = Annotated[str | None, Query(max_length=120)]
Base = Annotated[str | None, Query(max_length=30)]
AgregarTarea = Annotated[bool, Query()]

VALORES_PERMITIDOS = (
    ("prioridad", Prioridad),
    ("estado", None),
    ("alcance → tipo", TipoObjeto),
    ("tipo_respaldo", TipoRespaldo),
    ("modo_respaldo", ModoRespaldo),
    ("compresion", Compresion),
    ("tipo_frecuencia", TipoFrecuencia),
    ("dias_semana", DiaSemana),
    ("politica_omision", PoliticaOmision),
)


def valores_permitidos() -> list[tuple[str, str]]:
    permitidos = []
    for campo, enumeracion in VALORES_PERMITIDOS:
        valores = ["ACTIVA", "INACTIVA"] if enumeracion is None else [e.value for e in enumeracion]
        permitidos.append((campo, ", ".join(valores)))
    return permitidos


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
    contexto = contexto_detalle(
        detalle, monitoreo.zona_horaria, resultado.mensaje, tareas_con_borrador(request, detalle)
    )
    return renderizar(request, "parciales/_estrategia_detalle.html", contexto)


@router.get("/estrategias/{bd}/{codigo}/exportar", response_model=None)
def exportar(request: Request, bd: str, codigo: str) -> Response:
    archivo = servicio_gestion.exportar(_ajustes(request), bd, codigo)
    return Response(
        content=archivo.contenido,
        media_type=archivo.tipo_contenido,
        headers={"Content-Disposition": f'attachment; filename="{archivo.nombre}"'},
    )


def _destino_con_aviso(bd: str, codigo: str, aviso: str) -> str:
    return f"{ruta_detalle(bd, codigo)}?{urlencode({'aviso': aviso})}"


@router.get("/estrategias/{bd}/{codigo}/editar", response_class=HTMLResponse)
def pagina_editar(request: Request, bd: str, codigo: str, agregar_tarea: AgregarTarea = False) -> HTMLResponse:
    borrador = servicio_gestion.contenido_para_editar(_ajustes(request), bd, codigo, agregar_tarea)
    contexto: dict[str, Any] = {
        "seccion": "estrategias",
        "borrador": borrador,
        "ruta": ruta_detalle(borrador.bd, borrador.codigo),
        "valores": valores_permitidos(),
    }
    return renderizar(request, "estrategia_editar.html", contexto)


@router.post("/estrategias/{bd}/{codigo}/editar/validar", response_class=HTMLResponse, dependencies=OrigenConfiable)
def validar_borrador(request: Request, bd: str, codigo: str, campos: Formulario) -> HTMLResponse:
    resultado = servicio_gestion.validar_borrador(_ajustes(request), bd, codigo, campos.get("contenido", ""))
    contexto: dict[str, Any] = {
        "resultado": resultado,
        "ruta": ruta_detalle(resultado.bd, resultado.estrategia),
        "conteos": [(s, resultado.cantidad(s)) for s in Severidad if resultado.cantidad(s)],
        "aplicables": [],
    }
    return renderizar(request, "parciales/_validacion.html", contexto)


@router.post("/estrategias/{bd}/{codigo}/editar", response_model=None, dependencies=OrigenConfiable)
def guardar_edicion(request: Request, bd: str, codigo: str, campos: Formulario) -> Response:
    editada = servicio_gestion.guardar_edicion(_ajustes(request), bd, codigo, campos.get("contenido", ""))
    destino = _destino_con_aviso(editada.bd, editada.codigo, editada.mensaje)
    if es_htmx(request):
        return Response(status_code=204, headers={"HX-Redirect": destino})
    return RedirectResponse(destino, status_code=303)


@router.post("/estrategias/{bd}/{codigo}/tareas/{tarea}/eliminar", response_model=None, dependencies=OrigenConfiable)
def eliminar_tarea(request: Request, bd: str, codigo: str, tarea: str, monitoreo: Monitoreo) -> Response:
    editada = servicio_gestion.eliminar_tarea(_ajustes(request), bd, codigo, tarea)
    if not es_htmx(request):
        return RedirectResponse(_destino_con_aviso(editada.bd, editada.codigo, editada.mensaje), status_code=303)
    detalle = monitoreo.estrategia(editada.bd, editada.codigo, 5)
    contexto = contexto_detalle(detalle, monitoreo.zona_horaria, editada.mensaje, tareas_con_borrador(request, detalle))
    return renderizar(request, "parciales/_estrategia_detalle.html", contexto)
