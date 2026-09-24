from pathlib import Path

from cloudcr_backup.domain.enums import TipoArchivoParametros
from cloudcr_backup.oracle.inspector import buscar_pfiles, clasificar_pfile, directorios_pfile


def test_clasificar_pfile() -> None:
    assert clasificar_pfile("initXE.ora", "xe") is TipoArchivoParametros.PFILE_INSTANCIA
    assert clasificar_pfile("init.ora", "xe") is TipoArchivoParametros.PFILE_EJEMPLO
    assert clasificar_pfile("init.ora.7232026235414", "xe") is TipoArchivoParametros.PFILE_CREACION
    assert clasificar_pfile("initORCL.ora", "xe") is TipoArchivoParametros.PFILE_OTRO


def test_directorios_pfile_incluye_home_spfile_y_admin(tmp_path: Path) -> None:
    directorios = directorios_pfile(str(tmp_path / "home"), str(tmp_path / "db" / "spfileXE.ora"), str(tmp_path), "XE")
    assert tmp_path / "home" / "database" in directorios
    assert tmp_path / "home" / "dbs" in directorios
    assert tmp_path / "db" in directorios
    assert tmp_path / "admin" / "XE" / "pfile" in directorios


def test_buscar_pfiles_excluye_spfile_y_duplicados(tmp_path: Path) -> None:
    (tmp_path / "initXE.ora").write_text("x", encoding="ascii")
    (tmp_path / "init.ora.123").write_text("x", encoding="ascii")
    (tmp_path / "spfileXE.ora").write_text("x", encoding="ascii")
    (tmp_path / "otro.txt").write_text("x", encoding="ascii")
    encontrados = buscar_pfiles([tmp_path, tmp_path], str(tmp_path / "spfileXE.ora"))
    assert [Path(r).name for r in encontrados] == ["init.ora.123", "initXE.ora"]
