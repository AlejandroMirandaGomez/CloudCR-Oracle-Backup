from datetime import time
from pathlib import Path

from typer.testing import CliRunner

from cloudcr_backup.cli import cmd_tarea
from cloudcr_backup.domain.enums import ModoRespaldo, Prioridad, TipoFrecuencia, TipoObjeto, TipoRespaldo
from cloudcr_backup.domain.estrategia import Como, Destino, Estrategia, ObjetoAlcance, Programacion, Tarea
from cloudcr_backup.strategy.yaml_io import cargar_estrategia_yaml, guardar_estrategia_yaml

runner = CliRunner()


def _estrategia_con_una_tarea() -> Estrategia:
    return Estrategia(
        bd_id=1,
        codigo="EST001",
        nombre="Demo",
        prioridad=Prioridad.ALTA,
        creada_por="luis",
        alcance=[ObjetoAlcance(tipo=TipoObjeto.BASE_DATOS, identificador="", prioridad=Prioridad.ALTA)],
        tareas=[
            Tarea(
                codigo="T1",
                como=Como(tipo_respaldo=TipoRespaldo.COMPLETO, modo_respaldo=ModoRespaldo.AUTO),
                programacion=Programacion(tipo_frecuencia=TipoFrecuencia.DIARIA, horas=[time(2, 0)]),
                destino=Destino(ruta=r"C:\backups\XE"),
            )
        ],
    )


def _archivo(tmp_path: Path, estrategia: Estrategia | None = None) -> Path:
    ruta = tmp_path / "est.yaml"
    guardar_estrategia_yaml(estrategia or _estrategia_con_una_tarea(), ruta)
    return ruta


def test_agregar_una_tarea_nueva(tmp_path: Path) -> None:
    archivo = _archivo(tmp_path)
    resultado = runner.invoke(
        cmd_tarea.app,
        [
            "agregar",
            str(archivo),
            "T2",
            "--tipo-respaldo",
            "INCREMENTAL_N1_DIFERENCIAL",
            "--destino",
            r"C:\backups\XE",
            "--hora",
            "15:00",
        ],
    )
    assert resultado.exit_code == 0, resultado.stdout
    estrategia = cargar_estrategia_yaml(archivo)
    assert [t.codigo for t in estrategia.tareas] == ["T1", "T2"]
    nueva = estrategia.tarea("T2")
    assert nueva is not None
    assert nueva.como.tipo_respaldo is TipoRespaldo.INCREMENTAL_N1_DIFERENCIAL
    assert nueva.programacion.horas == [time(15, 0)]


def test_agregar_rechaza_un_codigo_duplicado(tmp_path: Path) -> None:
    archivo = _archivo(tmp_path)
    resultado = runner.invoke(
        cmd_tarea.app,
        ["agregar", str(archivo), "T1", "--tipo-respaldo", "COMPLETO", "--destino", r"C:\backups\XE"],
    )
    assert resultado.exit_code != 0
    assert "ya existe" in resultado.stdout


def test_agregar_exige_las_dos_horas_de_la_ventana_juntas(tmp_path: Path) -> None:
    archivo = _archivo(tmp_path)
    resultado = runner.invoke(
        cmd_tarea.app,
        [
            "agregar",
            str(archivo),
            "T2",
            "--tipo-respaldo",
            "COMPLETO",
            "--destino",
            r"C:\backups\XE",
            "--ventana-inicio",
            "12:30",
        ],
    )
    assert resultado.exit_code != 0
    assert "ventana" in resultado.stdout.lower()


def test_agregar_rechaza_una_hora_con_formato_invalido(tmp_path: Path) -> None:
    archivo = _archivo(tmp_path)
    resultado = runner.invoke(
        cmd_tarea.app,
        [
            "agregar",
            str(archivo),
            "T2",
            "--tipo-respaldo",
            "COMPLETO",
            "--destino",
            r"C:\backups\XE",
            "--hora",
            "no-es-una-hora",
        ],
    )
    assert resultado.exit_code != 0
    assert "hora válida" in resultado.stdout


def test_editar_cambia_solo_los_campos_indicados(tmp_path: Path) -> None:
    archivo = _archivo(tmp_path)
    resultado = runner.invoke(cmd_tarea.app, ["editar", str(archivo), "T1", "--canales", "1", "--compresion", "BASIC"])
    assert resultado.exit_code == 0, resultado.stdout
    tarea = cargar_estrategia_yaml(archivo).tarea("T1")
    assert tarea is not None
    assert tarea.como.opciones.compresion.value == "BASIC"
    assert tarea.como.tipo_respaldo is TipoRespaldo.COMPLETO
    assert tarea.programacion.horas == [time(2, 0)]


def test_editar_falla_si_la_tarea_no_existe(tmp_path: Path) -> None:
    archivo = _archivo(tmp_path)
    resultado = runner.invoke(cmd_tarea.app, ["editar", str(archivo), "T9", "--canales", "1"])
    assert resultado.exit_code != 0
    assert "No existe" in resultado.stdout


def test_eliminar_quita_la_tarea(tmp_path: Path) -> None:
    archivo = _archivo(tmp_path)
    resultado = runner.invoke(cmd_tarea.app, ["eliminar", str(archivo), "T1"])
    assert resultado.exit_code == 0, resultado.stdout
    estrategia = cargar_estrategia_yaml(archivo)
    assert estrategia.tareas == []


def test_eliminar_falla_si_la_tarea_no_existe(tmp_path: Path) -> None:
    archivo = _archivo(tmp_path)
    resultado = runner.invoke(cmd_tarea.app, ["eliminar", str(archivo), "T9"])
    assert resultado.exit_code != 0
    assert "No existe" in resultado.stdout
