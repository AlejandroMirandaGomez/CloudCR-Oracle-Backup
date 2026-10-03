from pathlib import Path

from cloudcr_backup.oracle.connection import ErrorConexionOracle
from cloudcr_backup.oracle.discovery import InstanciaDescubierta
from cloudcr_backup.services.cliente_oracle import elegir_oracle_home, preparar_cliente_oracle

HOME_XE = Path(r"C:\app\oracle\product\21c\dbhomeXE")
HOME_OTRO = Path(r"C:\app\oracle\product\19c\dbhome_1")


def _instancia(sid: str, home: Path | None, en_ejecucion: bool) -> InstanciaDescubierta:
    return InstanciaDescubierta(sid=sid, oracle_home=home, en_ejecucion=en_ejecucion, origenes=("servicio",))


def test_prefiere_una_instancia_en_ejecucion_con_home() -> None:
    instancias = [_instancia("ORCL", HOME_OTRO, False), _instancia("XE", HOME_XE, True), _instancia("X", None, True)]
    assert elegir_oracle_home(instancias) == HOME_XE


def test_sin_instancias_no_inicia_nada() -> None:
    iniciados: list[Path] = []
    assert preparar_cliente_oracle(lambda: [], iniciados.append) is None
    assert iniciados == []


def test_inicia_el_cliente_thick_antes_que_el_repositorio() -> None:
    iniciados: list[Path] = []
    assert preparar_cliente_oracle(lambda: [_instancia("XE", HOME_XE, True)], iniciados.append) == HOME_XE
    assert iniciados == [HOME_XE]


def test_si_el_cliente_no_inicia_sigue_en_thin() -> None:
    def falla(home: Path) -> None:
        raise ErrorConexionOracle("sin bibliotecas")

    assert preparar_cliente_oracle(lambda: [_instancia("XE", HOME_XE, True)], falla) is None


def test_si_el_descubrimiento_falla_sigue_en_thin() -> None:
    def explota() -> list[InstanciaDescubierta]:
        raise OSError("registro inaccesible")

    assert preparar_cliente_oracle(explota, lambda h: None) is None
