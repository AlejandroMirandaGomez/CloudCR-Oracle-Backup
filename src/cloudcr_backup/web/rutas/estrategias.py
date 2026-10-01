from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse

from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.domain.hallazgos import Hallazgo
from cloudcr_backup.oracle.explorador import Exploracion, InstanciaNoEncontrada
from cloudcr_backup.presentacion.arbol import OpcionesArbol, construir_nodos
from cloudcr_backup.presentacion.formato import ETIQUETA_SEVERIDAD
from cloudcr_backup.presentacion.seleccion import opciones_de_alcance
from cloudcr_backup.services import almacen_estrategias, creacion_estrategia
from cloudcr_backup.services.catalogo_estrategia import construir_catalogo
from cloudcr_backup.services.creacion_estrategia import ErrorCreacion, ResultadoValidacion
from cloudcr_backup.services.solicitud_estrategia import SolicitudEstrategia
from cloudcr_backup.strategy.prioridad import criterio_de
from cloudcr_backup.strategy.yaml_io import estrategia_a_yaml
from cloudcr_backup.web.dependencias import ProveedorExploracion, obtener_ajustes, obtener_servicio
from cloudcr_backup.web.errores_api import ErrorApi
from cloudcr_backup.web.rutas.comun import ErroresExploracion, renderizar, renderizar_error
from cloudcr_backup.web.rutas.instancias import OracleHome, validar_oracle_home
from cloudcr_backup.web.seguridad import exigir_origen_confiable

router = APIRouter()

Servicio = Annotated[ProveedorExploracion, Depends(obtener_servicio)]
AjustesWeb = Annotated[Ajustes, Depends(obtener_ajustes)]
Refrescar = Annotated[bool, Query()]

ESTADO_POR_TIPO_CREACION = {"bloqueada": 422, "caida_no_aceptada": 422, "duplicada": 409}


def _explorar(
    servicio: ProveedorExploracion, sid: str, oracle_home: str | None, refrescar: bool = False
) -> Exploracion:
    instancias = servicio.descubrir(refrescar=refrescar)
    exploracion, _ = servicio.explorar(sid, validar_oracle_home(oracle_home, instancias), refrescar)
    return exploracion


def _explorar_para_api(servicio: ProveedorExploracion, sid: str, oracle_home: str | None) -> Exploracion:
    try:
        return _explorar(servicio, sid, oracle_home)
    except InstanciaNoEncontrada as error:
        raise ErrorApi(404, str(error), "sid") from error
    except ErroresExploracion as error:
        raise ErrorApi(502, str(error), "sid", getattr(error, "sugerencia", None)) from error


def _hallazgo_a_json(hallazgo: Hallazgo) -> dict[str, Any]:
    return {
        "codigo": hallazgo.codigo,
        "severidad": hallazgo.severidad.value,
        "etiqueta_severidad": ETIQUETA_SEVERIDAD[hallazgo.severidad],
        "mensaje": hallazgo.mensaje,
        "sujeto": hallazgo.sujeto,
        "accion_sugerida": hallazgo.accion_sugerida,
    }


def _resumen_de(hallazgos: list[Hallazgo]) -> dict[str, int]:
    resumen: dict[str, int] = {}
    for hallazgo in hallazgos:
        resumen[hallazgo.severidad.value] = resumen.get(hallazgo.severidad.value, 0) + 1
    return resumen


def _respuesta_validacion(resultado: ResultadoValidacion) -> dict[str, Any]:
    estrategia = resultado.estrategia
    criterio = criterio_de(estrategia.prioridad)
    return {
        "bloqueante": resultado.bloqueante,
        "requiere_aceptar_caida": resultado.requiere_aceptar_caida,
        "hallazgos": [_hallazgo_a_json(h) for h in resultado.hallazgos],
        "resumen": _resumen_de(resultado.hallazgos),
        "criterio": {"rpo_horas": criterio.rpo_horas, "rto_horas": criterio.rto_horas},
        "yaml": estrategia_a_yaml(estrategia),
        "estrategia": estrategia.model_dump(mode="json", exclude_none=True),
    }


@router.get("/instancias/{sid}/estrategias/nueva", response_class=HTMLResponse)
def pagina_nueva(
    request: Request,
    sid: str,
    servicio: Servicio,
    ajustes: AjustesWeb,
    oracle_home: OracleHome = None,
    refrescar: Refrescar = False,
) -> HTMLResponse:
    try:
        exploracion = _explorar(servicio, sid, oracle_home, refrescar)
    except ErroresExploracion as error:
        return renderizar_error(request, error, sid.upper())
    perfil = exploracion.perfil
    existentes = almacen_estrategias.codigos_existentes(ajustes, sid, perfil.nombre)
    contexto = {
        "sid": sid.upper(),
        "perfil": perfil,
        "oracle_home": oracle_home or "",
        "raiz": construir_nodos(exploracion, OpcionesArbol(sin_seed=True), modo="web"),
        "seleccion": opciones_de_alcance(perfil),
        "catalogo": construir_catalogo(perfil, existentes, ajustes, sid),
        "hallazgos_instancia": exploracion.hallazgos,
    }
    return renderizar(request, "estrategia_nueva.html", contexto)


@router.get("/api/instancias/{sid}/estrategias/catalogo")
def catalogo(sid: str, servicio: Servicio, ajustes: AjustesWeb, oracle_home: OracleHome = None) -> dict[str, Any]:
    perfil = _explorar_para_api(servicio, sid, oracle_home).perfil
    existentes = almacen_estrategias.codigos_existentes(ajustes, sid, perfil.nombre)
    return construir_catalogo(perfil, existentes, ajustes, sid)


@router.post("/api/instancias/{sid}/estrategias/validar", dependencies=[Depends(exigir_origen_confiable)])
def validar(
    sid: str,
    solicitud: SolicitudEstrategia,
    servicio: Servicio,
    ajustes: AjustesWeb,
    oracle_home: OracleHome = None,
) -> dict[str, Any]:
    perfil = _explorar_para_api(servicio, sid, oracle_home).perfil
    resultado = creacion_estrategia.validar(solicitud, perfil, ajustes, sid)
    return _respuesta_validacion(resultado)


@router.post("/api/instancias/{sid}/estrategias", status_code=201, dependencies=[Depends(exigir_origen_confiable)])
def crear(
    sid: str,
    solicitud: SolicitudEstrategia,
    servicio: Servicio,
    ajustes: AjustesWeb,
    oracle_home: OracleHome = None,
) -> dict[str, Any]:
    perfil = _explorar_para_api(servicio, sid, oracle_home).perfil
    try:
        resultado = creacion_estrategia.guardar(solicitud, perfil, ajustes, sid)
    except ErrorCreacion as error:
        raise ErrorApi(
            ESTADO_POR_TIPO_CREACION.get(error.tipo, 422),
            str(error),
            error.tipo,
            extra={"hallazgos": [_hallazgo_a_json(h) for h in error.hallazgos]},
        ) from error
    return {
        "codigo": resultado.estrategia.codigo,
        "nombre": resultado.estrategia.nombre,
        "estado": resultado.estrategia.estado.value,
        "version": resultado.estrategia.version,
        "archivo": str(resultado.archivo),
        "repositorio": {"estado": resultado.repositorio.estado, "mensaje": resultado.repositorio.mensaje},
        "hallazgos": [_hallazgo_a_json(h) for h in resultado.hallazgos],
        "yaml": estrategia_a_yaml(resultado.estrategia),
    }
