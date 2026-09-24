from fastapi.testclient import TestClient

from cloudcr_backup.web.app import crear_app
from cloudcr_backup.web.config import ConfigWeb
from cloudcr_backup.web.seguridad import COOKIE_TOKEN, nombre_host
from tests.web.conftest import ServicioFalso

TOKEN = "token-de-prueba"


def _cliente_remoto(servicio: ServicioFalso) -> TestClient:
    config = ConfigWeb(host="0.0.0.0", token=TOKEN, clientes_sin_token=frozenset(), hosts_permitidos=None)
    return TestClient(crear_app(config, servicio=servicio))


def test_cliente_local_sin_token(cliente: TestClient) -> None:
    assert cliente.get("/salud").status_code == 200


def test_remoto_sin_token_es_rechazado(servicio: ServicioFalso) -> None:
    respuesta = _cliente_remoto(servicio).get("/instancias/XE")
    assert respuesta.status_code == 403
    assert servicio.llamadas == []


def test_remoto_con_token_invalido(servicio: ServicioFalso) -> None:
    assert _cliente_remoto(servicio).get("/salud", params={"token": "otro"}).status_code == 403


def test_remoto_con_token_valido_crea_cookie(servicio: ServicioFalso) -> None:
    cliente = _cliente_remoto(servicio)
    respuesta = cliente.get("/salud", params={"token": TOKEN})
    assert respuesta.status_code == 200
    assert COOKIE_TOKEN in respuesta.cookies
    assert "httponly" in respuesta.headers["set-cookie"].lower()
    assert cliente.get("/salud").status_code == 200


def test_host_no_permitido(servicio: ServicioFalso) -> None:
    config = ConfigWeb(clientes_sin_token=frozenset({"testclient"}))
    cliente = TestClient(crear_app(config, servicio=servicio))
    assert cliente.get("/salud", headers={"host": "atacante.example"}).status_code == 400
    assert cliente.get("/salud", headers={"host": "127.0.0.1:8765"}).status_code == 200
    assert cliente.get("/salud", headers={"host": "localhost:8765"}).status_code == 200


def test_cabeceras_de_seguridad(cliente: TestClient) -> None:
    cabeceras = cliente.get("/instancias/XE").headers
    assert "script-src 'self'" in cabeceras["content-security-policy"]
    assert cabeceras["x-content-type-options"] == "nosniff"
    assert cabeceras["x-frame-options"] == "DENY"


def test_config_remota_genera_token() -> None:
    config = ConfigWeb.desde_opciones(host="0.0.0.0", puerto=8765, token=None, ttl_cache_segundos=60)
    assert config.token and len(config.token) >= 32
    assert config.hosts_permitidos is None
    local = ConfigWeb.desde_opciones(host="127.0.0.1", puerto=8765, token=None, ttl_cache_segundos=60)
    assert local.token is None
    assert local.es_local


def test_nombre_host() -> None:
    assert nombre_host("127.0.0.1:8765") == "127.0.0.1"
    assert nombre_host("localhost") == "localhost"
    assert nombre_host("[::1]:8765") == "::1"
