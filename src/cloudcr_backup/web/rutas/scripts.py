import getpass
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.domain.errores import ErrorServicio, RecursoNoEncontrado
from cloudcr_backup.domain.monitoreo import DetalleEstrategia, TareaDetalle
from cloudcr_backup.domain.scripts import VistaScript
from cloudcr_backup.services import ejecucion as servicio_ejecucion
from cloudcr_backup.services import scripts as servicio_scripts
from cloudcr_backup.web.formularios import Formulario, entero, marcado, texto
from cloudcr_backup.web.monitoreo import ProveedorMonitoreo, ajustes_de_la_app, obtener_monitoreo
from cloudcr_backup.web.rutas.comun import es_htmx, renderizar
from cloudcr_backup.web.rutas.estrategias_registradas import ruta_detalle
from cloudcr_backup.web.segundo_plano import ejecutar_registrando
from cloudcr_backup.web.seguridad import exigir_origen_confiable

router = APIRouter()

Monitoreo = Annotated[ProveedorMonitoreo, Depends(obtener_monitoreo)]
Version = Annotated[int | None, Query(ge=1)]
OrigenConfiable = [Depends(exigir_origen_confiable)]


def ruta_script(bd: str, codigo: str, tarea: str) -> str:
    return f"{ruta_detalle(bd, codigo)}/scripts/{quote(tarea, safe='')}"


def _ajustes(request: Request) -> Ajustes:
    return ajustes_de_la_app(request.app)()


def quien_aprueba(solicitado: str) -> str:
    return solicitado if solicitado else f"{getpass.getuser()} (web)"


def _tarea(detalle: DetalleEstrategia, tarea: str) -> TareaDetalle:
    elegida = next((t for t in detalle.tareas if t.codigo.upper() == tarea.strip().upper()), None)
    if elegida is None:
        raise RecursoNoEncontrado(
            f"No existe la tarea {tarea.upper()} en la estrategia {detalle.resumen.codigo}.",
            "Vuelva al detalle de la estrategia y elija una de sus tareas.",
        )
    return elegida


def _vista_o_nada(ajustes: Ajustes, bd: str, codigo: str, tarea: str, version: int | None) -> VistaScript | None:
    try:
        return servicio_scripts.ver(ajustes, bd, codigo, tarea, version)
    except RecursoNoEncontrado:
        if version is not None:
            raise
        return None


def _contexto(
    request: Request,
    monitoreo: ProveedorMonitoreo,
    bd: str,
    codigo: str,
    tarea: str,
    vista: VistaScript | None,
    aviso: str | None = None,
    error: ErrorServicio | None = None,
) -> dict[str, Any]:
    detalle = monitoreo.estrategia(bd, codigo, 5)
    elegida = _tarea(detalle, tarea)
    ajustes = _ajustes(request)
    versiones: list[VistaScript] = []
    if vista is not None:
        versiones = [v for v in servicio_scripts.listar(ajustes, bd, codigo) if v.tarea == elegida.codigo]
    return {
        "seccion": "estrategias",
        "detalle": detalle,
        "resumen": detalle.resumen,
        "tarea": elegida,
        "vista": vista,
        "versiones": sorted(versiones, key=lambda v: v.version, reverse=True),
        "zona": elegida.programacion.zona_horaria,
        "ruta": ruta_script(detalle.resumen.bd, detalle.resumen.codigo, elegida.codigo),
        "ruta_estrategia": ruta_detalle(detalle.resumen.bd, detalle.resumen.codigo),
        "aviso": aviso,
        "error": error,
    }


def _panel(
    request: Request,
    monitoreo: ProveedorMonitoreo,
    bd: str,
    codigo: str,
    tarea: str,
    vista: VistaScript | None,
    aviso: str | None = None,
    error: ErrorServicio | None = None,
) -> Response:
    contexto = _contexto(request, monitoreo, bd, codigo, tarea, vista, aviso, error)
    if es_htmx(request):
        return renderizar(request, "parciales/_script.html", contexto)
    if error is not None:
        return renderizar(request, "script.html", contexto, 409)
    destino = contexto["ruta"]
    if vista is not None:
        destino += f"?version={vista.version}"
    return RedirectResponse(destino, status_code=303)


@router.get("/estrategias/{bd}/{codigo}/scripts/{tarea}", response_class=HTMLResponse)
def pagina_script(
    request: Request, bd: str, codigo: str, tarea: str, monitoreo: Monitoreo, version: Version = None
) -> HTMLResponse:
    vista = _vista_o_nada(_ajustes(request), bd, codigo, tarea, version)
    contexto = _contexto(request, monitoreo, bd, codigo, tarea, vista)
    plantilla = "parciales/_script.html" if es_htmx(request) else "script.html"
    return renderizar(request, plantilla, contexto)


@router.post("/estrategias/{bd}/{codigo}/generar-scripts", response_model=None, dependencies=OrigenConfiable)
def generar_scripts(request: Request, bd: str, codigo: str, campos: Formulario) -> Response:
    tarea = texto(campos, "tarea") or None
    vistas = servicio_scripts.generar(_ajustes(request), bd, codigo, tarea)
    if not es_htmx(request):
        primera = vistas[0]
        return RedirectResponse(ruta_script(primera.bd, primera.estrategia, primera.tarea), status_code=303)
    filas = [(v, ruta_script(v.bd, v.estrategia, v.tarea)) for v in vistas]
    return renderizar(request, "parciales/_scripts_generados.html", {"filas": filas})


@router.post(
    "/estrategias/{bd}/{codigo}/scripts/{tarea}/generar", response_model=None, dependencies=OrigenConfiable
)
def regenerar(request: Request, bd: str, codigo: str, tarea: str, monitoreo: Monitoreo) -> Response:
    ajustes = _ajustes(request)
    try:
        vista = servicio_scripts.generar(ajustes, bd, codigo, tarea)[0]
    except ErrorServicio as error:
        actual = _vista_o_nada(ajustes, bd, codigo, tarea, None)
        return _panel(request, monitoreo, bd, codigo, tarea, actual, None, error)
    aviso = f"Se generó la versión {vista.version}." if vista.nueva else "El script no cambió: se conserva la versión."
    return _panel(request, monitoreo, bd, codigo, tarea, vista, aviso)


@router.post(
    "/estrategias/{bd}/{codigo}/scripts/{tarea}/aprobar", response_model=None, dependencies=OrigenConfiable
)
def aprobar(request: Request, bd: str, codigo: str, tarea: str, monitoreo: Monitoreo, campos: Formulario) -> Response:
    ajustes = _ajustes(request)
    version = entero(campos, "version")
    try:
        vista = servicio_scripts.aprobar(
            ajustes,
            bd,
            codigo,
            tarea,
            quien_aprueba(texto(campos, "aprobado_por")),
            marcado(campos, "acepto_caida"),
            version,
        )
    except ErrorServicio as error:
        actual = _vista_o_nada(ajustes, bd, codigo, tarea, version)
        return _panel(request, monitoreo, bd, codigo, tarea, actual, None, error)
    aviso = f"Script versión {vista.version} aprobado por {vista.aprobado_por}. El agente ya puede ejecutarlo."
    return _panel(request, monitoreo, bd, codigo, tarea, vista, aviso)


@router.post(
    "/estrategias/{bd}/{codigo}/scripts/{tarea}/rechazar", response_model=None, dependencies=OrigenConfiable
)
def rechazar(request: Request, bd: str, codigo: str, tarea: str, monitoreo: Monitoreo, campos: Formulario) -> Response:
    ajustes = _ajustes(request)
    version = entero(campos, "version")
    try:
        vista = servicio_scripts.rechazar(ajustes, bd, codigo, tarea, texto(campos, "motivo"), version)
    except ErrorServicio as error:
        actual = _vista_o_nada(ajustes, bd, codigo, tarea, version)
        return _panel(request, monitoreo, bd, codigo, tarea, actual, None, error)
    return _panel(request, monitoreo, bd, codigo, tarea, vista, f"Script versión {vista.version} rechazado.")


@router.get("/estrategias/{bd}/{codigo}/scripts/{tarea}/simular", response_class=HTMLResponse)
def simular(request: Request, bd: str, codigo: str, tarea: str) -> HTMLResponse:
    simulacion = servicio_ejecucion.simular(_ajustes(request), bd, codigo, tarea)
    return renderizar(request, "parciales/_simulacion.html", {"simulacion": simulacion})


@router.post(
    "/estrategias/{bd}/{codigo}/scripts/{tarea}/ejecutar", response_model=None, dependencies=OrigenConfiable
)
def ejecutar(request: Request, bd: str, codigo: str, tarea: str, tareas: BackgroundTasks) -> Response:
    ajustes = _ajustes(request)
    ejecucion_id = servicio_ejecucion.programar_ahora(ajustes, bd, codigo, tarea)
    tareas.add_task(ejecutar_registrando, "ejecutar", servicio_ejecucion.ejecutar, ajustes, ejecucion_id)
    if not es_htmx(request):
        return RedirectResponse(f"/historial/{ejecucion_id}", status_code=303)
    return renderizar(request, "parciales/_ejecucion_lanzada.html", {"ejecucion_id": ejecucion_id})
