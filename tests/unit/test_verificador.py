from datetime import UTC, datetime
from pathlib import Path

from cloudcr_backup.domain.enums import EstadoPrueba
from cloudcr_backup.execution.correlator import PiezaCatalogo
from cloudcr_backup.execution.destino import BaseDestino
from cloudcr_backup.execution.runner import InvocacionRman, ResultadoRman
from cloudcr_backup.verification.verificador import script_verificacion, verificar

BASE = BaseDestino(oracle_home=Path("C:/oracle"), sid="XE")
MOMENTO = datetime(2026, 10, 4, tzinfo=UTC)


def pieza(handle: str, estado: str = "A", conjunto: int = 4) -> PiezaCatalogo:
    return PiezaCatalogo(handle=handle, bytes=10, tag="T", estado=estado, conjunto=conjunto, completada=None)


def lanzador(texto: str):  # type: ignore[no-untyped-def]
    def lanzar(invocacion: InvocacionRman) -> ResultadoRman:
        invocacion.log.write_text(texto, encoding="utf-8")
        return ResultadoRman(codigo_salida=0, agotado=False, duracion_segundos=0.1)

    return lanzar


OK = "connected to target database: XE\nRecovery Manager complete.\n"


def test_script_de_verificacion() -> None:
    assert script_verificacion("EST001_T1_X", [4, 5]) == (
        "CROSSCHECK BACKUP TAG 'EST001_T1_X';\nVALIDATE BACKUPSET 4, 5;\n"
    )


def test_todo_disponible_y_validado_da_ok(tmp_path: Path) -> None:
    resultado = verificar(
        BASE, "T", tmp_path, lambda tag: [pieza("a"), pieza("b", conjunto=5)], lanzador(OK), "X",
        medir=lambda ruta: 10, ahora=lambda: MOMENTO,
    )
    assert resultado.estado is EstadoPrueba.OK
    assert (tmp_path / "verificacion.rman").read_text(encoding="ascii").endswith("VALIDATE BACKUPSET 4, 5;\n")


def test_pieza_borrada_a_mano_queda_expired_y_falla(tmp_path: Path) -> None:
    llamadas: list[int] = []

    def consultar(tag: str) -> list[PiezaCatalogo]:
        llamadas.append(1)
        return [pieza("a")] if len(llamadas) == 1 else [pieza("a", estado="X")]

    resultado = verificar(BASE, "T", tmp_path, consultar, lanzador(OK), "X", medir=lambda ruta: None)
    assert resultado.estado is EstadoPrueba.FALLIDA
    detalle = {p.tipo: p for p in resultado.pruebas}
    assert detalle["EXISTENCIA"].resultado is EstadoPrueba.FALLIDA
    assert detalle["CROSSCHECK"].resultado is EstadoPrueba.FALLIDA


def test_validate_con_errores_falla(tmp_path: Path) -> None:
    log = "connected to target database: XE\nORA-19505: failed to identify file\nRecovery Manager complete.\n"
    resultado = verificar(BASE, "T", tmp_path, lambda tag: [pieza("a")], lanzador(log), "X", medir=lambda r: 1)
    assert resultado.estado is EstadoPrueba.FALLIDA
    assert "ORA-19505" in (resultado.pruebas[-1].detalle or "")


def test_sin_piezas_en_el_catalogo_falla_sin_lanzar_rman(tmp_path: Path) -> None:
    resultado = verificar(BASE, "T", tmp_path, lambda tag: [], lanzador(OK), "X")
    assert resultado.estado is EstadoPrueba.FALLIDA
    assert not (tmp_path / "verificacion.rman").exists()
