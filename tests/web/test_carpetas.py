from pathlib import Path

from fastapi.testclient import TestClient


def test_sin_ruta_lista_las_unidades(cliente: TestClient) -> None:
    respuesta = cliente.get("/api/carpetas")
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["ruta"] == ""
    assert cuerpo["padre"] is None
    assert cuerpo["carpetas"]
    assert cuerpo["separador"]


def test_lista_las_subcarpetas(cliente: TestClient, tmp_path: Path) -> None:
    (tmp_path / "uno").mkdir()
    (tmp_path / "dos").mkdir()
    cuerpo = cliente.get("/api/carpetas", params={"ruta": str(tmp_path)}).json()
    assert [c["nombre"] for c in cuerpo["carpetas"]] == ["dos", "uno"]
    assert cuerpo["ruta"] == str(tmp_path)
    assert cuerpo["padre"] == str(tmp_path.parent)
    assert cuerpo["carpetas"][0]["ruta"] == str(tmp_path / "dos")


def test_carpeta_inexistente_da_404(cliente: TestClient, tmp_path: Path) -> None:
    respuesta = cliente.get("/api/carpetas", params={"ruta": str(tmp_path / "no_existe")})
    assert respuesta.status_code == 404
    assert respuesta.json()["errores"][0]["campo"] == "ruta"


def test_con_cercana_la_ruta_inexistente_responde_200_con_el_ancestro(cliente: TestClient, tmp_path: Path) -> None:
    respuesta = cliente.get("/api/carpetas", params={"ruta": str(tmp_path / "a" / "b"), "cercana": "true"})
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["ruta"] == str(tmp_path)
    assert cuerpo["solicitada_existe"] is False


def test_el_listado_indica_que_la_ruta_existe(cliente: TestClient, tmp_path: Path) -> None:
    assert cliente.get("/api/carpetas", params={"ruta": str(tmp_path)}).json()["solicitada_existe"] is True


def test_ruta_relativa_da_422(cliente: TestClient) -> None:
    respuesta = cliente.get("/api/carpetas", params={"ruta": "relativa/carpeta"})
    assert respuesta.status_code == 422
    assert "absoluta" in respuesta.json()["errores"][0]["mensaje"]


def test_crear_carpeta(cliente: TestClient, tmp_path: Path) -> None:
    respuesta = cliente.post("/api/carpetas", json={"padre": str(tmp_path), "nombre": "nueva"})
    assert respuesta.status_code == 201
    assert respuesta.json() == {"nombre": "nueva", "ruta": str(tmp_path / "nueva")}
    assert (tmp_path / "nueva").is_dir()


def test_crear_carpeta_existente_da_409(cliente: TestClient, tmp_path: Path) -> None:
    (tmp_path / "ya").mkdir()
    respuesta = cliente.post("/api/carpetas", json={"padre": str(tmp_path), "nombre": "ya"})
    assert respuesta.status_code == 409


def test_crear_carpeta_con_nombre_invalido_da_422(cliente: TestClient, tmp_path: Path) -> None:
    for nombre in ("..", "a/b", "a:b", ""):
        respuesta = cliente.post("/api/carpetas", json={"padre": str(tmp_path), "nombre": nombre})
        assert respuesta.status_code == 422
    assert [p.name for p in tmp_path.iterdir()] == []


def test_crear_carpeta_en_un_padre_inexistente_da_404(cliente: TestClient, tmp_path: Path) -> None:
    respuesta = cliente.post("/api/carpetas", json={"padre": str(tmp_path / "no_existe"), "nombre": "x"})
    assert respuesta.status_code == 404


def test_crear_carpeta_sin_datos_da_422(cliente: TestClient) -> None:
    respuesta = cliente.post("/api/carpetas", json={})
    assert respuesta.status_code == 422
    assert {e["campo"] for e in respuesta.json()["errores"]} == {"padre", "nombre"}
