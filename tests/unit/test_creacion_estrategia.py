from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.domain.enums import EstadoEstrategia, LogMode
from cloudcr_backup.domain.estrategia import Estrategia
from cloudcr_backup.domain.perfil_bd import PerfilBD
from cloudcr_backup.services import almacen_estrategias, creacion_estrategia
from cloudcr_backup.services.creacion_estrategia import ErrorCreacion
from cloudcr_backup.strategy.yaml_io import cargar_estrategia_yaml
from tests.unit.ayudas_solicitud import solicitud


@pytest.fixture(autouse=True)
def repositorio_no_disponible(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_implementado(_: Ajustes) -> None:
        raise NotImplementedError

    monkeypatch.setattr(almacen_estrategias.repositorio_conexion, "abrir_repositorio", no_implementado)


@pytest.fixture
def ajustes(tmp_path: Path) -> Ajustes:
    return Ajustes(work_dir=tmp_path / "trabajo")


@pytest.fixture
def destino(tmp_path: Path) -> str:
    carpeta = tmp_path / "respaldos"
    carpeta.mkdir()
    return str(carpeta)


@pytest.fixture
def perfil_archivelog(perfil_xe: PerfilBD) -> PerfilBD:
    return perfil_xe.model_copy(update={"log_mode": LogMode.ARCHIVELOG})


def _codigos(hallazgos: list[Any]) -> set[str]:
    return {h.codigo for h in hallazgos}


def test_validar_en_noarchivelog_advierte_y_exige_aceptar_la_caida(
    perfil_xe: PerfilBD, ajustes: Ajustes, destino: str
) -> None:
    resultado = creacion_estrategia.validar(solicitud(destino), perfil_xe, ajustes, "XE")
    assert "ARCH_001" in _codigos(resultado.hallazgos)
    assert resultado.requiere_aceptar_caida
    assert not resultado.bloqueante


def test_validar_en_archivelog_no_exige_aceptar_la_caida(
    perfil_archivelog: PerfilBD, ajustes: Ajustes, destino: str
) -> None:
    resultado = creacion_estrategia.validar(solicitud(destino), perfil_archivelog, ajustes, "XE")
    assert not resultado.requiere_aceptar_caida
    assert "ARCH_001" not in _codigos(resultado.hallazgos)


def test_validar_marca_error_si_el_destino_no_existe(
    perfil_archivelog: PerfilBD, ajustes: Ajustes, tmp_path: Path
) -> None:
    resultado = creacion_estrategia.validar(solicitud(str(tmp_path / "no_existe")), perfil_archivelog, ajustes, "XE")
    assert "DST_001" in _codigos(resultado.hallazgos)
    assert resultado.bloqueante


def test_validar_no_marca_dst_001_si_el_destino_existe(
    perfil_archivelog: PerfilBD, ajustes: Ajustes, destino: str
) -> None:
    resultado = creacion_estrategia.validar(solicitud(destino), perfil_archivelog, ajustes, "XE")
    assert "DST_001" not in _codigos(resultado.hallazgos)


def test_validar_marca_error_si_un_objeto_ya_no_existe(
    perfil_archivelog: PerfilBD, ajustes: Ajustes, destino: str
) -> None:
    alcance = [{"tipo": "TABLESPACE", "identificador": "XEPDB1:FANTASMA", "prioridad": "ALTA"}]
    resultado = creacion_estrategia.validar(solicitud(destino, alcance=alcance), perfil_archivelog, ajustes, "XE")
    assert "ALC_002" in _codigos(resultado.hallazgos)
    assert resultado.bloqueante


def test_validar_sin_alcance_ni_tareas_marca_los_dos_errores(
    perfil_archivelog: PerfilBD, ajustes: Ajustes, destino: str
) -> None:
    resultado = creacion_estrategia.validar(
        solicitud(destino, alcance=[], esquema=None), perfil_archivelog, ajustes, "XE"
    )
    assert {"ALC_001", "GEN_002"} <= _codigos(resultado.hallazgos)
    assert resultado.bloqueante


def test_validar_sin_retencion_advierte(perfil_archivelog: PerfilBD, ajustes: Ajustes, destino: str) -> None:
    resultado = creacion_estrategia.validar(solicitud(destino, retencion={}), perfil_archivelog, ajustes, "XE")
    assert "RET_001" in _codigos(resultado.hallazgos)


def test_validar_detecta_un_codigo_ya_guardado(perfil_archivelog: PerfilBD, ajustes: Ajustes, destino: str) -> None:
    creacion_estrategia.guardar(solicitud(destino), perfil_archivelog, ajustes, "XE")
    resultado = creacion_estrategia.validar(solicitud(destino), perfil_archivelog, ajustes, "XE")
    assert "GEN_001" in _codigos(resultado.hallazgos)
    assert resultado.bloqueante


def test_guardar_escribe_el_yaml_y_se_puede_leer_de_vuelta(
    perfil_archivelog: PerfilBD, ajustes: Ajustes, destino: str
) -> None:
    resultado = creacion_estrategia.guardar(solicitud(destino, activar=True), perfil_archivelog, ajustes, "xe")
    assert resultado.archivo == ajustes.rutas.estrategias / "XE" / "EST010.yaml"
    leida = cargar_estrategia_yaml(resultado.archivo)
    assert leida.codigo == "EST010"
    assert leida.estado is EstadoEstrategia.ACTIVA
    assert leida.creada_en is not None
    assert [t.codigo for t in leida.tareas] == ["T1", "T2"]
    assert resultado.repositorio.estado == "omitida"


def test_guardar_con_errores_bloqueantes_no_escribe_nada(
    perfil_archivelog: PerfilBD, ajustes: Ajustes, tmp_path: Path
) -> None:
    with pytest.raises(ErrorCreacion) as error:
        creacion_estrategia.guardar(solicitud(str(tmp_path / "no_existe")), perfil_archivelog, ajustes, "XE")
    assert error.value.tipo == "bloqueada"
    assert "DST_001" in _codigos(error.value.hallazgos)
    assert almacen_estrategias.codigos_guardados(ajustes, "XE") == []


def test_guardar_exige_aceptar_la_caida_cuando_el_respaldo_es_consistente(
    perfil_xe: PerfilBD, ajustes: Ajustes, destino: str
) -> None:
    with pytest.raises(ErrorCreacion) as error:
        creacion_estrategia.guardar(solicitud(destino), perfil_xe, ajustes, "XE")
    assert error.value.tipo == "caida_no_aceptada"
    assert almacen_estrategias.codigos_guardados(ajustes, "XE") == []
    resultado = creacion_estrategia.guardar(solicitud(destino, aceptar_caida=True), perfil_xe, ajustes, "XE")
    assert resultado.archivo.is_file()


def test_guardar_dos_veces_la_misma_estrategia_falla_la_segunda(
    perfil_archivelog: PerfilBD, ajustes: Ajustes, destino: str
) -> None:
    creacion_estrategia.guardar(solicitud(destino), perfil_archivelog, ajustes, "XE")
    with pytest.raises(ErrorCreacion) as error:
        creacion_estrategia.guardar(solicitud(destino), perfil_archivelog, ajustes, "XE")
    assert error.value.tipo == "bloqueada"
    assert "GEN_001" in _codigos(error.value.hallazgos)


def test_las_estrategias_de_otra_instancia_no_chocan(
    perfil_archivelog: PerfilBD, ajustes: Ajustes, destino: str
) -> None:
    creacion_estrategia.guardar(solicitud(destino), perfil_archivelog, ajustes, "XE")
    resultado = creacion_estrategia.guardar(solicitud(destino), perfil_archivelog, ajustes, "ORCL")
    assert resultado.archivo.parent.name == "ORCL"


def test_el_archivo_existente_no_se_sobrescribe(perfil_archivelog: PerfilBD, ajustes: Ajustes, destino: str) -> None:
    ruta = almacen_estrategias.ruta_estrategia(ajustes, "XE", "EST010")
    ruta.parent.mkdir(parents=True)
    ruta.write_text("contenido previo", encoding="utf-8")
    with pytest.raises(ErrorCreacion):
        creacion_estrategia.guardar(solicitud(destino), perfil_archivelog, ajustes, "XE")
    assert ruta.read_text(encoding="utf-8") == "contenido previo"


@pytest.mark.parametrize("sid", ["", "..", "../x", "a/b", "a b", "x" * 65])
def test_un_sid_peligroso_no_forma_rutas(ajustes: Ajustes, sid: str) -> None:
    with pytest.raises(ValueError, match="no es válido"):
        almacen_estrategias.directorio_estrategias(ajustes, sid)


def test_el_repositorio_no_implementado_se_informa_sin_fallar(
    perfil_archivelog: PerfilBD, ajustes: Ajustes, destino: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_implementado(_: Ajustes) -> None:
        raise NotImplementedError

    monkeypatch.setattr(almacen_estrategias.repositorio_conexion, "abrir_repositorio", no_implementado)
    resultado = creacion_estrategia.guardar(
        solicitud(destino, guardar_en_repositorio=True), perfil_archivelog, ajustes, "XE"
    )
    assert resultado.repositorio.estado == "no_disponible"
    assert resultado.archivo.is_file()


def test_un_error_del_repositorio_se_informa_sin_perder_el_archivo(
    perfil_archivelog: PerfilBD, ajustes: Ajustes, destino: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def falla(_: Ajustes) -> None:
        raise RuntimeError("ORA-12541: sin listener")

    monkeypatch.setattr(almacen_estrategias.repositorio_conexion, "abrir_repositorio", falla)
    resultado = creacion_estrategia.guardar(
        solicitud(destino, guardar_en_repositorio=True), perfil_archivelog, ajustes, "XE"
    )
    assert resultado.repositorio.estado == "error"
    assert "ORA-12541" in resultado.repositorio.mensaje
    assert resultado.archivo.is_file()


class _ConexionFalsa:
    def __init__(self) -> None:
        self.cerrada = False

    def close(self) -> None:
        self.cerrada = True


def _repositorio_falso(monkeypatch: pytest.MonkeyPatch, bd: Any) -> tuple[_ConexionFalsa, list[str]]:
    conexion = _ConexionFalsa()
    llamadas: list[str] = []

    def abrir(_: Ajustes) -> _ConexionFalsa:
        return conexion

    def crear(_: Any, estrategia: Estrategia) -> Estrategia:
        llamadas.append(f"crear:{estrategia.codigo}:{estrategia.bd_id}:{estrategia.estado.value}")
        return estrategia

    def activar(_: Any, bd_id: int, codigo: str) -> None:
        llamadas.append(f"activar:{bd_id}:{codigo}")

    monkeypatch.setattr(almacen_estrategias.repositorio_conexion, "abrir_repositorio", abrir)
    monkeypatch.setattr(almacen_estrategias.repositorio_bases_datos, "obtener", lambda _c, _n: bd)
    monkeypatch.setattr(almacen_estrategias.servicio, "crear", crear)
    monkeypatch.setattr(almacen_estrategias.servicio, "activar", activar)
    monkeypatch.setattr(almacen_estrategias.servicio, "listar", lambda _c, _b: [])
    return conexion, llamadas


def test_guarda_y_activa_en_el_repositorio(
    perfil_archivelog: PerfilBD, ajustes: Ajustes, destino: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    conexion, llamadas = _repositorio_falso(monkeypatch, SimpleNamespace(id=7))
    resultado = creacion_estrategia.guardar(
        solicitud(destino, guardar_en_repositorio=True, activar=True), perfil_archivelog, ajustes, "XE"
    )
    assert resultado.repositorio.estado == "guardada"
    assert llamadas == ["crear:EST010:7:INACTIVA", "activar:7:EST010"]
    assert conexion.cerrada


def test_si_la_base_no_esta_registrada_se_informa(
    perfil_archivelog: PerfilBD, ajustes: Ajustes, destino: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    conexion, llamadas = _repositorio_falso(monkeypatch, None)
    resultado = creacion_estrategia.guardar(
        solicitud(destino, guardar_en_repositorio=True), perfil_archivelog, ajustes, "XE"
    )
    assert resultado.repositorio.estado == "no_registrada"
    assert llamadas == []
    assert conexion.cerrada


def test_los_codigos_del_repositorio_se_suman_a_los_del_archivo(
    ajustes: Ajustes, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Estrategia:
        codigo = "est077"

    _repositorio_falso(monkeypatch, SimpleNamespace(id=1))
    monkeypatch.setattr(almacen_estrategias.servicio, "listar", lambda _c, _b: [_Estrategia()])
    assert almacen_estrategias.codigos_existentes(ajustes, "XE", "XE") == ["EST077"]
