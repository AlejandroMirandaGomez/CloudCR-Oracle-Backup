import io
import json
from pathlib import Path

import pytest
from rich.console import Console

from cloudcr_backup.oracle.explorador import Exploracion
from cloudcr_backup.presentacion.arbol import OpcionesArbol
from cloudcr_backup.presentacion.formato import formato_bytes
from cloudcr_backup.presentacion.terminal import construir_arbol
from cloudcr_backup.reports.exportar_instancia import a_html, a_json, a_markdown

SALIDAS = Path(__file__).parent.parent / "fixtures" / "salidas"


def _texto(exploracion: Exploracion, opciones: OpcionesArbol, ancho: int = 250) -> str:
    buffer = io.StringIO()
    Console(file=buffer, width=ancho, color_system=None, legacy_windows=False).print(
        construir_arbol(exploracion, opciones)
    )
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("nombre", "opciones"),
    [
        ("completo", OpcionesArbol()),
        ("pdb_xepdb1", OpcionesArbol(pdb="XEPDB1")),
        ("sin_seed_rutas_completas", OpcionesArbol(sin_seed=True, rutas_completas=True)),
    ],
)
def test_salida_de_terminal_igual_a_la_de_referencia(
    exploracion_xe: Exploracion, nombre: str, opciones: OpcionesArbol
) -> None:
    esperado = (SALIDAS / f"arbol_{nombre}.txt").read_text(encoding="utf-8")
    assert _texto(exploracion_xe, opciones, ancho=300) == esperado


def test_jerarquia_completa(exploracion_xe: Exploracion) -> None:
    texto = _texto(exploracion_xe, OpcionesArbol())
    for esperado in (
        "Instancia XE",
        "Archivos de la instancia (compartidos por todos los contenedores)",
        "Control files (2)",
        "CONTROL01.CTL",
        "Grupo 1",
        "REDO01.LOG",
        "SPFILE (en uso)",
        "PFILE de creación",
        "CDB$ROOT",
        "PDB$SEED",
        "XEPDB1",
        "CLOUDCR_STRESS_TS.DBF",
        "tempfile",
        "NOARCHIVELOG",
    ):
        assert esperado in texto


def test_orden_de_la_jerarquia(exploracion_xe: Exploracion) -> None:
    texto = _texto(exploracion_xe, OpcionesArbol())
    assert texto.index("Archivos de la instancia") < texto.index("CDB$ROOT") < texto.index("XEPDB1  ·")
    bloque_pdb = texto[texto.index("XEPDB1  ·") :]
    assert (
        bloque_pdb.index("SYSTEM")
        < bloque_pdb.index("SYSAUX")
        < bloque_pdb.index("UNDOTBS1")
        < bloque_pdb.index("TEMP")
    )


def test_filtro_por_pdb_y_sin_seed(exploracion_xe: Exploracion) -> None:
    texto = _texto(exploracion_xe, OpcionesArbol(pdb="xepdb1"))
    assert "XEPDB1" in texto
    assert "CDB$ROOT" not in texto
    assert "PDB$SEED" not in texto
    assert "Control files" in texto
    assert "PDB$SEED" not in _texto(exploracion_xe, OpcionesArbol(sin_seed=True))


def test_rutas_completas(exploracion_xe: Exploracion) -> None:
    texto = _texto(exploracion_xe, OpcionesArbol(rutas_completas=True))
    datafile = next(d for d in exploracion_xe.perfil.datafiles if d.nombre_archivo == "USERS01.DBF")
    assert datafile.ruta in texto


def test_hallazgos_bajo_su_nodo(exploracion_xe: Exploracion) -> None:
    texto = _texto(exploracion_xe, OpcionesArbol())
    assert texto.index("Redo logs") < texto.index("RECOMENDACIÓN: Los grupos de redo") < texto.index("Grupo 1")


def test_exportaciones(exploracion_xe: Exploracion) -> None:
    datos = json.loads(a_json(exploracion_xe))
    assert datos["perfil"]["nombre"] == "XE"
    assert {h["codigo"] for h in datos["hallazgos"]} >= {"ARCH_001"}
    markdown = a_markdown(exploracion_xe, OpcionesArbol())
    assert markdown.startswith("# Instancia XE")
    assert "| ADVERTENCIA | ARCH_001 |" in markdown
    assert "<html" in a_html(exploracion_xe, OpcionesArbol()).lower()


def test_formato_bytes() -> None:
    assert formato_bytes(None) == "?"
    assert formato_bytes(512) == "512 B"
    assert formato_bytes(5 * 1024 * 1024) == "5 MB"
    assert formato_bytes(18710528) == "17.8 MB"
    assert formato_bytes(1350 * 1024 * 1024) == "1.3 GB"
    assert formato_bytes(34359721984) == "32 GB"
