import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from cloudcr_backup.domain.enums import Compresion, LogMode
from cloudcr_backup.domain.estrategia import Retencion
from cloudcr_backup.domain.recuperacion import (
    ArchivoDanado,
    BloqueCorrupto,
    Escenario,
    GrupoRedoActual,
    MiembroRedoDanado,
)
from cloudcr_backup.recovery.procedimientos import SolicitudProcedimiento, generar
from cloudcr_backup.retention import politica
from cloudcr_backup.rman.constructor import SolicitudScript, construir
from cloudcr_backup.strategy.yaml_io import cargar_estrategia_yaml
from cloudcr_backup.verification.verificador import script_verificacion

pytestmark = pytest.mark.oracle

ESTRATEGIAS = Path(__file__).resolve().parents[2] / "config" / "estrategias"
DANADO = ArchivoDanado(file_id=12, ruta="X", tablespace="USERS", contenedor="XEPDB1", estado="OFFLINE", origen="x")
MIEMBRO = MiembroRedoDanado(
    grupo=2, miembro="C:\\ORADATA\\XE\\REDO02B.LOG", estado_miembro="INVALID", estado_grupo="CURRENT", secuencia=41
)


def _solicitud_de_recuperacion(escenario: Escenario, **cambios: Any) -> SolicitudProcedimiento:
    base: dict[str, Any] = {
        "bd": "XE",
        "escenario": escenario,
        "log_mode": LogMode.ARCHIVELOG,
        "dbid": 3114375768,
        "destino_autobackup": "C:\\backups\\XE",
        "hasta": datetime(2026, 10, 4, 13, 0),
        "danados": [DANADO],
        "bloques": [BloqueCorrupto(file_id=12, bloque=131)],
        "miembros_redo": [MIEMBRO],
        "redo_actual": GrupoRedoActual(grupo=2, secuencia=41),
    }
    base.update(cambios)
    return SolicitudProcedimiento(**base)


VARIANTES_DE_RECUPERACION = {
    "datafile_pdb_cerrada": _solicitud_de_recuperacion(Escenario.DATAFILE, estado_pdbs={"XEPDB1": "MOUNTED"}),
    "tablespace_pdb_cerrada": _solicitud_de_recuperacion(Escenario.TABLESPACE, estado_pdbs={"XEPDB1": "MOUNTED"}),
    "pdb_cerrada": _solicitud_de_recuperacion(Escenario.PDB, estado_pdbs={"XEPDB1": "MOUNTED"}),
    "corrupcion-bloque_un_bloque": _solicitud_de_recuperacion(Escenario.CORRUPCION_BLOQUE, objetivo="12:131"),
    "miembro-redolog_grupo_inactivo": _solicitud_de_recuperacion(
        Escenario.MIEMBRO_REDOLOG, miembros_redo=[MIEMBRO.model_copy(update={"estado_grupo": "INACTIVE"})]
    ),
    "miembro-redolog_grupo_activo": _solicitud_de_recuperacion(
        Escenario.MIEMBRO_REDOLOG, miembros_redo=[MIEMBRO.model_copy(update={"estado_grupo": "ACTIVE"})]
    ),
    "total-noarchivelog_sin_controlfile": _solicitud_de_recuperacion(
        Escenario.TOTAL_NOARCHIVELOG, log_mode=LogMode.NOARCHIVELOG, sin_conexion=True
    ),
    "total-noarchivelog_con_pieza": _solicitud_de_recuperacion(
        Escenario.TOTAL_NOARCHIVELOG,
        log_mode=LogMode.NOARCHIVELOG,
        objetivo="controlfile",
        pieza_controlfile="C:\\backups\\XE\\C-3114375768-20261004-00",
    ),
}


def _rman() -> Path:
    home = os.environ.get("ORACLE_HOME")
    if not home:
        pytest.skip("Defina ORACLE_HOME para comprobar la sintaxis con RMAN.")
    ruta = Path(home) / "bin" / ("rman.exe" if sys.platform == "win32" else "rman")
    if not ruta.exists():
        pytest.skip(f"No existe {ruta}.")
    return ruta


def _scripts() -> dict[str, str]:
    scripts: dict[str, str] = {}
    for archivo in sorted(ESTRATEGIAS.glob("est*.yaml")):
        estrategia = cargar_estrategia_yaml(archivo)
        for tarea in estrategia.tareas:
            for log_mode in LogMode:
                for compresion in (Compresion.NINGUNA, Compresion.BASIC, Compresion.MEDIUM):
                    opciones = tarea.como.opciones.model_copy(update={"compresion": compresion})
                    variante = tarea.model_copy(update={"como": tarea.como.model_copy(update={"opciones": opciones})})
                    try:
                        generado = construir(SolicitudScript(estrategia=estrategia, tarea=variante, log_mode=log_mode))
                    except ValueError:
                        continue
                    clave = f"{estrategia.codigo}_{tarea.codigo}_{log_mode.value}_{compresion.value}"
                    scripts[clave] = generado.contenido
    scripts["retencion_informe"] = politica.script(Retencion(ventana_dias=30))
    scripts["retencion_purga"] = politica.script(
        Retencion(ventana_dias=30, archived_logs_dias=7, purga_automatica=True), purgar=True
    )
    scripts["retencion_purga_piezas"] = politica.script_purga(
        [r"C:\backups\XE\XE_EST004_T1_1.BKP", r"C:\backups\XE\XE_EST004_T1_2.BKP"], 7
    )
    scripts["retencion_redundancia"] = politica.script(Retencion(redundancia=2))
    scripts["verificacion"] = script_verificacion("EST001_T1_2610041300", [3, 4])
    for escenario in Escenario:
        procedimiento = generar(_solicitud_de_recuperacion(escenario))
        assert procedimiento.script is not None, procedimiento.motivo
        scripts[f"recuperacion_{escenario.value}"] = procedimiento.script
    for nombre, solicitud in VARIANTES_DE_RECUPERACION.items():
        procedimiento = generar(solicitud)
        assert procedimiento.script is not None, procedimiento.motivo
        scripts[f"recuperacion_{nombre}"] = procedimiento.script
    return scripts


@pytest.mark.parametrize(("nombre", "contenido"), sorted(_scripts().items()))
def test_rman_acepta_la_sintaxis(nombre: str, contenido: str, tmp_path: Path) -> None:
    rman = _rman()
    script = tmp_path / f"{nombre}.rman"
    script.write_bytes(contenido.encode("ascii"))
    salida = subprocess.run(
        [str(rman), "checksyntax", f"cmdfile={script.name}", "using", "TAG_PRUEBA", "CLOUDCR_0"],
        cwd=tmp_path,
        env={**os.environ, "NLS_LANG": "AMERICAN_AMERICA.AL32UTF8"},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert "The cmdfile has no syntax errors" in salida.stdout, salida.stdout[-2000:]
