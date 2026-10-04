from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.domain.ejecucion import ResultadoEjecucion
from cloudcr_backup.domain.enums import EstadoEjecucion, EstadoPrueba
from cloudcr_backup.execution import buzon, runner
from cloudcr_backup.execution.pipeline import bloqueo_bd
from cloudcr_backup.execution.runner import InvocacionRman
from cloudcr_backup.services import ejecucion
from tests.unit.test_evidencia_buzon import ejemplo
from tests.unit.test_pipeline import Escenario, contexto


def test_el_runner_borra_el_log_anterior_antes_de_lanzar(tmp_path: Path) -> None:
    log = tmp_path / "EST001.XE.LOG"
    log.write_text("Recovery Manager complete.\n", encoding="utf-8")
    invocacion = InvocacionRman(
        oracle_home=tmp_path / "sin-oracle", sid="XE", script=tmp_path / "EST001.XE.RMAN", log=log
    )
    resultado = runner.lanzar(invocacion)
    assert not resultado.lanzado
    assert not log.exists()


def test_el_runner_conserva_el_log_cuando_agrega(tmp_path: Path) -> None:
    log = tmp_path / "a.log"
    log.write_text("previo\n", encoding="utf-8")
    invocacion = InvocacionRman(
        oracle_home=tmp_path / "sin-oracle", sid="XE", script=tmp_path / "a.rman", log=log, agregar_al_log=True
    )
    runner.lanzar(invocacion)
    assert log.read_text(encoding="utf-8") == "previo\n"


def test_una_evidencia_nueva_registrada_descarta_la_vieja_del_buzon(tmp_path: Path) -> None:
    escenario = Escenario(tmp_path, contexto())
    llamadas: list[int] = []
    original = escenario.repositorio.persistir

    def persistir_falla_la_primera(registro: Any) -> None:
        llamadas.append(1)
        if len(llamadas) == 1:
            from cloudcr_backup.domain.errores import RepositorioNoDisponible

            raise RepositorioNoDisponible("BKPCAT todavía cerrada")
        original(registro)

    escenario.repositorio.persistir = persistir_falla_la_primera  # type: ignore[method-assign]
    resultado = escenario.ejecutar()
    assert resultado.estado_prueba is EstadoPrueba.OK
    assert not resultado.en_buzon
    assert buzon.pendientes(tmp_path / "buzon") == []


def test_base_ocupada_por_otro_rman_deja_la_ejecucion_bloqueada(tmp_path: Path) -> None:
    escenario = Escenario(tmp_path, contexto())
    with bloqueo_bd(tmp_path / "ejecuciones", "XE", 3600):
        resultado = escenario.ejecutar()
    assert resultado.estado is EstadoEjecucion.BLOQUEADA
    assert any("BD_OCUPADA" in motivo for motivo in resultado.motivos)
    assert escenario.invocaciones == []
    assert escenario.repositorio.persistidas[-1].estado is EstadoEjecucion.BLOQUEADA


def test_ejecutar_reintenta_sincronizar_el_buzon(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ajustes = Ajustes(work_dir=tmp_path)
    buzon.depositar(ajustes.rutas.buzon, ejemplo(41), datetime(2026, 10, 4))
    resultado = ResultadoEjecucion(
        ejecucion_id=41, estado=EstadoEjecucion.EXITOSA, estado_prueba=EstadoPrueba.OK, en_buzon=True
    )
    monkeypatch.setattr(ejecucion.pipeline, "ejecutar", lambda i, a: resultado)
    intentos: list[int] = []

    def sincronizar(a: Ajustes) -> int:
        intentos.append(1)
        if len(intentos) < 2:
            return 0
        return buzon.vaciar(a.rutas.buzon, lambda e: None)

    monkeypatch.setattr(ejecucion.buzon, "sincronizar", sincronizar)
    esperas: list[float] = []
    final = ejecucion.ejecutar(ajustes, 41, esperar=esperas.append)
    assert not final.en_buzon
    assert len(intentos) == 2
    assert esperas == [10.0, 10.0]
    assert "volvió a responder" in final.avisos[-1]


def test_ejecutar_sin_buzon_no_espera(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    resultado = ResultadoEjecucion(ejecucion_id=41, estado=EstadoEjecucion.EXITOSA, estado_prueba=EstadoPrueba.OK)
    monkeypatch.setattr(ejecucion.pipeline, "ejecutar", lambda i, a: resultado)
    esperas: list[float] = []
    assert ejecucion.ejecutar(Ajustes(work_dir=tmp_path), 41, esperar=esperas.append) == resultado
    assert esperas == []
