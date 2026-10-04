from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse

from cloudcr_backup.services import evidencias as servicio_evidencias
from cloudcr_backup.web.rutas.comun import renderizar

router = APIRouter()


@router.get("/evidencias", response_class=HTMLResponse)
def pagina_evidencias(request: Request) -> HTMLResponse:
    catalogo = servicio_evidencias.catalogo()
    return renderizar(request, "evidencias.html", {"seccion": "evidencias", "catalogo": catalogo})


@router.get("/evidencias/archivo/{ruta:path}")
def descargar_evidencia(ruta: str) -> FileResponse:
    archivo = servicio_evidencias.ruta_de_archivo(ruta)
    return FileResponse(archivo, filename=archivo.name, content_disposition_type="attachment")


@router.get("/api/evidencias")
def api_evidencias() -> dict[str, Any]:
    return servicio_evidencias.catalogo().model_dump(mode="json")
