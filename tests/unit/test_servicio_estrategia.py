import pytest

from cloudcr_backup.domain.enums import Prioridad
from cloudcr_backup.domain.estrategia import Estrategia
from cloudcr_backup.repository import estrategias as repositorio_estrategias
from cloudcr_backup.strategy import servicio
from cloudcr_backup.strategy.servicio import EstrategiaNoEncontrada, EstrategiaYaExiste


def _estrategia(codigo: str = "EST001", version: int = 1) -> Estrategia:
    return Estrategia(
        bd_id=1, codigo=codigo, nombre="Demo", prioridad=Prioridad.ALTA, creada_por="luis", version=version
    )


def test_crear_rechaza_un_codigo_duplicado(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repositorio_estrategias, "listar", lambda conexion, bd_id: [_estrategia("EST001")])
    with pytest.raises(EstrategiaYaExiste):
        servicio.crear(conexion=None, estrategia=_estrategia("EST001"))  # type: ignore[arg-type]


def test_crear_guarda_la_estrategia_con_version_1(monkeypatch: pytest.MonkeyPatch) -> None:
    guardadas: list[Estrategia] = []
    monkeypatch.setattr(repositorio_estrategias, "listar", lambda conexion, bd_id: [])

    def _crear_falso(conexion: object, estrategia: Estrategia) -> Estrategia:
        guardadas.append(estrategia)
        return estrategia

    monkeypatch.setattr(repositorio_estrategias, "crear", _crear_falso)
    resultado = servicio.crear(conexion=None, estrategia=_estrategia("EST002", version=5))  # type: ignore[arg-type]
    assert resultado.version == 1
    assert guardadas[0].version == 1


def test_editar_incrementa_la_version_respecto_de_la_guardada(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        repositorio_estrategias, "obtener", lambda conexion, bd_id, codigo: _estrategia(codigo, version=3)
    )
    guardadas: list[Estrategia] = []

    def _actualizar_falso(conexion: object, estrategia: Estrategia) -> Estrategia:
        guardadas.append(estrategia)
        return estrategia

    monkeypatch.setattr(repositorio_estrategias, "actualizar", _actualizar_falso)
    resultado = servicio.editar(conexion=None, estrategia_actualizada=_estrategia("EST001", version=3))  # type: ignore[arg-type]
    assert resultado.version == 4
    assert guardadas[0].version == 4


def test_editar_falla_si_la_estrategia_no_existe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repositorio_estrategias, "obtener", lambda conexion, bd_id, codigo: None)
    with pytest.raises(EstrategiaNoEncontrada):
        servicio.editar(conexion=None, estrategia_actualizada=_estrategia("EST999"))  # type: ignore[arg-type]


def test_activar_delega_en_el_repositorio(monkeypatch: pytest.MonkeyPatch) -> None:
    llamadas = []
    monkeypatch.setattr(
        repositorio_estrategias, "activar", lambda conexion, bd_id, codigo: llamadas.append((bd_id, codigo))
    )
    servicio.activar(conexion=None, bd_id=1, codigo="EST001")  # type: ignore[arg-type]
    assert llamadas == [(1, "EST001")]


def test_eliminar_es_una_desactivacion_logica(monkeypatch: pytest.MonkeyPatch) -> None:
    llamadas = []
    monkeypatch.setattr(
        repositorio_estrategias, "desactivar", lambda conexion, bd_id, codigo: llamadas.append((bd_id, codigo))
    )
    servicio.eliminar(conexion=None, bd_id=1, codigo="EST001")  # type: ignore[arg-type]
    assert llamadas == [(1, "EST001")]


def test_listar_y_obtener_delegan_en_el_repositorio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repositorio_estrategias, "listar", lambda conexion, bd_id: [_estrategia("EST001")])
    monkeypatch.setattr(repositorio_estrategias, "obtener", lambda conexion, bd_id, codigo: _estrategia(codigo))
    assert [e.codigo for e in servicio.listar(conexion=None, bd_id=1)] == ["EST001"]  # type: ignore[arg-type]
    obtenida = servicio.obtener(conexion=None, bd_id=1, codigo="EST001")  # type: ignore[arg-type]
    assert obtenida is not None
    assert obtenida.codigo == "EST001"
