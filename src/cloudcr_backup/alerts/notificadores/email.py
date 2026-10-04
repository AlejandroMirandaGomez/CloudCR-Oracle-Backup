import json
import os
import smtplib
import socket
from collections.abc import Callable
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from cloudcr_backup.domain.alertas import Condicion, SeveridadAlerta, VistaAlerta, alcanza

VARIABLE_CLAVE_SMTP = "CLOUDCR_SMTP_CLAVE"
PREFIJO = "notificacion.email."
PUERTO_POR_DEFECTO = 587
PUERTO_SSL = 465
SEVERIDAD_MINIMA_POR_DEFECTO = SeveridadAlerta.ALERTA
ESPERA_SEGUNDOS = 20.0
LARGO_MAXIMO_ASUNTO = 200

FabricaSmtp = Callable[[str, int, float], smtplib.SMTP]


class ConfiguracionCorreoIncompleta(ValueError):
    pass


@dataclass(frozen=True)
class ConfiguracionCorreo:
    servidor: str
    remitente: str
    destinatarios: list[str]
    puerto: int = PUERTO_POR_DEFECTO
    tls: bool = True
    severidad_minima: SeveridadAlerta = SEVERIDAD_MINIMA_POR_DEFECTO
    usuario: str | None = None


def _lista(valor: str) -> list[str]:
    texto = valor.strip()
    if texto.startswith("["):
        try:
            elementos = json.loads(texto)
        except json.JSONDecodeError:
            elementos = []
        return [str(e).strip() for e in elementos if str(e).strip()]
    return [parte.strip() for parte in texto.replace(";", ",").split(",") if parte.strip()]


def configuracion_desde_parametros(parametros: dict[str, str]) -> ConfiguracionCorreo:
    servidor = parametros.get(PREFIJO + "servidor", "").strip()
    remitente = parametros.get(PREFIJO + "remitente", "").strip()
    destinatarios = _lista(parametros.get(PREFIJO + "destinatarios", ""))
    faltantes = [
        nombre
        for nombre, valor in (("servidor", servidor), ("remitente", remitente), ("destinatarios", destinatarios))
        if not valor
    ]
    if faltantes:
        claves = ", ".join(PREFIJO + f for f in faltantes)
        raise ConfiguracionCorreoIncompleta(f"Falta configurar {claves} (use 'cloudcr param set').")
    try:
        puerto = int(parametros.get(PREFIJO + "puerto", str(PUERTO_POR_DEFECTO)))
    except ValueError as error:
        raise ConfiguracionCorreoIncompleta(f"{PREFIJO}puerto debe ser un número.") from error
    try:
        minima = SeveridadAlerta(parametros.get(PREFIJO + "severidad_minima", SEVERIDAD_MINIMA_POR_DEFECTO).upper())
    except ValueError as error:
        raise ConfiguracionCorreoIncompleta(
            f"{PREFIJO}severidad_minima debe ser ALERTA, ADVERTENCIA o RECOMENDACION."
        ) from error
    tls = parametros.get(PREFIJO + "tls", "true").strip().lower() not in ("false", "no", "0", "n")
    usuario = parametros.get(PREFIJO + "usuario", "").strip() or None
    return ConfiguracionCorreo(
        servidor=servidor,
        remitente=remitente,
        destinatarios=destinatarios,
        puerto=puerto,
        tls=tls,
        severidad_minima=minima,
        usuario=usuario,
    )


def _etiqueta_alcance(identificador: str) -> str:
    return identificador.split(":")[-1] or identificador


def asunto(alerta: VistaAlerta, condicion: Condicion) -> str:
    partes = [f"[CloudCR][{alerta.severidad.value}]", alerta.codigo]
    if alerta.bd:
        lugar = alerta.bd
        if alerta.estrategia:
            lugar += f" {alerta.estrategia}"
            if alerta.tarea:
                lugar += f"/{alerta.tarea}"
        partes.append(lugar)
    texto = " ".join(partes)
    alcance = [_etiqueta_alcance(o) for o in condicion.alcance if o]
    if alcance:
        texto += " · " + ", ".join(alcance)
    return texto[:LARGO_MAXIMO_ASUNTO]


def cuerpo(alerta: VistaAlerta, condicion: Condicion) -> str:
    lineas = [
        f"Alerta #{alerta.id}: {alerta.codigo} ({alerta.severidad.value})",
        "",
        alerta.mensaje,
        "",
    ]
    if condicion.accion_sugerida:
        lineas += [f"Acción sugerida: {condicion.accion_sugerida}", ""]
    if condicion.alcance:
        lineas.append(f"Alcance de la estrategia: {', '.join(condicion.alcance)}")
    if alerta.ejecucion_id is not None:
        lineas.append(f"Ejecución: {alerta.ejecucion_id} (cloudcr historial mostrar {alerta.ejecucion_id})")
    if alerta.abierta_en is not None:
        lineas.append(f"Abierta en (UTC): {alerta.abierta_en:%Y-%m-%d %H:%M:%S}")
    lineas += ["", f"Enviado por CloudCR Oracle Backup desde {socket.gethostname()}."]
    return "\n".join(lineas)


def _smtp_por_defecto(servidor: str, puerto: int, espera: float) -> smtplib.SMTP:
    if puerto == PUERTO_SSL:
        return smtplib.SMTP_SSL(servidor, puerto, timeout=espera)
    return smtplib.SMTP(servidor, puerto, timeout=espera)


class NotificadorEmail:
    nombre = "email"

    def __init__(
        self,
        configuracion: ConfiguracionCorreo,
        clave: str | None = None,
        fabrica_smtp: FabricaSmtp = _smtp_por_defecto,
    ) -> None:
        self._configuracion = configuracion
        self._clave = clave if clave is not None else os.environ.get(VARIABLE_CLAVE_SMTP) or None
        self._fabrica_smtp = fabrica_smtp

    def debe_enviar(self, alerta: VistaAlerta) -> bool:
        return alcanza(alerta.severidad, self._configuracion.severidad_minima)

    def mensaje(self, alerta: VistaAlerta, condicion: Condicion) -> EmailMessage:
        mensaje = EmailMessage()
        mensaje["From"] = self._configuracion.remitente
        mensaje["To"] = ", ".join(self._configuracion.destinatarios)
        mensaje["Subject"] = asunto(alerta, condicion)
        mensaje["Date"] = formatdate(localtime=True)
        mensaje["Message-ID"] = make_msgid(domain="cloudcr")
        mensaje.set_content(cuerpo(alerta, condicion))
        return mensaje

    def mensaje_de_prueba(self) -> EmailMessage:
        mensaje = EmailMessage()
        mensaje["From"] = self._configuracion.remitente
        mensaje["To"] = ", ".join(self._configuracion.destinatarios)
        mensaje["Subject"] = "[CloudCR] Correo de prueba"
        mensaje["Date"] = formatdate(localtime=True)
        mensaje["Message-ID"] = make_msgid(domain="cloudcr")
        mensaje.set_content(
            "Este es un correo de prueba de CloudCR Oracle Backup.\n"
            "Si lo recibió, las alertas con severidad "
            f"{self._configuracion.severidad_minima.value} o mayor llegarán a esta dirección.\n\n"
            f"Enviado desde {socket.gethostname()}."
        )
        return mensaje

    def enviar_prueba(self) -> None:
        self._enviar(self.mensaje_de_prueba())

    def notificar(self, alerta: VistaAlerta, condicion: Condicion) -> None:
        if not self.debe_enviar(alerta):
            return
        self._enviar(self.mensaje(alerta, condicion))

    def _enviar(self, mensaje: EmailMessage) -> None:
        configuracion = self._configuracion
        with self._fabrica_smtp(configuracion.servidor, configuracion.puerto, ESPERA_SEGUNDOS) as smtp:
            if configuracion.tls and configuracion.puerto != PUERTO_SSL:
                smtp.starttls()
            if self._clave:
                smtp.login(configuracion.usuario or configuracion.remitente, self._clave)
            smtp.send_message(mensaje)
