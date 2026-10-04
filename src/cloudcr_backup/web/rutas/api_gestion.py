from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.services import administracion as servicio_administracion
from cloudcr_backup.services import bases_datos as servicio_bases
from cloudcr_backup.services import gestion_estrategias as servicio_gestion
from cloudcr_backup.services.control_agente import ControlAgente
from cloudcr_backup.web.monitoreo import ajustes_de_la_app
from cloudcr_backup.web.rutas.sistema import obtener_control_agente
from cloudcr_backup.web.seguridad import exigir_origen_confiable

router = APIRouter(prefix="/api")

OrigenConfiable = [Depends(exigir_origen_confiable)]
Control = Annotated[ControlAgente, Depends(obtener_control_agente)]
SEGUNDOS_ESPERA_DETENCION = 2.0


class SolicitudImportacion(BaseModel):
    bd: str = Field(min_length=1, max_length=30)
    contenido: str = Field(min_length=1, max_length=servicio_gestion.LARGO_MAXIMO_YAML)
    reemplazar: bool = False


class SolicitudEdicion(BaseModel):
    contenido: str = Field(min_length=1, max_length=servicio_gestion.LARGO_MAXIMO_YAML)


class SolicitudParametro(BaseModel):
    valor: str = Field(max_length=servicio_administracion.LARGO_MAXIMO_VALOR)


class SolicitudRegistro(BaseModel):
    sid: str = Field(min_length=1, max_length=64)
    ambiente: str = Field(default="PRUEBAS", max_length=20)


class SolicitudAgente(BaseModel):
    simulado: bool = False


def _ajustes(request: Request) -> Ajustes:
    return ajustes_de_la_app(request.app)()


@router.get("/estrategias/{bd}/{codigo}/validar")
def api_validar(request: Request, bd: str, codigo: str) -> dict[str, Any]:
    resultado = servicio_gestion.validar(_ajustes(request), bd, codigo)
    return {**resultado.model_dump(mode="json"), "bloqueante": resultado.bloqueante}


@router.post("/estrategias/{bd}/{codigo}/recomendaciones/{recomendacion}/aplicar", dependencies=OrigenConfiable)
def api_aplicar_recomendacion(request: Request, bd: str, codigo: str, recomendacion: str) -> dict[str, Any]:
    return servicio_gestion.aplicar_recomendacion(_ajustes(request), bd, codigo, recomendacion).model_dump(mode="json")


@router.post("/estrategias/{bd}/{codigo}/editar/validar", dependencies=OrigenConfiable)
def api_validar_borrador(request: Request, bd: str, codigo: str, solicitud: SolicitudEdicion) -> dict[str, Any]:
    resultado = servicio_gestion.validar_borrador(_ajustes(request), bd, codigo, solicitud.contenido)
    return {**resultado.model_dump(mode="json"), "bloqueante": resultado.bloqueante}


@router.put("/estrategias/{bd}/{codigo}", dependencies=OrigenConfiable)
def api_guardar_edicion(request: Request, bd: str, codigo: str, solicitud: SolicitudEdicion) -> dict[str, Any]:
    editada = servicio_gestion.guardar_edicion(_ajustes(request), bd, codigo, solicitud.contenido)
    return {**editada.model_dump(mode="json"), "mensaje": editada.mensaje}


@router.delete("/estrategias/{bd}/{codigo}/tareas/{tarea}", dependencies=OrigenConfiable)
def api_eliminar_tarea(request: Request, bd: str, codigo: str, tarea: str) -> dict[str, Any]:
    editada = servicio_gestion.eliminar_tarea(_ajustes(request), bd, codigo, tarea)
    return {**editada.model_dump(mode="json"), "mensaje": editada.mensaje}


@router.get("/estrategias/{bd}/{codigo}/yaml")
def api_exportar(request: Request, bd: str, codigo: str) -> dict[str, Any]:
    archivo = servicio_gestion.exportar(_ajustes(request), bd, codigo)
    return {"nombre": archivo.nombre, "contenido": archivo.contenido.decode("utf-8")}


@router.post("/estrategias/importar", status_code=201, dependencies=OrigenConfiable)
def api_importar(request: Request, solicitud: SolicitudImportacion) -> dict[str, Any]:
    importada = servicio_gestion.importar(_ajustes(request), solicitud.bd, solicitud.contenido, solicitud.reemplazar)
    return importada.model_dump(mode="json")


@router.get("/estrategias/ejemplos")
def api_ejemplos() -> list[dict[str, Any]]:
    return [e.model_dump(mode="json") for e in servicio_gestion.ejemplos()]


@router.get("/sistema/entorno")
def api_entorno(request: Request) -> list[dict[str, Any]]:
    return [c.model_dump(mode="json") for c in servicio_administracion.comprobar_entorno(_ajustes(request))]


@router.get("/sistema/repositorio")
def api_repositorio(request: Request) -> dict[str, Any]:
    return servicio_administracion.estado_repositorio(_ajustes(request)).model_dump(mode="json")


@router.get("/sistema/parametros")
def api_parametros(request: Request) -> list[dict[str, Any]]:
    return [p.model_dump(mode="json") for p in servicio_administracion.parametros(_ajustes(request))]


@router.put("/sistema/parametros/{clave}", dependencies=OrigenConfiable)
def api_asignar_parametro(request: Request, clave: str, solicitud: SolicitudParametro) -> dict[str, Any]:
    return servicio_administracion.asignar_parametro(_ajustes(request), clave, solicitud.valor).model_dump(mode="json")


@router.post("/sistema/parametros/{clave}/restablecer", dependencies=OrigenConfiable)
def api_restablecer_parametro(request: Request, clave: str) -> dict[str, Any]:
    return servicio_administracion.restablecer_parametro(_ajustes(request), clave).model_dump(mode="json")


@router.get("/sistema/bases")
def api_bases(request: Request) -> list[dict[str, Any]]:
    return [b.model_dump(mode="json") for b in servicio_bases.listar(_ajustes(request))]


@router.post("/sistema/bases", status_code=201, dependencies=OrigenConfiable)
def api_registrar_base(request: Request, solicitud: SolicitudRegistro) -> dict[str, Any]:
    return servicio_bases.registrar(_ajustes(request), solicitud.sid, solicitud.ambiente).model_dump(mode="json")


@router.post("/sistema/bases/{nombre}/inspeccionar", dependencies=OrigenConfiable)
def api_inspeccionar_base(request: Request, nombre: str) -> dict[str, Any]:
    return servicio_bases.inspeccionar(_ajustes(request), nombre).model_dump(mode="json")


@router.get("/sistema/agente")
def api_control_agente(control: Control) -> dict[str, Any]:
    return control.estado().model_dump(mode="json")


@router.post("/sistema/agente/iniciar", dependencies=OrigenConfiable)
def api_iniciar_agente(control: Control, solicitud: SolicitudAgente) -> dict[str, Any]:
    return control.iniciar(solicitud.simulado).model_dump(mode="json")


@router.post("/sistema/agente/ciclo", dependencies=OrigenConfiable)
def api_ciclo_agente(control: Control, solicitud: SolicitudAgente) -> dict[str, Any]:
    return control.un_ciclo(solicitud.simulado).model_dump(mode="json")


@router.post("/sistema/agente/detener", dependencies=OrigenConfiable)
def api_detener_agente(control: Control) -> dict[str, Any]:
    return control.detener(SEGUNDOS_ESPERA_DETENCION).model_dump(mode="json")
