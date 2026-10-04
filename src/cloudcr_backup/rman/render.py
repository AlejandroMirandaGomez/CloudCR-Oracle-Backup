from importlib.resources import files
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

DIRECTORIO_PLANTILLAS = files("cloudcr_backup.rman") / "plantillas"
FIN_DE_LINEA = "\n"


class ScriptNoAscii(ValueError):
    pass


_entorno = Environment(
    loader=FileSystemLoader(str(DIRECTORIO_PLANTILLAS)),
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
    undefined=StrictUndefined,
    autoescape=False,
)


def normalizar(texto: str) -> str:
    limpio = texto.replace("\r\n", FIN_DE_LINEA).replace("\r", FIN_DE_LINEA).lstrip("﻿")
    try:
        limpio.encode("ascii")
    except UnicodeEncodeError as error:
        caracter = limpio[error.start]
        raise ScriptNoAscii(
            f"El script RMAN contiene el carácter {caracter!r}, que no es ASCII. "
            "RMAN solo lee archivos de comandos ASCII: revise rutas y nombres."
        ) from error
    return limpio if limpio.endswith(FIN_DE_LINEA) else limpio + FIN_DE_LINEA


def renderizar(plantilla: str, **contexto: Any) -> str:
    return normalizar(_entorno.get_template(plantilla).render(**contexto))


def bytes_ascii(texto: str) -> bytes:
    return normalizar(texto).encode("ascii")
