import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.domain.enums import LogMode, TipoObjeto
from cloudcr_backup.domain.errores import FiltroInvalido, OperacionNoPermitida, RecursoNoEncontrado
from cloudcr_backup.domain.estrategia import Estrategia
from cloudcr_backup.domain.monitoreo import EstadoAgente, EstadoLatido, Latido
from cloudcr_backup.domain.perfil_bd import PerfilBD
from cloudcr_backup.oracle.discovery import InstanciaDescubierta
from cloudcr_backup.oracle.explorador import Exploracion
from cloudcr_backup.repository import bases_datos as repositorio_bases_datos
from cloudcr_backup.repository import conexion as repositorio_conexion
from cloudcr_backup.repository import esquema as repositorio_esquema
from cloudcr_backup.repository import estrategias as repositorio_estrategias
from cloudcr_backup.repository import parametros as repositorio_parametros
from cloudcr_backup.repository.bases_datos import Ambiente, BaseDatosRegistrada
from cloudcr_backup.repository.esquema import EstadoEsquema
from cloudcr_backup.scheduling.reloj import RelojFijo
from cloudcr_backup.services import administracion, bases_datos, gestion_estrategias
from cloudcr_backup.services.control_agente import ControlAgente
from cloudcr_backup.strategy.yaml_io import cargar_estrategia_yaml, estrategia_a_yaml
from tests.unit.oracle_falso import ConexionFalsa

RAIZ = Path(__file__).resolve().parents[2]
PERFIL = RAIZ / "tests" / "fixtures" / "perfiles_bd" / "xe_noarchivelog.json"
BD = BaseDatosRegistrada(id=1, nombre="XE", oracle_home=r"C:\oracle", ambiente=Ambiente.PRUEBAS, activa=True)
AHORA = datetime(2026, 10, 4, 18, tzinfo=UTC)


def perfil() -> PerfilBD:
    return PerfilBD.model_validate_json(PERFIL.read_text(encoding="utf-8"))


def estrategia(codigo: str = "EST001") -> Estrategia:
    return cargar_estrategia_yaml(RAIZ / "config" / "estrategias" / f"{codigo.lower()}.yaml")


@pytest.fixture
def ajustes(tmp_path: Path) -> Ajustes:
    return Ajustes(work_dir=tmp_path)


@pytest.fixture
def repositorio(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    estado: dict[str, Any] = {"parametros": {"agente.tick_segundos": "60"}, "estrategias": {}, "editadas": []}
    monkeypatch.setattr(repositorio_conexion, "abrir_repositorio", lambda a: ConexionFalsa())
    monkeypatch.setattr(repositorio_bases_datos, "obtener", lambda c, n: BD if n == "XE" else None)
    monkeypatch.setattr(repositorio_bases_datos, "listar", lambda c: [BD])
    monkeypatch.setattr(repositorio_bases_datos, "ultimo_perfil", lambda c, i: perfil())
    monkeypatch.setattr(repositorio_parametros, "listar", lambda c: dict(estado["parametros"]))
    monkeypatch.setattr(repositorio_parametros, "obtener", lambda c, k: estado["parametros"].get(k))
    monkeypatch.setattr(repositorio_parametros, "asignar", lambda c, k, v: estado["parametros"].__setitem__(k, v))
    monkeypatch.setattr(repositorio_estrategias, "obtener", lambda c, b, codigo: estado["estrategias"].get(codigo))
    monkeypatch.setattr(repositorio_estrategias, "listar", lambda c, b: list(estado["estrategias"].values()))

    def crear(c: Any, nueva: Estrategia) -> Estrategia:
        guardada = nueva.model_copy(update={"id": 10})
        estado["estrategias"][nueva.codigo] = guardada
        return guardada

    def actualizar(c: Any, nueva: Estrategia) -> Estrategia:
        estado["editadas"].append(nueva)
        estado["estrategias"][nueva.codigo] = nueva
        return nueva

    monkeypatch.setattr(repositorio_estrategias, "crear", crear)
    monkeypatch.setattr(repositorio_estrategias, "actualizar", actualizar)
    return estado


def test_parametros_combinan_guardados_e_iniciales(ajustes: Ajustes, repositorio: dict[str, Any]) -> None:
    parametros = {p.clave: p for p in administracion.parametros(ajustes)}
    assert parametros["agente.tick_segundos"].valor == "60"
    assert parametros["agente.tick_segundos"].modificado is True
    assert parametros["alertas.disco_uso_pct"].valor == "85"
    assert parametros["alertas.disco_uso_pct"].modificado is False


def test_asignar_y_restablecer_parametro(ajustes: Ajustes, repositorio: dict[str, Any]) -> None:
    administracion.asignar_parametro(ajustes, " agente.tick_segundos ", " 15 ")
    assert repositorio["parametros"]["agente.tick_segundos"] == "15"
    administracion.restablecer_parametro(ajustes, "agente.tick_segundos")
    assert repositorio["parametros"]["agente.tick_segundos"] == "30"


@pytest.mark.parametrize("clave", ["", "con espacio", "x" * 101])
def test_clave_de_parametro_invalida(ajustes: Ajustes, repositorio: dict[str, Any], clave: str) -> None:
    with pytest.raises(OperacionNoPermitida):
        administracion.asignar_parametro(ajustes, clave, "1")


def test_restablecer_parametro_desconocido(ajustes: Ajustes, repositorio: dict[str, Any]) -> None:
    with pytest.raises(RecursoNoEncontrado):
        administracion.restablecer_parametro(ajustes, "no.existe")


def test_instalar_no_borra_un_repositorio_ya_instalado(
    ajustes: Ajustes, repositorio: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    instalados: list[bool] = []
    monkeypatch.setattr(repositorio_esquema, "estado", lambda c: EstadoEsquema(instalado=True, tablas={"ALERTA": 1}))
    monkeypatch.setattr(repositorio_esquema, "instalar", lambda c: instalados.append(True))
    with pytest.raises(OperacionNoPermitida, match="borraría"):
        administracion.instalar_repositorio(ajustes)
    assert instalados == []


def test_instalar_repositorio_vacio_carga_parametros(
    ajustes: Ajustes, repositorio: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    estados = iter([EstadoEsquema(instalado=False, tablas={}), EstadoEsquema(instalado=True, tablas={"ALERTA": 0})])
    monkeypatch.setattr(repositorio_esquema, "estado", lambda c: next(estados))
    monkeypatch.setattr(repositorio_esquema, "instalar", lambda c: None)
    resultado = administracion.instalar_repositorio(ajustes)
    assert resultado.instalado is True
    assert repositorio["parametros"]["alertas.disco_uso_pct"] == "85"


def test_listar_bases_combina_instancias_y_registro(
    ajustes: Ajustes, repositorio: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    instancias = [
        InstanciaDescubierta(sid="XE", oracle_home=Path(r"C:\oracle"), en_ejecucion=True),
        InstanciaDescubierta(sid="ORCL", oracle_home=Path(r"C:\otro"), en_ejecucion=False),
    ]
    monkeypatch.setattr(bases_datos, "descubrir_instancias", lambda: instancias)
    vistas = {v.nombre: v for v in bases_datos.listar(ajustes)}
    assert vistas["XE"].registrada and vistas["XE"].log_mode is LogMode.NOARCHIVELOG
    assert vistas["ORCL"].registrada is False and vistas["ORCL"].oracle_home == r"C:\otro"


def test_registrar_base_valida_el_ambiente(ajustes: Ajustes, repositorio: dict[str, Any]) -> None:
    with pytest.raises(FiltroInvalido):
        bases_datos.registrar(ajustes, "XE", "INVENTADO")


def test_inspeccionar_guarda_el_perfil(
    ajustes: Ajustes, repositorio: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    guardados: list[int] = []
    monkeypatch.setattr(bases_datos, "preparar_cliente_oracle", lambda: None)
    monkeypatch.setattr(
        bases_datos, "descubrir_instancias", lambda: [InstanciaDescubierta("XE", Path(r"C:\oracle"), True)]
    )
    monkeypatch.setattr(bases_datos, "explorar_local", lambda i: Exploracion(perfil=perfil(), hallazgos=[]))
    monkeypatch.setattr(repositorio_bases_datos, "guardar_perfil", lambda c, bd_id, p: guardados.append(bd_id))
    resultado = bases_datos.inspeccionar(ajustes, "xe")
    assert guardados == [1]
    assert resultado.log_mode is LogMode.NOARCHIVELOG and resultado.datafiles > 0


def test_ejemplos_del_proyecto() -> None:
    codigos = {e.codigo for e in gestion_estrategias.ejemplos()}
    assert {"EST001", "EST002", "EST003", "EST004"} <= codigos
    assert "EST002" in gestion_estrategias.contenido_ejemplo("est002.yaml")


@pytest.mark.parametrize("archivo", ["../pyproject.toml", "inexistente.yaml", ""])
def test_solo_se_leen_ejemplos_de_la_lista(archivo: str) -> None:
    with pytest.raises(RecursoNoEncontrado):
        gestion_estrategias.contenido_ejemplo(archivo)


def test_importar_crea_y_reemplazar_sube_version(ajustes: Ajustes, repositorio: dict[str, Any]) -> None:
    contenido = estrategia_a_yaml(estrategia("EST002"))
    creada = gestion_estrategias.importar(ajustes, "xe", contenido)
    assert (creada.codigo, creada.version, creada.reemplazada) == ("EST002", 1, False)
    assert repositorio["estrategias"]["EST002"].bd_id == 1
    with pytest.raises(OperacionNoPermitida, match="Ya existe"):
        gestion_estrategias.importar(ajustes, "XE", contenido)
    reemplazada = gestion_estrategias.importar(ajustes, "XE", contenido, reemplazar=True)
    assert (reemplazada.version, reemplazada.reemplazada) == (2, True)


@pytest.mark.parametrize("contenido", ["", "   ", "nombre: [roto", "- una\n- lista\n", "codigo: X\n"])
def test_importar_yaml_invalido(ajustes: Ajustes, repositorio: dict[str, Any], contenido: str) -> None:
    with pytest.raises(OperacionNoPermitida):
        gestion_estrategias.importar(ajustes, "XE", contenido)


def test_exportar_estrategia(ajustes: Ajustes, repositorio: dict[str, Any]) -> None:
    repositorio["estrategias"]["EST001"] = estrategia("EST001").model_copy(update={"bd_id": 1, "id": 1})
    archivo = gestion_estrategias.exportar(ajustes, "XE", "est001")
    assert archivo.nombre == "XE_EST001_v1.yaml"
    assert b"codigo: EST001" in archivo.contenido


def test_aplicar_arch_002_agrega_archived_logs(ajustes: Ajustes, repositorio: dict[str, Any]) -> None:
    repositorio["estrategias"]["EST001"] = estrategia("EST001").model_copy(update={"bd_id": 1, "id": 1})
    resultado = gestion_estrategias.aplicar_recomendacion(ajustes, "XE", "EST001", "arch_002")
    assert resultado.aplicada and resultado.version == 2
    assert any(o.tipo is TipoObjeto.ARCHIVELOG for o in repositorio["editadas"][-1].alcance)
    otra_vez = gestion_estrategias.aplicar_recomendacion(ajustes, "XE", "EST001", "ARCH_002")
    assert otra_vez.aplicada is False


def test_solo_arch_002_es_aplicable(ajustes: Ajustes, repositorio: dict[str, Any]) -> None:
    with pytest.raises(OperacionNoPermitida, match="DST_004") as error:
        gestion_estrategias.aplicar_recomendacion(ajustes, "XE", "EST001", "DST_004")
    assert "ARCH_002" in (error.value.sugerencia or "")


def test_validar_usa_el_perfil_guardado_si_la_base_no_responde(
    ajustes: Ajustes, repositorio: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    repositorio["estrategias"]["EST002"] = estrategia("EST002").model_copy(update={"bd_id": 1, "id": 2})

    def sin_base(base: Any) -> PerfilBD:
        raise RuntimeError("ORA-01034")

    monkeypatch.setattr(gestion_estrategias, "preparar_cliente_oracle", lambda: None)
    monkeypatch.setattr(gestion_estrategias, "perfil_actual", sin_base)
    resultado = gestion_estrategias.validar(ajustes, "XE", "EST002")
    assert resultado.perfil_en_vivo is False
    assert "ORA-01034" in resultado.avisos[0]
    assert resultado.tiene("ARCH_001")


class AgenteFalso:
    def __init__(self) -> None:
        self.detenido = threading.Event()
        self.ejecutando = threading.Event()
        self.una_vez: list[bool] = []

    def ejecutar(self, una_vez: bool = False) -> int:
        self.una_vez.append(una_vez)
        self.ejecutando.set()
        if not una_vez:
            self.detenido.wait(5)
        return 0

    def detener(self) -> None:
        self.detenido.set()


def latido(pid: int, vivo: bool) -> EstadoAgente:
    registro = Latido(
        hostname="EQUIPO", pid=pid, iniciado_en=AHORA, ultimo_tick=AHORA, estado=EstadoLatido.ACTIVO, version="0.1"
    )
    return EstadoAgente(latido=registro, vivo=vivo, segundos_desde_tick=1)


def control(ajustes: Ajustes, agente: AgenteFalso, agentes: list[EstadoAgente] | None = None) -> ControlAgente:
    construidos: list[bool] = []

    def construir(a: Ajustes, simulado: bool, avisar: Any) -> Any:
        construidos.append(simulado)
        return agente

    return ControlAgente(lambda: ajustes, construir, lambda a: agentes or [], RelojFijo(AHORA))


def test_iniciar_y_detener_el_agente_de_la_web(ajustes: Ajustes) -> None:
    agente = AgenteFalso()
    controlador = control(ajustes, agente)
    estado = controlador.iniciar(simulado=True)
    assert agente.ejecutando.wait(2)
    assert estado.corriendo and estado.simulado
    with pytest.raises(OperacionNoPermitida, match="ya está corriendo"):
        controlador.iniciar(simulado=True)
    with pytest.raises(OperacionNoPermitida):
        controlador.un_ciclo(simulado=True)
    final = controlador.detener(esperar_segundos=2)
    assert final.corriendo is False
    assert any("detenido" in m.texto for m in final.mensajes)


def test_no_inicia_si_ya_hay_otro_agente_vivo(ajustes: Ajustes) -> None:
    controlador = control(ajustes, AgenteFalso(), [latido(pid=999_999, vivo=True)])
    with pytest.raises(OperacionNoPermitida, match="PID 999999"):
        controlador.iniciar(simulado=False)


def test_un_ciclo_ejecuta_una_sola_vez(ajustes: Ajustes) -> None:
    agente = AgenteFalso()
    controlador = control(ajustes, agente)
    controlador.un_ciclo(simulado=True)
    assert agente.ejecutando.wait(2)
    hilo = controlador._ciclo
    assert hilo is not None
    hilo.join(2)
    assert agente.una_vez == [True]
    assert controlador.estado().ciclo_en_curso is False


def test_detener_sin_agente(ajustes: Ajustes) -> None:
    with pytest.raises(OperacionNoPermitida, match="no está corriendo"):
        control(ajustes, AgenteFalso()).detener()


def test_apagar_detiene_el_agente(ajustes: Ajustes) -> None:
    agente = AgenteFalso()
    controlador = control(ajustes, agente)
    controlador.iniciar(simulado=True)
    assert agente.ejecutando.wait(2)
    controlador.apagar(2)
    assert agente.detenido.is_set()
    assert controlador.estado().corriendo is False
