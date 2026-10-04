from pathlib import Path

import pytest

from cloudcr_backup.execution import runner
from cloudcr_backup.execution.runner import InvocacionRman, RutaNoAdmitida
from cloudcr_backup.rman.render import ScriptNoAscii

HOME = Path("C:/oracle/home")


def invocacion(tmp_path: Path, **cambios: object) -> InvocacionRman:
    base: dict[str, object] = {
        "oracle_home": HOME,
        "sid": "XE",
        "script": tmp_path / "carpeta con espacios" / "EST001.XE.RMAN",
        "log": tmp_path / "carpeta con espacios" / "EST001.XE.LOG",
        "argumentos": ("EST001_T1_2610041300", "CLOUDCR_7"),
    }
    base.update(cambios)
    return InvocacionRman(**base)  # type: ignore[arg-type]


def test_comando_usa_rutas_relativas_y_pasa_tag_y_command_id(tmp_path: Path) -> None:
    partes = runner.comando(invocacion(tmp_path))
    assert partes[1:] == [
        "target",
        "/",
        "cmdfile=EST001.XE.RMAN",
        "log=EST001.XE.LOG",
        "using",
        "EST001_T1_2610041300",
        "CLOUDCR_7",
    ]
    assert partes[0].startswith(str(HOME))


def test_log_en_otra_carpeta_con_espacios_no_se_admite(tmp_path: Path) -> None:
    with pytest.raises(RutaNoAdmitida):
        runner.comando(invocacion(tmp_path, log=tmp_path / "otro lugar" / "x.log"))


def test_agregar_al_log(tmp_path: Path) -> None:
    assert "append" in runner.comando(invocacion(tmp_path, agregar_al_log=True, argumentos=()))


def test_entorno_fija_home_sid_y_nls_lang(tmp_path: Path) -> None:
    variables = runner.entorno(invocacion(tmp_path), base={"PATH": "x", "NLS_LANG": "SPANISH_SPAIN.WE8MSWIN1252"})
    assert variables["ORACLE_HOME"] == str(HOME)
    assert variables["ORACLE_SID"] == "XE"
    assert variables["NLS_LANG"] == "AMERICAN_AMERICA.AL32UTF8"
    assert variables["PATH"] == "x"


def test_escribir_script_en_ascii_sin_bom_y_con_lf(tmp_path: Path) -> None:
    ruta = tmp_path / "a" / "s.rman"
    runner.escribir_script(ruta, "\ufeffRUN {\r\n  BACKUP DATABASE;\r\n}")
    assert ruta.read_bytes() == b"RUN {\n  BACKUP DATABASE;\n}\n"


def test_escribir_script_no_ascii_falla(tmp_path: Path) -> None:
    with pytest.raises(ScriptNoAscii):
        runner.escribir_script(tmp_path / "s.rman", "BACKUP TABLESPACE AÑO;")


def test_lanzar_informa_cuando_rman_no_existe(tmp_path: Path) -> None:
    inv = invocacion(tmp_path, oracle_home=tmp_path / "no-existe")
    resultado = runner.lanzar(inv)
    assert not resultado.lanzado
    assert resultado.codigo_salida is None
    assert resultado.error_lanzamiento is not None


def test_linea_de_comando_cita_el_ejecutable_con_espacios() -> None:
    texto = runner.linea_de_comando(["C:\\Program Files\\rman.exe", "target", "/", "cmdfile=a.rman"])
    assert texto == '"C:\\Program Files\\rman.exe" target / cmdfile=a.rman'
