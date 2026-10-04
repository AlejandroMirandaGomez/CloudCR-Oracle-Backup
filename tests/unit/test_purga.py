from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.domain.estrategia import Retencion
from cloudcr_backup.repository import parametros as repositorio_parametros
from cloudcr_backup.repository import piezas as repositorio_piezas
from cloudcr_backup.repository.piezas import PiezaRegistrada
from cloudcr_backup.retention import politica
from cloudcr_backup.services import resolucion, retencion
from tests.unit.test_servicios_juan import BD, cargar

AHORA = datetime(2026, 10, 4, 12, 0)
VIEJA = "C:\\BACKUPS\\XE\\XE_EST004_T1_VIEJA.BKP"
NUEVA = "C:\\BACKUPS\\XE\\XE_EST004_T1_NUEVA.BKP"
AJENA = "C:\\BACKUPS\\XE\\XE_EST003_T1_AJENA.BKP"


def pieza(id_: int, ejecucion: int, ruta: str, estrategia_id: int, tarea: str = "T1", dias: int = 0) -> PiezaRegistrada:
    fin = AHORA - timedelta(days=dias)
    return PiezaRegistrada(
        id=id_,
        ejecucion_id=ejecucion,
        nombre_archivo=ruta,
        tamano_bytes=10,
        tag="T",
        vence_en=None,
        obsoleta=False,
        estrategia_id=estrategia_id,
        estrategia_codigo="X",
        tarea_codigo=tarea,
        fin=fin,
    )


def test_script_de_purga_borra_piezas_concretas_y_archived_logs() -> None:
    assert politica.script_purga([VIEJA], 7) == (
        f"DELETE NOPROMPT BACKUPPIECE '{VIEJA}';\n"
        "DELETE NOPROMPT ARCHIVELOG ALL BACKED UP 1 TIMES TO DISK COMPLETED BEFORE 'SYSDATE-7';\n"
    )
    assert "CONFIGURE" not in politica.script_purga([VIEJA, NUEVA], None)
    with pytest.raises(politica.PoliticaNoDefinida):
        politica.script_purga([], None)


def test_redundancia_se_aplica_por_tarea() -> None:
    piezas = [
        pieza(1, 1, "n0_vieja", 4, "T1", dias=14),
        pieza(2, 2, "n0_nueva", 4, "T1", dias=7),
        pieza(3, 3, "n1_a", 4, "T2", dias=3),
        pieza(4, 4, "n1_b", 4, "T2", dias=2),
        pieza(5, 5, "n1_c", 4, "T2", dias=1),
    ]
    vencidas = politica.vencidas(piezas, Retencion(redundancia=2), AHORA)
    assert [p.ruta for p in vencidas] == ["n1_a"]


@pytest.fixture
def entorno(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    estado: dict[str, Any] = {"marcadas": [], "scripts": []}
    est004 = cargar("EST004", 4).model_copy(
        update={"retencion": Retencion(ventana_dias=30, archived_logs_dias=7, purga_automatica=True)}
    )
    monkeypatch.setattr(retencion, "preparar_cliente_oracle", lambda: None)
    monkeypatch.setattr("cloudcr_backup.repository.conexion.abrir_repositorio", lambda a: _Conexion())
    monkeypatch.setattr(resolucion, "estrategia", lambda c, bd, codigo: (BD, est004))
    monkeypatch.setattr(repositorio_parametros, "listar", lambda c: {})
    monkeypatch.setattr(
        repositorio_piezas,
        "de_base",
        lambda c, b: [pieza(1, 1, VIEJA, 4, dias=40), pieza(2, 2, NUEVA, 4), pieza(3, 3, AJENA, 3, dias=60)],
    )

    def marcar(c: Any, ids: list[int]) -> int:
        estado["marcadas"].extend(ids)
        return len(ids)

    monkeypatch.setattr(repositorio_piezas, "marcar_obsoletas", marcar)
    estado["ajustes"] = Ajustes(work_dir=tmp_path, repositorio_dsn="x")
    return estado


class _Conexion:
    def close(self) -> None:
        return None


def informe_rman(*obsoletas: str) -> str:
    lineas = "\n".join(f"  Backup Piece       3      2026-09-01 02:00:10 {ruta}" for ruta in obsoletas)
    cabecera = "connected to target database: XE\nReport of obsolete backups and copies\n"
    return f"{cabecera}{lineas}\nRecovery Manager complete.\n"


def test_purga_solo_borra_piezas_propias_que_rman_informa_obsoletas(
    entorno: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def ejecutar(base: Any, carpeta: Path, nombre: str, contenido: str, nls: str) -> tuple[str, Path, None]:
        entorno["scripts"].append(contenido)
        if contenido.startswith("CROSSCHECK"):
            return informe_rman(VIEJA, AJENA), tmp_path / "i.log", None
        return (
            f"connected to target database: XE\ndeleted backup piece\nbackup piece handle={VIEJA} RECID=1 STAMP=2\n"
            "Recovery Manager complete.\n",
            tmp_path / "p.log",
            None,
        )

    monkeypatch.setattr(retencion, "_ejecutar_rman", ejecutar)
    resultado = retencion.purgar(entorno["ajustes"], "XE", "EST004", confirmado=True)
    assert resultado.correcta
    assert resultado.candidatas == [VIEJA]
    assert AJENA not in entorno["scripts"][1]
    assert NUEVA not in entorno["scripts"][1]
    assert f"DELETE NOPROMPT BACKUPPIECE '{VIEJA}';" in entorno["scripts"][1]
    assert "DELETE NOPROMPT OBSOLETE" not in entorno["scripts"][1]
    assert resultado.borradas == [VIEJA]
    assert entorno["marcadas"] == [1]


def test_purga_sin_obsoletas_propias_no_borra_piezas(
    entorno: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def ejecutar(base: Any, carpeta: Path, nombre: str, contenido: str, nls: str) -> tuple[str, Path, None]:
        entorno["scripts"].append(contenido)
        if contenido.startswith("CROSSCHECK"):
            return informe_rman(AJENA), tmp_path / "i.log", None
        return "connected to target database: XE\nRecovery Manager complete.\n", tmp_path / "p.log", None

    monkeypatch.setattr(retencion, "_ejecutar_rman", ejecutar)
    resultado = retencion.purgar(entorno["ajustes"], "XE", "EST004", confirmado=True)
    assert resultado.candidatas == []
    assert "BACKUPPIECE" not in entorno["scripts"][1]
    assert "ARCHIVELOG" in entorno["scripts"][1]
    assert entorno["marcadas"] == []


def test_purga_se_detiene_si_el_informe_de_rman_falla(
    entorno: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def ejecutar(base: Any, carpeta: Path, nombre: str, contenido: str, nls: str) -> tuple[str, Path, None]:
        entorno["scripts"].append(contenido)
        return "RMAN-06171: not connected to target database\n", tmp_path / "i.log", None

    monkeypatch.setattr(retencion, "_ejecutar_rman", ejecutar)
    resultado = retencion.purgar(entorno["ajustes"], "XE", "EST004", confirmado=True)
    assert not resultado.correcta
    assert len(entorno["scripts"]) == 1
