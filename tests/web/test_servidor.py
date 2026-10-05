from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cloudcr_backup.cli.app import app
from cloudcr_backup.web import servidor
from cloudcr_backup.web.config import ConfigWeb

URL = "http://127.0.0.1:8765/"
HOME_ORACLE = Path("C:/oracle/dbhome")


def _iniciar(
    monkeypatch: pytest.MonkeyPatch, config: ConfigWeb, cliente_oracle: Path | None
) -> tuple[list[str], list[str]]:
    avisos: list[str] = []
    informes: list[str] = []
    monkeypatch.setattr(servidor, "preparar_cliente_oracle", lambda: cliente_oracle)
    monkeypatch.setattr(servidor, "puerto_libre", lambda host, desde: desde)
    monkeypatch.setattr(servidor, "crear_app", lambda configuracion: object())
    monkeypatch.setattr(servidor.uvicorn, "run", lambda *args, **kwargs: None)
    servidor.iniciar_servidor(config, abrir_navegador=False, avisar=avisos.append, informar=informes.append)
    return avisos, informes


def test_el_cliente_oracle_se_informa_aparte_del_aviso_de_la_url(
    monkeypatch: pytest.MonkeyPatch, config_pruebas: ConfigWeb
) -> None:
    avisos, informes = _iniciar(monkeypatch, config_pruebas, HOME_ORACLE)
    assert avisos == [servidor.url_acceso(config_pruebas)]
    assert len(informes) == 1
    assert informes[0].startswith("Cliente Oracle iniciado desde ")
    assert str(HOME_ORACLE) in informes[0]


def test_sin_cliente_oracle_solo_se_avisa_la_url(monkeypatch: pytest.MonkeyPatch, config_pruebas: ConfigWeb) -> None:
    avisos, informes = _iniciar(monkeypatch, config_pruebas, None)
    assert avisos == [servidor.url_acceso(config_pruebas)]
    assert informes == []


def test_la_consola_no_antepone_la_interfaz_web_al_aviso_del_cliente_oracle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def servidor_falso(
        config: ConfigWeb,
        abrir_navegador: bool,
        avisar: Callable[[str], None],
        informar: Callable[[str], None],
    ) -> None:
        informar("Cliente Oracle iniciado desde C:\\oracle\\dbhome (antes de abrir el repositorio).")
        avisar(URL)

    monkeypatch.setattr(servidor, "iniciar_servidor", servidor_falso)
    monkeypatch.setenv("COLUMNS", "250")
    resultado = CliRunner().invoke(app, ["web", "--no-abrir", "--sin-agente"])
    lineas = [linea.strip() for linea in resultado.output.splitlines() if linea.strip()]
    assert lineas == [
        "Cliente Oracle iniciado desde C:\\oracle\\dbhome (antes de abrir el repositorio).",
        f"Interfaz web disponible en {URL}",
        "Presione Ctrl+C para detenerla.",
    ]
