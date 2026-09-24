from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cloudcr_backup.oracle.discovery import InstanciaDescubierta
from cloudcr_backup.oracle.explorador import Exploracion
from cloudcr_backup.web.app import crear_app
from cloudcr_backup.web.config import ConfigWeb

HOME_FICTICIO = Path("C:/oracle/product/21c/dbhomeXE")


class ServicioFalso:
    def __init__(self, exploracion: Exploracion, instancias: list[InstanciaDescubierta]) -> None:
        self.exploracion = exploracion
        self.instancias = instancias
        self.error: Exception | None = None
        self.llamadas: list[tuple[str, Path | None, bool]] = []

    def descubrir(self, refrescar: bool = False) -> list[InstanciaDescubierta]:
        return list(self.instancias)

    def explorar(self, sid: str, oracle_home: Path | None, refrescar: bool) -> tuple[Exploracion, float]:
        self.llamadas.append((sid, oracle_home, refrescar))
        if self.error is not None:
            raise self.error
        return self.exploracion, 5.0


@pytest.fixture
def instancias_ficticias() -> list[InstanciaDescubierta]:
    return [InstanciaDescubierta(sid="XE", oracle_home=HOME_FICTICIO, en_ejecucion=True, origenes=("servicio",))]


@pytest.fixture
def servicio(exploracion_xe: Exploracion, instancias_ficticias: list[InstanciaDescubierta]) -> ServicioFalso:
    return ServicioFalso(exploracion_xe, instancias_ficticias)


@pytest.fixture
def config_pruebas() -> ConfigWeb:
    return ConfigWeb(clientes_sin_token=frozenset({"testclient"}), hosts_permitidos=frozenset({"testserver"}))


@pytest.fixture
def cliente(config_pruebas: ConfigWeb, servicio: ServicioFalso) -> TestClient:
    return TestClient(crear_app(config_pruebas, servicio=servicio))


@pytest.fixture
def cabecera_htmx() -> dict[str, str]:
    return {"HX-Request": "true"}
