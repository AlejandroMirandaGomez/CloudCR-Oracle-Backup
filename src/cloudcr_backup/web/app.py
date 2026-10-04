from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from importlib.resources import files

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from cloudcr_backup import __version__
from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.presentacion.arbol import id_nodo
from cloudcr_backup.presentacion.formato import ETIQUETA_SEVERIDAD, conteo_severidad, formato_bytes
from cloudcr_backup.presentacion.historial import local
from cloudcr_backup.presentacion.operaciones import ETIQUETA_ESTADO_SCRIPT, TONO_ESTADO_SCRIPT, TONO_SEVERIDAD
from cloudcr_backup.scheduling.reloj import utc_consciente
from cloudcr_backup.services.control_agente import ControlAgente
from cloudcr_backup.web.config import ConfigWeb
from cloudcr_backup.web.dependencias import ProveedorExploracion, ServicioExploracion
from cloudcr_backup.web.errores_api import registrar_manejadores
from cloudcr_backup.web.errores_servicio import registrar_manejador_servicio
from cloudcr_backup.web.monitoreo import ProveedorMonitoreo, ServicioMonitoreo, ajustes_de_la_app
from cloudcr_backup.web.rutas import (
    alertas,
    api_gestion,
    carpetas,
    criterios,
    estrategias,
    estrategias_registradas,
    exportaciones,
    gestion_estrategias,
    historial,
    inicio,
    instancias,
    monitoreo,
    operaciones,
    recuperacion,
    retencion,
    scripts,
    sistema,
)
from cloudcr_backup.web.seguridad import MiddlewareAcceso

RAIZ_WEB = files("cloudcr_backup.web")
FORMATO_HORA_LOCAL = "%Y-%m-%d %H:%M"
SEGUNDOS_APAGADO_AGENTE = 30.0


DIAS_SEMANA = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


def hora_local(momento: datetime | None, zona: str, formato: str = FORMATO_HORA_LOCAL) -> str:
    return local(utc_consciente(momento), zona).strftime(formato) if momento is not None else "—"


def hora_servidor(momento: datetime | None, zona: str, formato: str = FORMATO_HORA_LOCAL) -> str:
    if momento is None:
        return "—"
    if momento.tzinfo is None:
        return momento.strftime(formato)
    return local(momento, zona).strftime(formato)


def dia_semana(momento: datetime | None, zona: str) -> str:
    return DIAS_SEMANA[local(utc_consciente(momento), zona).weekday()] if momento is not None else ""


def crear_plantillas() -> Jinja2Templates:
    plantillas = Jinja2Templates(directory=str(RAIZ_WEB / "plantillas"))
    plantillas.env.globals["version"] = __version__
    plantillas.env.globals["conteo_severidad"] = conteo_severidad
    plantillas.env.filters["bytes"] = formato_bytes
    plantillas.env.filters["id_nodo"] = id_nodo
    plantillas.env.filters["etiqueta_severidad"] = lambda severidad: ETIQUETA_SEVERIDAD[severidad]
    plantillas.env.filters["local"] = hora_local
    plantillas.env.filters["dia_semana"] = dia_semana
    plantillas.env.filters["hora_servidor"] = hora_servidor
    plantillas.env.filters["tono_script"] = lambda estado: TONO_ESTADO_SCRIPT[estado]
    plantillas.env.filters["etiqueta_script"] = lambda estado: ETIQUETA_ESTADO_SCRIPT[estado]
    plantillas.env.filters["tono_severidad"] = lambda severidad: TONO_SEVERIDAD[severidad]
    return plantillas


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI) -> AsyncIterator[None]:
    config: ConfigWeb = app.state.config
    control: ControlAgente | None = getattr(app.state, "control_agente", None)
    if config.iniciar_agente and control is not None:
        control.iniciar_si_corresponde()
    yield
    if control is not None:
        control.apagar(SEGUNDOS_APAGADO_AGENTE)


def crear_app(
    config: ConfigWeb,
    servicio: ProveedorExploracion | None = None,
    ajustes: Ajustes | None = None,
    monitoreo_servicio: ProveedorMonitoreo | None = None,
    control_agente: ControlAgente | None = None,
) -> FastAPI:
    app = FastAPI(
        title="CloudCR Oracle Backup",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=ciclo_de_vida,
    )
    app.state.config = config
    app.state.servicio = servicio or ServicioExploracion(ttl_segundos=config.ttl_cache_segundos)
    app.state.ajustes = ajustes
    app.state.monitoreo = monitoreo_servicio or ServicioMonitoreo(ajustes_de_la_app(app))
    app.state.control_agente = control_agente or ControlAgente(ajustes_de_la_app(app))
    app.state.plantillas = crear_plantillas()
    app.add_middleware(MiddlewareAcceso, config=config)
    registrar_manejadores(app)
    registrar_manejador_servicio(app)
    app.mount("/estaticos", StaticFiles(directory=str(RAIZ_WEB / "estaticos")), name="estaticos")
    app.include_router(inicio.router)
    app.include_router(instancias.router)
    app.include_router(exportaciones.router)
    app.include_router(gestion_estrategias.router)
    app.include_router(estrategias.router)
    app.include_router(carpetas.router)
    app.include_router(monitoreo.router)
    app.include_router(historial.router)
    app.include_router(alertas.router)
    app.include_router(estrategias_registradas.router)
    app.include_router(operaciones.router)
    app.include_router(scripts.router)
    app.include_router(retencion.router)
    app.include_router(recuperacion.router)
    app.include_router(criterios.router)
    app.include_router(sistema.router)
    app.include_router(api_gestion.router)
    return app
