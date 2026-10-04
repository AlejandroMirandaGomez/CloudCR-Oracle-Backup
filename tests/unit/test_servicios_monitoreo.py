import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.domain.enums import EstadoEjecucion, EstadoEstrategia
from cloudcr_backup.domain.errores import OperacionNoPermitida, RecursoNoEncontrado
from cloudcr_backup.domain.historial import ConsultaHistorial
from cloudcr_backup.domain.monitoreo import ColorSemaforo
from cloudcr_backup.repository import estrategias as repositorio_estrategias
from cloudcr_backup.services import consulta_estrategias, historial, monitoreo


@pytest.fixture
def ajustes(tmp_path: Path, repositorio_parcheado: dict[str, Any]) -> Ajustes:
    return Ajustes(work_dir=tmp_path)


def test_consultar_convierte_las_fechas_locales_a_utc(ajustes: Ajustes, repositorio_parcheado: dict[str, Any]) -> None:
    consulta = ConsultaHistorial(
        bd="xe", estrategia="est001", estado=EstadoEjecucion.FALLIDA, desde=date(2026, 10, 3), hasta=date(2026, 10, 3),
        limite=20, pagina=3,
    )
    pagina = historial.consultar(ajustes, consulta)
    filtros = repositorio_parcheado["filtros"]
    assert filtros.bd_id == 1
    assert filtros.estrategia_codigo == "EST001"
    assert filtros.desde == datetime(2026, 10, 3, 6, 0)
    assert filtros.hasta.date() == date(2026, 10, 4) and filtros.hasta.hour == 5
    assert repositorio_parcheado["paginacion"] == (20, 40)
    assert pagina.total == 1
    assert pagina.filas[0].programada_para.tzinfo is not None


def test_consultar_una_bd_desconocida(ajustes: Ajustes) -> None:
    with pytest.raises(RecursoNoEncontrado, match="ORCL"):
        historial.consultar(ajustes, ConsultaHistorial(bd="ORCL"))


def test_rango_de_fechas_invertido(ajustes: Ajustes) -> None:
    with pytest.raises(OperacionNoPermitida):
        historial.consultar(ajustes, ConsultaHistorial(desde=date(2026, 10, 5), hasta=date(2026, 10, 1)))


def test_detalle_sin_evidencia_lo_avisa(ajustes: Ajustes) -> None:
    detalle = historial.detalle(ajustes, 40)
    assert detalle.errores == "RMAN-03009"
    assert detalle.script_version == 1
    assert detalle.evidencia is None
    assert "evidencia.json" in detalle.avisos[0]
    with pytest.raises(RecursoNoEncontrado):
        historial.detalle(ajustes, 99)


def test_detalle_lee_la_evidencia_y_el_log(ajustes: Ajustes) -> None:
    carpeta = ajustes.rutas.ejecuciones / "40"
    carpeta.mkdir(parents=True)
    log = carpeta / "rman.log"
    log.write_text("\n".join(f"linea {i}" for i in range(100)), encoding="utf-8")
    (carpeta / "evidencia.json").write_text(json.dumps({"log_rman": str(log), "piezas": 2}), encoding="utf-8")
    detalle = historial.detalle(ajustes, 40)
    assert detalle.evidencia == {"log_rman": str(log), "piezas": 2}
    assert detalle.log_rman is not None and detalle.log_rman.existe
    assert detalle.log_rman.primeras_lineas[0] == "linea 0"
    assert detalle.log_rman.ultimas_lineas[-1] == "linea 99"
    assert detalle.avisos == []


@pytest.mark.parametrize(("formato", "tipo"), [("csv", "text/csv"), ("md", "text/markdown"), ("html", "text/html")])
def test_exportar(ajustes: Ajustes, formato: str, tipo: str) -> None:
    archivo = historial.exportar(ajustes, ConsultaHistorial(bd="XE"), formato)
    assert archivo.nombre.endswith(f".{formato}")
    assert archivo.tipo_contenido.startswith(tipo)
    assert b"EST001" in archivo.contenido


def test_exportar_formato_invalido(ajustes: Ajustes) -> None:
    with pytest.raises(OperacionNoPermitida):
        historial.exportar(ajustes, ConsultaHistorial(), "pdf")


def test_exportar_evidencia(ajustes: Ajustes) -> None:
    archivo = historial.exportar_evidencia(ajustes, 40, "md")
    assert archivo.nombre == "evidencia-ejecucion-40.md"
    assert b"RMAN-03009" in archivo.contenido
    with pytest.raises(OperacionNoPermitida):
        historial.exportar_evidencia(ajustes, 40, "csv")


def test_estado_general(ajustes: Ajustes) -> None:
    general = monitoreo.estado_general(ajustes, ahora=datetime(2026, 10, 3, 20, 0, tzinfo=UTC))
    [semaforo] = general.semaforos
    assert semaforo.color is ColorSemaforo.ROJO
    assert any("T1" in m for m in semaforo.motivos)
    assert semaforo.proxima_ejecucion is not None
    assert general.tick_segundos == 30
    assert general.agentes == []


def test_estado_general_filtra_por_bd(ajustes: Ajustes) -> None:
    assert monitoreo.estado_general(ajustes, bd="ORCL").semaforos == []


def test_detalle_de_estrategia(ajustes: Ajustes) -> None:
    detalle = consulta_estrategias.detalle(ajustes, "XE", "EST001", 3)
    t1, t2 = detalle.tareas
    assert t1.script is not None and t1.script.version == 1
    assert len(t1.proximas) == 3
    assert t1.termino_clase == "Full / total"
    assert "Diaria a las 13:00" in t1.descripcion_programacion
    assert t2.script is None
    assert detalle.alcance == ["XEPDB1:VENTAS", "CONTROLFILE"]
    assert detalle.rpo_horas > 0


def test_estrategia_inexistente(ajustes: Ajustes) -> None:
    with pytest.raises(RecursoNoEncontrado):
        consulta_estrategias.detalle(ajustes, "XE", "EST999")


def test_proximas_de_tarea_sin_bd(ajustes: Ajustes) -> None:
    assert len(consulta_estrategias.proximas_de_tarea(ajustes, None, "est001", "t1", 4)) == 4
    with pytest.raises(RecursoNoEncontrado):
        consulta_estrategias.proximas_de_tarea(ajustes, None, "EST001", "T9", 4)
    with pytest.raises(OperacionNoPermitida):
        consulta_estrategias.proximas_de_tarea(ajustes, None, "EST001", "T1", 0)


def test_activar_y_desactivar(ajustes: Ajustes, monkeypatch: pytest.MonkeyPatch) -> None:
    llamadas: list[tuple[str, int, str]] = []
    monkeypatch.setattr(repositorio_estrategias, "activar", lambda c, b, e: llamadas.append(("activar", b, e)))
    monkeypatch.setattr(repositorio_estrategias, "desactivar", lambda c, b, e: llamadas.append(("desactivar", b, e)))
    assert consulta_estrategias.cambiar_estado(ajustes, "XE", "EST001", False).estado is EstadoEstrategia.INACTIVA
    assert consulta_estrategias.cambiar_estado(ajustes, "XE", "EST001", True).estado is EstadoEstrategia.ACTIVA
    assert llamadas == [("desactivar", 1, "EST001"), ("activar", 1, "EST001")]


def test_listar_estrategias_con_color(ajustes: Ajustes) -> None:
    [resumen] = consulta_estrategias.listar(ajustes)
    assert resumen.codigo == "EST001"
    assert resumen.tareas == 2 and resumen.tareas_con_script == 1
    assert resumen.color is ColorSemaforo.ROJO


def test_probar_correo_sin_configuracion_explica_que_falta(ajustes: Ajustes, monkeypatch: pytest.MonkeyPatch) -> None:
    from cloudcr_backup.services import alertas

    monkeypatch.setattr(alertas, "_parametros", lambda a: {})
    with pytest.raises(OperacionNoPermitida, match=r"notificacion.email.servidor"):
        alertas.probar_correo(ajustes)
    estado = alertas.estado_correo(ajustes)
    assert not estado.configurado
    assert not estado.canal_activo


def test_probar_correo_traduce_el_rechazo_de_credenciales(ajustes: Ajustes, monkeypatch: pytest.MonkeyPatch) -> None:
    import smtplib

    from cloudcr_backup.alerts.notificadores.email import NotificadorEmail
    from cloudcr_backup.services import alertas

    parametros = {
        "notificacion.email.servidor": "smtp.ejemplo.com",
        "notificacion.email.remitente": "a@ejemplo.com",
        "notificacion.email.destinatarios": "b@ejemplo.com",
        "notificacion.canales": '["consola","email"]',
    }
    monkeypatch.setattr(alertas, "_parametros", lambda a: parametros)
    monkeypatch.setenv("CLOUDCR_SMTP_CLAVE", "x")

    def rechazar(self: NotificadorEmail) -> None:
        raise smtplib.SMTPAuthenticationError(535, b"mal")

    monkeypatch.setattr(NotificadorEmail, "enviar_prueba", rechazar)
    with pytest.raises(OperacionNoPermitida, match="rechazó las credenciales"):
        alertas.probar_correo(ajustes)
    assert alertas.estado_correo(ajustes).canal_activo

    monkeypatch.setattr(NotificadorEmail, "enviar_prueba", lambda self: None)
    resultado = alertas.probar_correo(ajustes)
    assert resultado.destinatarios == ["b@ejemplo.com"]


def test_probar_correo_sin_clave_explica_que_falta_la_contrasena(
    ajustes: Ajustes, monkeypatch: pytest.MonkeyPatch
) -> None:
    import smtplib

    from cloudcr_backup.alerts.notificadores.email import NotificadorEmail
    from cloudcr_backup.services import alertas

    parametros = {
        "notificacion.email.servidor": "smtp.ejemplo.com",
        "notificacion.email.remitente": "a@ejemplo.com",
        "notificacion.email.destinatarios": "b@ejemplo.com",
    }
    monkeypatch.setattr(alertas, "_parametros", lambda a: parametros)
    monkeypatch.delenv("CLOUDCR_SMTP_CLAVE", raising=False)

    def sin_autenticar(self: NotificadorEmail) -> None:
        raise smtplib.SMTPSenderRefused(530, b"Authentication Required", "a@ejemplo.com")

    monkeypatch.setattr(NotificadorEmail, "enviar_prueba", sin_autenticar)
    with pytest.raises(OperacionNoPermitida, match="no está definida") as error:
        alertas.probar_correo(ajustes)
    assert ".env" in (error.value.sugerencia or "")


def _configuracion_equipo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    archivo = tmp_path / "notificaciones.yaml"
    archivo.write_text(
        "servidor: smtp.ejemplo.com\npuerto: 587\ntls: true\nremitente: a@ejemplo.com\n"
        "destinatarios:\n  - b@ejemplo.com\n  - c@ejemplo.com\ncanales:\n  - consola\n  - email\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CLOUDCR_NOTIFICACIONES", str(archivo))


def test_cargar_configuracion_del_equipo_aplica_lo_que_falta(
    ajustes: Ajustes, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cloudcr_backup.services import administracion, alertas

    _configuracion_equipo(tmp_path, monkeypatch)
    guardados: dict[str, str] = {"notificacion.canales": '["consola"]'}
    monkeypatch.setattr(alertas, "_parametros", lambda a: dict(guardados))
    monkeypatch.setattr(administracion, "asignar_parametro", lambda a, k, v: guardados.__setitem__(k, v))
    resultado = alertas.cargar_configuracion_del_equipo(ajustes)
    assert guardados["notificacion.email.servidor"] == "smtp.ejemplo.com"
    assert guardados["notificacion.email.tls"] == "true"
    assert guardados["notificacion.email.destinatarios"] == '["b@ejemplo.com", "c@ejemplo.com"]'
    assert guardados["notificacion.canales"] == '["consola", "email"]'
    assert resultado.conservados == []
    assert "notificacion.email.remitente" in resultado.aplicados


def test_cargar_configuracion_del_equipo_respeta_lo_cambiado_a_mano_salvo_sobrescribir(
    ajustes: Ajustes, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cloudcr_backup.services import administracion, alertas

    _configuracion_equipo(tmp_path, monkeypatch)
    guardados: dict[str, str] = {"notificacion.email.remitente": "otro@ejemplo.com", "notificacion.email.puerto": "587"}
    monkeypatch.setattr(alertas, "_parametros", lambda a: dict(guardados))
    monkeypatch.setattr(administracion, "asignar_parametro", lambda a, k, v: guardados.__setitem__(k, v))
    resultado = alertas.cargar_configuracion_del_equipo(ajustes)
    assert resultado.conservados == ["notificacion.email.remitente"]
    assert guardados["notificacion.email.remitente"] == "otro@ejemplo.com"
    forzado = alertas.cargar_configuracion_del_equipo(ajustes, sobrescribir=True)
    assert forzado.conservados == []
    assert guardados["notificacion.email.remitente"] == "a@ejemplo.com"


def test_configuracion_del_equipo_rechaza_claves_desconocidas_y_archivo_ausente(
    ajustes: Ajustes, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cloudcr_backup.services import alertas

    archivo = tmp_path / "mala.yaml"
    archivo.write_text("clave_secreta: x\n", encoding="utf-8")
    monkeypatch.setenv("CLOUDCR_NOTIFICACIONES", str(archivo))
    monkeypatch.setattr(alertas, "_parametros", lambda a: {})
    with pytest.raises(OperacionNoPermitida, match="desconocidas"):
        alertas.cargar_configuracion_del_equipo(ajustes)
    monkeypatch.setenv("CLOUDCR_NOTIFICACIONES", str(tmp_path / "no_existe.yaml"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(alertas, "archivo_configuracion_equipo", lambda: None)
    with pytest.raises(RecursoNoEncontrado):
        alertas.cargar_configuracion_del_equipo(ajustes)


def test_el_yaml_del_equipo_del_proyecto_es_valido_y_no_trae_secretos() -> None:
    from cloudcr_backup.services import alertas

    raiz = Path(__file__).resolve().parents[2]
    valores = alertas._valores_de_configuracion(raiz / "config" / "notificaciones.yaml")
    assert valores["notificacion.email.servidor"] == "smtp.gmail.com"
    assert "email" in valores["notificacion.canales"]
    assert not any("clave" in k.lower() or "password" in k.lower() for k in valores)
    assert ".env.local" in (raiz / ".gitignore").read_text(encoding="utf-8")
