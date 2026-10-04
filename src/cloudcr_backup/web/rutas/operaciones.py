import getpass
import logging
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.domain.errores import FiltroInvalido
from cloudcr_backup.services import ejecucion, recuperacion, retencion, scripts
from cloudcr_backup.web.monitoreo import ajustes_de_la_app
from cloudcr_backup.web.seguridad import exigir_origen_confiable

REGISTRO = logging.getLogger("cloudcr.web.operaciones")
FORMATOS_HASTA = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M")

router = APIRouter(prefix="/api")

OrigenConfiable = [Depends(exigir_origen_confiable)]


class SolicitudAprobacion(BaseModel):
    acepto_caida: bool = False
    aprobado_por: str | None = Field(default=None, max_length=100)
    version: int | None = Field(default=None, ge=1)


class SolicitudRechazo(BaseModel):
    motivo: str = Field(min_length=1, max_length=1000)
    version: int | None = Field(default=None, ge=1)


class SolicitudEjecucion(BaseModel):
    bd: str | None = Field(default=None, max_length=30)
    estrategia: str = Field(min_length=1, max_length=20)
    tarea: str = Field(min_length=1, max_length=10)


class SolicitudPurga(BaseModel):
    confirmar: bool = False


def _ajustes(request: Request) -> Ajustes:
    return ajustes_de_la_app(request.app)()


def _quien(solicitado: str | None) -> str:
    return solicitado.strip() if solicitado and solicitado.strip() else f"{getpass.getuser()} (web)"


def _hasta(texto: str | None) -> datetime | None:
    if not texto:
        return None
    for formato in FORMATOS_HASTA:
        try:
            return datetime.strptime(texto, formato)
        except ValueError:
            continue
    raise FiltroInvalido(f"'{texto}' no es una fecha válida.", "Use 'AAAA-MM-DD HH:MM'.")


def _en_segundo_plano(nombre: str, funcion: Any, *argumentos: Any) -> None:
    try:
        funcion(*argumentos)
    except Exception:
        REGISTRO.exception("La operación %s lanzada desde la web falló", nombre)


@router.get("/scripts/{bd}/{codigo}")
def api_listar_scripts(request: Request, bd: str, codigo: str) -> list[dict[str, Any]]:
    return [v.model_dump(mode="json") for v in scripts.listar(_ajustes(request), bd, codigo)]


@router.get("/scripts/{bd}/{codigo}/{tarea}")
def api_ver_script(
    request: Request, bd: str, codigo: str, tarea: str, version: Annotated[int | None, Query(ge=1)] = None
) -> dict[str, Any]:
    return scripts.ver(_ajustes(request), bd, codigo, tarea, version).model_dump(mode="json")


@router.post("/scripts/{bd}/{codigo}/generar", dependencies=OrigenConfiable)
def api_generar_script(
    request: Request, bd: str, codigo: str, tarea: Annotated[str | None, Query(max_length=10)] = None
) -> list[dict[str, Any]]:
    return [v.model_dump(mode="json") for v in scripts.generar(_ajustes(request), bd, codigo, tarea)]


@router.post("/scripts/{bd}/{codigo}/{tarea}/aprobar", dependencies=OrigenConfiable)
def api_aprobar_script(
    request: Request, bd: str, codigo: str, tarea: str, solicitud: SolicitudAprobacion
) -> dict[str, Any]:
    vista = scripts.aprobar(
        _ajustes(request),
        bd,
        codigo,
        tarea,
        _quien(solicitud.aprobado_por),
        solicitud.acepto_caida,
        solicitud.version,
    )
    return vista.model_dump(mode="json")


@router.post("/scripts/{bd}/{codigo}/{tarea}/rechazar", dependencies=OrigenConfiable)
def api_rechazar_script(
    request: Request, bd: str, codigo: str, tarea: str, solicitud: SolicitudRechazo
) -> dict[str, Any]:
    vista = scripts.rechazar(_ajustes(request), bd, codigo, tarea, solicitud.motivo, solicitud.version)
    return vista.model_dump(mode="json")


@router.get("/ejecuciones/simular/{bd}/{codigo}/{tarea}")
def api_simular(request: Request, bd: str, codigo: str, tarea: str) -> dict[str, Any]:
    return ejecucion.simular(_ajustes(request), bd, codigo, tarea).model_dump(mode="json")


@router.post("/ejecuciones", dependencies=OrigenConfiable)
def api_ejecutar(request: Request, solicitud: SolicitudEjecucion, tareas: BackgroundTasks) -> JSONResponse:
    configuracion = _ajustes(request)
    ejecucion_id = ejecucion.programar_ahora(configuracion, solicitud.bd, solicitud.estrategia, solicitud.tarea)
    tareas.add_task(_en_segundo_plano, "ejecutar", ejecucion.ejecutar, configuracion, ejecucion_id)
    return JSONResponse(
        {"ejecucion_id": ejecucion_id, "estado": "PROGRAMADA", "detalle": f"/api/historial/{ejecucion_id}"},
        status_code=202,
    )


@router.post("/ejecuciones/{ejecucion_id}/verificar", dependencies=OrigenConfiable)
def api_verificar(request: Request, ejecucion_id: int, tareas: BackgroundTasks) -> JSONResponse:
    configuracion = _ajustes(request)
    tareas.add_task(_en_segundo_plano, "verificar", ejecucion.verificar, configuracion, ejecucion_id)
    return JSONResponse({"ejecucion_id": ejecucion_id, "detalle": f"/api/historial/{ejecucion_id}"}, status_code=202)


@router.get("/retencion/{bd}")
def api_retencion(request: Request, bd: str, rman: bool = False) -> dict[str, Any]:
    return retencion.informe(_ajustes(request), bd, rman).model_dump(mode="json")


@router.post("/retencion/{bd}/{codigo}/purgar", dependencies=OrigenConfiable)
def api_purgar(request: Request, bd: str, codigo: str, solicitud: SolicitudPurga) -> dict[str, Any]:
    return retencion.purgar(_ajustes(request), bd, codigo, solicitud.confirmar).model_dump(mode="json")


@router.get("/recuperacion/{bd}/puntos")
def api_puntos(request: Request, bd: str) -> dict[str, Any]:
    return recuperacion.puntos(_ajustes(request), bd).model_dump(mode="json")


@router.get("/recuperacion/{bd}/diagnostico")
def api_diagnostico(request: Request, bd: str) -> dict[str, Any]:
    return recuperacion.diagnostico(_ajustes(request), bd).model_dump(mode="json")


@router.get("/recuperacion/{bd}/plan/{escenario}")
def api_plan(
    request: Request,
    bd: str,
    escenario: str,
    objetivo: Annotated[str | None, Query(max_length=130)] = None,
    hasta: Annotated[str | None, Query(max_length=19)] = None,
) -> dict[str, Any]:
    return recuperacion.plan(_ajustes(request), bd, escenario, objetivo, _hasta(hasta)).model_dump(mode="json")
