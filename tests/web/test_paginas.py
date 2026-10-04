from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.web.conftest import ServicioFalso


def test_salud(cliente: TestClient) -> None:
    respuesta = cliente.get("/salud")
    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "ok"


def test_inicio_redirige_a_la_unica_instancia_en_ejecucion(cliente: TestClient) -> None:
    respuesta = cliente.get("/", follow_redirects=False)
    assert respuesta.status_code == 303
    assert respuesta.headers["location"] == "/instancias/XE"


def test_inicio_sin_instancias_redirige_a_la_lista(cliente: TestClient, servicio: ServicioFalso) -> None:
    servicio.instancias = []
    respuesta = cliente.get("/", follow_redirects=False)
    assert respuesta.headers["location"] == "/instancias"


def test_lista_de_instancias(cliente: TestClient) -> None:
    respuesta = cliente.get("/instancias")
    assert respuesta.status_code == 200
    assert "<html" in respuesta.text
    assert "XE" in respuesta.text
    assert "Explorar manualmente" in respuesta.text


def test_lista_vacia(cliente: TestClient, servicio: ServicioFalso) -> None:
    servicio.instancias = []
    assert "No se encontró ninguna instancia Oracle" in cliente.get("/instancias").text


def test_pagina_del_explorador(cliente: TestClient) -> None:
    respuesta = cliente.get("/instancias/XE")
    assert respuesta.status_code == 200
    html = respuesta.text
    for esperado in (
        "<html",
        "Modo de archivado",
        "NOARCHIVELOG",
        'id="nodo-instancia"',
        'id="nodo-controlfiles"',
        'id="nodo-redo"',
        'id="nodo-contenedor-3"',
        "USERS01.DBF",
        "Observaciones",
        "ARCH_001",
        'href="#nodo-archivado"',
        "/estaticos/htmx.min.js",
    ):
        assert esperado in html


def test_explorar_manual_redirige(cliente: TestClient) -> None:
    respuesta = cliente.get("/explorar", params={"sid": " xe "}, follow_redirects=False)
    assert respuesta.headers["location"] == "/instancias/XE"


def test_estaticos_disponibles(cliente: TestClient) -> None:
    assert cliente.get("/estaticos/htmx.min.js").status_code == 200
    assert cliente.get("/estaticos/app.css").status_code == 200
    assert cliente.get("/estaticos/app.js").status_code == 200


def test_texto_con_html_se_escapa(cliente: TestClient, servicio: ServicioFalso) -> None:
    perfil = servicio.exploracion.perfil
    datafiles = [perfil.datafiles[0].model_copy(update={"ruta": "C:\\ORACLE\\<script>alert(1)</script>.DBF"})]
    servicio.exploracion = servicio.exploracion.__class__(
        perfil=perfil.model_copy(update={"datafiles": datafiles + perfil.datafiles[1:]}),
        hallazgos=servicio.exploracion.hallazgos,
    )
    html = cliente.get("/instancias/XE").text
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_criterios_muestra_prioridades_esquemas_y_vocabulario(cliente: TestClient) -> None:
    respuesta = cliente.get("/criterios")
    assert respuesta.status_code == 200
    assert "ALTA" in respuesta.text
    assert "MEDIA" in respuesta.text
    assert "BAJA" in respuesta.text
    assert "total+" in respuesta.text
    assert "BACKUP INCREMENTAL LEVEL 0 DATABASE" in respuesta.text
    assert "Parcial" in respuesta.text


def test_evidencias_lista_las_diez_y_descarga_como_adjunto(
    cliente: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "E1_explorador.html").write_text("<script>alert(1)</script>", encoding="utf-8")
    monkeypatch.setenv("CLOUDCR_EVIDENCIAS_DIR", str(tmp_path))
    respuesta = cliente.get("/evidencias")
    assert respuesta.status_code == 200
    assert "1 de 10 capturadas" in respuesta.text
    assert "Pendiente" in respuesta.text
    descarga = cliente.get("/evidencias/archivo/E1_explorador.html")
    assert descarga.status_code == 200
    assert descarga.headers["content-disposition"].startswith("attachment")
    assert cliente.get("/evidencias/archivo/../x").status_code in (404, 400)
    assert len(cliente.get("/api/evidencias").json()["evidencias"]) == 10
