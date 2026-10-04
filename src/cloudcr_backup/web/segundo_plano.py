import logging
from collections.abc import Callable
from typing import Any

REGISTRO = logging.getLogger("cloudcr.web.segundo_plano")


def ejecutar_registrando(nombre: str, funcion: Callable[..., Any], *argumentos: Any) -> None:
    try:
        funcion(*argumentos)
    except Exception:
        REGISTRO.exception("La operación %s lanzada desde la web falló", nombre)
