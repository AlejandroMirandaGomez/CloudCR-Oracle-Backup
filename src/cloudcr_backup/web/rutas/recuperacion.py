from datetime import date, datetime
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.domain.errores import ErrorServicio, FiltroInvalido, OperacionNoPermitida
from cloudcr_backup.domain.recuperacion import Escenario, VistaRecuperacion
from cloudcr_backup.presentacion.operaciones import AYUDA_OBJETIVO, ETIQUETA_ESCENARIO
from cloudcr_backup.services import bases_datos as servicio_bases
from cloudcr_backup.services import recuperacion as servicio_recuperacion
from cloudcr_backup.web.formularios import Formulario, entero, marcado, texto
from cloudcr_backup.web.monitoreo import ajustes_de_la_app
from cloudcr_backup.web.rutas.comun import es_htmx, renderizar
from cloudcr_backup.web.rutas.retencion import base_elegida
from cloudcr_backup.web.rutas.scripts import quien_aprueba
from cloudcr_backup.web.segundo_plano import ejecutar_registrando
from cloudcr_backup.web.seguridad import exigir_origen_confiable

router = APIRouter()

FORMATOS_MOMENTO = ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S")
FORMATO_FECHA = "%Y-%m-%d"
EVENTO_CALENDARIO_ACTUALIZADO = "calendario-actualizado"
Texto = Annotated[str | None, Query(max_length=130)]
Semana = Annotated[str | None, Query(max_length=10)]
OrigenConfiable = [Depends(exigir_origen_confiable)]


def _ajustes(request: Request) -> Ajustes:
    return ajustes_de_la_app(request.app)()


def momento_desde_texto(valor: str | None) -> datetime | None:
    texto_limpio = (valor or "").strip()
    if not texto_limpio:
        return None
    for formato in FORMATOS_MOMENTO:
        try:
            return datetime.strptime(texto_limpio, formato)
        except ValueError:
            continue
    raise FiltroInvalido(f"'{texto_limpio}' no es una fecha y hora válida.", "Use el formato AAAA-MM-DD HH:MM.")


def fecha_desde_texto(valor: str | None) -> date | None:
    texto_limpio = (valor or "").strip()
    if not texto_limpio:
        return None
    try:
        return datetime.strptime(texto_limpio, FORMATO_FECHA).date()
    except ValueError as error:
        raise FiltroInvalido(f"'{texto_limpio}' no es una fecha válida.", "Use el formato AAAA-MM-DD.") from error


def _escenarios() -> list[tuple[str, str, str]]:
    return [(e.value, ETIQUETA_ESCENARIO[e], AYUDA_OBJETIVO[e]) for e in Escenario]


def ruta_procedimiento(bd: str, procedimiento_id: int) -> str:
    return f"/recuperacion/{quote(bd, safe='')}/procedimientos/{procedimiento_id}"


@router.get("/recuperacion", response_class=HTMLResponse)
def pagina_recuperacion(
    request: Request, bd: Annotated[str | None, Query(max_length=30)] = None, semana: Semana = None
) -> HTMLResponse:
    ajustes = _ajustes(request)
    bases = servicio_bases.registradas(ajustes)
    elegida = base_elegida(bd, bases)
    puntos = servicio_recuperacion.puntos(ajustes, elegida) if elegida else None
    calendario = (
        servicio_recuperacion.calendario(ajustes, elegida, fecha_desde_texto(semana), puntos)
        if elegida and puntos is not None
        else None
    )
    contexto: dict[str, Any] = {
        "seccion": "recuperacion",
        "bases": bases,
        "bd": elegida,
        "puntos": puntos,
        "calendario": calendario,
        "escenarios": _escenarios(),
        "etiquetas": ETIQUETA_ESCENARIO,
        "zona": ajustes.zona_horaria,
    }
    plantilla = "parciales/_recuperacion.html" if es_htmx(request) else "recuperacion.html"
    return renderizar(request, plantilla, contexto)


@router.get("/recuperacion/{bd}/calendario", response_class=HTMLResponse)
def calendario(request: Request, bd: str, semana: Semana = None) -> HTMLResponse:
    resultado = servicio_recuperacion.calendario(_ajustes(request), bd, fecha_desde_texto(semana))
    return renderizar(request, "parciales/_calendario_recuperacion.html", {"calendario": resultado})


@router.get("/recuperacion/{bd}/diagnostico", response_class=HTMLResponse)
def diagnostico(request: Request, bd: str) -> HTMLResponse:
    ajustes = _ajustes(request)
    resultado = servicio_recuperacion.diagnostico(ajustes, bd)
    contexto = {
        "diagnostico": resultado,
        "procedimientos": servicio_recuperacion.procedimientos_sugeridos(ajustes, resultado),
        "zona": ajustes.zona_horaria,
        "etiquetas": ETIQUETA_ESCENARIO,
    }
    respuesta = renderizar(request, "parciales/_diagnostico.html", contexto)
    respuesta.headers["HX-Trigger"] = EVENTO_CALENDARIO_ACTUALIZADO
    return respuesta


@router.get("/recuperacion/{bd}/plan", response_class=HTMLResponse)
def plan(
    request: Request,
    bd: str,
    escenario: Annotated[str, Query(min_length=1, max_length=30)],
    objetivo: Texto = None,
    hasta: Annotated[str | None, Query(max_length=19)] = None,
) -> HTMLResponse:
    procedimiento = servicio_recuperacion.plan(
        _ajustes(request), bd, escenario, (objetivo or "").strip() or None, momento_desde_texto(hasta)
    )
    contexto = {"procedimiento": procedimiento, "etiqueta": ETIQUETA_ESCENARIO[procedimiento.escenario]}
    return renderizar(request, "parciales/_procedimiento.html", contexto)


def _contexto_control(ajustes: Ajustes, vista: VistaRecuperacion, error: ErrorServicio | None = None) -> dict[str, Any]:
    return {
        "seccion": "recuperacion",
        "zona": ajustes.zona_horaria,
        "vista": vista,
        "etiqueta": ETIQUETA_ESCENARIO[vista.registro.escenario],
        "ruta": ruta_procedimiento(vista.bd, vista.registro.id),
        "error": error,
    }


def _control(request: Request, ajustes: Ajustes, vista: VistaRecuperacion) -> Response:
    if es_htmx(request):
        return renderizar(request, "parciales/_control_recuperacion.html", _contexto_control(ajustes, vista))
    return RedirectResponse(ruta_procedimiento(vista.bd, vista.registro.id), status_code=303)


def _control_con_error(
    request: Request, ajustes: Ajustes, bd: str, procedimiento_id: int, error: ErrorServicio
) -> Response:
    vista = servicio_recuperacion.estado_procedimiento(ajustes, bd, procedimiento_id)
    contexto = _contexto_control(ajustes, vista, error)
    if es_htmx(request):
        return renderizar(request, "parciales/_control_recuperacion.html", contexto)
    return renderizar(request, "recuperacion_procedimiento.html", contexto, 409)


def _id_procedimiento(campos: dict[str, str]) -> int:
    procedimiento_id = entero(campos, "procedimiento_id")
    if procedimiento_id is None:
        raise OperacionNoPermitida("Falta indicar el procedimiento.", "Genere el procedimiento y use sus botones.")
    return procedimiento_id


@router.get("/recuperacion/{bd}/procedimientos/{procedimiento_id}", response_class=HTMLResponse)
def procedimiento(request: Request, bd: str, procedimiento_id: int) -> HTMLResponse:
    ajustes = _ajustes(request)
    vista = servicio_recuperacion.estado_procedimiento(ajustes, bd, procedimiento_id)
    plantilla = "parciales/_control_recuperacion.html" if es_htmx(request) else "recuperacion_procedimiento.html"
    return renderizar(request, plantilla, _contexto_control(ajustes, vista))


@router.post("/recuperacion/{bd}/aprobar", response_model=None, dependencies=OrigenConfiable)
def aprobar(request: Request, bd: str, campos: Formulario) -> Response:
    ajustes = _ajustes(request)
    procedimiento_id = _id_procedimiento(campos)
    try:
        vista = servicio_recuperacion.aprobar(
            ajustes,
            bd,
            procedimiento_id,
            quien_aprueba(texto(campos, "aprobado_por")),
            marcado(campos, "confirmo"),
        )
    except ErrorServicio as error:
        return _control_con_error(request, ajustes, bd, procedimiento_id, error)
    return _control(request, ajustes, vista)


@router.post("/recuperacion/{bd}/ejecutar", response_model=None, dependencies=OrigenConfiable)
def ejecutar(request: Request, bd: str, campos: Formulario, tareas: BackgroundTasks) -> Response:
    ajustes = _ajustes(request)
    procedimiento_id = _id_procedimiento(campos)
    try:
        vista = servicio_recuperacion.preparar_ejecucion(ajustes, bd, procedimiento_id, marcado(campos, "confirmo"))
    except ErrorServicio as error:
        return _control_con_error(request, ajustes, bd, procedimiento_id, error)
    tareas.add_task(
        ejecutar_registrando,
        "recuperacion",
        servicio_recuperacion.completar_ejecucion,
        ajustes,
        vista.bd,
        procedimiento_id,
    )
    return _control(request, ajustes, vista)
