from typing import Any

import oracledb

from cloudcr_backup.oracle.inspector import ritmo_cambio_log


class CursorFalso:
    def __init__(self, filas: list[tuple[Any, ...]] | None = None, error: bool = False) -> None:
        self._filas = filas or []
        self._error = error
        self.consultas: list[str] = []

    def execute(self, sql: str) -> None:
        self.consultas.append(sql)
        if self._error:
            raise oracledb.DatabaseError("ORA-00942: table or view does not exist")

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._filas


def test_lee_cambios_y_horas() -> None:
    ritmo = ritmo_cambio_log(CursorFalso([(49, 24.0)]))  # type: ignore[arg-type]
    assert ritmo is not None
    assert ritmo.cambios == 49
    assert ritmo.minutos_promedio == 30


def test_sin_filas_devuelve_cero_cambios() -> None:
    ritmo = ritmo_cambio_log(CursorFalso([(0, None)]))  # type: ignore[arg-type]
    assert ritmo is not None
    assert ritmo.cambios == 0
    assert ritmo.minutos_promedio is None


def test_sin_privilegios_no_rompe_la_inspeccion() -> None:
    assert ritmo_cambio_log(CursorFalso(error=True)) is None  # type: ignore[arg-type]
