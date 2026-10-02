from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from cloudcr_backup.services import destinos
from cloudcr_backup.services.destinos import ErrorDestino
from cloudcr_backup.web.errores_api import ErrorApi
from cloudcr_backup.web.seguridad import exigir_origen_confiable

router = APIRouter(prefix="/api/carpetas")

ESTADO_POR_TIPO = {"invalido": 422, "no_existe": 404, "existe": 409, "sin_permiso": 403}


class NuevaCarpeta(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    padre: str
    nombre: str


def _a_error_api(error: ErrorDestino, campo: str) -> ErrorApi:
    return ErrorApi(ESTADO_POR_TIPO.get(error.tipo, 422), str(error), campo)


@router.get("")
def listar(ruta: Annotated[str | None, Query()] = None, cercana: Annotated[bool, Query()] = False) -> dict[str, Any]:
    try:
        listado = destinos.listar_carpetas(ruta, cercana)
    except ErrorDestino as error:
        raise _a_error_api(error, "ruta") from error
    return asdict(listado)


@router.post("", status_code=201, dependencies=[Depends(exigir_origen_confiable)])
def crear(datos: NuevaCarpeta) -> dict[str, Any]:
    try:
        carpeta = destinos.crear_carpeta(datos.padre, datos.nombre)
    except ErrorDestino as error:
        raise _a_error_api(error, "nombre") from error
    return asdict(carpeta)
