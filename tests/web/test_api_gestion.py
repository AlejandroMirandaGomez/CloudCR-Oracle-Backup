from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.domain.administracion import (
    EstrategiaImportada,
    ParametroRepositorio,
    ResultadoValidacion,
    VistaBaseDatos,
)
from cloudcr_backup.domain.enums import Severidad
from cloudcr_backup.domain.errores import OperacionNoPermitida
from cloudcr_backup.domain.hallazgos import Hallazgo
from cloudcr_backup.domain.historial import ArchivoExportado
from cloudcr_backup.services import administracion, bases_datos, gestion_estrategias
from cloudcr_backup.web.app import crear_app
from cloudcr_backup.web.config import ConfigWeb
from tests.web.conftest import ServicioFalso
from tests.web.test_pantallas_operaciones import ControlFalso

ORIGEN_AJENO = {"origin": "http://atacante.example"}


@pytest.fixture
def control() -> ControlFalso:
    return ControlFalso()


@pytest.fixture
def api(config_pruebas: ConfigWeb, servicio: ServicioFalso, control: ControlFalso, tmp_path: Path) -> TestClient:
    app = crear_app(config_pruebas, servicio=servicio, ajustes=Ajustes(work_dir=tmp_path), control_agente=control)
    return TestClient(app)


def test_validar_incluye_si_es_bloqueante(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    resultado = ResultadoValidacion(
        bd="XE",
        estrategia="EST001",
        version=1,
        hallazgos=[Hallazgo(codigo="ARCH_004", severidad=Severidad.ERROR, mensaje="x", sujeto="EST001")],
        perfil_capturado_en=datetime(2026, 10, 4, 13),
    )
    monkeypatch.setattr(gestion_estrategias, "validar", lambda a, bd, codigo: resultado)
    cuerpo = api.get("/api/estrategias/XE/EST001/validar").json()
    assert cuerpo["bloqueante"] is True
    assert cuerpo["hallazgos"][0]["codigo"] == "ARCH_004"


def test_importar_y_exportar_yaml(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    recibido: list[Any] = []

    def importar(a: Any, bd: str, contenido: str, reemplazar: bool) -> EstrategiaImportada:
        recibido.append((bd, contenido, reemplazar))
        return EstrategiaImportada(bd="XE", codigo="EST002", nombre="Consistente", version=1)

    monkeypatch.setattr(gestion_estrategias, "importar", importar)
    respuesta = api.post("/api/estrategias/importar", json={"bd": "XE", "contenido": "codigo: EST002"})
    assert respuesta.status_code == 201
    assert recibido == [("XE", "codigo: EST002", False)]
    assert api.post("/api/estrategias/importar", json={"bd": "XE", "contenido": ""}).status_code == 422
    archivo = ArchivoExportado(nombre="XE_EST002_v1.yaml", tipo_contenido="application/x-yaml", contenido=b"codigo: X")
    monkeypatch.setattr(gestion_estrategias, "exportar", lambda a, bd, codigo: archivo)
    assert api.get("/api/estrategias/XE/EST002/yaml").json() == {
        "nombre": "XE_EST002_v1.yaml",
        "contenido": "codigo: X",
    }


def test_parametros_por_api(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        administracion, "asignar_parametro", lambda a, clave, valor: ParametroRepositorio(clave=clave, valor=valor)
    )
    respuesta = api.put("/api/sistema/parametros/agente.tick_segundos", json={"valor": "20"})
    assert respuesta.json() == {"clave": "agente.tick_segundos", "valor": "20", "inicial": None}


def test_errores_de_servicio_en_json(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def registrar(*a: Any) -> VistaBaseDatos:
        raise OperacionNoPermitida("La base XE ya está registrada.")

    monkeypatch.setattr(bases_datos, "registrar", registrar)
    respuesta = api.post("/api/sistema/bases", json={"sid": "XE"})
    assert respuesta.status_code == 409
    assert respuesta.json()["errores"][0]["mensaje"] == "La base XE ya está registrada."


def test_control_del_agente_por_api(api: TestClient, control: ControlFalso) -> None:
    assert api.get("/api/sistema/agente").json()["corriendo"] is False
    assert api.post("/api/sistema/agente/iniciar", json={"simulado": True}).json()["corriendo"] is True
    assert api.post("/api/sistema/agente/detener").json()["corriendo"] is False
    assert api.post("/api/sistema/agente/iniciar", json={}, headers=ORIGEN_AJENO).status_code == 403
    assert control.llamadas == ["iniciar:True", "detener"]
