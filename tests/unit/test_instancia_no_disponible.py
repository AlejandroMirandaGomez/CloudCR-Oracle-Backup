from pathlib import Path
from types import SimpleNamespace
from typing import Any

import oracledb
import pytest

from cloudcr_backup.oracle import explorador
from cloudcr_backup.oracle.connection import (
    ErrorConexionOracle,
    ErrorInstanciaNoDisponible,
    traducir_instancia_no_disponible,
)
from cloudcr_backup.oracle.discovery import InstanciaDescubierta


def error_oracle(codigo: int) -> oracledb.DatabaseError:
    return oracledb.DatabaseError(SimpleNamespace(code=codigo, message=f"ORA-{codigo:05d}"))


@pytest.mark.parametrize("codigo", [1034, 1033, 1507, 12560, 27101, 1109, 1219, 1110, 1113, 1116, 1122, 1157])
def test_codigos_de_instancia_no_disponible_se_traducen(codigo: int) -> None:
    traducido = traducir_instancia_no_disponible(error_oracle(codigo), "XE")
    assert isinstance(traducido, ErrorInstanciaNoDisponible)
    assert f"ORA-{codigo:05d}" in str(traducido)
    assert "XE" in str(traducido)


@pytest.mark.parametrize(
    ("codigo", "texto"),
    [(1507, "no está montada"), (1219, "no está abierta"), (1109, "no está abierta"), (1157, "faltan archivos")],
)
def test_base_que_no_abre_explica_que_la_instancia_esta_iniciada(codigo: int, texto: str) -> None:
    traducido = traducir_instancia_no_disponible(error_oracle(codigo), "XE")
    assert traducido is not None
    assert "está iniciada" in str(traducido)
    assert texto in str(traducido)


@pytest.mark.parametrize("codigo", [1031, 1017, 942])
def test_otros_errores_no_se_consideran_instancia_no_disponible(codigo: int) -> None:
    assert traducir_instancia_no_disponible(error_oracle(codigo), "XE") is None


def test_error_sin_codigo_no_se_traduce() -> None:
    assert traducir_instancia_no_disponible(oracledb.DatabaseError("sin detalle"), "XE") is None


def test_el_error_de_instancia_sigue_siendo_un_error_de_conexion() -> None:
    assert issubclass(ErrorInstanciaNoDisponible, ErrorConexionOracle)


class ConexionFalsa:
    def __init__(self) -> None:
        self.cerrada = False

    def close(self) -> None:
        self.cerrada = True


def instancia() -> InstanciaDescubierta:
    return InstanciaDescubierta(
        sid="XE", oracle_home=Path("C:/oracle/dbhomeXE"), en_ejecucion=True, origenes=("servicio",)
    )


def preparar_exploracion(monkeypatch: pytest.MonkeyPatch, fallo: Exception) -> ConexionFalsa:
    conexion = ConexionFalsa()

    def inspeccionar_que_falla(*_: Any, **__: Any) -> None:
        raise fallo

    monkeypatch.setattr(explorador, "conectar_local", lambda _parametros: conexion)
    monkeypatch.setattr(explorador, "inspeccionar", inspeccionar_que_falla)
    return conexion


def test_explorar_con_base_sin_montar_lanza_error_de_instancia_no_disponible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conexion = preparar_exploracion(monkeypatch, error_oracle(1507))
    with pytest.raises(ErrorInstanciaNoDisponible, match="ORA-01507"):
        explorador.explorar_local(instancia())
    assert conexion.cerrada


def test_explorar_con_base_sin_abrir_lanza_error_de_instancia_no_disponible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preparar_exploracion(monkeypatch, error_oracle(1219))
    with pytest.raises(ErrorInstanciaNoDisponible, match="no está abierta"):
        explorador.explorar_local(instancia())


def test_explorar_convierte_otros_errores_de_oracle_en_error_de_conexion(monkeypatch: pytest.MonkeyPatch) -> None:
    conexion = preparar_exploracion(monkeypatch, error_oracle(942))
    with pytest.raises(ErrorConexionOracle, match="ORA-00942") as excepcion:
        explorador.explorar_local(instancia())
    assert not isinstance(excepcion.value, ErrorInstanciaNoDisponible)
    assert conexion.cerrada
