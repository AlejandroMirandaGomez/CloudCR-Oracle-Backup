from pathlib import Path

import pytest

from cloudcr_backup.config.ajustes import cargar_ajustes, obtener_clave_repositorio


def test_usa_valores_predeterminados_sin_config(tmp_path: Path) -> None:
    ajustes = cargar_ajustes(ruta_config=tmp_path / "no_existe.yaml")
    assert ajustes.repositorio_usuario == "BKP_ADMIN"
    assert ajustes.nls_lang == "AMERICAN_AMERICA.AL32UTF8"


def test_yaml_sobreescribe_el_valor_predeterminado(tmp_path: Path) -> None:
    ruta = tmp_path / "cloudcr.yaml"
    ruta.write_text("repositorio_usuario: OTRO_USUARIO\n", encoding="utf-8")
    ajustes = cargar_ajustes(ruta_config=ruta)
    assert ajustes.repositorio_usuario == "OTRO_USUARIO"


def test_variable_de_entorno_tiene_prioridad_sobre_el_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ruta = tmp_path / "cloudcr.yaml"
    ruta.write_text("repositorio_usuario: DEL_YAML\n", encoding="utf-8")
    monkeypatch.setenv("CLOUDCR_REPOSITORIO_USUARIO", "DEL_ENTORNO")
    ajustes = cargar_ajustes(ruta_config=ruta)
    assert ajustes.repositorio_usuario == "DEL_ENTORNO"


def test_override_explicito_tiene_prioridad_sobre_todo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ruta = tmp_path / "cloudcr.yaml"
    ruta.write_text("repositorio_usuario: DEL_YAML\n", encoding="utf-8")
    monkeypatch.setenv("CLOUDCR_REPOSITORIO_USUARIO", "DEL_ENTORNO")
    ajustes = cargar_ajustes(ruta_config=ruta, repositorio_usuario="DEL_FLAG")
    assert ajustes.repositorio_usuario == "DEL_FLAG"


def test_clave_repositorio_nunca_sale_del_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLOUDCR_REPO_CLAVE", raising=False)
    assert obtener_clave_repositorio() is None
    monkeypatch.setenv("CLOUDCR_REPO_CLAVE", "secreta")
    assert obtener_clave_repositorio() == "secreta"
