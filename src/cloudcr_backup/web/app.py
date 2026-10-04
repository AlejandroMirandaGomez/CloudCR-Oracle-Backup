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
from cloudcr_backup.web.config import ConfigWeb
from cloudcr_backup.web.dependencias import ProveedorExploracion, ServicioExploracion
from cloudcr_backup.web.errores_api import registrar_manejadores
from cloudcr_backup.web.errores_servicio import registrar_manejador_servicio
from cloudcr_backup.web.monitoreo import ProveedorMonitoreo, ServicioMonitoreo, ajustes_de_la_app
from cloudcr_backup.web.rutas import (
    alertas,
    carpetas,
    estrategias,
    estrategias_registradas,
    exportaciones,
    historial,
    inicio,
    instancias,
    monitoreo,
    operaciones,
)
from cloudcr_backup.web.seguridad import MiddlewareAcceso

RAIZ_WEB = files("cloudcr_backup.web")
FORMATO_HORA_LOCAL = "%Y-%m-%d %H:%M"


DIAS_SEMANA = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


def hora_local(momento: datetime | None, zona: str, formato: str = FORMATO_HORA_LOCAL) -> str:
    return local(momento, zona).strftime(formato) if momento is not None else "—"


def dia_semana(momento: datetime | None, zona: str) -> str:
    return DIAS_SEMANA[local(momento, zona).weekday()] if momento is not None else ""


def crear_plantillas() -> Jinja2Templates:
    plantillas = Jinja2Templates(directory=str(RAIZ_WEB / "plantillas"))
    plantillas.env.globals["version"] = __version__
    plantillas.env.globals["conteo_severidad"] = conteo_severidad
    plantillas.env.filters["bytes"] = formato_bytes
    plantillas.env.filters["id_nodo"] = id_nodo
    plantillas.env.filters["etiqueta_severidad"] = lambda severidad: ETIQUETA_SEVERIDAD[severidad]
    plantillas.env.filters["local"] = hora_local
    plantillas.env.filters["dia_semana"] = dia_semana
    return plantillas


def crear_app(
    config: ConfigWeb,
    servicio: ProveedorExploracion | None = None,
    ajustes: Ajustes | None = None,
    monitoreo_servicio: ProveedorMonitoreo | None = None,
) -> FastAPI:
    app = FastAPI(
        title="CloudCR Oracle Backup",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.config = config
    app.state.servicio = servicio or ServicioExploracion(ttl_segundos=config.ttl_cache_segundos)
    app.state.ajustes = ajustes
    app.state.monitoreo = monitoreo_servicio or ServicioMonitoreo(ajustes_de_la_app(app))
    app.state.plantillas = crear_plantillas()
    app.add_middleware(MiddlewareAcceso, config=config)
    registrar_manejadores(app)
    registrar_manejador_servicio(app)
    app.mount("/estaticos", StaticFiles(directory=str(RAIZ_WEB / "estaticos")), name="estaticos")
    app.include_router(inicio.router)
    app.include_router(instancias.router)
    app.include_router(exportaciones.router)
    app.include_router(estrategias.router)
    app.include_router(carpetas.router)
    app.include_router(monitoreo.router)
    app.include_router(historial.router)
    app.include_router(alertas.router)
    app.include_router(estrategias_registradas.router)
    app.include_router(operaciones.router)
    return app
