import json
import logging
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from cloudcr_backup.cli.app import app
from cloudcr_backup.domain.errores import OperacionNoPermitida
from cloudcr_backup.repository import alertas as repositorio_alertas
from cloudcr_backup.services import agente as servicio_agente
from cloudcr_backup.services import alertas as servicio_alertas
from cloudcr_backup.services import cliente_oracle

RAIZ = Path(__file__).resolve().parents[2]
EST001 = RAIZ / "config" / "estrategias" / "est001.yaml"
HORA = re.compile(r"\b(\d{2}:\d{2}) [A-Z0-9+-]+\b")

corredor = CliRunner()


@pytest.fixture
def entorno(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, repositorio_parcheado: dict[str, Any]) -> Path:
    monkeypatch.setenv("CLOUDCR_WORK_DIR", str(tmp_path))
    monkeypatch.setenv("CLOUDCR_CONFIG", str(tmp_path / "no-existe.yaml"))
    monkeypatch.setenv("COLUMNS", "250")
    return tmp_path


@pytest.fixture
def sin_log_de_archivo() -> Iterator[None]:
    yield
    raiz = logging.getLogger("cloudcr")
    for manejador in list(raiz.handlers):
        raiz.removeHandler(manejador)
        manejador.close()


def test_tarea_proximas_desde_yaml_da_las_cuatro_horas_de_est001() -> None:
    resultado = corredor.invoke(app, ["tarea", "proximas", "--archivo", str(EST001), "T1", "-n", "10"])
    assert resultado.exit_code == 0, resultado.output
    horas = HORA.findall(resultado.output)
    assert len(horas) == 10
    assert set(horas) == {"13:00", "15:00", "18:00", "21:00"}
    assert "Diaria a las 13:00, 15:00, 18:00 y 21:00" in resultado.output


def test_tarea_proximas_con_archivo_y_dos_argumentos_es_error() -> None:
    resultado = corredor.invoke(app, ["tarea", "proximas", "--archivo", str(EST001), "EST001", "T1"])
    assert resultado.exit_code == 2


def test_tarea_proximas_desde_el_repositorio(entorno: Path) -> None:
    resultado = corredor.invoke(app, ["tarea", "proximas", "EST001", "T1", "-n", "3"])
    assert resultado.exit_code == 0, resultado.output
    assert HORA.findall(resultado.output) == ["13:00"] * 3


def test_tarea_proximas_de_una_tarea_inexistente(entorno: Path) -> None:
    resultado = corredor.invoke(app, ["tarea", "proximas", "EST001", "T9", "--bd", "XE"])
    assert resultado.exit_code == 1
    assert "No existe la tarea T9" in resultado.output


def test_estado(entorno: Path) -> None:
    resultado = corredor.invoke(app, ["estado"])
    assert resultado.exit_code == 0, resultado.output
    assert "EST001" in resultado.output
    assert "Rojo" in resultado.output
    assert "Sin alertas vigentes" in resultado.output
    assert "nunca" in resultado.output


def test_estado_json(entorno: Path) -> None:
    resultado = corredor.invoke(app, ["estado", "--json"])
    datos = json.loads(resultado.output)
    assert datos["semaforos"][0]["color"] == "ROJO"


def test_estado_sin_repositorio(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLOUDCR_WORK_DIR", str(tmp_path))
    monkeypatch.setenv("CLOUDCR_CONFIG", str(tmp_path / "no-existe.yaml"))
    resultado = corredor.invoke(app, ["estado"])
    assert resultado.exit_code == 2
    assert "Sugerencia" in resultado.output
    assert "Traceback" not in resultado.output


def test_historial_tabla(entorno: Path) -> None:
    resultado = corredor.invoke(app, ["historial", "--bd", "XE"])
    assert resultado.exit_code == 0, resultado.output
    for esperado in ("Fecha", "Pruebas", "EST001", "Error", "Pendiente", "Símbolos"):
        assert esperado in resultado.output


def test_historial_fecha_invalida(entorno: Path) -> None:
    resultado = corredor.invoke(app, ["historial", "--desde", "03/10/2026"])
    assert resultado.exit_code == 2
    assert "AAAA-MM-DD" in resultado.output


def test_historial_json_y_exportacion(entorno: Path) -> None:
    datos = json.loads(corredor.invoke(app, ["historial", "--salida", "json"]).output)
    assert datos["filas"][0]["estrategia"] == "EST001"
    destino = entorno / "historial.csv"
    resultado = corredor.invoke(app, ["historial", "--salida", "csv", "--archivo", str(destino)])
    assert resultado.exit_code == 0, resultado.output
    assert destino.read_bytes().startswith("﻿".encode())


def test_historial_mostrar(entorno: Path) -> None:
    resultado = corredor.invoke(app, ["historial", "mostrar", "40"])
    assert resultado.exit_code == 0, resultado.output
    assert "RMAN-03009" in resultado.output
    assert "evidencia.json" in resultado.output
    faltante = corredor.invoke(app, ["historial", "mostrar", "99"])
    assert faltante.exit_code == 1
    assert "No existe la ejecución 99" in faltante.output


def test_reporte_historial_html_en_carpeta(entorno: Path) -> None:
    resultado = corredor.invoke(app, ["reporte", "historial", "--formato", "html", "--archivo", str(entorno)])
    assert resultado.exit_code == 0, resultado.output
    [archivo] = list(entorno.glob("historial-*.html"))
    assert "<table>" in archivo.read_text(encoding="utf-8")


def test_reporte_evidencia(entorno: Path) -> None:
    resultado = corredor.invoke(app, ["reporte", "evidencia", "40"])
    assert resultado.exit_code == 0, resultado.output
    assert "# Evidencia de la ejecución 40" in resultado.output


def test_alertas_vacias(entorno: Path) -> None:
    resultado = corredor.invoke(app, ["alertas"])
    assert resultado.exit_code == 0
    assert "No hay alertas" in resultado.output


def test_alertas_estado_invalido(entorno: Path) -> None:
    resultado = corredor.invoke(app, ["alertas", "listar", "--estado", "rara"])
    assert resultado.exit_code == 2
    assert "vigentes" in resultado.output


def test_reconocer_una_alerta_no_abierta(entorno: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def falla(ajustes: Any, alerta_id: int) -> None:
        raise OperacionNoPermitida("La alerta 7 está RESUELTA; solo se puede reconocer una alerta ABIERTA.")

    monkeypatch.setattr(servicio_alertas, "reconocer", falla)
    resultado = corredor.invoke(app, ["alertas", "reconocer", "7"])
    assert resultado.exit_code == 2
    assert "RESUELTA" in resultado.output


def test_alertas_evaluar(entorno: Path, monkeypatch: pytest.MonkeyPatch, perfil_xe: Any) -> None:
    abiertas: list[Any] = []

    def abrir(conexion: Any, condicion: Any) -> tuple[Any, bool]:
        abiertas.append(condicion)
        from cloudcr_backup.domain.enums import EstadoAlerta
        from cloudcr_backup.repository.alertas import AlertaDetallada

        alerta = AlertaDetallada(
            len(abiertas), condicion.codigo_regla, condicion.clave_dedup, condicion.severidad.value,
            EstadoAlerta.ABIERTA, condicion.mensaje, 1, 2, 3, None, None, None, "XE", "EST001", "T1",
        )
        return alerta, True

    monkeypatch.setattr(repositorio_alertas, "abrir", abrir)
    resultado = corredor.invoke(app, ["alertas", "evaluar"])
    assert resultado.exit_code == 0, resultado.output
    codigos = {c.codigo_regla for c in abiertas}
    assert {"BD_NOARCHIVELOG", "EJECUCION_FALLIDA"} <= codigos
    assert "NUEVA ALERTA" in resultado.output


def test_agente_estado_sin_latidos(entorno: Path) -> None:
    resultado = corredor.invoke(app, ["agente", "estado"])
    assert resultado.exit_code == 1
    assert "nunca corrió" in resultado.output


def test_agente_se_niega_a_correr_sin_pipeline(entorno: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(servicio_agente, "pipeline_disponible", lambda: None)
    resultado = corredor.invoke(app, ["agente", "ejecutar", "--una-vez"])
    assert resultado.exit_code == 2
    assert "pipeline" in resultado.output
    assert "--simulado" in resultado.output


def test_agente_simulado_una_vez(
    entorno: Path, monkeypatch: pytest.MonkeyPatch, sin_log_de_archivo: None
) -> None:
    def abrir_falla(conexion: Any, condicion: Any) -> None:
        raise RuntimeError("alerta no persistida en esta prueba")

    monkeypatch.setattr(cliente_oracle, "descubrir_instancias", lambda: [])
    monkeypatch.setattr(repositorio_alertas, "abrir", abrir_falla)
    resultado = corredor.invoke(app, ["agente", "ejecutar", "--una-vez", "--simulado"])
    assert resultado.exit_code == 0, resultado.output
    assert "MODO SIMULACIÓN" in resultado.output
    latido = json.loads(next((entorno / "agente").glob("latido_*.json")).read_text(encoding="utf-8"))
    assert latido["estado"] == "detenido"
    assert latido["simulado"] is True
    estado = corredor.invoke(app, ["agente", "estado"])
    assert "SIMULACIÓN" in estado.output
    assert (entorno / "logs" / "cloudcr.log").exists()
