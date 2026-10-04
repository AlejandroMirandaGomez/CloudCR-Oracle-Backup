from typing import Annotated
from urllib.parse import parse_qs

from fastapi import Depends, Request

from cloudcr_backup.domain.errores import OperacionNoPermitida

LARGO_MAXIMO_FORMULARIO = 256_000
TIPO_FORMULARIO = "application/x-www-form-urlencoded"
VALORES_VERDADEROS = frozenset({"on", "true", "1", "si", "sí", "yes"})


async def campos_formulario(request: Request) -> dict[str, str]:
    cuerpo = await request.body()
    if not cuerpo:
        return {}
    if len(cuerpo) > LARGO_MAXIMO_FORMULARIO:
        raise OperacionNoPermitida(f"El formulario es demasiado grande (máximo {LARGO_MAXIMO_FORMULARIO} bytes).")
    if TIPO_FORMULARIO not in request.headers.get("content-type", ""):
        raise OperacionNoPermitida(f"El formulario debe enviarse como {TIPO_FORMULARIO}.")
    texto = cuerpo.decode("utf-8", errors="replace")
    return {clave: valores[-1] for clave, valores in parse_qs(texto, keep_blank_values=True).items()}


Formulario = Annotated[dict[str, str], Depends(campos_formulario)]


def marcado(campos: dict[str, str], clave: str) -> bool:
    return campos.get(clave, "").strip().lower() in VALORES_VERDADEROS


def texto(campos: dict[str, str], clave: str) -> str:
    return campos.get(clave, "").strip()


def entero(campos: dict[str, str], clave: str) -> int | None:
    valor = texto(campos, clave)
    if not valor:
        return None
    try:
        numero = int(valor)
    except ValueError as error:
        raise OperacionNoPermitida(f"El campo {clave} debe ser un número entero.") from error
    if numero < 1:
        raise OperacionNoPermitida(f"El campo {clave} debe ser mayor que cero.")
    return numero
