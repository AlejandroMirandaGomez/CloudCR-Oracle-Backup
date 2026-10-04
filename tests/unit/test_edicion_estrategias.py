import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.domain.enums import Compresion, TipoRespaldo
from cloudcr_backup.domain.errores import OperacionNoPermitida, RecursoNoEncontrado
from cloudcr_backup.domain.estrategia import Estrategia, tareas_con_script_afectado
from cloudcr_backup.domain.perfil_bd import PerfilBD
from cloudcr_backup.repository import bases_datos as repositorio_bases_datos
from cloudcr_backup.repository import conexion as repositorio_conexion
from cloudcr_backup.repository import ejecuciones as repositorio_ejecuciones
from cloudcr_backup.repository import esquema as repositorio_esquema
from cloudcr_backup.repository import estrategias as repositorio_estrategias
from cloudcr_backup.repository import parametros as repositorio_parametros
from cloudcr_backup.repository.bases_datos import Ambiente, BaseDatosRegistrada
from cloudcr_backup.repository.esquema import EstadoEsquema
from cloudcr_backup.repository.estrategias import TareaConHistorial
from cloudcr_backup.scheduling.reloj import RelojFijo
from cloudcr_backup.services import administracion, gestion_estrategias
from cloudcr_backup.services.control_agente import ControlAgente
from cloudcr_backup.strategy.yaml_io import cargar_estrategia_yaml, estrategia_a_yaml, estrategia_desde_yaml
from tests.unit.oracle_falso import ConexionFalsa

RAIZ = Path(__file__).resolve().parents[2]
PERFIL = RAIZ / "tests" / "fixtures" / "perfiles_bd" / "xe_noarchivelog.json"
BD = BaseDatosRegistrada(id=1, nombre="XE", oracle_home=r"C:\oracle", ambiente=Ambiente.PRUEBAS, activa=True)
AHORA = datetime(2026, 10, 4, 18, tzinfo=UTC)


def perfil() -> PerfilBD:
    return PerfilBD.model_validate_json(PERFIL.read_text(encoding="utf-8"))


def estrategia(codigo: str = "EST004") -> Estrategia:
    cargada = cargar_estrategia_yaml(RAIZ / "config" / "estrategias" / f"{codigo.lower()}.yaml")
    return cargada.model_copy(update={"bd_id": 1, "id": 7})


@pytest.fixture
def ajustes(tmp_path: Path) -> Ajustes:
    return Ajustes(work_dir=tmp_path)


@pytest.fixture
def repositorio(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    estado: dict[str, Any] = {
        "parametros": {},
        "estrategias": {"EST004": estrategia("EST004")},
        "editadas": [],
        "error_al_editar": None,
    }
    monkeypatch.setattr(repositorio_conexion, "abrir_repositorio", lambda a: ConexionFalsa())
    monkeypatch.setattr(repositorio_bases_datos, "obtener", lambda c, n: BD if n == "XE" else None)
    monkeypatch.setattr(repositorio_bases_datos, "ultimo_perfil", lambda c, i: perfil())
    monkeypatch.setattr(repositorio_parametros, "listar", lambda c: dict(estado["parametros"]))
    monkeypatch.setattr(repositorio_parametros, "obtener", lambda c, k: estado["parametros"].get(k))
    monkeypatch.setattr(repositorio_parametros, "asignar", lambda c, k, v: estado["parametros"].__setitem__(k, v))
    monkeypatch.setattr(repositorio_estrategias, "obtener", lambda c, b, codigo: estado["estrategias"].get(codigo))
    monkeypatch.setattr(repositorio_estrategias, "listar", lambda c, b: list(estado["estrategias"].values()))

    def actualizar(c: Any, nueva: Estrategia) -> Estrategia:
        if estado["error_al_editar"] is not None:
            raise estado["error_al_editar"]
        estado["editadas"].append(nueva)
        estado["estrategias"][nueva.codigo] = nueva
        return nueva

    monkeypatch.setattr(repositorio_estrategias, "actualizar", actualizar)
    return estado


def con_tarea_modificada(base: Estrategia, codigo: str, cambio: Any) -> Estrategia:
    copia = base.model_copy(deep=True)
    cambio(copia.tarea(codigo))
    return copia


def test_cambiar_solo_el_horario_no_afecta_el_script() -> None:
    anterior = estrategia()
    nueva = con_tarea_modificada(anterior, "T2", lambda t: t.programacion.horas.clear())
    assert tareas_con_script_afectado(anterior, nueva) == []


def test_cambiar_el_como_o_el_destino_afecta_solo_esa_tarea() -> None:
    anterior = estrategia()
    nueva = con_tarea_modificada(anterior, "T2", lambda t: setattr(t.como.opciones, "compresion", Compresion.BASIC))
    assert tareas_con_script_afectado(anterior, nueva) == ["T2"]
    nueva = con_tarea_modificada(anterior, "T3", lambda t: setattr(t.destino, "ruta", r"D:\otra"))
    assert tareas_con_script_afectado(anterior, nueva) == ["T3"]


def test_cambiar_el_alcance_afecta_todas_las_tareas_existentes() -> None:
    anterior = estrategia()
    nueva = anterior.model_copy(update={"alcance": anterior.alcance[:1]})
    assert tareas_con_script_afectado(anterior, nueva) == ["T1", "T2", "T3"]


def test_una_tarea_nueva_no_cuenta_como_afectada() -> None:
    anterior = estrategia()
    nueva = anterior.model_copy(deep=True)
    nueva.tareas.append(anterior.tareas[0].model_copy(update={"codigo": "T9"}))
    assert tareas_con_script_afectado(anterior, nueva) == []


def preparar_actualizacion(
    monkeypatch: pytest.MonkeyPatch, anterior: Estrategia, respuestas: list[Any]
) -> ConexionFalsa:
    monkeypatch.setattr(repositorio_estrategias, "obtener", lambda c, b, codigo: anterior)
    return ConexionFalsa([(7,), *respuestas])


def sentencias(conexion: ConexionFalsa) -> list[str]:
    return [sql for sql, _ in conexion.ejecutados]


TAREAS_EXISTENTES = [[("T1", 11), ("T2", 12), ("T3", 13)]]


def test_actualizar_modifica_las_tareas_en_su_lugar(monkeypatch: pytest.MonkeyPatch) -> None:
    anterior = estrategia()
    nueva = con_tarea_modificada(anterior, "T2", lambda t: t.programacion.horas.clear())
    conexion = preparar_actualizacion(monkeypatch, anterior, TAREAS_EXISTENTES)
    repositorio_estrategias.actualizar(conexion, nueva)  # type: ignore[arg-type]
    todas = sentencias(conexion)
    assert not any(s.startswith("DELETE FROM tarea ") for s in todas)
    assert sum(s.startswith("UPDATE tarea ") for s in todas) == 3
    assert not any(s.startswith("UPDATE script_rman") for s in todas)
    assert conexion.commits == 1 and conexion.rollbacks == 0


def test_actualizar_obsoleta_el_script_de_la_tarea_que_cambio(monkeypatch: pytest.MonkeyPatch) -> None:
    anterior = estrategia()
    nueva = con_tarea_modificada(anterior, "T2", lambda t: setattr(t.como.opciones, "compresion", Compresion.BASIC))
    conexion = preparar_actualizacion(monkeypatch, anterior, TAREAS_EXISTENTES)
    repositorio_estrategias.actualizar(conexion, nueva)  # type: ignore[arg-type]
    obsoletos = [p for s, p in conexion.ejecutados if s.startswith("UPDATE script_rman SET estado = 'OBSOLETO'")]
    assert [p["codigo"] for p in obsoletos] == ["T2"]


def test_actualizar_agrega_una_tarea_nueva(monkeypatch: pytest.MonkeyPatch) -> None:
    anterior = estrategia()
    nueva = anterior.model_copy(deep=True)
    nueva.tareas.append(anterior.tareas[0].model_copy(update={"codigo": "T4"}))
    conexion = preparar_actualizacion(monkeypatch, anterior, TAREAS_EXISTENTES)
    repositorio_estrategias.actualizar(conexion, nueva)  # type: ignore[arg-type]
    inserciones = [p for s, p in conexion.ejecutados if s.startswith("INSERT INTO tarea ")]
    assert [p["codigo"] for p in inserciones] == ["T4"]


def test_actualizar_elimina_una_tarea_sin_ejecuciones(monkeypatch: pytest.MonkeyPatch) -> None:
    anterior = estrategia()
    nueva = anterior.model_copy(update={"tareas": anterior.tareas[:2]})
    conexion = preparar_actualizacion(monkeypatch, anterior, [*TAREAS_EXISTENTES, (0,)])
    repositorio_estrategias.actualizar(conexion, nueva)  # type: ignore[arg-type]
    todas = sentencias(conexion)
    assert "DELETE FROM tarea WHERE id = :id" in todas
    assert "DELETE FROM script_rman WHERE tarea_id = :id" in todas
    assert "UPDATE alerta SET tarea_id = NULL WHERE tarea_id = :id" in todas
    assert conexion.commits == 1


def test_actualizar_no_elimina_una_tarea_con_ejecuciones(monkeypatch: pytest.MonkeyPatch) -> None:
    anterior = estrategia()
    nueva = anterior.model_copy(update={"tareas": anterior.tareas[:2]})
    conexion = preparar_actualizacion(monkeypatch, anterior, [*TAREAS_EXISTENTES, (3,)])
    with pytest.raises(TareaConHistorial, match="T3"):
        repositorio_estrategias.actualizar(conexion, nueva)  # type: ignore[arg-type]
    assert conexion.rollbacks == 1 and conexion.commits == 0
    assert "DELETE FROM tarea WHERE id = :id" not in sentencias(conexion)


def test_contenido_para_editar_devuelve_el_yaml_actual(ajustes: Ajustes, repositorio: dict[str, Any]) -> None:
    borrador = gestion_estrategias.contenido_para_editar(ajustes, "XE", "EST004")
    assert borrador.version == 1 and borrador.tarea_agregada is None
    assert "codigo: EST004" in borrador.contenido


def test_contenido_para_editar_con_tarea_nueva_usa_el_siguiente_codigo(
    ajustes: Ajustes, repositorio: dict[str, Any]
) -> None:
    borrador = gestion_estrategias.contenido_para_editar(ajustes, "XE", "EST004", agregar_tarea=True)
    assert borrador.tarea_agregada == "T4"
    guardada = estrategia_desde_yaml(borrador.contenido)
    assert [t.codigo for t in guardada.tareas] == ["T1", "T2", "T3", "T4"]
    assert guardada.tarea("T4").como.tipo_respaldo is TipoRespaldo.COMPLETO


def test_guardar_edicion_sube_la_version_e_indica_que_regenerar(
    ajustes: Ajustes, repositorio: dict[str, Any]
) -> None:
    editado = con_tarea_modificada(
        repositorio["estrategias"]["EST004"], "T1", lambda t: setattr(t.como.opciones, "compresion", Compresion.BASIC)
    )
    resultado = gestion_estrategias.guardar_edicion(ajustes, "xe", "est004", estrategia_a_yaml(editado))
    assert resultado.version == 2 and resultado.tareas_a_regenerar == ["T1"]
    assert "Cambió lo que se respalda o cómo se respalda en T1" in resultado.mensaje
    assert "su script anterior quedó obsoleto" in resultado.mensaje
    assert repositorio["editadas"][-1].bd_id == 1


def test_guardar_edicion_informa_tareas_agregadas_y_eliminadas(
    ajustes: Ajustes, repositorio: dict[str, Any]
) -> None:
    base = repositorio["estrategias"]["EST004"]
    editado = base.model_copy(deep=True)
    editado.tareas = [*base.tareas[:2], base.tareas[0].model_copy(update={"codigo": "T7"})]
    resultado = gestion_estrategias.guardar_edicion(ajustes, "XE", "EST004", estrategia_a_yaml(editado))
    assert resultado.tareas_agregadas == ["T7"] and resultado.tareas_eliminadas == ["T3"]
    assert "Tareas agregadas: T7." in resultado.mensaje and "Tareas eliminadas: T3." in resultado.mensaje
    assert "Genere y apruebe el script de T7" in resultado.mensaje
    assert "obsoleto" not in resultado.mensaje


def test_no_se_puede_cambiar_el_codigo_al_editar(ajustes: Ajustes, repositorio: dict[str, Any]) -> None:
    otro = repositorio["estrategias"]["EST004"].model_copy(update={"codigo": "EST999"})
    with pytest.raises(OperacionNoPermitida, match="código de la estrategia"):
        gestion_estrategias.guardar_edicion(ajustes, "XE", "EST004", estrategia_a_yaml(otro))
    assert repositorio["editadas"] == []


def test_codigos_de_tarea_repetidos_o_invalidos(ajustes: Ajustes, repositorio: dict[str, Any]) -> None:
    base = repositorio["estrategias"]["EST004"]
    repetida = base.model_copy(deep=True)
    repetida.tareas[1].codigo = "T1"
    with pytest.raises(OperacionNoPermitida, match="repetido: T1"):
        gestion_estrategias.guardar_edicion(ajustes, "XE", "EST004", estrategia_a_yaml(repetida))
    larga = base.model_copy(deep=True)
    larga.tareas[0].codigo = "TAREA-MUY-LARGA"
    with pytest.raises(OperacionNoPermitida, match="no es válido"):
        gestion_estrategias.guardar_edicion(ajustes, "XE", "EST004", estrategia_a_yaml(larga))


def test_yaml_invalido_o_vacio_al_editar(ajustes: Ajustes, repositorio: dict[str, Any]) -> None:
    with pytest.raises(OperacionNoPermitida):
        gestion_estrategias.guardar_edicion(ajustes, "XE", "EST004", "   ")
    with pytest.raises(OperacionNoPermitida, match="campos inválidos"):
        gestion_estrategias.guardar_edicion(ajustes, "XE", "EST004", "codigo: EST004\nnombre: x\n")


def test_editar_una_estrategia_inexistente(ajustes: Ajustes, repositorio: dict[str, Any]) -> None:
    with pytest.raises(RecursoNoEncontrado):
        gestion_estrategias.contenido_para_editar(ajustes, "XE", "EST777")


def test_tarea_con_historial_se_muestra_como_operacion_no_permitida(
    ajustes: Ajustes, repositorio: dict[str, Any]
) -> None:
    repositorio["error_al_editar"] = TareaConHistorial("La tarea T3 ya tiene ejecuciones registradas")
    base = repositorio["estrategias"]["EST004"]
    with pytest.raises(OperacionNoPermitida, match="T3") as error:
        gestion_estrategias.guardar_edicion(
            ajustes, "XE", "EST004", estrategia_a_yaml(base.model_copy(update={"tareas": base.tareas[:2]}))
        )
    assert "no se guardaron" in (error.value.sugerencia or "")


def test_eliminar_tarea(ajustes: Ajustes, repositorio: dict[str, Any]) -> None:
    resultado = gestion_estrategias.eliminar_tarea(ajustes, "XE", "EST004", " t3 ")
    assert resultado.tareas_eliminadas == ["T3"] and resultado.version == 2
    assert [t.codigo for t in repositorio["editadas"][-1].tareas] == ["T1", "T2"]


def test_no_se_elimina_la_unica_tarea(ajustes: Ajustes, repositorio: dict[str, Any]) -> None:
    repositorio["estrategias"]["EST001"] = estrategia("EST001")
    with pytest.raises(OperacionNoPermitida, match="única tarea"):
        gestion_estrategias.eliminar_tarea(ajustes, "XE", "EST001", "T1")
    assert repositorio["editadas"] == []


def test_eliminar_una_tarea_que_no_existe(ajustes: Ajustes, repositorio: dict[str, Any]) -> None:
    with pytest.raises(RecursoNoEncontrado, match="T9"):
        gestion_estrategias.eliminar_tarea(ajustes, "XE", "EST004", "T9")


def test_validar_borrador_no_guarda_y_usa_la_version_siguiente(
    ajustes: Ajustes, repositorio: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def sin_base(base: Any) -> PerfilBD:
        raise RuntimeError("ORA-01034")

    monkeypatch.setattr(gestion_estrategias, "preparar_cliente_oracle", lambda: None)
    monkeypatch.setattr(gestion_estrategias, "perfil_actual", sin_base)
    base = repositorio["estrategias"]["EST004"]
    resultado = gestion_estrategias.validar_borrador(ajustes, "XE", "EST004", estrategia_a_yaml(base))
    assert resultado.version == 2 and resultado.perfil_en_vivo is False
    assert repositorio["editadas"] == []


def test_reiniciar_repositorio_exige_la_frase(ajustes: Ajustes, repositorio: dict[str, Any]) -> None:
    with pytest.raises(OperacionNoPermitida, match="confirmación") as error:
        administracion.reiniciar_repositorio(ajustes, "borrar", True)
    assert "BORRAR TODO" in (error.value.sugerencia or "")


def preparar_reinicio(monkeypatch: pytest.MonkeyPatch, en_curso: int) -> dict[str, list[str]]:
    llamadas: dict[str, list[str]] = {"pasos": []}
    estados = iter(
        [
            EstadoEsquema(instalado=True, tablas={"ALERTA": 1}),
            EstadoEsquema(instalado=True, tablas={"ALERTA": 0}),
        ]
    )
    monkeypatch.setattr(repositorio_esquema, "estado", lambda c: next(estados))
    monkeypatch.setattr(repositorio_ejecuciones, "contar_en_curso", lambda c: en_curso)
    monkeypatch.setattr(repositorio_esquema, "desinstalar", lambda c: llamadas["pasos"].append("desinstalar"))
    monkeypatch.setattr(repositorio_esquema, "instalar", lambda c: llamadas["pasos"].append("instalar"))
    return llamadas


def test_reiniciar_repositorio_borra_y_vuelve_a_instalar(
    ajustes: Ajustes, repositorio: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    llamadas = preparar_reinicio(monkeypatch, en_curso=0)
    resultado = administracion.reiniciar_repositorio(ajustes, " BORRAR TODO ", True)
    assert llamadas["pasos"] == ["desinstalar", "instalar"]
    assert resultado.instalado is True
    assert repositorio["parametros"]["alertas.disco_uso_pct"] == "85"


def test_reiniciar_repositorio_sin_reinstalar(
    ajustes: Ajustes, repositorio: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    llamadas = preparar_reinicio(monkeypatch, en_curso=0)
    monkeypatch.setattr(administracion, "estado_repositorio", lambda a: administracion.EstadoRepositorio(
        instalado=False, esperadas=12
    ))
    administracion.reiniciar_repositorio(ajustes, "BORRAR TODO", False)
    assert llamadas["pasos"] == ["desinstalar"]
    assert repositorio["parametros"] == {}


def test_reiniciar_repositorio_se_niega_con_respaldos_en_curso(
    ajustes: Ajustes, repositorio: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    llamadas = preparar_reinicio(monkeypatch, en_curso=1)
    with pytest.raises(OperacionNoPermitida, match="en curso"):
        administracion.reiniciar_repositorio(ajustes, "BORRAR TODO", True)
    assert llamadas["pasos"] == []


def test_autoinicio_del_agente_por_defecto_y_al_cambiarlo(ajustes: Ajustes, repositorio: dict[str, Any]) -> None:
    assert administracion.autoinicio_agente(ajustes) is True
    administracion.asignar_autoinicio_agente(ajustes, False)
    assert repositorio["parametros"]["agente.iniciar_con_web"] == "false"
    assert administracion.autoinicio_agente(ajustes) is False
    administracion.asignar_autoinicio_agente(ajustes, True)
    assert administracion.autoinicio_agente(ajustes) is True


class AgenteFalso:
    def __init__(self) -> None:
        self.detenido = threading.Event()
        self.ejecutando = threading.Event()

    def ejecutar(self, una_vez: bool = False) -> int:
        self.ejecutando.set()
        self.detenido.wait(5)
        return 0

    def detener(self) -> None:
        self.detenido.set()


def control_con(ajustes: Ajustes, autoinicio: Any, agente: AgenteFalso) -> tuple[ControlAgente, list[bool]]:
    construidos: list[bool] = []

    def construir(a: Ajustes, simulado: bool, avisar: Any) -> Any:
        construidos.append(simulado)
        return agente

    controlador = ControlAgente(lambda: ajustes, construir, lambda a: [], RelojFijo(AHORA), autoinicio)
    return controlador, construidos


def test_iniciar_si_corresponde_arranca_el_agente_real(ajustes: Ajustes) -> None:
    agente = AgenteFalso()
    controlador, construidos = control_con(ajustes, lambda a: True, agente)
    controlador.iniciar_si_corresponde()
    assert agente.ejecutando.wait(2)
    assert construidos == [False]
    assert controlador.estado().corriendo is True
    controlador.apagar(2)


def test_iniciar_si_corresponde_respeta_el_interruptor(ajustes: Ajustes) -> None:
    controlador, construidos = control_con(ajustes, lambda a: False, AgenteFalso())
    controlador.iniciar_si_corresponde()
    assert construidos == []
    assert any("desactivado" in m.texto for m in controlador.estado().mensajes)


def test_iniciar_si_corresponde_nunca_lanza_error(ajustes: Ajustes) -> None:
    def fallar(a: Ajustes) -> bool:
        raise OperacionNoPermitida("No hay repositorio")

    controlador, construidos = control_con(ajustes, fallar, AgenteFalso())
    controlador.iniciar_si_corresponde()
    assert construidos == []
    assert any("No se inició el agente automáticamente" in m.texto for m in controlador.estado().mensajes)
