import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.domain.administracion import (
    BorradorEdicion,
    ComprobacionEntorno,
    EjemploEstrategia,
    EstadoControlAgente,
    EstadoRepositorio,
    EstrategiaEditada,
    EstrategiaImportada,
    ParametroRepositorio,
    PerfilGuardado,
    RecomendacionAplicada,
    ResultadoValidacion,
    TablaRepositorio,
    VistaBaseDatos,
)
from cloudcr_backup.domain.enums import EstadoEjecucion, EstadoPrueba, EstadoScript, LogMode, ModoRespaldo, Severidad
from cloudcr_backup.domain.errores import OperacionNoPermitida, RecursoNoEncontrado
from cloudcr_backup.domain.hallazgos import Hallazgo
from cloudcr_backup.domain.historial import ArchivoExportado
from cloudcr_backup.domain.recuperacion import Diagnostico, Escenario, Procedimiento, PuntosRecuperacion
from cloudcr_backup.domain.retencion import InformeRetencion, ResultadoPurga, RetencionEstrategia
from cloudcr_backup.domain.scripts import FilaExplicacion, SimulacionEjecucion, VistaScript
from cloudcr_backup.services import (
    administracion,
    bases_datos,
    ejecucion,
    gestion_estrategias,
    recuperacion,
    retencion,
    scripts,
)
from cloudcr_backup.web.app import crear_app
from cloudcr_backup.web.config import ConfigWeb
from tests.web.conftest import ServicioFalso
from tests.web.monitoreo_falso import MonitoreoFalso, fila_historial

AHORA = datetime(2026, 10, 4, 18, tzinfo=UTC)
HTMX = {"HX-Request": "true"}
FORMULARIO = {"Content-Type": "application/x-www-form-urlencoded"}
HTMX_FORMULARIO = {**HTMX, **FORMULARIO}
ORIGEN_AJENO = {"origin": "http://atacante.example", **FORMULARIO}
RUTA_SCRIPT = "/estrategias/XE/EST001/scripts/T1"


def vista(**cambios: Any) -> VistaScript:
    base: dict[str, Any] = {
        "bd": "XE",
        "estrategia": "EST001",
        "tarea": "T1",
        "tarea_id": 3,
        "script_id": 9,
        "version": 2,
        "estado": EstadoScript.BORRADOR,
        "hash_sha256": "a" * 64,
        "contenido": "SHUTDOWN IMMEDIATE;\nRUN {\n}\n",
        "modo": ModoRespaldo.CONSISTENTE,
        "creado_en": datetime(2026, 10, 4, 12),
        "archivo": r"C:\work\scripts\XE\EST001\T1_v2.rman",
        "archivo_intacto": True,
        "explicacion": [FilaExplicacion(campo="Tipo de respaldo", clausula="BACKUP INCREMENTAL LEVEL 0")],
        "hallazgos": [
            Hallazgo(codigo="ARCH_001", severidad=Severidad.ADVERTENCIA, mensaje="NOARCHIVELOG", sujeto="XE")
        ],
    }
    base.update(cambios)
    return VistaScript(**base)


class ControlFalso:
    def __init__(self) -> None:
        self.llamadas: list[str] = []
        self.corriendo = False

    def estado(self) -> EstadoControlAgente:
        return EstadoControlAgente(
            corriendo=self.corriendo, simulado=True, iniciado_en=AHORA if self.corriendo else None
        )

    def iniciar(self, simulado: bool) -> EstadoControlAgente:
        self.llamadas.append(f"iniciar:{simulado}")
        self.corriendo = True
        return self.estado()

    def un_ciclo(self, simulado: bool) -> EstadoControlAgente:
        self.llamadas.append(f"ciclo:{simulado}")
        return self.estado()

    def detener(self, esperar_segundos: float = 0) -> EstadoControlAgente:
        self.llamadas.append("detener")
        self.corriendo = False
        return self.estado()

    def apagar(self, esperar_segundos: float) -> None:
        self.llamadas.append("apagar")

    def iniciar_si_corresponde(self) -> None:
        self.llamadas.append("autoinicio")


@pytest.fixture
def monitoreo() -> MonitoreoFalso:
    return MonitoreoFalso()


@pytest.fixture
def control() -> ControlFalso:
    return ControlFalso()


@pytest.fixture
def web(
    config_pruebas: ConfigWeb, servicio: ServicioFalso, monitoreo: MonitoreoFalso, control: ControlFalso, tmp_path: Path
) -> TestClient:
    app = crear_app(
        config_pruebas,
        servicio=servicio,
        ajustes=Ajustes(work_dir=tmp_path),
        monitoreo_servicio=monitoreo,
        control_agente=control,
    )
    return TestClient(app)


@pytest.fixture
def con_bases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bases_datos, "registradas", lambda a: ["XE"])


def sin_en_linea(html: str) -> bool:
    return re.search(r"<script(?![^>]*\bsrc=)", html) is None and " style=" not in html


def test_pagina_de_script_con_borrador_consistente(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scripts, "ver", lambda a, bd, codigo, tarea, version: vista())
    monkeypatch.setattr(
        scripts, "listar", lambda a, bd, codigo: [vista(), vista(version=1, estado=EstadoScript.OBSOLETO)]
    )
    respuesta = web.get(RUTA_SCRIPT)
    assert respuesta.status_code == 200
    html = respuesta.text
    assert sin_en_linea(html)
    assert "Borrador sin aprobar" in html
    assert 'name="acepto_caida"' in html
    assert "SHUTDOWN IMMEDIATE" in html
    assert "BACKUP INCREMENTAL LEVEL 0" in html
    assert "ARCH_001" in html
    assert f'href="{RUTA_SCRIPT}?version=1"' in html
    assert "2026-10-04 12:00" in html


def test_pagina_de_script_sin_scripts_ofrece_generar(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def ver(*a: Any) -> VistaScript:
        raise RecursoNoEncontrado("La tarea EST001/T1 no tiene scripts generados.")

    monkeypatch.setattr(scripts, "ver", ver)
    respuesta = web.get(RUTA_SCRIPT)
    assert respuesta.status_code == 200
    assert "Generar el script" in respuesta.text


def test_tarea_inexistente_da_404(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scripts, "ver", lambda *a: vista())
    monkeypatch.setattr(scripts, "listar", lambda *a: [vista()])
    assert web.get("/estrategias/XE/EST001/scripts/T9").status_code == 404


def test_aprobar_pasa_los_campos_del_formulario(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    recibido: list[Any] = []

    def aprobar(a: Any, bd: str, codigo: str, tarea: str, por: str, acepto: bool, version: int | None) -> VistaScript:
        recibido.append((por, acepto, version))
        return vista(estado=EstadoScript.APROBADO, aprobado_por=por, aprobado_en=datetime(2026, 10, 4, 20))

    monkeypatch.setattr(scripts, "aprobar", aprobar)
    monkeypatch.setattr(scripts, "listar", lambda *a: [vista(estado=EstadoScript.APROBADO)])
    respuesta = web.post(
        f"{RUTA_SCRIPT}/aprobar", content="version=2&aprobado_por=Ale&acepto_caida=on", headers=HTMX_FORMULARIO
    )
    assert respuesta.status_code == 200
    assert recibido == [("Ale", True, 2)]
    assert "aprobado por Ale" in respuesta.text
    assert "Ejecutar ahora" in respuesta.text
    assert "Simular la ejecución" in respuesta.text
    assert "2026-10-04 14:00" in respuesta.text


def test_aprobar_rechazado_se_muestra_en_el_panel(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def aprobar(*a: Any) -> VistaScript:
        raise OperacionNoPermitida("El script hace un respaldo CONSISTENTE.", "Acepte la caída del servicio.")

    monkeypatch.setattr(scripts, "aprobar", aprobar)
    monkeypatch.setattr(scripts, "ver", lambda *a: vista())
    monkeypatch.setattr(scripts, "listar", lambda *a: [vista()])
    respuesta = web.post(f"{RUTA_SCRIPT}/aprobar", content="version=2", headers=HTMX_FORMULARIO)
    assert respuesta.status_code == 200
    assert "mensaje-error" in respuesta.text
    assert "CONSISTENTE" in respuesta.text
    assert "Borrador sin aprobar" in respuesta.text


def test_aprobar_sin_javascript_redirige(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scripts, "aprobar", lambda *a: vista(estado=EstadoScript.APROBADO))
    monkeypatch.setattr(scripts, "listar", lambda *a: [vista()])
    respuesta = web.post(f"{RUTA_SCRIPT}/aprobar", content="version=2", headers=FORMULARIO, follow_redirects=False)
    assert respuesta.status_code == 303
    assert respuesta.headers["location"] == f"{RUTA_SCRIPT}?version=2"


def test_rechazar_pasa_el_motivo(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    recibido: list[Any] = []

    def rechazar(a: Any, bd: str, codigo: str, tarea: str, motivo: str, version: int | None) -> VistaScript:
        recibido.append((motivo, version))
        return vista(estado=EstadoScript.RECHAZADO, motivo_rechazo=motivo)

    monkeypatch.setattr(scripts, "rechazar", rechazar)
    monkeypatch.setattr(scripts, "listar", lambda *a: [vista(estado=EstadoScript.RECHAZADO)])
    respuesta = web.post(
        f"{RUTA_SCRIPT}/rechazar", content="version=2&motivo=Destino+equivocado", headers=HTMX_FORMULARIO
    )
    assert recibido == [("Destino equivocado", 2)]
    assert "Rechazado" in respuesta.text


def test_version_invalida_en_el_formulario(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scripts, "ver", lambda *a: vista())
    monkeypatch.setattr(scripts, "listar", lambda *a: [vista()])
    respuesta = web.post(f"{RUTA_SCRIPT}/aprobar", content="version=dos", headers=HTMX_FORMULARIO)
    assert "número entero" in respuesta.text


def test_regenerar_avisa_version_nueva(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scripts, "generar", lambda a, bd, codigo, tarea: [vista(version=3, nueva=True)])
    monkeypatch.setattr(scripts, "listar", lambda *a: [vista(version=3)])
    respuesta = web.post(f"{RUTA_SCRIPT}/generar", headers=HTMX)
    assert "Se generó la versión 3." in respuesta.text


def test_generar_scripts_de_la_estrategia(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    pedidas: list[Any] = []

    def generar(a: Any, bd: str, codigo: str, tarea: str | None) -> list[VistaScript]:
        pedidas.append(tarea)
        return [vista(nueva=True, avisos=["No se generó: EST001/T2 imposible"])]

    monkeypatch.setattr(scripts, "generar", generar)
    respuesta = web.post("/estrategias/XE/EST001/generar-scripts", headers=HTMX)
    assert pedidas == [None]
    assert "Versión nueva" in respuesta.text
    assert f'href="{RUTA_SCRIPT}"' in respuesta.text
    assert "EST001/T2 imposible" in respuesta.text
    sin_js = web.post("/estrategias/XE/EST001/generar-scripts", follow_redirects=False)
    assert sin_js.status_code == 303
    assert sin_js.headers["location"] == RUTA_SCRIPT


def test_simular_muestra_preflight_y_comando(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    simulacion = SimulacionEjecucion(
        bd="XE",
        estrategia="EST001",
        tarea="T1",
        script_id=9,
        version=2,
        archivo="T1_v2.rman",
        contenido="RUN {}",
        comando="rman.exe target / cmdfile=EST001.XE.RMAN",
        tag="EST001_T1_2610041800",
        command_id="CLOUDCR_0",
        aprobado=False,
        problemas=["SCRIPT_ALTERADO: el hash no coincide"],
    )
    monkeypatch.setattr(ejecucion, "simular", lambda a, bd, codigo, tarea: simulacion)
    respuesta = web.get(f"{RUTA_SCRIPT}/simular", headers=HTMX)
    assert "bloquearía la ejecución" in respuesta.text
    assert "SCRIPT_ALTERADO" in respuesta.text
    assert "cmdfile=EST001.XE.RMAN" in respuesta.text


def test_ejecutar_ahora_lanza_en_segundo_plano(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    lanzadas: list[int] = []
    monkeypatch.setattr(ejecucion, "programar_ahora", lambda a, bd, codigo, tarea: 77)
    monkeypatch.setattr(ejecucion, "ejecutar", lambda a, ejecucion_id: lanzadas.append(ejecucion_id))
    respuesta = web.post(f"{RUTA_SCRIPT}/ejecutar", headers=HTMX)
    assert respuesta.status_code == 200
    assert 'href="/historial/77"' in respuesta.text
    assert lanzadas == [77]
    sin_js = web.post(f"{RUTA_SCRIPT}/ejecutar", follow_redirects=False)
    assert sin_js.headers["location"] == "/historial/77"


def test_ejecutar_sin_script_aprobado(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def programar(*a: Any) -> int:
        raise OperacionNoPermitida("La tarea EST001/T1 no tiene un script APROBADO.")

    monkeypatch.setattr(ejecucion, "programar_ahora", programar)
    respuesta = web.post(f"{RUTA_SCRIPT}/ejecutar", headers=HTMX)
    assert "no tiene un script APROBADO" in respuesta.text


@pytest.mark.parametrize(
    "ruta",
    [
        f"{RUTA_SCRIPT}/aprobar",
        f"{RUTA_SCRIPT}/ejecutar",
        "/estrategias/XE/EST001/generar-scripts",
        "/estrategias/importar",
        "/historial/40/verificar",
        "/retencion/XE/EST001/purgar",
        "/sistema/parametros",
        "/sistema/bases/registrar",
        "/sistema/agente/iniciar",
        "/sistema/repositorio/instalar",
    ],
)
def test_acciones_desde_otro_origen_se_rechazan(web: TestClient, control: ControlFalso, ruta: str) -> None:
    assert web.post(ruta, content="x=1", headers=ORIGEN_AJENO).status_code == 403
    assert control.llamadas == []


def test_formulario_que_no_es_urlencoded(web: TestClient) -> None:
    respuesta = web.post("/sistema/parametros", content="{}", headers={**HTMX, "Content-Type": "application/json"})
    assert "application/x-www-form-urlencoded" in respuesta.text


def test_detalle_de_estrategia_tiene_las_acciones_nuevas(web: TestClient) -> None:
    html = web.get("/estrategias/XE/EST001").text
    assert 'hx-get="/estrategias/XE/EST001/validar"' in html
    assert 'action="/estrategias/XE/EST001/generar-scripts"' in html
    assert 'href="/estrategias/XE/EST001/exportar"' in html
    assert f'href="{RUTA_SCRIPT}"' in html


def test_validar_y_aplicar_recomendacion(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    resultado = ResultadoValidacion(
        bd="XE",
        estrategia="EST001",
        version=1,
        hallazgos=[
            Hallazgo(
                codigo="ARCH_002", severidad=Severidad.RECOMENDACION, mensaje="Considere archived", sujeto="EST001"
            ),
            Hallazgo(codigo="DST_002", severidad=Severidad.ERROR, mensaje="Sin espacio", sujeto="T1"),
        ],
        perfil_capturado_en=datetime(2026, 10, 4, 13),
    )
    monkeypatch.setattr(gestion_estrategias, "validar", lambda a, bd, codigo: resultado)
    html = web.get("/estrategias/XE/EST001/validar", headers=HTMX).text
    assert "no se puede aprobar" in html
    assert 'hx-post="/estrategias/XE/EST001/recomendaciones/ARCH_002/aplicar"' in html
    assert "recomendaciones/DST_002" not in html
    aplicada = RecomendacionAplicada(
        bd="XE", estrategia="EST001", codigo="ARCH_002", version=2, aplicada=True, mensaje="Se agregó ARCHIVELOG."
    )
    monkeypatch.setattr(gestion_estrategias, "aplicar_recomendacion", lambda a, bd, codigo, rec: aplicada)
    detalle = web.post("/estrategias/XE/EST001/recomendaciones/ARCH_002/aplicar", headers=HTMX).text
    assert "Se agregó ARCHIVELOG." in detalle
    assert "EST001" in detalle


def test_exportar_yaml(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    archivo = ArchivoExportado(
        nombre="XE_EST001_v1.yaml", tipo_contenido="application/x-yaml", contenido=b"codigo: EST001\n"
    )
    monkeypatch.setattr(gestion_estrategias, "exportar", lambda a, bd, codigo: archivo)
    respuesta = web.get("/estrategias/XE/EST001/exportar")
    assert respuesta.content == b"codigo: EST001\n"
    assert 'filename="XE_EST001_v1.yaml"' in respuesta.headers["content-disposition"]


def test_importar_desde_ejemplo(web: TestClient, monkeypatch: pytest.MonkeyPatch, con_bases: None) -> None:
    ejemplos = [EjemploEstrategia(archivo="est002.yaml", codigo="EST002", nombre="Consistente")]
    monkeypatch.setattr(gestion_estrategias, "ejemplos", lambda: ejemplos)
    monkeypatch.setattr(gestion_estrategias, "contenido_ejemplo", lambda archivo: f"codigo: {archivo}")
    pagina = web.get("/estrategias/importar")
    assert sin_en_linea(pagina.text)
    assert "EST002 · Consistente (est002.yaml)" in pagina.text
    assert "codigo: est002.yaml" in web.get("/estrategias/importar?ejemplo=est002.yaml", headers=HTMX).text
    recibido: list[Any] = []

    def importar(a: Any, bd: str, contenido: str, reemplazar: bool) -> EstrategiaImportada:
        recibido.append((bd, contenido, reemplazar))
        return EstrategiaImportada(bd="XE", codigo="EST002", nombre="Consistente", version=1)

    monkeypatch.setattr(gestion_estrategias, "importar", importar)
    respuesta = web.post(
        "/estrategias/importar", content="bd=XE&ejemplo=est002.yaml&contenido=&reemplazar=on", headers=HTMX_FORMULARIO
    )
    assert recibido == [("XE", "codigo: est002.yaml", True)]
    assert 'href="/estrategias/XE/EST002"' in respuesta.text


def test_verificar_desde_el_historial(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    verificadas: list[int] = []
    monkeypatch.setattr(ejecucion, "verificar", lambda a, ejecucion_id: verificadas.append(ejecucion_id))
    pagina = web.get("/historial/40").text
    assert 'action="/historial/40/verificar"' in pagina
    respuesta = web.post("/historial/40/verificar", headers=HTMX)
    assert "Verificación de la ejecución 40 lanzada" in respuesta.text
    assert verificadas == [40]


def test_historial_en_curso_se_actualiza_solo(web: TestClient, monitoreo: MonitoreoFalso) -> None:
    monitoreo.filas = [fila_historial(41, EstadoEjecucion.EN_CURSO)]
    html = web.get("/historial/41").text
    assert 'hx-trigger="every 5s"' in html
    assert "/historial/41/verificar" not in html


def test_simulacion_no_ofrece_verificar(web: TestClient, monitoreo: MonitoreoFalso) -> None:
    fila = fila_historial(42).model_copy(update={"estado_prueba": EstadoPrueba.NO_APLICA})
    monitoreo.filas = [fila]
    assert "/historial/42/verificar" not in web.get("/historial/42").text


def informe(purga: bool) -> InformeRetencion:
    return InformeRetencion(
        bd="XE",
        generado_en=AHORA,
        estrategias=[
            RetencionEstrategia(
                estrategia="EST001",
                nombre="Producción diaria",
                politica="RECOVERY WINDOW OF 30 DAYS",
                descripcion="Conservar 30 días",
                purga_automatica=purga,
                piezas_total=3,
            )
        ],
        archivelogs_sin_respaldo=4,
    )


def test_retencion_sin_purga_automatica(web: TestClient, monkeypatch: pytest.MonkeyPatch, con_bases: None) -> None:
    pedidos: list[Any] = []

    def informar(a: Any, bd: str, rman: bool) -> InformeRetencion:
        pedidos.append((bd, rman))
        return informe(False)

    monkeypatch.setattr(retencion, "informe", informar)
    html = web.get("/retencion?bd=xe&rman=true").text
    assert sin_en_linea(html)
    assert pedidos == [("XE", True)]
    assert "RECOVERY WINDOW OF 30 DAYS" in html
    assert "/purgar" not in html


def test_purgar_solo_con_purga_automatica(web: TestClient, monkeypatch: pytest.MonkeyPatch, con_bases: None) -> None:
    monkeypatch.setattr(retencion, "informe", lambda a, bd, rman: informe(True))
    assert 'hx-post="/retencion/XE/EST001/purgar"' in web.get("/retencion").text
    recibido: list[bool] = []

    def purgar(a: Any, bd: str, codigo: str, confirmado: bool) -> ResultadoPurga:
        recibido.append(confirmado)
        return ResultadoPurga(bd="XE", estrategia="EST001", script="DELETE NOPROMPT OBSOLETE;", borradas=["a.bkp"])

    monkeypatch.setattr(retencion, "purgar", purgar)
    respuesta = web.post("/retencion/XE/EST001/purgar", content="confirmar=on", headers=HTMX_FORMULARIO)
    assert recibido == [True]
    assert "1 piezas borradas" in respuesta.text


def test_retencion_sin_bases(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bases_datos, "registradas", lambda a: [])
    assert "No hay bases de datos registradas" in web.get("/retencion").text


def test_recuperacion_puntos_diagnostico_y_plan(
    web: TestClient, monkeypatch: pytest.MonkeyPatch, con_bases: None
) -> None:
    monkeypatch.setattr(
        recuperacion, "puntos", lambda a, bd: PuntosRecuperacion(bd="XE", log_mode=LogMode.NOARCHIVELOG)
    )
    html = web.get("/recuperacion").text
    assert sin_en_linea(html)
    assert 'hx-get="/recuperacion/XE/diagnostico"' in html
    assert 'value="total-noarchivelog"' in html
    monkeypatch.setattr(
        recuperacion,
        "diagnostico",
        lambda a, bd: Diagnostico(bd="XE", generado_en=AHORA, avisos=["V$RECOVER_FILE no informa archivos."]),
    )
    assert "V$RECOVER_FILE no informa archivos." in web.get("/recuperacion/XE/diagnostico", headers=HTMX).text
    recibido: list[Any] = []

    def plan(a: Any, bd: str, escenario: str, objetivo: str | None, hasta: datetime | None) -> Procedimiento:
        recibido.append((escenario, objetivo, hasta))
        return Procedimiento(
            bd="XE",
            escenario=Escenario.PUNTO_EN_TIEMPO,
            posible=True,
            motivo="Hay ARCHIVELOG continuo.",
            pasos=["Fijar SET UNTIL TIME"],
            script="RUN { SET UNTIL TIME; }",
        )

    monkeypatch.setattr(recuperacion, "plan", plan)
    respuesta = web.get(
        "/recuperacion/XE/plan?escenario=punto-en-tiempo&objetivo=&hasta=2026-10-04T13:30", headers=HTMX
    )
    assert recibido == [("punto-en-tiempo", None, datetime(2026, 10, 4, 13, 30))]
    assert "SET UNTIL TIME" in respuesta.text
    assert "Recuperación a un punto en el tiempo" in respuesta.text


def test_plan_con_fecha_invalida(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    respuesta = web.get("/recuperacion/XE/plan?escenario=datafile&hasta=ayer", headers=HTMX)
    assert "no es una fecha y hora válida" in respuesta.text


def test_sistema_carga_sus_secciones(web: TestClient) -> None:
    html = web.get("/sistema").text
    assert sin_en_linea(html)
    for zona in ("agente", "bases", "entorno", "archivado", "repositorio", "parametros"):
        assert f'hx-get="/sistema/{zona}"' in html


def test_sistema_entorno_y_repositorio(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        administracion,
        "comprobar_entorno",
        lambda a: [ComprobacionEntorno(nombre="rman.exe", ok=False, detalle="No encontrado", sugerencia="Revise")],
    )
    assert "Sugerencia: Revise" in web.get("/sistema/entorno", headers=HTMX).text
    instalado = EstadoRepositorio(instalado=True, esperadas=12, tablas=[TablaRepositorio(nombre="ALERTA", filas=3)])
    monkeypatch.setattr(administracion, "estado_repositorio", lambda a: instalado)
    html = web.get("/sistema/repositorio", headers=HTMX).text
    assert "Instalado: 1 de 12" in html
    assert "/sistema/repositorio/instalar" not in html


def test_sistema_parametros(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    lista = [ParametroRepositorio(clave="agente.tick_segundos", valor="15", inicial="30")]
    monkeypatch.setattr(administracion, "parametros", lambda a: lista)
    html = web.get("/sistema/parametros", headers=HTMX).text
    assert "modificado (inicial: 30)" in html
    asignados: list[Any] = []
    monkeypatch.setattr(
        administracion,
        "asignar_parametro",
        lambda a, clave, valor: asignados.append((clave, valor)) or ParametroRepositorio(clave=clave, valor=valor),
    )
    respuesta = web.post("/sistema/parametros", content="clave=agente.tick_segundos&valor=10", headers=HTMX_FORMULARIO)
    assert asignados == [("agente.tick_segundos", "10")]
    assert "Parámetro agente.tick_segundos actualizado." in respuesta.text


def test_sistema_bases(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    vistas = [
        VistaBaseDatos(nombre="XE", registrada=True, id=1, ambiente="PRUEBAS", activa=True, en_ejecucion=True),
        VistaBaseDatos(nombre="ORCL", registrada=False, en_ejecucion=False),
    ]
    monkeypatch.setattr(bases_datos, "listar", lambda a: vistas)
    html = web.get("/sistema/bases", headers=HTMX).text
    assert 'hx-post="/sistema/bases/XE/inspeccionar"' in html
    assert 'value="ORCL"' in html
    registradas: list[Any] = []
    monkeypatch.setattr(
        bases_datos,
        "registrar",
        lambda a, sid, ambiente: (
            registradas.append((sid, ambiente)) or vistas[1].model_copy(update={"ambiente": ambiente})
        ),
    )
    web.post("/sistema/bases/registrar", content="sid=ORCL&ambiente=PRUEBAS", headers=HTMX_FORMULARIO)
    assert registradas == [("ORCL", "PRUEBAS")]
    guardado = PerfilGuardado(bd="XE", capturado_en=AHORA, log_mode=LogMode.ARCHIVELOG, tablespaces=5, datafiles=7)
    monkeypatch.setattr(bases_datos, "inspeccionar", lambda a, nombre: guardado)
    assert "ARCHIVELOG, 5 tablespaces, 7 datafiles" in web.post("/sistema/bases/XE/inspeccionar", headers=HTMX).text


def test_sistema_agente(web: TestClient, control: ControlFalso) -> None:
    html = web.get("/sistema/agente", headers=HTMX).text
    assert "Iniciar" in html
    assert 'hx-trigger="every 5s"' not in html
    corriendo = web.post("/sistema/agente/iniciar", content="simulado=on", headers=HTMX_FORMULARIO).text
    assert "Detener el agente" in corriendo
    assert 'hx-trigger="every 5s"' in corriendo
    web.post("/sistema/agente/detener", headers=HTMX)
    web.post("/sistema/agente/ciclo", content="", headers=HTMX_FORMULARIO)
    assert control.llamadas == ["iniciar:True", "detener", "ciclo:False"]


def test_navegacion_incluye_las_secciones_nuevas(web: TestClient) -> None:
    html = web.get("/estado").text
    for ruta in ("/retencion", "/recuperacion", "/sistema"):
        assert f'href="{ruta}"' in html


def borrador(**cambios: Any) -> BorradorEdicion:
    base: dict[str, Any] = {
        "bd": "XE",
        "codigo": "EST001",
        "nombre": "Respaldo diario",
        "version": 1,
        "contenido": "codigo: EST001\nnombre: Respaldo diario\n",
    }
    return BorradorEdicion.model_validate({**base, **cambios})


def edicion(**cambios: Any) -> EstrategiaEditada:
    base: dict[str, Any] = {"bd": "XE", "codigo": "EST001", "nombre": "Respaldo diario", "version": 2}
    return EstrategiaEditada.model_validate({**base, **cambios})


def test_pagina_editar_muestra_el_yaml_y_los_valores_permitidos(
    web: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    pedidos: list[bool] = []

    def contenido(a: Any, bd: str, codigo: str, agregar_tarea: bool) -> BorradorEdicion:
        pedidos.append(agregar_tarea)
        return borrador(tarea_agregada="T2" if agregar_tarea else None)

    monkeypatch.setattr(gestion_estrategias, "contenido_para_editar", contenido)
    html = web.get("/estrategias/XE/EST001/editar").text
    assert sin_en_linea(html)
    assert "Editar EST001 — Respaldo diario" in html
    assert "codigo: EST001" in html
    assert "Guardar como versión 2" in html
    assert "INCREMENTAL_N1_ACUMULATIVO" in html and "SEMANAL" in html and "EN_LINEA" in html
    assert 'hx-post="/estrategias/XE/EST001/editar/validar"' in html
    assert "Se agregó la tarea" not in html
    agregada = web.get("/estrategias/XE/EST001/editar?agregar_tarea=true").text
    assert "Se agregó la tarea T2" in agregada
    assert pedidos == [False, True]


def test_editar_una_estrategia_inexistente_da_404(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def no_existe(a: Any, bd: str, codigo: str, agregar_tarea: bool) -> BorradorEdicion:
        raise RecursoNoEncontrado("No existe la estrategia EST777.")

    monkeypatch.setattr(gestion_estrategias, "contenido_para_editar", no_existe)
    assert web.get("/estrategias/XE/EST777/editar").status_code == 404


def test_validar_borrador_no_ofrece_aplicar_recomendaciones(
    web: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    resultado = ResultadoValidacion(
        bd="XE",
        estrategia="EST001",
        version=2,
        hallazgos=[
            Hallazgo(
                codigo="ARCH_002", severidad=Severidad.RECOMENDACION, mensaje="Considere archived", sujeto="EST001"
            )
        ],
        perfil_capturado_en=datetime(2026, 10, 4, 13),
    )
    recibido: list[str] = []

    def validar(a: Any, bd: str, codigo: str, contenido: str) -> ResultadoValidacion:
        recibido.append(contenido)
        return resultado

    monkeypatch.setattr(gestion_estrategias, "validar_borrador", validar)
    html = web.post(
        "/estrategias/XE/EST001/editar/validar", content="contenido=codigo%3A+EST001", headers=HTMX_FORMULARIO
    ).text
    assert recibido == ["codigo: EST001"]
    assert "ARCH_002" in html and "versión 2" in html
    assert "Aplicar esta recomendación" not in html


def test_guardar_edicion_redirige_al_detalle_con_el_aviso(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    guardadas: list[tuple[str, str, str]] = []

    def guardar(a: Any, bd: str, codigo: str, contenido: str) -> EstrategiaEditada:
        guardadas.append((bd, codigo, contenido))
        return edicion(tareas_a_regenerar=["T1"])

    monkeypatch.setattr(gestion_estrategias, "guardar_edicion", guardar)
    htmx = web.post("/estrategias/XE/EST001/editar", content="contenido=x%3A+1", headers=HTMX_FORMULARIO)
    assert htmx.status_code == 204
    assert htmx.headers["hx-redirect"].startswith("/estrategias/XE/EST001?aviso=")
    assert "versi%C3%B3n+2" in htmx.headers["hx-redirect"]
    sin_js = web.post(
        "/estrategias/XE/EST001/editar", content="contenido=x%3A+1", headers=FORMULARIO, follow_redirects=False
    )
    assert sin_js.status_code == 303
    assert guardadas[0] == ("XE", "EST001", "x: 1")


def test_el_detalle_muestra_el_aviso_de_la_edicion(web: TestClient) -> None:
    html = web.get("/estrategias/XE/EST001?aviso=Estrategia+EST001+guardada+como+versi%C3%B3n+2.").text
    assert "Estrategia EST001 guardada como versión 2." in html
    assert "<script>" not in web.get("/estrategias/XE/EST001?aviso=%3Cscript%3Ealert(1)%3C/script%3E").text


def test_guardar_edicion_rechazada_se_muestra_en_el_panel(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def rechazar(a: Any, bd: str, codigo: str, contenido: str) -> EstrategiaEditada:
        raise OperacionNoPermitida("La tarea T1 ya tiene ejecuciones registradas.", "Los cambios no se guardaron.")

    monkeypatch.setattr(gestion_estrategias, "guardar_edicion", rechazar)
    respuesta = web.post("/estrategias/XE/EST001/editar", content="contenido=x", headers=HTMX_FORMULARIO)
    assert "La tarea T1 ya tiene ejecuciones registradas." in respuesta.text
    assert "Los cambios no se guardaron." in respuesta.text


def test_detalle_ofrece_editar_agregar_y_eliminar_tarea(web: TestClient) -> None:
    html = web.get("/estrategias/XE/EST001").text
    assert 'href="/estrategias/XE/EST001/editar"' in html
    assert 'href="/estrategias/XE/EST001/editar?agregar_tarea=true"' in html
    assert 'action="/estrategias/XE/EST001/tareas/T1/eliminar"' in html


def test_eliminar_tarea_actualiza_el_detalle(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    eliminadas: list[tuple[str, str, str]] = []

    def eliminar(a: Any, bd: str, codigo: str, tarea: str) -> EstrategiaEditada:
        eliminadas.append((bd, codigo, tarea))
        return edicion(tareas_eliminadas=["T2"])

    monkeypatch.setattr(gestion_estrategias, "eliminar_tarea", eliminar)
    html = web.post("/estrategias/XE/EST001/tareas/T2/eliminar", headers=HTMX).text
    assert eliminadas == [("XE", "EST001", "T2")]
    assert "Tareas eliminadas: T2." in html
    sin_js = web.post("/estrategias/XE/EST001/tareas/T2/eliminar", follow_redirects=False)
    assert sin_js.status_code == 303 and sin_js.headers["location"].startswith("/estrategias/XE/EST001?aviso=")


def test_eliminar_la_unica_tarea_se_rechaza(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def rechazar(a: Any, bd: str, codigo: str, tarea: str) -> EstrategiaEditada:
        raise OperacionNoPermitida("T1 es la única tarea de EST001.")

    monkeypatch.setattr(gestion_estrategias, "eliminar_tarea", rechazar)
    respuesta = web.post("/estrategias/XE/EST001/tareas/T1/eliminar", headers=HTMX)
    assert "única tarea" in respuesta.text


def test_descargar_la_evidencia_de_una_ejecucion(web: TestClient) -> None:
    pagina = web.get("/historial/40").text
    assert 'href="/historial/40/evidencia/html"' in pagina and 'href="/historial/40/evidencia/md"' in pagina
    markdown = web.get("/historial/40/evidencia/md")
    assert markdown.content == b"evidencia"
    assert 'filename="evidencia-ejecucion-40.md"' in markdown.headers["content-disposition"]
    assert "text/html" in web.get("/historial/40/evidencia/html").headers["content-type"]
    assert web.get("/historial/40/evidencia/csv").status_code == 409


def test_reiniciar_repositorio_exige_confirmacion_escrita(web: TestClient) -> None:
    respuesta = web.post(
        "/sistema/repositorio/reiniciar", content="confirmacion=borrar&reinstalar=on", headers=HTMX_FORMULARIO
    )
    assert "Falta la confirmación escrita." in respuesta.text
    assert "BORRAR TODO" in respuesta.text


def test_reiniciar_repositorio_borra_y_reinstala(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    pedidos: list[tuple[str, bool]] = []

    def reiniciar(a: Any, confirmacion: str, reinstalar: bool) -> EstadoRepositorio:
        pedidos.append((confirmacion, reinstalar))
        return EstadoRepositorio(instalado=True, esperadas=12)

    monkeypatch.setattr(administracion, "reiniciar_repositorio", reiniciar)
    monkeypatch.setattr(
        administracion, "estado_repositorio", lambda a: EstadoRepositorio(instalado=True, esperadas=12)
    )
    html = web.post(
        "/sistema/repositorio/reiniciar", content="confirmacion=BORRAR+TODO&reinstalar=on", headers=HTMX_FORMULARIO
    ).text
    assert pedidos == [("BORRAR TODO", True)]
    assert "vuelto a instalar vacío" in html
    web.post("/sistema/repositorio/reiniciar", content="confirmacion=BORRAR+TODO", headers=HTMX_FORMULARIO)
    assert pedidos[-1] == ("BORRAR TODO", False)


def test_no_se_reinicia_el_repositorio_con_el_agente_corriendo(
    web: TestClient, control: ControlFalso, monkeypatch: pytest.MonkeyPatch
) -> None:
    llamadas: list[str] = []
    monkeypatch.setattr(administracion, "reiniciar_repositorio", lambda a, c, r: llamadas.append("reiniciar"))
    control.corriendo = True
    respuesta = web.post(
        "/sistema/repositorio/reiniciar", content="confirmacion=BORRAR+TODO", headers=HTMX_FORMULARIO
    )
    assert "El agente de esta web está corriendo" in respuesta.text
    assert llamadas == []


def test_el_repositorio_ofrece_la_zona_de_borrado(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        administracion, "estado_repositorio", lambda a: EstadoRepositorio(instalado=True, esperadas=12)
    )
    html = web.get("/sistema/repositorio", headers=HTMX).text
    assert 'action="/sistema/repositorio/reiniciar"' in html
    assert "BORRAR TODO" in html


def test_archivado_muestra_el_modo_y_el_procedimiento(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    base = VistaBaseDatos(
        nombre="XE", registrada=True, id=1, activa=True, log_mode=LogMode.NOARCHIVELOG,
        perfil_capturado_en=datetime(2026, 10, 4, 13),
    )
    monkeypatch.setattr(bases_datos, "listar", lambda a: [base])
    html = web.get("/sistema/archivado", headers=HTMX).text
    assert "NOARCHIVELOG" in html
    assert "ALTER DATABASE ARCHIVELOG;" in html and "SHUTDOWN IMMEDIATE;" in html
    assert "nunca cambia el modo de archivado" in html


def test_interruptor_del_inicio_automatico_del_agente(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    asignados: list[bool] = []
    monkeypatch.setattr(administracion, "autoinicio_agente", lambda a: True)
    monkeypatch.setattr(
        administracion, "asignar_autoinicio_agente", lambda a, activo: asignados.append(activo)
    )
    html = web.get("/sistema/agente", headers=HTMX).text
    assert 'action="/sistema/agente/autoinicio"' in html and "checked" in html
    web.post("/sistema/agente/autoinicio", content="activo=on", headers=HTMX_FORMULARIO)
    web.post("/sistema/agente/autoinicio", content="", headers=HTMX_FORMULARIO)
    assert asignados == [True, False]


def test_la_web_inicia_el_agente_solo_si_se_pide(
    servicio: ServicioFalso, monitoreo: MonitoreoFalso, tmp_path: Path
) -> None:
    for iniciar, esperado in ((True, ["autoinicio", "apagar"]), (False, ["apagar"])):
        control = ControlFalso()
        config = ConfigWeb(
            clientes_sin_token=frozenset({"testclient"}),
            hosts_permitidos=frozenset({"testserver"}),
            iniciar_agente=iniciar,
        )
        app = crear_app(
            config,
            servicio=servicio,
            ajustes=Ajustes(work_dir=tmp_path),
            monitoreo_servicio=monitoreo,
            control_agente=control,
        )
        with TestClient(app) as cliente:
            assert cliente.get("/salud").status_code == 200
        assert control.llamadas == esperado


@pytest.mark.parametrize(
    "ruta",
    [
        "/estrategias/XE/EST001/editar",
        "/estrategias/XE/EST001/editar/validar",
        "/estrategias/XE/EST001/tareas/T1/eliminar",
        "/sistema/repositorio/reiniciar",
        "/sistema/agente/autoinicio",
    ],
)
def test_las_acciones_nuevas_rechazan_otro_origen(web: TestClient, control: ControlFalso, ruta: str) -> None:
    assert web.post(ruta, content="x=1", headers=ORIGEN_AJENO).status_code == 403
    assert control.llamadas == []
