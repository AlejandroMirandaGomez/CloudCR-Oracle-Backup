import secrets

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.types import ASGIApp

from cloudcr_backup.web.config import ConfigWeb

COOKIE_TOKEN = "cloudcr_token"
POLITICA_CONTENIDO = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)
CABECERAS_SEGURIDAD = {
    "Content-Security-Policy": POLITICA_CONTENIDO,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def nombre_host(cabecera_host: str) -> str:
    if cabecera_host.startswith("["):
        return cabecera_host[1:].split("]", 1)[0]
    return cabecera_host.rsplit(":", 1)[0] if cabecera_host.count(":") == 1 else cabecera_host


class MiddlewareAcceso(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, config: ConfigWeb) -> None:
        super().__init__(app)
        self._config = config

    def _host_permitido(self, request: Request) -> bool:
        permitidos = self._config.hosts_permitidos
        if permitidos is None:
            return True
        return nombre_host(request.headers.get("host", "")) in permitidos

    def _token_valido(self, request: Request) -> bool:
        cliente = request.client.host if request.client else ""
        if cliente in self._config.clientes_sin_token:
            return True
        esperado = self._config.token
        recibido = request.query_params.get("token") or request.cookies.get(COOKIE_TOKEN) or ""
        return bool(esperado) and secrets.compare_digest(recibido.encode(), (esperado or "").encode())

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not self._host_permitido(request):
            respuesta: Response = PlainTextResponse("Host no permitido.", status_code=400)
        elif not self._token_valido(request):
            respuesta = PlainTextResponse("Acceso denegado: token inválido o ausente.", status_code=403)
        else:
            respuesta = await call_next(request)
            if self._config.token and request.query_params.get("token") == self._config.token:
                respuesta.set_cookie(COOKIE_TOKEN, self._config.token, httponly=True, samesite="strict")
        for nombre, valor in CABECERAS_SEGURIDAD.items():
            respuesta.headers.setdefault(nombre, valor)
        return respuesta
