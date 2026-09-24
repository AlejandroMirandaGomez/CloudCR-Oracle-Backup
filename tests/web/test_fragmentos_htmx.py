from fastapi.testclient import TestClient

from cloudcr_backup.oracle.connection import ErrorConexionOracle
from cloudcr_backup.oracle.explorador import InstanciaNoEncontrada
from tests.web.conftest import HOME_FICTICIO, ServicioFalso


def test_explorador_como_fragmento(cliente: TestClient, cabecera_htmx: dict[str, str]) -> None:
    html = cliente.get("/instancias/XE", headers=cabecera_htmx).text
    assert "<html" not in html
    assert 'id="contenido"' in html
    assert 'id="zona-arbol"' in html


def test_arbol_como_fragmento_con_filtro_de_pdb(cliente: TestClient, cabecera_htmx: dict[str, str]) -> None:
    html = cliente.get("/instancias/XE/arbol", params={"pdb": "XEPDB1"}, headers=cabecera_htmx).text
    assert "<html" not in html
    assert 'id="nodo-contenedor-3"' in html
    assert 'id="nodo-contenedor-1"' not in html
    assert 'id="nodo-controlfiles"' in html


def test_arbol_sin_seed_y_rutas_completas(cliente: TestClient, cabecera_htmx: dict[str, str]) -> None:
    html = cliente.get(
        "/instancias/XE/arbol", params={"sin_seed": "true", "rutas_completas": "true"}, headers=cabecera_htmx
    ).text
    assert 'id="nodo-contenedor-2"' not in html
    assert "C:\\ORACLE\\ORADATA\\XE\\XEPDB1\\USERS01.DBF" in html


def test_arbol_sin_htmx_devuelve_pagina_completa(cliente: TestClient) -> None:
    html = cliente.get("/instancias/XE/arbol", params={"pdb": "XEPDB1"}).text
    assert "<html" in html
    assert "selected>XEPDB1" in html


def test_pdb_inexistente_muestra_aviso(cliente: TestClient, cabecera_htmx: dict[str, str]) -> None:
    html = cliente.get("/instancias/XE/arbol", params={"pdb": "NOEXISTE"}, headers=cabecera_htmx).text
    assert "no tiene un contenedor llamado NOEXISTE" in html
    assert 'id="nodo-contenedor-1"' in html


def test_refrescar_se_pasa_al_servicio(
    cliente: TestClient, servicio: ServicioFalso, cabecera_htmx: dict[str, str]
) -> None:
    cliente.get("/instancias/XE", params={"refrescar": "true"}, headers=cabecera_htmx)
    assert servicio.llamadas[-1] == ("XE", None, True)


def test_oracle_home_detectado_se_acepta(cliente: TestClient, servicio: ServicioFalso) -> None:
    respuesta = cliente.get("/instancias/XE", params={"oracle_home": str(HOME_FICTICIO)})
    assert respuesta.status_code == 200
    assert servicio.llamadas[-1][1] == HOME_FICTICIO


def test_oracle_home_desconocido_se_rechaza(cliente: TestClient, servicio: ServicioFalso) -> None:
    respuesta = cliente.get("/instancias/XE", params={"oracle_home": "\\\\servidor\\compartido\\oracle"})
    assert respuesta.status_code == 502
    assert "solo acepta un ORACLE_HOME detectado" in respuesta.text
    assert servicio.llamadas == []


def test_error_de_conexion_como_fragmento(
    cliente: TestClient, servicio: ServicioFalso, cabecera_htmx: dict[str, str]
) -> None:
    servicio.error = ErrorConexionOracle("La instancia XE no está disponible (ORA-01034).", "Inicie el servicio.")
    respuesta = cliente.get("/instancias/XE", headers=cabecera_htmx)
    assert respuesta.status_code == 200
    assert 'role="alert"' in respuesta.text
    assert "ORA-01034" in respuesta.text
    assert "Inicie el servicio." in respuesta.text


def test_instancia_inexistente_como_pagina(cliente: TestClient, servicio: ServicioFalso) -> None:
    servicio.error = InstanciaNoEncontrada("No se encontró la instancia ORCL.")
    respuesta = cliente.get("/instancias/ORCL")
    assert respuesta.status_code == 404
    assert "<html" in respuesta.text
    assert "No se encontró la instancia ORCL." in respuesta.text
