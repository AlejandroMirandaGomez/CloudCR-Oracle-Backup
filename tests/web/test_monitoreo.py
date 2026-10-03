import re
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient
from rich.table import Table

from cloudcr_backup.domain.errores import RepositorioNoDisponible
from cloudcr_backup.presentacion.historial import construir_tabla
from cloudcr_backup.presentacion.terminal_monitoreo import tabla_historial
from cloudcr_backup.web.app import crear_app
from cloudcr_backup.web.config import ConfigWeb
from tests.web.conftest import ServicioFalso
from tests.web.monitoreo_falso import MonitoreoFalso

PAGINAS = ("/estado", "/historial", "/historial/40", "/alertas", "/estrategias", "/estrategias/XE/EST001")
ORIGEN_AJENO = {"origin": "http://atacante.example"}


@pytest.fixture
def monitoreo() -> MonitoreoFalso:
    return MonitoreoFalso()


@pytest.fixture
def web(config_pruebas: ConfigWeb, servicio: ServicioFalso, monitoreo: MonitoreoFalso) -> TestClient:
    return TestClient(crear_app(config_pruebas, servicio=servicio, monitoreo_servicio=monitoreo))


class Celdas(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.filas: list[list[str]] = []
        self._fila: list[str] | None = None
        self._celda: list[str] | None = None
        self._en_cuerpo = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tbody":
            self._en_cuerpo = True
        elif tag == "tr" and self._en_cuerpo:
            self._fila = []
        elif tag == "td" and self._fila is not None:
            self._celda = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._fila is not None and self._celda is not None:
            self._fila.append("".join(self._celda).strip())
            self._celda = None
        elif tag == "tr" and self._fila is not None:
            self.filas.append(self._fila)
            self._fila = None
        elif tag == "tbody":
            self._en_cuerpo = False

    def handle_data(self, data: str) -> None:
        if self._celda is not None:
            self._celda.append(data)


@pytest.mark.parametrize("ruta", PAGINAS)
def test_paginas_completas(web: TestClient, ruta: str) -> None:
    respuesta = web.get(ruta)
    assert respuesta.status_code == 200, respuesta.text
    assert "<html" in respuesta.text
    assert 'href="/estado"' in respuesta.text
    assert 'aria-current="page"' in respuesta.text


@pytest.mark.parametrize("ruta", PAGINAS)
def test_sin_scripts_ni_estilos_en_linea(web: TestClient, ruta: str) -> None:
    html = web.get(ruta).text
    assert not re.search(r"<script(?![^>]*\bsrc=)", html)
    assert " style=" not in html
    assert "<style" not in html
    assert not re.search(r"\son[a-z]+\s*=", html)


@pytest.mark.parametrize("ruta", ("/estado", "/historial", "/alertas"))
def test_fragmentos_htmx(web: TestClient, ruta: str, cabecera_htmx: dict[str, str]) -> None:
    respuesta = web.get(ruta, headers=cabecera_htmx)
    assert respuesta.status_code == 200
    assert "<html" not in respuesta.text
    assert "<table" in respuesta.text


def test_estado_muestra_semaforo_con_texto(web: TestClient) -> None:
    html = web.get("/estado").text
    assert "✕ Rojo" in html
    assert "Última ejecución de T1: Error." in html
    assert "SIMULACIÓN" in html
    assert 'hx-trigger="every 30s"' in html


def test_nombres_se_escapan(web: TestClient) -> None:
    for ruta in ("/estado", "/estrategias", "/estrategias/XE/EST001"):
        html = web.get(ruta).text
        assert "<script>alert(1)</script>" not in html, ruta
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html, ruta


def test_api_estado_y_agente(web: TestClient) -> None:
    datos = web.get("/api/estado").json()
    assert datos["semaforos"][0]["color"] == "ROJO"
    assert web.get("/api/estado", params={"bd": "ORCL"}).json()["semaforos"] == []
    [agente] = web.get("/api/agente").json()
    assert agente["vivo"] is True
    assert agente["latido"]["simulado"] is True


def test_historial_pasa_los_filtros_y_pagina(web: TestClient, monitoreo: MonitoreoFalso) -> None:
    respuesta = web.get(
        "/historial",
        params={
            "bd": "xe",
            "estrategia": "EST001",
            "estado": "fallida",
            "desde": "2026-10-01",
            "limite": "25",
            "pagina": "2",
        },
    )
    assert respuesta.status_code == 200
    consulta = monitoreo.consultas[-1]
    assert consulta.bd == "xe"
    assert consulta.estado is not None and consulta.estado.value == "FALLIDA"
    assert consulta.desde is not None and consulta.desde.isoformat() == "2026-10-01"
    assert (consulta.limite, consulta.pagina) == (25, 2)
    assert "Página 2 de 5" in respuesta.text
    assert "pagina=1" in respuesta.text and "pagina=3" in respuesta.text
    assert "/historial/exportar/csv?bd=xe&amp;estrategia=EST001&amp;estado=FALLIDA" in respuesta.text


def test_filtros_vacios_se_ignoran(web: TestClient, monitoreo: MonitoreoFalso) -> None:
    assert web.get("/historial", params={"bd": "", "estado": "", "desde": ""}).status_code == 200
    consulta = monitoreo.consultas[-1]
    assert (consulta.bd, consulta.estado, consulta.desde) == (None, None, None)


def test_fecha_invalida(web: TestClient) -> None:
    api = web.get("/api/historial", params={"desde": "03/10/2026"})
    assert api.status_code == 422
    assert "AAAA-MM-DD" in api.json()["errores"][0]["sugerencia"]
    pagina = web.get("/historial", params={"estado": "INVENTADO"})
    assert pagina.status_code == 422
    assert "<html" in pagina.text
    assert "Revise los filtros" in pagina.text


def test_api_historial(web: TestClient) -> None:
    datos = web.get("/api/historial").json()
    assert datos["total"] == 120
    assert datos["columnas"][5] == "◆"
    assert datos["tabla"][1][10] == "Error"
    assert datos["filas"][0]["estrategia"] == "EST001"


def test_detalle_de_ejecucion(web: TestClient) -> None:
    html = web.get("/historial/41").text
    assert "RMAN-03009" in html
    assert "evidencia.json" in html
    assert web.get("/api/historial/41").json()["errores"].startswith("RMAN-03009")
    assert web.get("/historial/99").status_code == 404
    assert web.get("/api/historial/99").status_code == 404


@pytest.mark.parametrize(("formato", "tipo"), [("csv", "text/csv"), ("md", "text/markdown"), ("html", "text/html")])
def test_exportaciones(web: TestClient, formato: str, tipo: str) -> None:
    respuesta = web.get(f"/historial/exportar/{formato}", params={"bd": "XE"})
    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"].startswith(tipo)
    assert respuesta.headers["content-disposition"] == f'attachment; filename="historial-prueba.{formato}"'


def test_exportacion_con_formato_desconocido(web: TestClient) -> None:
    assert web.get("/historial/exportar/pdf").status_code == 409


def test_historial_web_y_cli_muestran_las_mismas_filas(web: TestClient, monitoreo: MonitoreoFalso) -> None:
    esperado = construir_tabla(monitoreo.filas).matriz()
    parser = Celdas()
    parser.feed(web.get("/historial").text)
    web_filas = [fila[1:] for fila in parser.filas]
    for fila_web, fila_esperada in zip(web_filas, esperado, strict=True):
        assert fila_web[:7] == fila_esperada[:7]
        assert fila_web[8:] == fila_esperada[8:]
        assert fila_web[7].startswith(fila_esperada[7])
    cli: Table = tabla_historial(construir_tabla(monitoreo.filas))
    columnas = [[str(celda) for celda in columna._cells] for columna in cli.columns]
    cli_filas = [list(fila)[1:] for fila in zip(*columnas, strict=True)]
    assert cli_filas == esperado
    assert web.get("/api/historial").json()["tabla"] == esperado


def test_alertas_lista_y_acciones_htmx(
    web: TestClient, monitoreo: MonitoreoFalso, cabecera_htmx: dict[str, str]
) -> None:
    html = web.get("/alertas").text
    assert "Reconocer" in html and "Resolver" in html
    assert 'hx-confirm="¿Reconocer la alerta 7' in html
    respuesta = web.post("/alertas/7/reconocer", headers=cabecera_htmx)
    assert respuesta.status_code == 200
    assert "Alerta 7 (EJECUCION_FALLIDA) reconocida." in respuesta.text
    assert "<html" not in respuesta.text
    assert monitoreo.acciones == ["reconocer:7"]


def test_accion_sin_javascript_redirige(web: TestClient) -> None:
    respuesta = web.post("/alertas/7/resolver", params={"estado": "todas"}, follow_redirects=False)
    assert respuesta.status_code == 303
    assert respuesta.headers["location"] == "/alertas?estado=todas&severidad="


def test_evaluar_desde_la_pantalla(web: TestClient, cabecera_htmx: dict[str, str]) -> None:
    respuesta = web.post("/alertas/evaluar", headers=cabecera_htmx)
    assert "1 nuevas" in respuesta.text and "1 resueltas" in respuesta.text


def test_api_alertas(web: TestClient, monitoreo: MonitoreoFalso) -> None:
    assert web.get("/api/alertas").json()[0]["id"] == 7
    assert web.post("/api/alertas/7/reconocer").json()["estado"] == "RECONOCIDA"
    conflicto = web.post("/api/alertas/8/reconocer")
    assert conflicto.status_code == 409
    assert "RESUELTA" in conflicto.json()["errores"][0]["mensaje"]
    assert web.post("/api/alertas/7/resolver").json()["estado"] == "RESUELTA"
    assert web.post("/api/alertas/evaluar").json()["abiertas"] == ["X:1"]


@pytest.mark.parametrize(
    "ruta",
    (
        "/api/alertas/7/reconocer",
        "/api/alertas/7/resolver",
        "/api/alertas/evaluar",
        "/alertas/7/reconocer",
        "/api/estrategias/XE/EST001/desactivar",
        "/estrategias/XE/EST001/desactivar",
    ),
)
def test_post_desde_otro_origen_se_rechaza(web: TestClient, monitoreo: MonitoreoFalso, ruta: str) -> None:
    respuesta = web.post(ruta, headers=ORIGEN_AJENO)
    assert respuesta.status_code == 403
    assert monitoreo.acciones == []


def test_estrategias(web: TestClient) -> None:
    html = web.get("/estrategias").text
    assert 'href="/estrategias/XE/EST001"' in html
    assert "/instancias/XE/estrategias/nueva" in html
    detalle = web.get("/estrategias/XE/EST001").text
    assert "Incremental nivel 0 (total+)" in detalle
    assert "«total+»" in detalle
    assert "Diaria a las 13:00" in detalle
    assert "domingo 2026-10-04 07:00" in detalle
    assert "Desactivar" in detalle
    assert web.get("/estrategias/XE/EST999").status_code == 404


def test_activar_y_desactivar(web: TestClient, monitoreo: MonitoreoFalso, cabecera_htmx: dict[str, str]) -> None:
    respuesta = web.post("/estrategias/XE/EST001/desactivar", headers=cabecera_htmx)
    assert "Estrategia EST001 desactivada." in respuesta.text
    assert "Activar" in respuesta.text
    sin_js = web.post("/estrategias/XE/EST001/activar", follow_redirects=False)
    assert sin_js.status_code == 303
    assert sin_js.headers["location"] == "/estrategias/XE/EST001"
    assert monitoreo.acciones == ["desactivar:XE/EST001", "activar:XE/EST001"]


def test_api_estrategias(web: TestClient) -> None:
    assert web.get("/api/estrategias").json()[0]["codigo"] == "EST001"
    detalle = web.get("/api/estrategias/XE/EST001", params={"n": 3}).json()
    assert len(detalle["tareas"][0]["proximas"]) == 3
    proximas = web.get("/api/estrategias/XE/EST001/tareas/T1/proximas", params={"n": 4}).json()
    assert len(proximas["proximas"]) == 4
    assert web.get("/api/estrategias/XE/EST001/tareas/T1/proximas", params={"n": 0}).status_code == 422
    assert web.post("/api/estrategias/XE/EST001/desactivar").json()["estado"] == "INACTIVA"
    assert web.post("/api/estrategias/XE/EST001/activar").json()["estado"] == "ACTIVA"


@pytest.mark.parametrize("ruta", ("/api/estado", "/api/historial", "/api/alertas", "/api/estrategias", "/api/agente"))
def test_repositorio_caido_es_503_con_sugerencia_en_json(web: TestClient, monitoreo: MonitoreoFalso, ruta: str) -> None:
    monitoreo.error = RepositorioNoDisponible("ORA-12541: no listener", "Inicie el listener.")
    respuesta = web.get(ruta)
    assert respuesta.status_code == 503
    assert respuesta.json()["errores"][0] == {
        "campo": "",
        "mensaje": "ORA-12541: no listener",
        "sugerencia": "Inicie el listener.",
    }


@pytest.mark.parametrize("ruta", PAGINAS)
def test_repositorio_caido_es_panel_amable(web: TestClient, monitoreo: MonitoreoFalso, ruta: str) -> None:
    monitoreo.error = RepositorioNoDisponible("ORA-12541: no listener", "Inicie el listener.")
    respuesta = web.get(ruta)
    assert respuesta.status_code == 503
    assert "El repositorio no está disponible" in respuesta.text
    assert "Inicie el listener." in respuesta.text
    assert "Traceback" not in respuesta.text


def test_repositorio_caido_en_fragmento(
    web: TestClient, monitoreo: MonitoreoFalso, cabecera_htmx: dict[str, str]
) -> None:
    monitoreo.error = RepositorioNoDisponible("sin repositorio")
    respuesta = web.get("/estado", headers=cabecera_htmx)
    assert respuesta.status_code == 200
    assert "<html" not in respuesta.text
    assert "sin repositorio" in respuesta.text
