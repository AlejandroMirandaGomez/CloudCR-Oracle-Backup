from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Any

import pytest

from cloudcr_backup.alerts.notificadores.consola import NotificadorConsola
from cloudcr_backup.alerts.notificadores.email import (
    ConfiguracionCorreo,
    ConfiguracionCorreoIncompleta,
    NotificadorEmail,
    asunto,
    configuracion_desde_parametros,
)
from cloudcr_backup.alerts.notificadores.seleccion import canales, construir_notificadores
from cloudcr_backup.domain.alertas import Condicion, SeveridadAlerta, VistaAlerta
from cloudcr_backup.domain.enums import EstadoAlerta

PARAMETROS_CORREO = {
    "notificacion.email.servidor": "smtp.gmail.com",
    "notificacion.email.remitente": "cloudcr@example.com",
    "notificacion.email.destinatarios": '["dba@example.com", "jefe@example.com"]',
}


def _alerta(severidad: SeveridadAlerta = SeveridadAlerta.ALERTA, **cambios: Any) -> VistaAlerta:
    datos: dict[str, Any] = {
        "id": 12,
        "codigo": "EJECUCION_FALLIDA",
        "clave_dedup": "EJECUCION_FALLIDA:XE/EST001/T1",
        "severidad": severidad,
        "estado": EstadoAlerta.ABIERTA,
        "mensaje": "La ejecución 40 falló.",
        "bd": "XE",
        "estrategia": "EST001",
        "tarea": "T1",
        "ejecucion_id": 40,
        "abierta_en": datetime(2026, 10, 3, 19, 0, tzinfo=UTC),
    }
    datos.update(cambios)
    return VistaAlerta(**datos)


def _condicion(**cambios: Any) -> Condicion:
    datos: dict[str, Any] = {
        "codigo_regla": "EJECUCION_FALLIDA",
        "sujeto": "XE/EST001/T1",
        "severidad": SeveridadAlerta.ALERTA,
        "mensaje": "La ejecución 40 falló.",
        "accion_sugerida": "Revise el log.",
        "alcance": ["XEPDB1:VENTAS", "XEPDB1:FINANZAS", "CONTROLFILE"],
    }
    datos.update(cambios)
    return Condicion(**datos)


class SmtpFalso:
    def __init__(self, servidor: str, puerto: int, espera: float) -> None:
        self.servidor = servidor
        self.puerto = puerto
        self.tls = False
        self.credenciales: tuple[str, str] | None = None
        self.enviados: list[EmailMessage] = []
        INSTANCIAS.append(self)

    def __enter__(self) -> "SmtpFalso":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def starttls(self) -> None:
        self.tls = True

    def login(self, usuario: str, clave: str) -> None:
        self.credenciales = (usuario, clave)

    def send_message(self, mensaje: EmailMessage) -> None:
        self.enviados.append(mensaje)


INSTANCIAS: list[SmtpFalso] = []


@pytest.fixture(autouse=True)
def _limpiar() -> None:
    INSTANCIAS.clear()


def test_asunto_incluye_bd_estrategia_tarea_y_alcance() -> None:
    assert (
        asunto(_alerta(), _condicion())
        == "[CloudCR][ALERTA] EJECUCION_FALLIDA XE EST001/T1 · VENTAS, FINANZAS, CONTROLFILE"
    )


def test_asunto_de_alerta_de_base_sin_estrategia() -> None:
    alerta = _alerta(codigo="BD_NOARCHIVELOG", estrategia=None, tarea=None, severidad=SeveridadAlerta.ADVERTENCIA)
    assert asunto(alerta, _condicion(alcance=[])) == "[CloudCR][ADVERTENCIA] BD_NOARCHIVELOG XE"


def test_configuracion_desde_parametros() -> None:
    configuracion = configuracion_desde_parametros(
        {**PARAMETROS_CORREO, "notificacion.email.puerto": "465", "notificacion.email.severidad_minima": "advertencia"}
    )
    assert configuracion.destinatarios == ["dba@example.com", "jefe@example.com"]
    assert configuracion.puerto == 465
    assert configuracion.severidad_minima is SeveridadAlerta.ADVERTENCIA
    assert configuracion.tls


def test_destinatarios_separados_por_coma() -> None:
    parametros = {**PARAMETROS_CORREO, "notificacion.email.destinatarios": "a@x.com; b@x.com"}
    assert configuracion_desde_parametros(parametros).destinatarios == ["a@x.com", "b@x.com"]


def test_configuracion_incompleta_dice_que_falta() -> None:
    with pytest.raises(ConfiguracionCorreoIncompleta, match=r"notificacion\.email\.servidor"):
        configuracion_desde_parametros({"notificacion.email.remitente": "x@y.com"})


def test_envia_con_tls_y_clave_del_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLOUDCR_SMTP_CLAVE", "clave-de-aplicacion")
    notificador = NotificadorEmail(configuracion_desde_parametros(PARAMETROS_CORREO), fabrica_smtp=SmtpFalso)
    notificador.notificar(_alerta(), _condicion())
    [smtp] = INSTANCIAS
    assert smtp.tls
    assert smtp.credenciales == ("cloudcr@example.com", "clave-de-aplicacion")
    [mensaje] = smtp.enviados
    assert mensaje["To"] == "dba@example.com, jefe@example.com"
    assert "VENTAS" in mensaje["Subject"]
    assert "Revise el log." in mensaje.get_content()
    assert "historial mostrar 40" in mensaje.get_content()


def test_sin_clave_no_intenta_autenticarse() -> None:
    notificador = NotificadorEmail(
        ConfiguracionCorreo("smtp.local", "a@b.c", ["d@e.f"], tls=False), clave="", fabrica_smtp=SmtpFalso
    )
    notificador.notificar(_alerta(), _condicion())
    assert INSTANCIAS[0].credenciales is None
    assert not INSTANCIAS[0].tls


def test_no_envia_por_debajo_de_la_severidad_minima() -> None:
    notificador = NotificadorEmail(configuracion_desde_parametros(PARAMETROS_CORREO), fabrica_smtp=SmtpFalso)
    notificador.notificar(_alerta(SeveridadAlerta.ADVERTENCIA), _condicion())
    assert INSTANCIAS == []


def test_consola_imprime_la_alerta_nueva() -> None:
    lineas: list[str] = []
    NotificadorConsola(lineas.append).notificar(_alerta(), _condicion())
    assert lineas[0].startswith("NUEVA ALERTA [ALERTA] EJECUCION_FALLIDA #12")
    assert "Revise el log." in lineas[1]


def test_canales() -> None:
    assert canales({}) == ["consola"]
    assert canales({"notificacion.canales": '["consola", "EMAIL"]'}) == ["consola", "email"]
    assert canales({"notificacion.canales": "consola,email"}) == ["consola", "email"]


def test_construir_notificadores_reporta_correo_incompleto_sin_fallar() -> None:
    notificadores, problemas = construir_notificadores({"notificacion.canales": '["consola", "email", "sms"]'})
    assert [n.nombre for n in notificadores] == ["consola"]
    assert len(problemas) == 2


def test_construir_notificadores_con_correo_completo() -> None:
    parametros = {**PARAMETROS_CORREO, "notificacion.canales": '["email"]'}
    notificadores, problemas = construir_notificadores(parametros)
    assert [n.nombre for n in notificadores] == ["email"]
    assert problemas == []
