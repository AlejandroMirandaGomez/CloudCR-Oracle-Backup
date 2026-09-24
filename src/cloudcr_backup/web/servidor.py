import socket
import threading
import time
import urllib.request
import webbrowser
from collections.abc import Callable

import uvicorn

from cloudcr_backup.web.app import crear_app
from cloudcr_backup.web.config import ConfigWeb

INTENTOS_PUERTO = 20
ESPERA_ARRANQUE_SEGUNDOS = 15.0


class PuertoNoDisponible(RuntimeError):
    pass


def puerto_libre(host: str, desde: int, intentos: int = INTENTOS_PUERTO) -> int:
    familia = socket.AF_INET6 if ":" in host else socket.AF_INET
    for puerto in range(desde, desde + intentos):
        with socket.socket(familia, socket.SOCK_STREAM) as prueba:
            try:
                prueba.bind((host, puerto))
            except OSError:
                continue
            return puerto
    raise PuertoNoDisponible(f"No hay puertos libres entre {desde} y {desde + intentos - 1}.")


def url_base(config: ConfigWeb) -> str:
    host = "127.0.0.1" if config.host in ("0.0.0.0", "::") else config.host
    host = f"[{host}]" if ":" in host else host
    return f"http://{host}:{config.puerto}"


def url_acceso(config: ConfigWeb) -> str:
    base = url_base(config) + "/"
    return f"{base}?token={config.token}" if config.token else base


def _abrir_cuando_responda(config: ConfigWeb) -> None:
    limite = time.monotonic() + ESPERA_ARRANQUE_SEGUNDOS
    while time.monotonic() < limite:
        try:
            with urllib.request.urlopen(url_base(config) + "/salud", timeout=1):
                webbrowser.open(url_acceso(config))
                return
        except OSError:
            time.sleep(0.3)


def iniciar_servidor(config: ConfigWeb, abrir_navegador: bool, avisar: Callable[[str], None]) -> None:
    puerto = puerto_libre(config.host, config.puerto)
    config_final = ConfigWeb(
        host=config.host,
        puerto=puerto,
        token=config.token,
        ttl_cache_segundos=config.ttl_cache_segundos,
        clientes_sin_token=config.clientes_sin_token,
        hosts_permitidos=config.hosts_permitidos,
    )
    avisar(url_acceso(config_final))
    if abrir_navegador:
        threading.Thread(target=_abrir_cuando_responda, args=(config_final,), daemon=True).start()
    uvicorn.run(crear_app(config_final), host=config_final.host, port=puerto, log_level="warning")
