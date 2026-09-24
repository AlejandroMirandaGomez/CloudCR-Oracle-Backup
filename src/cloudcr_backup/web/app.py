from importlib.resources import files

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from cloudcr_backup import __version__
from cloudcr_backup.presentacion.arbol import id_nodo
from cloudcr_backup.presentacion.formato import ETIQUETA_SEVERIDAD, conteo_severidad, formato_bytes
from cloudcr_backup.web.config import ConfigWeb
from cloudcr_backup.web.dependencias import ProveedorExploracion, ServicioExploracion
from cloudcr_backup.web.rutas import exportaciones, inicio, instancias
from cloudcr_backup.web.seguridad import MiddlewareAcceso

RAIZ_WEB = files("cloudcr_backup.web")


def crear_plantillas() -> Jinja2Templates:
    plantillas = Jinja2Templates(directory=str(RAIZ_WEB / "plantillas"))
    plantillas.env.globals["version"] = __version__
    plantillas.env.globals["conteo_severidad"] = conteo_severidad
    plantillas.env.filters["bytes"] = formato_bytes
    plantillas.env.filters["id_nodo"] = id_nodo
    plantillas.env.filters["etiqueta_severidad"] = lambda severidad: ETIQUETA_SEVERIDAD[severidad]
    return plantillas


def crear_app(config: ConfigWeb, servicio: ProveedorExploracion | None = None) -> FastAPI:
    app = FastAPI(
        title="CloudCR Oracle Backup",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.config = config
    app.state.servicio = servicio or ServicioExploracion(ttl_segundos=config.ttl_cache_segundos)
    app.state.plantillas = crear_plantillas()
    app.add_middleware(MiddlewareAcceso, config=config)
    app.mount("/estaticos", StaticFiles(directory=str(RAIZ_WEB / "estaticos")), name="estaticos")
    app.include_router(inicio.router)
    app.include_router(instancias.router)
    app.include_router(exportaciones.router)
    return app
