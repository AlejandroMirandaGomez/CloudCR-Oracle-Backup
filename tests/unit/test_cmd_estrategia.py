from datetime import datetime, time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cloudcr_backup.cli import cmd_estrategia
from cloudcr_backup.domain.enums import LogMode, ModoRespaldo, Prioridad, TipoFrecuencia, TipoObjeto, TipoRespaldo
from cloudcr_backup.domain.estrategia import Como, Destino, Estrategia, ObjetoAlcance, Programacion, Tarea
from cloudcr_backup.domain.perfil_bd import PerfilBD
from cloudcr_backup.repository import bases_datos as repositorio_bases_datos
from cloudcr_backup.repository import conexion as repositorio_conexion
from cloudcr_backup.repository import estrategias as repositorio_estrategias
from cloudcr_backup.repository.bases_datos import Ambiente, BaseDatosRegistrada
from cloudcr_backup.strategy.yaml_io import guardar_estrategia_yaml

runner = CliRunner()


def _estrategia(codigo: str = "EST001") -> Estrategia:
    return Estrategia(
        bd_id=1,
        codigo=codigo,
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


def _perfil() -> PerfilBD:
    return PerfilBD(
        nombre="XE",
        nombre_instancia="XE",
        dbid=1,
        host="localhost",
        version="21.3.0.0.0",
        edicion="XE",
        es_cdb=False,
        log_mode=LogMode.ARCHIVELOG,
        open_mode="READ WRITE",
        estado_instancia="OPEN",
        oracle_home=None,
        diagnostic_dest=None,
        capturado_en=datetime.now(),
        contenedores=[],
        tablespaces=[],
        datafiles=[],
        tempfiles=[],
        controlfiles=[],
        redo_grupos=[],
        archivos_parametros=[],
        destinos_archivado=[],
        destino_archivado_configurado=False,
        area_recuperacion=None,
        archivelogs_sin_respaldo=0,
    )


def _bd_registrada(nombre: str) -> BaseDatosRegistrada:
    return BaseDatosRegistrada(id=7, nombre=nombre, oracle_home="x", ambiente=Ambiente.PRUEBAS, activa=True)


def test_validar_con_archivo_no_toca_el_repositorio(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    archivo = tmp_path / "est.yaml"
    guardar_estrategia_yaml(_estrategia(), archivo)
    monkeypatch.setattr(cmd_estrategia, "_perfil_local", lambda sid: _perfil())
    resultado = runner.invoke(cmd_estrategia.app, ["validar", "--archivo", str(archivo)])
    assert resultado.exit_code == 0
    assert "EST001" in resultado.stdout


def test_validar_sin_archivo_ni_bd_y_codigo_falla() -> None:
    resultado = runner.invoke(cmd_estrategia.app, ["validar"])
    assert resultado.exit_code != 0


def test_mostrar_con_archivo_incluye_el_rpo_y_la_tarea(tmp_path: Path) -> None:
    archivo = tmp_path / "est.yaml"
    guardar_estrategia_yaml(_estrategia(), archivo)
    resultado = runner.invoke(cmd_estrategia.app, ["mostrar", "--archivo", str(archivo)])
    assert resultado.exit_code == 0
    assert "RPO" in resultado.stdout


def test_listar_sin_repositorio_implementado_da_un_mensaje_claro() -> None:
    resultado = runner.invoke(cmd_estrategia.app, ["listar", "--bd", "XE"])
    assert resultado.exit_code != 0
    assert "repositorio" in resultado.stdout.lower()


def test_importar_crea_la_estrategia_con_el_bd_id_resuelto(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    archivo = tmp_path / "est.yaml"
    guardar_estrategia_yaml(_estrategia(), archivo)
    monkeypatch.setattr(repositorio_conexion, "abrir_repositorio", lambda ajustes: object())
    monkeypatch.setattr(repositorio_bases_datos, "obtener", lambda conexion, nombre: _bd_registrada(nombre))
    monkeypatch.setattr(repositorio_estrategias, "listar", lambda conexion, bd_id: [])
    guardadas: list[Estrategia] = []

    def _crear_falso(conexion: object, estrategia: Estrategia) -> Estrategia:
        guardadas.append(estrategia)
        return estrategia

    monkeypatch.setattr(repositorio_estrategias, "crear", _crear_falso)
    resultado = runner.invoke(cmd_estrategia.app, ["importar", str(archivo), "--bd", "XE"])
    assert resultado.exit_code == 0
    assert guardadas[0].bd_id == 7


def test_listar_muestra_las_estrategias_de_la_bd(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repositorio_conexion, "abrir_repositorio", lambda ajustes: object())
    monkeypatch.setattr(repositorio_bases_datos, "obtener", lambda conexion, nombre: _bd_registrada(nombre))
    monkeypatch.setattr(repositorio_estrategias, "listar", lambda conexion, bd_id: [_estrategia("EST001")])
    resultado = runner.invoke(cmd_estrategia.app, ["listar", "--bd", "XE"])
    assert resultado.exit_code == 0
    assert "EST001" in resultado.stdout


def test_activar_delega_en_el_servicio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repositorio_conexion, "abrir_repositorio", lambda ajustes: object())
    monkeypatch.setattr(repositorio_bases_datos, "obtener", lambda conexion, nombre: _bd_registrada(nombre))
    llamadas = []
    monkeypatch.setattr(
        repositorio_estrategias, "activar", lambda conexion, bd_id, codigo: llamadas.append((bd_id, codigo))
    )
    resultado = runner.invoke(cmd_estrategia.app, ["activar", "EST001", "--bd", "XE"])
    assert resultado.exit_code == 0
    assert llamadas == [(7, "EST001")]


def test_aplicar_recomendacion_arch_002_agrega_archivelog(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repositorio_conexion, "abrir_repositorio", lambda ajustes: object())
    monkeypatch.setattr(repositorio_bases_datos, "obtener", lambda conexion, nombre: _bd_registrada(nombre))
    monkeypatch.setattr(repositorio_estrategias, "obtener", lambda conexion, bd_id, codigo: _estrategia(codigo))
    guardadas: list[Estrategia] = []

    def _actualizar_falso(conexion: object, estrategia: Estrategia) -> Estrategia:
        guardadas.append(estrategia)
        return estrategia

    monkeypatch.setattr(repositorio_estrategias, "actualizar", _actualizar_falso)
    resultado = runner.invoke(cmd_estrategia.app, ["aplicar-recomendacion", "EST001", "ARCH_002", "--bd", "XE"])
    assert resultado.exit_code == 0
    assert any(o.tipo is TipoObjeto.ARCHIVELOG for o in guardadas[0].alcance)


def test_aplicar_recomendacion_no_soportada_falla_con_mensaje_claro() -> None:
    resultado = runner.invoke(cmd_estrategia.app, ["aplicar-recomendacion", "EST001", "ARCH_099", "--bd", "XE"])
    assert resultado.exit_code != 0
    assert "ARCH_099" in resultado.stdout
