import json

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize(
    ("formato", "tipo", "fragmento"),
    [
        ("json", "application/json", '"perfil"'),
        ("md", "text/markdown", "# Instancia XE"),
        ("html", "text/html", "<html"),
    ],
)
def test_exportaciones(cliente: TestClient, formato: str, tipo: str, fragmento: str) -> None:
    respuesta = cliente.get(f"/instancias/XE/exportar/{formato}")
    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"].startswith(tipo)
    disposicion = respuesta.headers["content-disposition"]
    assert disposicion.startswith("attachment;")
    assert f".{formato}" in disposicion
    assert "instancia-XE-" in disposicion
    assert fragmento in respuesta.text


def test_exportacion_json_valida(cliente: TestClient) -> None:
    datos = json.loads(cliente.get("/instancias/XE/exportar/json").text)
    assert datos["perfil"]["nombre"] == "XE"


def test_exportacion_con_filtro(cliente: TestClient) -> None:
    texto = cliente.get("/instancias/XE/exportar/md", params={"pdb": "XEPDB1"}).text
    assert "XEPDB1" in texto
    assert "CDB$ROOT" not in texto


def test_formato_desconocido(cliente: TestClient) -> None:
    assert cliente.get("/instancias/XE/exportar/pdf").status_code == 404


def test_pdb_inexistente_en_exportacion(cliente: TestClient) -> None:
    assert cliente.get("/instancias/XE/exportar/json", params={"pdb": "NOEXISTE"}).status_code == 404
