from pathlib import Path

import pytest
from typer.testing import CliRunner

from cloudcr_backup.cli.app import app
from cloudcr_backup.domain.errores import RecursoNoEncontrado
from cloudcr_backup.services import evidencias


@pytest.fixture
def carpeta(tmp_path: Path) -> Path:
    (tmp_path / "E1_explorador.html").write_text("x", encoding="utf-8")
    (tmp_path / "E3_E5_en_linea.md").write_text("x", encoding="utf-8")
    (tmp_path / "E2_script_alterado").mkdir()
    (tmp_path / "E2_script_alterado" / "evidencia.json").write_text("{}", encoding="utf-8")
    (tmp_path / "procedimiento_E6_E7.md").write_text("x", encoding="utf-8")
    return tmp_path


def test_catalogo_marca_las_capturadas_y_las_pendientes(carpeta: Path) -> None:
    catalogo = evidencias.catalogo(carpeta)
    por_id = {e.id: e for e in catalogo.evidencias}
    assert por_id["E1"].disponible
    assert por_id["E2"].archivos == ["E2_script_alterado/evidencia.json"]
    assert por_id["E3"].disponible and por_id["E5"].disponible
    assert not por_id["E6"].disponible
    assert not por_id["E7"].disponible
    assert catalogo.disponibles == 4
    assert len(catalogo.evidencias) == 10


def test_ruta_de_archivo_no_permite_salir_de_la_carpeta(
    carpeta: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    fuera = tmp_path_factory.mktemp("fuera") / "secreto.txt"
    fuera.write_text("no", encoding="utf-8")
    assert evidencias.ruta_de_archivo("E1_explorador.html", carpeta).name == "E1_explorador.html"
    with pytest.raises(RecursoNoEncontrado):
        evidencias.ruta_de_archivo("../" + fuera.parent.name + "/secreto.txt", carpeta)
    with pytest.raises(RecursoNoEncontrado):
        evidencias.ruta_de_archivo("no_existe.txt", carpeta)


def test_comando_evidencias(carpeta: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(evidencias.VARIABLE_CARPETA, str(carpeta))
    monkeypatch.setenv("COLUMNS", "200")
    resultado = CliRunner().invoke(app, ["evidencias"])
    assert resultado.exit_code == 0, resultado.output
    assert "4 de 10 capturadas" in resultado.output
    assert "Pendiente" in resultado.output
