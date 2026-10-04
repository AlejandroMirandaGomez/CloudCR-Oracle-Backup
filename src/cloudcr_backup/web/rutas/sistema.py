from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.domain.errores import ErrorServicio, OperacionNoPermitida
from cloudcr_backup.repository.bases_datos import Ambiente
from cloudcr_backup.services import administracion as servicio_administracion
from cloudcr_backup.services import alertas as servicio_alertas
from cloudcr_backup.services import bases_datos as servicio_bases
from cloudcr_backup.services.control_agente import ControlAgente
from cloudcr_backup.web.formularios import Formulario, marcado, texto
from cloudcr_backup.web.monitoreo import ProveedorMonitoreo, ajustes_de_la_app, obtener_monitoreo
from cloudcr_backup.web.rutas.comun import es_htmx, renderizar
from cloudcr_backup.web.seguridad import exigir_origen_confiable

router = APIRouter()

OrigenConfiable = [Depends(exigir_origen_confiable)]
Monitoreo = Annotated[ProveedorMonitoreo, Depends(obtener_monitoreo)]
SEGUNDOS_ESPERA_DETENCION = 2.0


def obtener_control_agente(request: Request) -> ControlAgente:
    control: ControlAgente = request.app.state.control_agente
    return control


Control = Annotated[ControlAgente, Depends(obtener_control_agente)]


def _ajustes(request: Request) -> Ajustes:
    return ajustes_de_la_app(request.app)()


def _volver(request: Request, ancla: str) -> Response | None:
    if es_htmx(request):
        return None
    return RedirectResponse(f"/sistema#{ancla}", status_code=303)


@router.get("/sistema", response_class=HTMLResponse)
def pagina_sistema(request: Request) -> HTMLResponse:
    return renderizar(request, "sistema.html", {"seccion": "sistema"})


@router.get("/sistema/entorno", response_class=HTMLResponse)
def entorno(request: Request) -> HTMLResponse:
    comprobaciones = servicio_administracion.comprobar_entorno(_ajustes(request))
    return renderizar(request, "parciales/_entorno.html", {"comprobaciones": comprobaciones})


def _repositorio(request: Request, aviso: str | None = None) -> HTMLResponse:
    estado = servicio_administracion.estado_repositorio(_ajustes(request))
    return renderizar(request, "parciales/_repositorio.html", {"estado": estado, "aviso": aviso})


@router.get("/sistema/repositorio", response_class=HTMLResponse)
def repositorio(request: Request) -> HTMLResponse:
    return _repositorio(request)


@router.post("/sistema/repositorio/reiniciar", response_model=None, dependencies=OrigenConfiable)
def reiniciar_repositorio(request: Request, control: Control, campos: Formulario) -> Response:
    if control.estado().corriendo:
        raise OperacionNoPermitida(
            "El agente de esta web está corriendo y usa el repositorio.", "Deténgalo en Sistema → Agente y reintente."
        )
    reinstalar = marcado(campos, "reinstalar")
    servicio_administracion.reiniciar_repositorio(_ajustes(request), campos.get("confirmacion", ""), reinstalar)
    aviso = (
        "Repositorio borrado y vuelto a instalar vacío, con sus parámetros iniciales."
        if reinstalar
        else "Repositorio borrado. Instálelo de nuevo para volver a usar la herramienta."
    )
    return _volver(request, "repositorio") or _repositorio(request, aviso)


@router.post("/sistema/repositorio/instalar", response_model=None, dependencies=OrigenConfiable)
def instalar_repositorio(request: Request) -> Response:
    servicio_administracion.instalar_repositorio(_ajustes(request))
    aviso = "Repositorio instalado con sus parámetros iniciales."
    return _volver(request, "repositorio") or _repositorio(request, aviso)


def _parametros(request: Request, aviso: str | None = None) -> HTMLResponse:
    parametros = servicio_administracion.parametros(_ajustes(request))
    return renderizar(request, "parciales/_parametros.html", {"parametros": parametros, "aviso": aviso})


@router.get("/sistema/parametros", response_class=HTMLResponse)
def parametros(request: Request) -> HTMLResponse:
    return _parametros(request)


@router.post("/sistema/parametros", response_model=None, dependencies=OrigenConfiable)
def asignar_parametro(request: Request, campos: Formulario) -> Response:
    parametro = servicio_administracion.asignar_parametro(
        _ajustes(request), texto(campos, "clave"), campos.get("valor", "")
    )
    return _volver(request, "parametros") or _parametros(request, f"Parámetro {parametro.clave} actualizado.")


@router.post("/sistema/parametros/restablecer", response_model=None, dependencies=OrigenConfiable)
def restablecer_parametro(request: Request, campos: Formulario) -> Response:
    parametro = servicio_administracion.restablecer_parametro(_ajustes(request), texto(campos, "clave"))
    aviso = f"Parámetro {parametro.clave} restablecido a {parametro.valor!r}."
    return _volver(request, "parametros") or _parametros(request, aviso)


def _bases(request: Request, aviso: str | None = None) -> HTMLResponse:
    ajustes = _ajustes(request)
    contexto: dict[str, Any] = {
        "bases": servicio_bases.listar(ajustes),
        "ambientes": [a.value for a in Ambiente],
        "zona": ajustes.zona_horaria,
        "aviso": aviso,
    }
    return renderizar(request, "parciales/_bases.html", contexto)


@router.get("/sistema/bases", response_class=HTMLResponse)
def bases(request: Request) -> HTMLResponse:
    return _bases(request)


@router.post("/sistema/bases/registrar", response_model=None, dependencies=OrigenConfiable)
def registrar_base(request: Request, campos: Formulario) -> Response:
    vista = servicio_bases.registrar(_ajustes(request), texto(campos, "sid"), texto(campos, "ambiente") or "PRUEBAS")
    aviso = f"Base {vista.nombre} registrada en ambiente {vista.ambiente}. Guarde ahora su perfil."
    return _volver(request, "bases") or _bases(request, aviso)


@router.post("/sistema/bases/{nombre}/inspeccionar", response_model=None, dependencies=OrigenConfiable)
def inspeccionar_base(request: Request, nombre: str) -> Response:
    perfil = servicio_bases.inspeccionar(_ajustes(request), nombre)
    aviso = (
        f"Perfil de {perfil.bd} guardado: {perfil.log_mode.value}, {perfil.tablespaces} tablespaces, "
        f"{perfil.datafiles} datafiles."
    )
    return _volver(request, "bases") or _bases(request, aviso)


@router.post("/sistema/bases/{nombre}/activar", response_model=None, dependencies=OrigenConfiable)
def activar_base(request: Request, nombre: str) -> Response:
    servicio_bases.cambiar_activa(_ajustes(request), nombre, True)
    return _volver(request, "bases") or _bases(request, f"Base {nombre.upper()} activada.")


@router.post("/sistema/bases/{nombre}/desactivar", response_model=None, dependencies=OrigenConfiable)
def desactivar_base(request: Request, nombre: str) -> Response:
    servicio_bases.cambiar_activa(_ajustes(request), nombre, False)
    return _volver(request, "bases") or _bases(request, f"Base {nombre.upper()} desactivada.")


@router.get("/sistema/archivado", response_class=HTMLResponse)
def archivado(request: Request) -> HTMLResponse:
    contexto = {
        "bases": servicio_bases.listar(_ajustes(request)),
        "procedimiento": servicio_administracion.PROCEDIMIENTO_ARCHIVELOG,
    }
    return renderizar(request, "parciales/_archivado.html", contexto)


def _correo(request: Request, aviso: str | None = None) -> HTMLResponse:
    estado = servicio_alertas.estado_correo(_ajustes(request))
    return renderizar(request, "parciales/_correo.html", {"estado": estado, "aviso": aviso})


@router.get("/sistema/correo", response_class=HTMLResponse)
def correo(request: Request) -> HTMLResponse:
    return _correo(request)


@router.post("/sistema/correo/configurar", response_model=None, dependencies=OrigenConfiable)
def configurar_correo(request: Request, campos: Formulario) -> Response:
    resultado = servicio_alertas.cargar_configuracion_del_equipo(_ajustes(request), marcado(campos, "sobrescribir"))
    aviso = f"Configuración de correo del equipo cargada ({len(resultado.aplicados)} valores aplicados)."
    if resultado.conservados:
        aviso += f" Se conservaron {len(resultado.conservados)} valores cambiados a mano."
    return _volver(request, "correo") or _correo(request, aviso)


@router.post("/sistema/correo/probar", response_model=None, dependencies=OrigenConfiable)
def probar_correo(request: Request) -> Response:
    resultado = servicio_alertas.probar_correo(_ajustes(request))
    aviso = f"Correo de prueba enviado por {resultado.servidor} a {', '.join(resultado.destinatarios)}."
    return _volver(request, "correo") or _correo(request, aviso)


def _autoinicio(ajustes: Ajustes) -> bool | None:
    try:
        return servicio_administracion.autoinicio_agente(ajustes)
    except ErrorServicio:
        return None


def _agente(request: Request, control: ControlAgente, monitoreo: ProveedorMonitoreo) -> HTMLResponse:
    contexto = {
        "control": control.estado(),
        "agentes": monitoreo.agentes(),
        "zona": monitoreo.zona_horaria,
        "autoinicio": _autoinicio(_ajustes(request)),
    }
    return renderizar(request, "parciales/_agente.html", contexto)


@router.get("/sistema/agente", response_class=HTMLResponse)
def agente(request: Request, control: Control, monitoreo: Monitoreo) -> HTMLResponse:
    return _agente(request, control, monitoreo)


@router.post("/sistema/agente/autoinicio", response_model=None, dependencies=OrigenConfiable)
def autoinicio_agente(request: Request, control: Control, monitoreo: Monitoreo, campos: Formulario) -> Response:
    servicio_administracion.asignar_autoinicio_agente(_ajustes(request), marcado(campos, "activo"))
    return _volver(request, "agente") or _agente(request, control, monitoreo)


@router.post("/sistema/agente/iniciar", response_model=None, dependencies=OrigenConfiable)
def iniciar_agente(request: Request, control: Control, monitoreo: Monitoreo, campos: Formulario) -> Response:
    control.iniciar(marcado(campos, "simulado"))
    return _volver(request, "agente") or _agente(request, control, monitoreo)


@router.post("/sistema/agente/ciclo", response_model=None, dependencies=OrigenConfiable)
def ciclo_agente(request: Request, control: Control, monitoreo: Monitoreo, campos: Formulario) -> Response:
    control.un_ciclo(marcado(campos, "simulado"))
    return _volver(request, "agente") or _agente(request, control, monitoreo)


@router.post("/sistema/agente/detener", response_model=None, dependencies=OrigenConfiable)
def detener_agente(request: Request, control: Control, monitoreo: Monitoreo) -> Response:
    control.detener(SEGUNDOS_ESPERA_DETENCION)
    return _volver(request, "agente") or _agente(request, control, monitoreo)
