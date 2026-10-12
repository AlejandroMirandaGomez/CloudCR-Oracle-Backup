from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.domain.enums import EstadoPrueba, EstadoScript, LogMode, TipoRespaldo
from cloudcr_backup.domain.errores import OperacionNoPermitida
from cloudcr_backup.domain.recuperacion import (
    ArchivoDanado,
    BloqueCorrupto,
    Diagnostico,
    Escenario,
    FallaDetectada,
    MiembroRedoDanado,
    Procedimiento,
    PuntoRecuperacion,
    PuntosRecuperacion,
    RegistroRecuperacion,
    ResultadoRecuperacion,
    VistaRecuperacion,
)
from cloudcr_backup.recovery import calendario as calendario_semanal
from cloudcr_backup.services import bases_datos, recuperacion
from cloudcr_backup.web.app import crear_app
from cloudcr_backup.web.config import ConfigWeb
from tests.web.conftest import ServicioFalso
from tests.web.monitoreo_falso import MonitoreoFalso
from tests.web.test_pantallas_operaciones import ControlFalso, sin_en_linea

HTMX = {"HX-Request": "true"}
FORMULARIO = {"Content-Type": "application/x-www-form-urlencoded"}
HTMX_FORMULARIO = {**HTMX, **FORMULARIO}
ORIGEN_AJENO = {"origin": "http://atacante.example", **FORMULARIO}
AHORA = datetime(2026, 10, 8, 15, 10, tzinfo=UTC)


@pytest.fixture
def web(
    config_pruebas: ConfigWeb, servicio: ServicioFalso, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> TestClient:
    monkeypatch.setattr(bases_datos, "registradas", lambda a: ["XE"])
    app = crear_app(
        config_pruebas,
        servicio=servicio,
        ajustes=Ajustes(work_dir=tmp_path),
        monitoreo_servicio=MonitoreoFalso(),
        control_agente=ControlFalso(),
    )
    return TestClient(app)


def registro(**cambios: Any) -> RegistroRecuperacion:
    base: dict[str, Any] = {
        "id": 4,
        "bd_id": 1,
        "escenario": Escenario.DATAFILE,
        "objetivo": "7 (C:\\ORADATA\\XE\\USERS01.DBF)",
        "ruta_script": "C:\\w\\recuperacion\\XE\\datafile_20261008_151000.rman",
        "contenido": "ALTER DATABASE DATAFILE 7 OFFLINE;\n",
        "hash_sha256": "b" * 64,
        "estado": EstadoScript.BORRADOR,
    }
    base.update(cambios)
    return RegistroRecuperacion(**base)


def vista(**cambios: Any) -> VistaRecuperacion:
    base: dict[str, Any] = {"registro": registro(), "bd": "XE", "ambiente": "PRUEBAS", "archivo_intacto": True}
    base.update(cambios)
    return VistaRecuperacion(**base)


def puntos_de_la_semana(a: Any, bd: str) -> PuntosRecuperacion:
    punto = PuntoRecuperacion(
        ejecucion_id=11,
        estrategia="EST001",
        tarea="T1",
        tipo_respaldo=TipoRespaldo.COMPLETO,
        completado_en=datetime(2026, 10, 6, 3, 30),
        base_completa=True,
        estado_prueba=EstadoPrueba.OK,
    )
    return PuntosRecuperacion(bd="XE", log_mode=LogMode.ARCHIVELOG, puntos=[punto])


def test_la_pantalla_muestra_el_calendario_y_los_once_escenarios(
    web: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(recuperacion, "puntos", puntos_de_la_semana)
    monkeypatch.setattr(
        recuperacion,
        "fallas_detectadas",
        lambda a, bd: [FallaDetectada(bd="XE", detectada_en=AHORA, resumen="Datafiles dañados: 7 (USERS).")],
    )
    html = web.get("/recuperacion?bd=XE&semana=2026-10-07").text
    assert sin_en_linea(html)
    assert 'id="zona-calendario"' in html
    assert "Calendario semanal de XE" in html
    assert "Semana del 05/10/2026 al 11/10/2026" in html
    assert "celda-falla" in html and "celda-respaldo" in html
    assert "Falla detectada en 2026-10-08 09:10" in html
    assert 'hx-get="/recuperacion/XE/calendario?semana=2026-09-28"' in html
    assert html.count('<option value="') >= 11 + 1
    for escenario in Escenario:
        assert f'value="{escenario.value}"' in html
    assert "2:C:\\ORADATA\\XE\\REDO02B.LOG" in html
    assert "Bloque dañado (FILE#:BLOQUE)" in html


def test_sin_fallas_vigentes_el_calendario_no_muestra_nada_rojo(
    web: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(recuperacion, "puntos", puntos_de_la_semana)
    monkeypatch.setattr(recuperacion, "fallas_detectadas", lambda a, bd: [])
    html = web.get("/recuperacion?bd=XE&semana=2026-10-07").text
    calendario = html[html.index('id="calendario"') : html.index("leyenda-calendario")]
    assert "celda-respaldo" in calendario
    assert "celda-falla" not in calendario
    assert "tono-peligro" not in calendario.split("<tbody>")[1]
    assert "semaforo tono-exito" in calendario
    assert "1 respaldo</span>" in calendario
    assert 'hx-trigger="calendario-actualizado from:body"' in calendario
    assert 'hx-get="/recuperacion/XE/calendario?semana=2026-10-05"' in calendario


def test_el_diagnostico_pide_refrescar_el_calendario(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    sano = Diagnostico(bd="XE", generado_en=AHORA, log_mode=LogMode.ARCHIVELOG)
    monkeypatch.setattr(recuperacion, "diagnostico", lambda a, bd: sano)
    monkeypatch.setattr(recuperacion, "procedimientos_sugeridos", lambda a, resultado: [])
    respuesta = web.get("/recuperacion/XE/diagnostico", headers=HTMX)
    assert respuesta.headers["HX-Trigger"] == "calendario-actualizado"


def test_navegar_el_calendario(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    recibidos: list[Any] = []

    def calendario(a: Any, bd: str, semana: date | None = None, resumen: Any = None) -> Any:
        recibidos.append(semana)
        return calendario_semanal.construir("XE", [], [], semana or date(2026, 10, 11), "America/Costa_Rica")

    monkeypatch.setattr(recuperacion, "calendario", calendario)
    html = web.get("/recuperacion/XE/calendario?semana=2026-09-30", headers=HTMX).text
    assert recibidos == [date(2026, 9, 30)]
    assert "Semana del 28/09/2026 al 04/10/2026" in html
    assert "No hay respaldos utilizables" in html
    malo = web.get("/recuperacion/XE/calendario?semana=ayer", headers=HTMX)
    assert "no es una fecha válida" in malo.text


def test_el_diagnostico_muestra_bloques_redo_y_sugerencia(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    diagnostico = Diagnostico(
        bd="XE",
        generado_en=AHORA,
        log_mode=LogMode.ARCHIVELOG,
        archivos=[
            ArchivoDanado(
                file_id=1,
                ruta="C:\\X\\SYSTEM01.DBF",
                tablespace="SYSTEM",
                contenedor="CDB$ROOT",
                estado="OFFLINE",
                origen="x",
            )
        ],
        bloques=[BloqueCorrupto(file_id=7, bloque=131, tipo="CHECKSUM")],
        miembros_redo=[
            MiembroRedoDanado(grupo=2, miembro="C:\\R\\REDO02B.LOG", estado_miembro="INVALID", estado_grupo="CURRENT")
        ],
        sugeridos=[Escenario.DATAFILE_CRITICO, Escenario.CORRUPCION_BLOQUE],
    )
    monkeypatch.setattr(recuperacion, "diagnostico", lambda a, bd: diagnostico)
    monkeypatch.setattr(recuperacion, "procedimientos_sugeridos", lambda a, resultado: [])
    html = web.get("/recuperacion/XE/diagnostico", headers=HTMX).text
    assert "Sí (SYSTEM/UNDO)" in html
    assert "Bloques corruptos" in html and "CHECKSUM" in html
    assert "REDO02B.LOG" in html
    assert "Escenario sugerido" in html and "<code>datafile-critico</code>" in html
    assert "PERDIDA_DATAFILE_CRITICO" in html
    assert "Procedimiento sugerido" not in html


def test_el_diagnostico_muestra_debajo_el_procedimiento_sugerido_listo_para_aprobar(
    web: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    diagnostico = Diagnostico(
        bd="XE",
        generado_en=AHORA,
        log_mode=LogMode.ARCHIVELOG,
        archivos=[
            ArchivoDanado(
                file_id=17,
                ruta="C:\\X\\CLIENTEPDB\\A1_01.DBF",
                tablespace="A1",
                contenedor="CLIENTEPDB",
                estado="OFFLINE",
                origen="V$RECOVER_FILE",
            )
        ],
        sugeridos=[Escenario.DATAFILE],
    )
    recibidos: list[Any] = []

    def sugeridos(a: Any, resultado: Diagnostico) -> list[Procedimiento]:
        recibidos.append(resultado.sugeridos)
        return [
            Procedimiento(
                bd="XE",
                escenario=Escenario.DATAFILE,
                posible=True,
                motivo="ok",
                objetivo="17 (C:\\X\\CLIENTEPDB\\A1_01.DBF)",
                pasos=["Cerrar la PDB"],
                script="RESTORE DATAFILE 17;\n",
                archivo="C:\\w\\datafile.rman",
                id=9,
                estado=EstadoScript.BORRADOR,
                hash_sha256="c" * 64,
            )
        ]

    monkeypatch.setattr(recuperacion, "diagnostico", lambda a, bd: diagnostico)
    monkeypatch.setattr(recuperacion, "procedimientos_sugeridos", sugeridos)
    html = web.get("/recuperacion/XE/diagnostico", headers=HTMX).text
    assert recibidos == [[Escenario.DATAFILE]]
    assert "aparece al final de este diagnóstico" in html
    assert "Elíjalo en" not in html
    assert html.index("Datafiles que necesitan recuperación") < html.index("Procedimiento sugerido")
    assert "RESTORE DATAFILE 17;" in html
    assert "Pérdida de un datafile no crítico" in html
    assert 'id="control-recuperacion-9"' in html
    assert 'hx-post="/recuperacion/XE/aprobar"' in html
    assert 'name="procedimiento_id" value="9"' in html
    assert "c" * 64 in html


def test_el_plan_registrado_ofrece_aprobar(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def plan(a: Any, bd: str, escenario: str, objetivo: Any, hasta: Any) -> Procedimiento:
        return Procedimiento(
            bd="XE",
            escenario=Escenario.DATAFILE,
            posible=True,
            motivo="ok",
            pasos=["Restaurar"],
            script="RESTORE DATAFILE 7;\n",
            archivo="C:\\w\\datafile.rman",
            id=4,
            estado=EstadoScript.BORRADOR,
            hash_sha256="b" * 64,
        )

    monkeypatch.setattr(recuperacion, "plan", plan)
    html = web.get("/recuperacion/XE/plan?escenario=datafile", headers=HTMX).text
    assert 'id="control-recuperacion-4"' in html
    assert 'hx-post="/recuperacion/XE/aprobar"' in html
    assert 'name="procedimiento_id" value="4"' in html
    assert 'name="confirmo"' in html
    assert "b" * 64 in html


def test_aprobar_desde_la_web(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    recibidos: list[Any] = []

    def aprobar(a: Any, bd: str, procedimiento_id: int, por: str, confirmo: bool) -> VistaRecuperacion:
        recibidos.append((bd, procedimiento_id, por, confirmo))
        return vista(
            registro=registro(estado=EstadoScript.APROBADO, aprobado_por=por), aviso="Procedimiento 4 aprobado."
        )

    monkeypatch.setattr(recuperacion, "aprobar", aprobar)
    html = web.post(
        "/recuperacion/XE/aprobar", content="procedimiento_id=4&aprobado_por=Ana&confirmo=on", headers=HTMX_FORMULARIO
    ).text
    assert recibidos == [("XE", 4, "Ana", True)]
    assert "Procedimiento 4 aprobado." in html
    assert 'hx-post="/recuperacion/XE/ejecutar"' in html
    assert "Ejecutar procedimiento" in html and "de verdad" in html
    sin_js = web.post(
        "/recuperacion/XE/aprobar",
        content="procedimiento_id=4&aprobado_por=Ana&confirmo=on",
        headers=FORMULARIO,
        follow_redirects=False,
    )
    assert sin_js.status_code == 303
    assert sin_js.headers["location"] == "/recuperacion/XE/procedimientos/4"
    assert web.post("/recuperacion/XE/aprobar", content="procedimiento_id=4", headers=ORIGEN_AJENO).status_code == 403


def test_aprobar_con_error_muestra_el_motivo(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def aprobar(*argumentos: Any) -> VistaRecuperacion:
        raise OperacionNoPermitida("Falta confirmar que revisó los pasos y el script.")

    monkeypatch.setattr(recuperacion, "aprobar", aprobar)
    monkeypatch.setattr(recuperacion, "estado_procedimiento", lambda a, bd, i: vista())
    html = web.post("/recuperacion/XE/aprobar", content="procedimiento_id=4", headers=HTMX_FORMULARIO).text
    assert "Falta confirmar" in html
    assert "Aprobar el procedimiento 4" in html
    sin_id = web.post("/recuperacion/XE/aprobar", content="", headers=HTMX_FORMULARIO)
    assert "Falta indicar el procedimiento" in sin_id.text


def test_ejecutar_lanza_en_segundo_plano_y_la_tarjeta_se_actualiza(
    web: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    preparados: list[Any] = []
    completados: list[Any] = []
    en_curso = registro(estado=EstadoScript.APROBADO, resultado=ResultadoRecuperacion.EN_CURSO)

    def preparar(a: Any, bd: str, procedimiento_id: int, confirmo: bool) -> VistaRecuperacion:
        preparados.append((bd, procedimiento_id, confirmo))
        return vista(registro=en_curso, bloqueo="ya se está ejecutando", aviso="Ejecución lanzada.")

    monkeypatch.setattr(recuperacion, "preparar_ejecucion", preparar)
    monkeypatch.setattr(recuperacion, "completar_ejecucion", lambda a, bd, i: completados.append((bd, i)))
    html = web.post("/recuperacion/XE/ejecutar", content="procedimiento_id=4&confirmo=on", headers=HTMX_FORMULARIO).text
    assert preparados == [("XE", 4, True)]
    assert completados == [("XE", 4)]
    assert 'hx-get="/recuperacion/XE/procedimientos/4"' in html and 'hx-trigger="every 3s"' in html
    terminado = registro(
        estado=EstadoScript.APROBADO, resultado=ResultadoRecuperacion.EJECUTADO_OK, mensaje="RMAN terminó sin errores."
    )
    monkeypatch.setattr(
        recuperacion,
        "estado_procedimiento",
        lambda a, bd, i: vista(registro=terminado, bloqueo="ya se ejecutó", log_rman="Recovery Manager complete."),
    )
    html = web.get("/recuperacion/XE/procedimientos/4", headers=HTMX).text
    assert "every 3s" not in html
    assert "Ejecutado sin errores" in html and "Recovery Manager complete." in html
    pagina = web.get("/recuperacion/XE/procedimientos/4").text
    assert sin_en_linea(pagina)
    assert "Procedimiento de recuperación 4" in pagina and "ALTER DATABASE DATAFILE 7 OFFLINE;" in pagina


def test_en_produccion_tambien_hay_boton_de_ejecutar(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    aprobada = vista(registro=registro(estado=EstadoScript.APROBADO), ambiente="PRODUCCION")
    monkeypatch.setattr(recuperacion, "estado_procedimiento", lambda a, bd, i: aprobada)
    html = web.get("/recuperacion/XE/procedimientos/4", headers=HTMX).text
    assert "Ejecutar procedimiento" in html
    assert "ambiente PRODUCCION" in html
    assert 'hx-post="/recuperacion/XE/ejecutar"' in html


def test_ejecutar_bloqueado_muestra_el_motivo(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    ejecutada = vista(
        registro=registro(estado=EstadoScript.APROBADO, resultado=ResultadoRecuperacion.EJECUTADO_OK),
        bloqueo="El procedimiento 4 ya se ejecutó.",
    )

    def preparar(*argumentos: Any) -> VistaRecuperacion:
        raise OperacionNoPermitida(ejecutada.bloqueo or "")

    monkeypatch.setattr(recuperacion, "estado_procedimiento", lambda a, bd, i: ejecutada)
    monkeypatch.setattr(recuperacion, "preparar_ejecucion", preparar)
    respuesta = web.post("/recuperacion/XE/ejecutar", content="procedimiento_id=4&confirmo=on", headers=FORMULARIO)
    assert respuesta.status_code == 409
    assert "ya se ejecutó" in respuesta.text
