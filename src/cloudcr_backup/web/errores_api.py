from typing import Any

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

PREFIJO_API = "/api/"
PREFIJO_VALOR_INVALIDO = "Value error, "

MENSAJES_POR_TIPO = {
    "missing": "Este campo es obligatorio.",
    "enum": "El valor elegido no es válido.",
    "time_parsing": "Hora inválida (use HH:MM).",
    "time_type": "Hora inválida (use HH:MM).",
    "date_parsing": "Fecha inválida (use AAAA-MM-DD).",
    "date_type": "Fecha inválida (use AAAA-MM-DD).",
    "date_from_datetime_parsing": "Fecha inválida (use AAAA-MM-DD).",
    "int_parsing": "Debe ser un número entero.",
    "int_type": "Debe ser un número entero.",
    "bool_parsing": "Debe ser verdadero o falso.",
    "json_invalid": "El cuerpo de la solicitud no es un JSON válido.",
}


class ErrorApi(Exception):
    def __init__(
        self,
        estado: int,
        mensaje: str,
        campo: str = "",
        sugerencia: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(mensaje)
        self.estado = estado
        self.mensaje = mensaje
        self.campo = campo
        self.sugerencia = sugerencia
        self.extra = extra or {}


def _campo(ubicacion: tuple[Any, ...]) -> str:
    return ".".join(str(parte) for parte in ubicacion if parte not in ("body", "query", "path"))


def _mensaje(error: dict[str, Any]) -> str:
    tipo = error.get("type", "")
    contexto = error.get("ctx") or {}
    if tipo == "string_too_short":
        return "Este campo es obligatorio." if contexto.get("min_length") == 1 else "Es demasiado corto."
    if tipo == "string_too_long":
        return f"Es demasiado largo (máximo {contexto.get('max_length')} caracteres)."
    if tipo in {"greater_than_equal", "greater_than"}:
        return f"Debe ser mayor o igual que {contexto.get('ge', contexto.get('gt'))}."
    if tipo == "too_long":
        return f"Hay demasiados elementos (máximo {contexto.get('max_length')})."
    if tipo in MENSAJES_POR_TIPO:
        return MENSAJES_POR_TIPO[tipo]
    texto = str(error.get("msg", "Valor inválido."))
    return texto.removeprefix(PREFIJO_VALOR_INVALIDO)


def _respuesta(estado: int, errores: list[dict[str, Any]], extra: dict[str, Any] | None = None) -> JSONResponse:
    return JSONResponse({"errores": errores, **(extra or {})}, status_code=estado)


async def manejar_error_api(_: Request, error: Exception) -> Response:
    assert isinstance(error, ErrorApi)
    detalle: dict[str, Any] = {"campo": error.campo, "mensaje": error.mensaje}
    if error.sugerencia:
        detalle["sugerencia"] = error.sugerencia
    return _respuesta(error.estado, [detalle], error.extra)


async def manejar_validacion(request: Request, error: Exception) -> Response:
    assert isinstance(error, RequestValidationError)
    if not request.url.path.startswith(PREFIJO_API):
        return await request_validation_exception_handler(request, error)
    errores = [{"campo": _campo(tuple(e["loc"])), "mensaje": _mensaje(e)} for e in error.errors()]
    return _respuesta(422, errores)


def registrar_manejadores(app: FastAPI) -> None:
    app.add_exception_handler(ErrorApi, manejar_error_api)
    app.add_exception_handler(RequestValidationError, manejar_validacion)
