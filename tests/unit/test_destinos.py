from pathlib import Path

import pytest

from cloudcr_backup.services import destinos
from cloudcr_backup.services.destinos import ErrorDestino


def test_ruta_absoluta_de_windows_se_reconoce() -> None:
    assert destinos.ruta_es_absoluta(r"C:\backups\XE")
    assert not destinos.ruta_es_absoluta(r"backups\XE")
    assert not destinos.ruta_es_absoluta("")


def test_normalizar_ruta_quita_espacios_y_unifica_separadores() -> None:
    assert destinos.normalizar_ruta("  C:/backups/XE  ") == r"C:\backups\XE"


def test_sin_ruta_lista_las_unidades() -> None:
    listado = destinos.listar_carpetas(None)
    assert listado.ruta == ""
    assert listado.padre is None
    assert listado.carpetas


def test_lista_las_subcarpetas_en_orden_y_omite_archivos(tmp_path: Path) -> None:
    (tmp_path / "beta").mkdir()
    (tmp_path / "Alfa").mkdir()
    (tmp_path / "archivo.txt").write_text("x", encoding="utf-8")
    listado = destinos.listar_carpetas(str(tmp_path))
    assert [c.nombre for c in listado.carpetas] == ["Alfa", "beta"]
    assert listado.ruta == str(tmp_path)
    assert listado.padre == str(tmp_path.parent)
    assert not listado.truncado


def test_en_la_raiz_de_una_unidad_el_padre_es_la_lista_de_unidades(tmp_path: Path) -> None:
    raiz = Path(tmp_path.anchor)
    assert destinos.listar_carpetas(str(raiz)).padre == ""


def test_con_cercana_una_ruta_inexistente_muestra_el_ancestro_que_si_existe(tmp_path: Path) -> None:
    listado = destinos.listar_carpetas(str(tmp_path / "no" / "existe"), cercana=True)
    assert listado.ruta == str(tmp_path)
    assert not listado.solicitada_existe


def test_con_cercana_una_ruta_existente_se_muestra_tal_cual(tmp_path: Path) -> None:
    listado = destinos.listar_carpetas(str(tmp_path), cercana=True)
    assert listado.ruta == str(tmp_path)
    assert listado.solicitada_existe


def test_con_cercana_una_ruta_relativa_cae_a_las_unidades() -> None:
    listado = destinos.listar_carpetas("relativa/carpeta", cercana=True)
    assert listado.ruta == ""
    assert listado.carpetas
    assert not listado.solicitada_existe


def test_ruta_relativa_se_rechaza() -> None:
    with pytest.raises(ErrorDestino) as error:
        destinos.listar_carpetas("carpeta/relativa")
    assert error.value.tipo == "invalido"


def test_carpeta_inexistente_se_informa(tmp_path: Path) -> None:
    with pytest.raises(ErrorDestino) as error:
        destinos.listar_carpetas(str(tmp_path / "no_existe"))
    assert error.value.tipo == "no_existe"


def test_un_archivo_no_es_una_carpeta(tmp_path: Path) -> None:
    archivo = tmp_path / "datos.txt"
    archivo.write_text("x", encoding="utf-8")
    with pytest.raises(ErrorDestino) as error:
        destinos.listar_carpetas(str(archivo))
    assert error.value.tipo == "no_existe"


def test_la_lista_se_trunca_cuando_hay_demasiadas_carpetas(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(destinos, "MAXIMO_CARPETAS_LISTADAS", 2)
    for nombre in ("a", "b", "c"):
        (tmp_path / nombre).mkdir()
    listado = destinos.listar_carpetas(str(tmp_path))
    assert len(listado.carpetas) == 2
    assert listado.truncado


def test_crear_carpeta(tmp_path: Path) -> None:
    carpeta = destinos.crear_carpeta(str(tmp_path), "  respaldos  ")
    assert carpeta.nombre == "respaldos"
    assert (tmp_path / "respaldos").is_dir()


def test_crear_carpeta_existente_falla(tmp_path: Path) -> None:
    (tmp_path / "ya_existe").mkdir()
    with pytest.raises(ErrorDestino) as error:
        destinos.crear_carpeta(str(tmp_path), "ya_existe")
    assert error.value.tipo == "existe"


@pytest.mark.parametrize(
    "nombre", ["", "   ", ".", "..", "a/b", "a\\b", "a:b", "a*b", "a?b", 'a"b', "a<b", "a|b", "fin."]
)
def test_crear_carpeta_con_nombre_invalido_falla(tmp_path: Path, nombre: str) -> None:
    with pytest.raises(ErrorDestino) as error:
        destinos.crear_carpeta(str(tmp_path), nombre)
    assert error.value.tipo == "invalido"


def test_crear_carpeta_con_nombre_demasiado_largo_falla(tmp_path: Path) -> None:
    with pytest.raises(ErrorDestino):
        destinos.crear_carpeta(str(tmp_path), "x" * 101)


def test_crear_carpeta_en_un_padre_inexistente_falla(tmp_path: Path) -> None:
    with pytest.raises(ErrorDestino) as error:
        destinos.crear_carpeta(str(tmp_path / "no_existe"), "nueva")
    assert error.value.tipo == "no_existe"


def test_destino_existente_es_escribible_y_no_deja_archivos(tmp_path: Path) -> None:
    estado = destinos.inspeccionar_destino(str(tmp_path))
    assert estado.escribible
    assert estado.libre_bytes is not None
    assert estado.total_bytes is not None
    assert list(tmp_path.iterdir()) == []


def test_destino_inexistente_no_es_escribible_pero_informa_el_espacio_del_volumen(tmp_path: Path) -> None:
    estado = destinos.inspeccionar_destino(str(tmp_path / "no" / "existe"))
    assert not estado.escribible
    assert estado.libre_bytes is not None


def test_un_archivo_como_destino_no_es_escribible(tmp_path: Path) -> None:
    archivo = tmp_path / "datos.txt"
    archivo.write_text("x", encoding="utf-8")
    assert not destinos.inspeccionar_destino(str(archivo)).escribible
