from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.domain.ejecucion import ResultadoEjecucion
from cloudcr_backup.domain.enums import EstadoEjecucion, EstadoPrueba, EstadoScript, ModoRespaldo
from cloudcr_backup.domain.errores import OperacionNoPermitida, RecursoNoEncontrado
from cloudcr_backup.domain.recuperacion import Diagnostico, Escenario, Procedimiento, PuntosRecuperacion
from cloudcr_backup.domain.retencion import InformeRetencion, ResultadoPurga
from cloudcr_backup.domain.scripts import SimulacionEjecucion, VistaScript
from cloudcr_backup.services import ejecucion, recuperacion, retencion, scripts
from cloudcr_backup.web.app import crear_app
from cloudcr_backup.web.config import ConfigWeb
from tests.web.conftest import ServicioFalso

AHORA = datetime(2026, 10, 4, 12, tzinfo=UTC)


def vista(**cambios: Any) -> VistaScript:
    base: dict[str, Any] = {
        "bd": "XE",
        "estrategia": "EST001",
        "tarea": "T1",
        "tarea_id": 3,
        "script_id": 9,
        "version": 1,
        "estado": EstadoScript.BORRADOR,
        "hash_sha256": "b" * 64,
        "contenido": "RUN {\n}\n",
        "modo": ModoRespaldo.EN_LINEA,
    }
    base.update(cambios)
    return VistaScript(**base)


@pytest.fixture
def api(config_pruebas: ConfigWeb, servicio: ServicioFalso, tmp_path: Path) -> TestClient:
    return TestClient(crear_app(config_pruebas, servicio=servicio, ajustes=Ajustes(work_dir=tmp_path)))


def test_ver_y_listar_scripts(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scripts, "ver", lambda a, bd, codigo, tarea, version: vista(version=version or 1))
    monkeypatch.setattr(scripts, "listar", lambda a, bd, codigo: [vista(), vista(version=2)])
    assert api.get("/api/scripts/XE/EST001/T1?version=2").json()["version"] == 2
    assert [v["version"] for v in api.get("/api/scripts/XE/EST001").json()] == [1, 2]


def test_generar_y_aprobar_script(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scripts, "generar", lambda a, bd, codigo, tarea: [vista(nueva=True)])
    recibido: list[Any] = []

    def aprobar(a: Any, bd: str, codigo: str, tarea: str, por: str, acepto: bool, version: Any) -> VistaScript:
        recibido.append((por, acepto))
        return vista(estado=EstadoScript.APROBADO, aprobado_por=por)

    monkeypatch.setattr(scripts, "aprobar", aprobar)
    assert api.post("/api/scripts/XE/EST001/generar?tarea=T1").json()[0]["nueva"] is True
    respuesta = api.post("/api/scripts/XE/EST001/T1/aprobar", json={"acepto_caida": True, "aprobado_por": "juan"})
    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "APROBADO"
    assert recibido == [("juan", True)]


def test_aprobar_consistente_sin_caida_devuelve_409(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def aprobar(*a: Any) -> VistaScript:
        raise OperacionNoPermitida("El script hace un respaldo CONSISTENTE.", "Apruebe con --acepto-caida.")

    monkeypatch.setattr(scripts, "aprobar", aprobar)
    respuesta = api.post("/api/scripts/XE/EST002/T1/aprobar", json={})
    assert respuesta.status_code == 409
    assert "CONSISTENTE" in respuesta.json()["errores"][0]["mensaje"]


def test_rechazar_exige_motivo(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scripts, "rechazar", lambda *a: vista(estado=EstadoScript.RECHAZADO))
    assert api.post("/api/scripts/XE/EST001/T1/rechazar", json={"motivo": ""}).status_code == 422
    assert api.post("/api/scripts/XE/EST001/T1/rechazar", json={"motivo": "no"}).json()["estado"] == "RECHAZADO"


def test_las_acciones_rechazan_otro_origen(api: TestClient) -> None:
    respuesta = api.post("/api/scripts/XE/EST001/generar", headers={"Origin": "http://malicioso.example"})
    assert respuesta.status_code == 403


def test_ejecutar_devuelve_202_y_corre_en_segundo_plano(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    corridas: list[int] = []
    monkeypatch.setattr(ejecucion, "programar_ahora", lambda a, bd, codigo, tarea: 41)

    def ejecutar(a: Any, ejecucion_id: int) -> ResultadoEjecucion:
        corridas.append(ejecucion_id)
        return ResultadoEjecucion(ejecucion_id=41, estado=EstadoEjecucion.EXITOSA, estado_prueba=EstadoPrueba.OK)

    monkeypatch.setattr(ejecucion, "ejecutar", ejecutar)
    respuesta = api.post("/api/ejecuciones", json={"bd": "XE", "estrategia": "EST001", "tarea": "T1"})
    assert respuesta.status_code == 202
    assert respuesta.json()["ejecucion_id"] == 41
    assert corridas == [41]


def test_ejecutar_sin_script_aprobado_devuelve_409(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def programar(*a: Any) -> int:
        raise OperacionNoPermitida("La tarea no tiene un script APROBADO.")

    monkeypatch.setattr(ejecucion, "programar_ahora", programar)
    assert api.post("/api/ejecuciones", json={"estrategia": "EST001", "tarea": "T1"}).status_code == 409


def test_simular_y_verificar(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    simulacion = SimulacionEjecucion(
        bd="XE",
        estrategia="EST001",
        tarea="T1",
        script_id=9,
        version=1,
        archivo="x",
        contenido="RUN {\n}\n",
        comando="rman target /",
        tag="T",
        command_id="CLOUDCR_0",
        aprobado=True,
    )
    monkeypatch.setattr(ejecucion, "simular", lambda *a: simulacion)
    verificadas: list[int] = []
    monkeypatch.setattr(ejecucion, "verificar", lambda a, i: verificadas.append(i))
    assert api.get("/api/ejecuciones/simular/XE/EST001/T1").json()["aprobado"] is True
    assert api.post("/api/ejecuciones/41/verificar").status_code == 202
    assert verificadas == [41]


def test_retencion(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(retencion, "informe", lambda a, bd, rman: InformeRetencion(bd=bd, generado_en=AHORA))
    monkeypatch.setattr(
        retencion, "purgar", lambda a, bd, codigo, confirmar: ResultadoPurga(bd=bd, estrategia=codigo, script="x")
    )
    assert api.get("/api/retencion/XE").json()["bd"] == "XE"
    assert api.post("/api/retencion/XE/EST004/purgar", json={"confirmar": True}).json()["estrategia"] == "EST004"


def test_recuperacion(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    recibido: list[Any] = []

    def plan(a: Any, bd: str, escenario: str, objetivo: Any, hasta: Any) -> Procedimiento:
        recibido.append((escenario, objetivo, hasta))
        return Procedimiento(bd=bd, escenario=Escenario.PUNTO_EN_TIEMPO, posible=True, motivo="ok")

    monkeypatch.setattr(recuperacion, "plan", plan)
    monkeypatch.setattr(recuperacion, "puntos", lambda a, bd: PuntosRecuperacion(bd=bd))
    monkeypatch.setattr(recuperacion, "diagnostico", lambda a, bd: Diagnostico(bd=bd, generado_en=AHORA))
    assert api.get("/api/recuperacion/XE/puntos").json()["bd"] == "XE"
    assert api.get("/api/recuperacion/XE/diagnostico").json()["archivos"] == []
    respuesta = api.get("/api/recuperacion/XE/plan/punto-en-tiempo?hasta=2026-10-04 13:00")
    assert respuesta.json()["posible"] is True
    assert recibido == [("punto-en-tiempo", None, datetime(2026, 10, 4, 13, 0))]
    assert api.get("/api/recuperacion/XE/plan/pdb?hasta=ayer").status_code == 422


def test_recurso_inexistente_devuelve_404(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def ver(*a: Any) -> VistaScript:
        raise RecursoNoEncontrado("No existe la estrategia EST999.")

    monkeypatch.setattr(scripts, "ver", ver)
    assert api.get("/api/scripts/XE/EST999/T1").status_code == 404
