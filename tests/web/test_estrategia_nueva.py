import json
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.domain.enums import LogMode
from cloudcr_backup.oracle.connection import ErrorConexionOracle
from cloudcr_backup.oracle.explorador import Exploracion, InstanciaNoEncontrada
from cloudcr_backup.services import almacen_estrategias
from cloudcr_backup.web.app import crear_app
from cloudcr_backup.web.config import ConfigWeb
from tests.unit.ayudas_solicitud import datos_solicitud
from tests.web.conftest import HOME_FICTICIO, ServicioFalso

RUTA_VALIDAR = "/api/instancias/XE/estrategias/validar"
RUTA_CREAR = "/api/instancias/XE/estrategias"


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
def cliente_estrategias(config_pruebas: ConfigWeb, servicio: ServicioFalso, ajustes: Ajustes) -> TestClient:
    return TestClient(crear_app(config_pruebas, servicio=servicio, ajustes=ajustes))


@pytest.fixture
def servicio_archivelog(servicio: ServicioFalso) -> ServicioFalso:
    perfil = servicio.exploracion.perfil.model_copy(update={"log_mode": LogMode.ARCHIVELOG})
    servicio.exploracion = Exploracion(perfil=perfil, hallazgos=servicio.exploracion.hallazgos)
    return servicio


def _datos_json(html: str) -> dict[str, Any]:
    coincidencia = re.search(r'<script type="application/json" id="datos-estrategia">(.*?)</script>', html, re.S)
    assert coincidencia is not None
    datos: dict[str, Any] = json.loads(coincidencia.group(1))
    return datos


def test_el_explorador_ofrece_el_boton_para_crear_la_estrategia(cliente_estrategias: TestClient) -> None:
    html = cliente_estrategias.get("/instancias/XE").text
    assert 'href="/instancias/XE/estrategias/nueva"' in html
    assert "Crear estrategia de respaldo" in html


def test_el_boton_conserva_el_oracle_home(cliente_estrategias: TestClient) -> None:
    html = cliente_estrategias.get("/instancias/XE", params={"oracle_home": str(HOME_FICTICIO)}).text
    assert "/estrategias/nueva?oracle_home=" in html


def test_la_pagina_conserva_el_oracle_home_en_sus_enlaces_y_en_la_api(cliente_estrategias: TestClient) -> None:
    html = cliente_estrategias.get("/instancias/XE/estrategias/nueva", params={"oracle_home": str(HOME_FICTICIO)}).text
    assert f'data-oracle-home="{HOME_FICTICIO}"' in html
    assert "?oracle_home=" in html.split("Volver al explorador")[0].rsplit("<a", 1)[1]


def _casillas(html: str) -> list[dict[str, str]]:
    casillas = []
    for etiqueta in re.findall(r"<input[^>]*casilla-alcance[^>]*>", html, re.S):
        atributos = dict(re.findall(r'([\w-]+)="([^"]*)"', etiqueta))
        atributos["disabled"] = "si" if re.search(r"\sdisabled[\s>]", etiqueta) else "no"
        casillas.append(atributos)
    return casillas


def _casilla(html: str, tipo: str, identificador: str) -> dict[str, str]:
    return next(c for c in _casillas(html) if c["data-tipo"] == tipo and c["data-identificador"] == identificador)


def test_la_pagina_del_formulario_muestra_el_arbol_con_casillas(cliente_estrategias: TestClient) -> None:
    respuesta = cliente_estrategias.get("/instancias/XE/estrategias/nueva")
    assert respuesta.status_code == 200
    html = respuesta.text
    for esperado in (
        "Crear estrategia de respaldo",
        'id="arbol"',
        "/estaticos/estrategia.js",
        "/estaticos/estrategia.css",
        'id="dialogo-carpetas"',
        'id="campo-destino"',
        'id="abrir-explorador"',
    ):
        assert esperado in html
    tipos = {(c["data-tipo"], c["data-identificador"]) for c in _casillas(html)}
    assert {
        ("BASE_DATOS", ""),
        ("PDB", "XEPDB1"),
        ("TABLESPACE", "XEPDB1:USERS"),
        ("TABLESPACE", "USERS"),
        ("CONTROLFILE", ""),
        ("SPFILE", ""),
        ("ARCHIVELOG", ""),
    } <= tipos
    assert any(tipo == "DATAFILE" for tipo, _ in tipos)


def test_cada_casilla_declara_que_la_cubre(cliente_estrategias: TestClient) -> None:
    html = cliente_estrategias.get("/instancias/XE/estrategias/nueva").text
    tablespace = _casilla(html, "TABLESPACE", "XEPDB1:USERS")
    assert tablespace["data-cubierta-por"].split()[-1] == "instancia"
    assert _casilla(html, "BASE_DATOS", "")["data-cubierta-por"] == ""
    assert _casilla(html, "CONTROLFILE", "")["data-cubierta-por"] == "instancia"
    assert _casilla(html, "SPFILE", "")["data-cubierta-por"] == "instancia"
    assert _casilla(html, "ARCHIVELOG", "")["data-cubierta-por"] == ""


def test_el_arbol_del_formulario_no_incluye_la_semilla_ni_ofrece_los_temporales(
    cliente_estrategias: TestClient,
) -> None:
    html = cliente_estrategias.get("/instancias/XE/estrategias/nueva").text
    assert "PDB$SEED" not in html
    identificadores = {c["data-identificador"] for c in _casillas(html)}
    assert "TEMP" not in identificadores
    assert "XEPDB1:TEMP" not in identificadores


def test_archived_logs_aparece_deshabilitado_en_noarchivelog(cliente_estrategias: TestClient) -> None:
    html = cliente_estrategias.get("/instancias/XE/estrategias/nueva").text
    casilla = _casilla(html, "ARCHIVELOG", "")
    assert casilla["disabled"] == "si"
    assert "NOARCHIVELOG" in casilla["title"]


def test_archived_logs_aparece_habilitado_en_archivelog(
    cliente_estrategias: TestClient, servicio_archivelog: ServicioFalso
) -> None:
    html = cliente_estrategias.get("/instancias/XE/estrategias/nueva").text
    assert _casilla(html, "ARCHIVELOG", "")["disabled"] == "no"


def test_los_datos_embebidos_incluyen_el_catalogo(cliente_estrategias: TestClient) -> None:
    catalogo = _datos_json(cliente_estrategias.get("/instancias/XE/estrategias/nueva").text)["catalogo"]
    assert catalogo["codigo_sugerido"] == "EST001"
    assert catalogo["instancia"]["log_mode"] == "NOARCHIVELOG"
    assert [p["valor"] for p in catalogo["prioridades"]] == ["ALTA", "MEDIA", "BAJA"]
    assert catalogo["compresiones"] == ["NINGUNA", "BASIC"]
    assert catalogo["canales_maximos"] == 1
    assert len(catalogo["esquemas"]) == 5


def test_el_codigo_sugerido_continua_la_numeracion_de_lo_guardado(
    cliente_estrategias: TestClient, ajustes: Ajustes
) -> None:
    carpeta = ajustes.rutas.estrategias / "XE"
    carpeta.mkdir(parents=True)
    (carpeta / "EST004.yaml").write_text("x", encoding="utf-8")
    catalogo = _datos_json(cliente_estrategias.get("/instancias/XE/estrategias/nueva").text)["catalogo"]
    assert catalogo["codigo_sugerido"] == "EST005"
    assert catalogo["codigos_existentes"] == ["EST004"]


def test_el_formulario_de_una_instancia_inexistente_da_404(
    cliente_estrategias: TestClient, servicio: ServicioFalso
) -> None:
    servicio.error = InstanciaNoEncontrada("No existe la instancia ZZ.")
    respuesta = cliente_estrategias.get("/instancias/ZZ/estrategias/nueva")
    assert respuesta.status_code == 404
    assert "No existe la instancia ZZ." in respuesta.text


def test_si_oracle_no_responde_el_formulario_muestra_el_error(
    cliente_estrategias: TestClient, servicio: ServicioFalso
) -> None:
    servicio.error = ErrorConexionOracle("La instancia está detenida.", "Inicie el servicio.")
    respuesta = cliente_estrategias.get("/instancias/XE/estrategias/nueva")
    assert respuesta.status_code == 502
    assert "La instancia está detenida." in respuesta.text


def test_el_oracle_home_no_detectado_se_rechaza_en_el_formulario(cliente_estrategias: TestClient) -> None:
    respuesta = cliente_estrategias.get("/instancias/XE/estrategias/nueva", params={"oracle_home": "D:/otro"})
    assert respuesta.status_code == 502
    assert "ORACLE_HOME" in respuesta.text


def test_catalogo_por_api(cliente_estrategias: TestClient) -> None:
    respuesta = cliente_estrategias.get("/api/instancias/XE/estrategias/catalogo")
    assert respuesta.status_code == 200
    catalogo = respuesta.json()
    assert catalogo["instancia"]["sid"] == "XE"
    assert {e["valor"] for e in catalogo["esquemas"]} >= {"COMPLETO_SEMANAL", "CONSISTENTE_NOARCHIVELOG"}
    assert catalogo["destino_sugerido"].endswith("XE")
    esquema_alto = next(p for p in catalogo["prioridades"] if p["valor"] == "ALTA")
    assert esquema_alto["esquema_recomendado"] == "CONSISTENTE_NOARCHIVELOG"


def test_el_esquema_recomendado_en_archivelog_sigue_la_prioridad(
    cliente_estrategias: TestClient, servicio_archivelog: ServicioFalso
) -> None:
    catalogo = cliente_estrategias.get("/api/instancias/XE/estrategias/catalogo").json()
    recomendados = {p["valor"]: p["esquema_recomendado"] for p in catalogo["prioridades"]}
    assert recomendados == {
        "ALTA": "N0_N1_ACUMULATIVO_CON_ARCHIVELOGS",
        "MEDIA": "N0_SEMANAL_N1_DIFERENCIAL_DIARIO",
        "BAJA": "COMPLETO_SEMANAL",
    }


def test_validar_devuelve_hallazgos_yaml_y_estrategia(
    cliente_estrategias: TestClient, servicio_archivelog: ServicioFalso, destino: str
) -> None:
    respuesta = cliente_estrategias.post(RUTA_VALIDAR, json=datos_solicitud(destino))
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["bloqueante"] is False
    assert cuerpo["requiere_aceptar_caida"] is False
    assert "codigo: EST010" in cuerpo["yaml"]
    assert cuerpo["estrategia"]["codigo"] == "EST010"
    assert cuerpo["criterio"] == {"rpo_horas": 1.0, "rto_horas": 4.0}
    codigos = {h["codigo"] for h in cuerpo["hallazgos"]}
    assert "ARCH_002" in codigos
    assert all(h["etiqueta_severidad"] for h in cuerpo["hallazgos"])
    assert sum(cuerpo["resumen"].values()) == len(cuerpo["hallazgos"])


def test_validar_en_noarchivelog_pide_aceptar_la_caida(cliente_estrategias: TestClient, destino: str) -> None:
    cuerpo = cliente_estrategias.post(RUTA_VALIDAR, json=datos_solicitud(destino)).json()
    assert cuerpo["requiere_aceptar_caida"] is True
    assert "ARCH_001" in {h["codigo"] for h in cuerpo["hallazgos"]}


def test_validar_con_destino_inexistente_es_bloqueante(
    cliente_estrategias: TestClient, servicio_archivelog: ServicioFalso, tmp_path: Path
) -> None:
    cuerpo = cliente_estrategias.post(RUTA_VALIDAR, json=datos_solicitud(str(tmp_path / "no_existe"))).json()
    assert cuerpo["bloqueante"] is True
    assert "DST_001" in {h["codigo"] for h in cuerpo["hallazgos"]}


def test_validar_con_campos_invalidos_da_422_con_los_campos(cliente_estrategias: TestClient, destino: str) -> None:
    datos = datos_solicitud(destino, nombre="", codigo="no valido!", prioridad="URGENTE")
    respuesta = cliente_estrategias.post(RUTA_VALIDAR, json=datos)
    assert respuesta.status_code == 422
    errores = {e["campo"]: e["mensaje"] for e in respuesta.json()["errores"]}
    assert set(errores) >= {"nombre", "codigo", "prioridad"}
    assert errores["nombre"] == "Este campo es obligatorio."
    assert "letras" in errores["codigo"]


def test_validar_con_hora_invalida_da_un_mensaje_en_espanol(cliente_estrategias: TestClient, destino: str) -> None:
    esquema = {**datos_solicitud(destino)["esquema"], "hora_n0": "99:99"}
    respuesta = cliente_estrategias.post(RUTA_VALIDAR, json=datos_solicitud(destino, esquema=esquema))
    assert respuesta.status_code == 422
    assert respuesta.json()["errores"][0] == {"campo": "esquema.hora_n0", "mensaje": "Hora inválida (use HH:MM)."}


def test_validar_sin_cuerpo_json_da_422(cliente_estrategias: TestClient) -> None:
    respuesta = cliente_estrategias.post(
        RUTA_VALIDAR, content="no es json", headers={"Content-Type": "application/json"}
    )
    assert respuesta.status_code == 422
    assert respuesta.json()["errores"]


def test_los_422_fuera_de_la_api_conservan_el_formato_original(cliente_estrategias: TestClient) -> None:
    respuesta = cliente_estrategias.get("/explorar", params={"sid": ""})
    assert respuesta.status_code == 422
    assert "detail" in respuesta.json()


def test_validar_si_oracle_falla_da_502_con_sugerencia(
    cliente_estrategias: TestClient, servicio: ServicioFalso, destino: str
) -> None:
    servicio.error = ErrorConexionOracle("La instancia está detenida.", "Inicie el servicio.")
    respuesta = cliente_estrategias.post(RUTA_VALIDAR, json=datos_solicitud(destino))
    assert respuesta.status_code == 502
    assert respuesta.json()["errores"][0]["sugerencia"] == "Inicie el servicio."


def test_validar_instancia_inexistente_da_404(
    cliente_estrategias: TestClient, servicio: ServicioFalso, destino: str
) -> None:
    servicio.error = InstanciaNoEncontrada("No existe la instancia ZZ.")
    assert cliente_estrategias.post(RUTA_VALIDAR, json=datos_solicitud(destino)).status_code == 404


def test_crear_guarda_el_archivo_y_responde_201(
    cliente_estrategias: TestClient, servicio_archivelog: ServicioFalso, destino: str, ajustes: Ajustes
) -> None:
    respuesta = cliente_estrategias.post(RUTA_CREAR, json=datos_solicitud(destino, activar=True))
    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["codigo"] == "EST010"
    assert cuerpo["estado"] == "ACTIVA"
    assert cuerpo["version"] == 1
    assert Path(cuerpo["archivo"]) == ajustes.rutas.estrategias / "XE" / "EST010.yaml"
    assert Path(cuerpo["archivo"]).is_file()
    assert cuerpo["repositorio"]["estado"] == "omitida"
    assert "codigo: EST010" in cuerpo["yaml"]


def test_crear_informa_si_el_repositorio_no_esta_disponible(
    cliente_estrategias: TestClient, servicio_archivelog: ServicioFalso, destino: str
) -> None:
    respuesta = cliente_estrategias.post(RUTA_CREAR, json=datos_solicitud(destino, guardar_en_repositorio=True))
    assert respuesta.status_code == 201
    assert respuesta.json()["repositorio"]["estado"] == "no_disponible"


def test_crear_en_noarchivelog_sin_aceptar_la_caida_se_rechaza(
    cliente_estrategias: TestClient, destino: str, ajustes: Ajustes
) -> None:
    respuesta = cliente_estrategias.post(RUTA_CREAR, json=datos_solicitud(destino))
    assert respuesta.status_code == 422
    assert respuesta.json()["errores"][0]["campo"] == "caida_no_aceptada"
    assert not ajustes.rutas.estrategias.exists()
    aceptada = cliente_estrategias.post(RUTA_CREAR, json=datos_solicitud(destino, aceptar_caida=True))
    assert aceptada.status_code == 201


def test_crear_con_errores_bloqueantes_devuelve_los_hallazgos(
    cliente_estrategias: TestClient, servicio_archivelog: ServicioFalso, tmp_path: Path
) -> None:
    respuesta = cliente_estrategias.post(RUTA_CREAR, json=datos_solicitud(str(tmp_path / "no_existe")))
    assert respuesta.status_code == 422
    cuerpo = respuesta.json()
    assert cuerpo["errores"][0]["campo"] == "bloqueada"
    assert "DST_001" in {h["codigo"] for h in cuerpo["hallazgos"]}


def test_crear_dos_veces_el_mismo_codigo_se_rechaza(
    cliente_estrategias: TestClient, servicio_archivelog: ServicioFalso, destino: str
) -> None:
    assert cliente_estrategias.post(RUTA_CREAR, json=datos_solicitud(destino)).status_code == 201
    segunda = cliente_estrategias.post(RUTA_CREAR, json=datos_solicitud(destino))
    assert segunda.status_code == 422
    assert "GEN_001" in {h["codigo"] for h in segunda.json()["hallazgos"]}


def test_crear_con_tareas_a_mano(
    cliente_estrategias: TestClient, servicio_archivelog: ServicioFalso, destino: str
) -> None:
    tareas = [
        {
            "como": {"tipo_respaldo": "COMPLETO", "modo_respaldo": "EN_LINEA", "opciones": {"compresion": "BASIC"}},
            "programacion": {
                "tipo_frecuencia": "SEMANAL",
                "horas": ["02:00", "14:00"],
                "dias_semana": ["LUN", "JUE"],
                "ventana": {"inicio": "01:00", "fin": "05:00"},
                "zona_horaria": "America/Costa_Rica",
            },
        }
    ]
    respuesta = cliente_estrategias.post(RUTA_CREAR, json=datos_solicitud(destino, esquema=None, tareas=tareas))
    assert respuesta.status_code == 201
    yaml_guardado = Path(respuesta.json()["archivo"]).read_text(encoding="utf-8")
    assert "BASIC" in yaml_guardado
    assert "JUE" in yaml_guardado


def test_una_compresion_no_soportada_por_la_edicion_bloquea(
    cliente_estrategias: TestClient, servicio_archivelog: ServicioFalso, destino: str
) -> None:
    tareas = [
        {
            "como": {"tipo_respaldo": "COMPLETO", "modo_respaldo": "EN_LINEA", "opciones": {"compresion": "HIGH"}},
            "programacion": {"tipo_frecuencia": "DIARIA", "horas": ["02:00"]},
        }
    ]
    cuerpo = cliente_estrategias.post(RUTA_VALIDAR, json=datos_solicitud(destino, esquema=None, tareas=tareas)).json()
    assert cuerpo["bloqueante"] is True
    assert "MET_003" in {h["codigo"] for h in cuerpo["hallazgos"]}


@pytest.mark.parametrize("ruta", [RUTA_VALIDAR, RUTA_CREAR, "/api/carpetas"])
def test_las_escrituras_rechazan_solicitudes_de_otro_origen(
    cliente_estrategias: TestClient, servicio_archivelog: ServicioFalso, destino: str, ruta: str
) -> None:
    cuerpo = {"padre": destino, "nombre": "x"} if ruta == "/api/carpetas" else datos_solicitud(destino)
    ajeno = cliente_estrategias.post(ruta, json=cuerpo, headers={"Origin": "http://sitio-malicioso.example"})
    assert ajeno.status_code == 403
    cruzado = cliente_estrategias.post(ruta, json=cuerpo, headers={"Sec-Fetch-Site": "cross-site"})
    assert cruzado.status_code == 403
    nulo = cliente_estrategias.post(ruta, json=cuerpo, headers={"Origin": "null"})
    assert nulo.status_code == 403


def test_el_mismo_origen_se_acepta(
    cliente_estrategias: TestClient, servicio_archivelog: ServicioFalso, destino: str
) -> None:
    respuesta = cliente_estrategias.post(
        RUTA_VALIDAR,
        json=datos_solicitud(destino),
        headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"},
    )
    assert respuesta.status_code == 200


def test_las_escrituras_no_se_aceptan_por_otro_host(
    config_pruebas: ConfigWeb, servicio: ServicioFalso, ajustes: Ajustes, destino: str
) -> None:
    cliente = TestClient(crear_app(config_pruebas, servicio=servicio, ajustes=ajustes), base_url="http://evil.example")
    assert cliente.post(RUTA_VALIDAR, json=datos_solicitud(destino)).status_code == 400


def test_la_pagina_declara_los_recursos_con_la_politica_de_seguridad(cliente_estrategias: TestClient) -> None:
    respuesta = cliente_estrategias.get("/instancias/XE/estrategias/nueva")
    assert "script-src 'self'" in respuesta.headers["content-security-policy"]
    assert "<script>" not in respuesta.text
    assert "style=" not in respuesta.text
    assert "onclick=" not in respuesta.text


def test_el_nombre_con_html_se_escapa_en_los_datos_embebidos(
    cliente_estrategias: TestClient, servicio: ServicioFalso, ajustes: Ajustes
) -> None:
    perfil = servicio.exploracion.perfil.model_copy(update={"nombre": "</script><script>alert(1)</script>"})
    servicio.exploracion = Exploracion(perfil=perfil, hallazgos=servicio.exploracion.hallazgos)
    html = cliente_estrategias.get("/instancias/XE/estrategias/nueva").text
    assert "</script><script>alert(1)" not in html
