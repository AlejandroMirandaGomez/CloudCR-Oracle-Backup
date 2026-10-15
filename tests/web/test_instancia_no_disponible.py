import pytest
from fastapi.testclient import TestClient

from cloudcr_backup.oracle.connection import ErrorConexionOracle, ErrorInstanciaNoDisponible
from tests.web.conftest import ServicioFalso

RUTAS_QUE_EXPLORAN = ["/instancias/XE", "/instancias/XE/estrategias/nueva"]


@pytest.fixture
def instancia_sin_montar(servicio: ServicioFalso) -> None:
    servicio.error = ErrorInstanciaNoDisponible(
        "La instancia XE está iniciada, pero su base de datos no está montada (ORA-01507)."
    )


@pytest.mark.parametrize("ruta", RUTAS_QUE_EXPLORAN)
@pytest.mark.usefixtures("instancia_sin_montar")
def test_instancia_no_disponible_muestra_mensaje_con_dos_salidas(cliente: TestClient, ruta: str) -> None:
    respuesta = cliente.get(ruta)
    assert respuesta.status_code == 502
    assert "<html" in respuesta.text
    assert "Algo sucedió con la instancia Oracle XE" in respuesta.text
    assert "ORA-01507" in respuesta.text
    assert '<a class="boton primario" href="/recuperacion?bd=XE">Ir a Recuperación</a>' in respuesta.text
    assert '<a class="boton" href="/">Volver al menú</a>' in respuesta.text
    assert "Reintentar" not in respuesta.text


@pytest.mark.usefixtures("instancia_sin_montar")
def test_instancia_no_disponible_como_fragmento(cliente: TestClient, cabecera_htmx: dict[str, str]) -> None:
    respuesta = cliente.get("/instancias/XE", headers=cabecera_htmx)
    assert respuesta.status_code == 200
    assert "<html" not in respuesta.text
    assert "Algo sucedió con la instancia Oracle XE" in respuesta.text
    assert 'href="/recuperacion?bd=XE"' in respuesta.text
    assert 'href="/"' in respuesta.text


def test_otro_error_de_conexion_conserva_su_pantalla(cliente: TestClient, servicio: ServicioFalso) -> None:
    servicio.error = ErrorConexionOracle("Usuario o contraseña inválidos (ORA-01017).")
    respuesta = cliente.get("/instancias/XE")
    assert respuesta.status_code == 502
    assert "No se pudo inspeccionar la instancia XE" in respuesta.text
    assert "Algo sucedió con la instancia Oracle" not in respuesta.text
    assert "Reintentar" in respuesta.text
