from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from cloudcr_backup.oracle.connection import ErrorConexionOracle
from cloudcr_backup.oracle.discovery import InstanciaDescubierta
from cloudcr_backup.presentacion.arbol import OpcionesArbol, construir_nodos, perfil_tiene_pdb
from cloudcr_backup.presentacion.resumen import resumir
from cloudcr_backup.web.dependencias import ProveedorExploracion, obtener_servicio
from cloudcr_backup.web.rutas.comun import ErroresExploracion, es_htmx, renderizar, renderizar_error

router = APIRouter()

Servicio = Annotated[ProveedorExploracion, Depends(obtener_servicio)]


def opciones_desde_consulta(
    pdb: Annotated[str | None, Query()] = None,
    sin_seed: Annotated[bool, Query()] = False,
    rutas_completas: Annotated[bool, Query()] = False,
) -> OpcionesArbol:
    return OpcionesArbol(pdb=pdb or None, sin_seed=sin_seed, rutas_completas=rutas_completas)


Opciones = Annotated[OpcionesArbol, Depends(opciones_desde_consulta)]
OracleHome = Annotated[str | None, Query()]
Refrescar = Annotated[bool, Query()]


def homes_conocidos(instancias: list[InstanciaDescubierta]) -> list[str]:
    return sorted({str(i.oracle_home) for i in instancias if i.oracle_home}, key=str.lower)


def validar_oracle_home(oracle_home: str | None, instancias: list[InstanciaDescubierta]) -> Path | None:
    if not oracle_home:
        return None
    permitidos = {h.lower(): h for h in homes_conocidos(instancias)}
    if oracle_home.lower() not in permitidos:
        raise ErrorConexionOracle(
            "Por seguridad, la interfaz web solo acepta un ORACLE_HOME detectado en este equipo.",
            "Para usar otro ORACLE_HOME ejecute 'cloudcr explorar <SID> --oracle-home <ORACLE_HOME>' en la terminal.",
        )
    return Path(permitidos[oracle_home.lower()])


def consulta(opciones: OpcionesArbol, oracle_home: str | None) -> str:
    parametros: dict[str, str] = {}
    if opciones.pdb:
        parametros["pdb"] = opciones.pdb
    if opciones.sin_seed:
        parametros["sin_seed"] = "true"
    if opciones.rutas_completas:
        parametros["rutas_completas"] = "true"
    if oracle_home:
        parametros["oracle_home"] = oracle_home
    return urlencode(parametros)


def contexto_explorador(
    servicio: ProveedorExploracion,
    sid: str,
    opciones: OpcionesArbol,
    oracle_home: str | None,
    refrescar: bool,
) -> dict[str, Any]:
    instancias = servicio.descubrir(refrescar=refrescar)
    exploracion, antiguedad = servicio.explorar(sid, validar_oracle_home(oracle_home, instancias), refrescar)
    aviso_pdb = None
    if opciones.pdb and not perfil_tiene_pdb(exploracion.perfil, opciones.pdb):
        aviso_pdb = f"La instancia no tiene un contenedor llamado {opciones.pdb}; se muestran todos."
        opciones = OpcionesArbol(sin_seed=opciones.sin_seed, rutas_completas=opciones.rutas_completas)
    return {
        "sid": sid.upper(),
        "instancias": instancias,
        "exploracion": exploracion,
        "perfil": exploracion.perfil,
        "hallazgos": exploracion.hallazgos,
        "resumen": resumir(exploracion),
        "raiz": construir_nodos(exploracion, opciones, modo="web"),
        "opciones": opciones,
        "oracle_home": oracle_home or "",
        "consulta": consulta(opciones, oracle_home),
        "antiguedad": int(antiguedad),
        "aviso_pdb": aviso_pdb,
    }


@router.get("/instancias", response_class=HTMLResponse)
def listar(request: Request, servicio: Servicio, refrescar: Refrescar = False) -> HTMLResponse:
    instancias = servicio.descubrir(refrescar=refrescar)
    contexto = {"instancias": instancias, "homes": homes_conocidos(instancias), "sid": None}
    plantilla = "parciales/_tabla_instancias.html" if es_htmx(request) else "instancias.html"
    return renderizar(request, plantilla, contexto)


@router.get("/explorar")
def explorar_manual(sid: Annotated[str, Query(min_length=1)], oracle_home: OracleHome = None) -> RedirectResponse:
    destino = f"/instancias/{sid.strip().upper()}"
    if oracle_home:
        destino += "?" + urlencode({"oracle_home": oracle_home})
    return RedirectResponse(destino, status_code=303)


@router.get("/instancias/{sid}", response_class=HTMLResponse)
def explorador(
    request: Request,
    sid: str,
    servicio: Servicio,
    opciones: Opciones,
    oracle_home: OracleHome = None,
    refrescar: Refrescar = False,
) -> HTMLResponse:
    try:
        contexto = contexto_explorador(servicio, sid, opciones, oracle_home, refrescar)
    except ErroresExploracion as error:
        return renderizar_error(request, error, sid.upper())
    plantilla = "parciales/_contenido.html" if es_htmx(request) else "explorador.html"
    return renderizar(request, plantilla, contexto)


@router.get("/instancias/{sid}/arbol", response_class=HTMLResponse)
def arbol(
    request: Request,
    sid: str,
    servicio: Servicio,
    opciones: Opciones,
    oracle_home: OracleHome = None,
    refrescar: Refrescar = False,
) -> HTMLResponse:
    try:
        contexto = contexto_explorador(servicio, sid, opciones, oracle_home, refrescar)
    except ErroresExploracion as error:
        return renderizar_error(request, error, sid.upper())
    plantilla = "parciales/_zona_arbol.html" if es_htmx(request) else "explorador.html"
    return renderizar(request, plantilla, contexto)
