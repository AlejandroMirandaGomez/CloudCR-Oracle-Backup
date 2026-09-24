from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse

from cloudcr_backup import __version__
from cloudcr_backup.web.dependencias import ProveedorExploracion, obtener_servicio

router = APIRouter()


@router.get("/")
def inicio(servicio: Annotated[ProveedorExploracion, Depends(obtener_servicio)]) -> RedirectResponse:
    en_ejecucion = [i for i in servicio.descubrir() if i.en_ejecucion]
    if len(en_ejecucion) == 1:
        return RedirectResponse(f"/instancias/{en_ejecucion[0].sid}", status_code=303)
    return RedirectResponse("/instancias", status_code=303)


@router.get("/salud")
def salud() -> dict[str, str]:
    return {"estado": "ok", "version": __version__}
