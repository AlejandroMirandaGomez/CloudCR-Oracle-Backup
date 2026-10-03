from fastapi import FastAPI, Request
from fastapi.responses import Response

from cloudcr_backup.domain.errores import (
    ErrorServicio,
    FiltroInvalido,
    OperacionNoPermitida,
    PipelineNoDisponible,
    RecursoNoEncontrado,
    RepositorioNoDisponible,
)
from cloudcr_backup.web.errores_api import PREFIJO_API, ErrorApi, manejar_error_api
from cloudcr_backup.web.rutas.comun import es_htmx, renderizar

ESTADO_POR_ERROR: tuple[tuple[type[ErrorServicio], int], ...] = (
    (RepositorioNoDisponible, 503),
    (PipelineNoDisponible, 503),
    (RecursoNoEncontrado, 404),
    (FiltroInvalido, 422),
    (OperacionNoPermitida, 409),
)

TITULO_POR_ESTADO = {
    503: "El repositorio no está disponible",
    404: "No se encontró lo que buscaba",
    409: "No se pudo completar la acción",
    422: "Revise los filtros",
}


def estado_de(error: ErrorServicio) -> int:
    return next((estado for tipo, estado in ESTADO_POR_ERROR if isinstance(error, tipo)), 500)


async def manejar_error_servicio(request: Request, error: Exception) -> Response:
    assert isinstance(error, ErrorServicio)
    estado = estado_de(error)
    if request.url.path.startswith(PREFIJO_API):
        return await manejar_error_api(request, ErrorApi(estado, error.mensaje, sugerencia=error.sugerencia))
    contexto = {
        "titulo": TITULO_POR_ESTADO.get(estado, "Ocurrió un problema"),
        "mensaje": error.mensaje,
        "sugerencia": error.sugerencia,
        "estado": estado,
    }
    if es_htmx(request):
        return renderizar(request, "parciales/_error_servicio.html", contexto)
    return renderizar(request, "error_servicio.html", contexto, estado)


def registrar_manejador_servicio(app: FastAPI) -> None:
    app.add_exception_handler(ErrorServicio, manejar_error_servicio)
