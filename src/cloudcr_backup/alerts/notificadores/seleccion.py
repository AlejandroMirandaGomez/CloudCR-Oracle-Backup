import json
import os
from collections.abc import Callable

from cloudcr_backup.alerts.motor import Notificador
from cloudcr_backup.alerts.notificadores.consola import NotificadorConsola
from cloudcr_backup.alerts.notificadores.email import (
    VARIABLE_CLAVE_SMTP,
    ConfiguracionCorreoIncompleta,
    NotificadorEmail,
    configuracion_desde_parametros,
)

PARAMETRO_CANALES = "notificacion.canales"
CANALES_POR_DEFECTO = ("consola",)


def canales(parametros: dict[str, str]) -> list[str]:
    texto = parametros.get(PARAMETRO_CANALES, "").strip()
    if not texto:
        return list(CANALES_POR_DEFECTO)
    try:
        valor = json.loads(texto)
    except json.JSONDecodeError:
        valor = texto.split(",")
    if isinstance(valor, str):
        valor = [valor]
    return [str(c).strip().lower() for c in valor if str(c).strip()]


def construir_notificadores(
    parametros: dict[str, str], escribir: Callable[[str], None] = print
) -> tuple[list[Notificador], list[str]]:
    notificadores: list[Notificador] = []
    problemas: list[str] = []
    for canal in canales(parametros):
        if canal == "consola":
            notificadores.append(NotificadorConsola(escribir))
        elif canal in ("email", "correo"):
            if not os.environ.get(VARIABLE_CLAVE_SMTP):
                problemas.append(
                    f"El canal de correo está activo pero {VARIABLE_CLAVE_SMTP} no está definida en este proceso: "
                    "los servidores que exigen autenticación (como Gmail) rechazarán el envío. "
                    "Defínala en .env y reinicie."
                )
            try:
                notificadores.append(NotificadorEmail(configuracion_desde_parametros(parametros)))
            except ConfiguracionCorreoIncompleta as error:
                problemas.append(f"El canal de correo está activo pero incompleto: {error}")
        else:
            problemas.append(f"El canal de notificación {canal!r} no existe (use consola o email).")
    return notificadores, problemas
