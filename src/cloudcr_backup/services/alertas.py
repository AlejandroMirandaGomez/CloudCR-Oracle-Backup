import json
import os
import smtplib
from collections.abc import Callable, Sequence
from pathlib import Path

import yaml

from cloudcr_backup.alerts.motor import MotorAlertas
from cloudcr_backup.alerts.notificadores.email import (
    VARIABLE_CLAVE_SMTP,
    ConfiguracionCorreoIncompleta,
    NotificadorEmail,
    configuracion_desde_parametros,
)
from cloudcr_backup.alerts.notificadores.seleccion import canales, construir_notificadores
from cloudcr_backup.config.ajustes import Ajustes, cargar_ajustes
from cloudcr_backup.domain.alertas import (
    Condicion,
    EstadoCorreo,
    ResultadoConfiguracionCorreo,
    ResultadoPruebaCorreo,
    ResumenEvaluacion,
    SeveridadAlerta,
    VistaAlerta,
)
from cloudcr_backup.domain.enums import EstadoAlerta
from cloudcr_backup.domain.errores import FiltroInvalido, OperacionNoPermitida, RecursoNoEncontrado
from cloudcr_backup.repository import alertas as repositorio_alertas
from cloudcr_backup.scheduling.reloj import RelojSistema
from cloudcr_backup.services import administracion
from cloudcr_backup.services.agente import sesion_agente
from cloudcr_backup.services.conversiones import vista_alerta
from cloudcr_backup.services.sesion import conexion_repositorio

FILTRO_VIGENTES = "VIGENTES"
FILTRO_TODAS = "TODAS"
LIMITE_POR_DEFECTO = 200


def _sin_salida(_: str) -> None:
    return None


def evaluar(
    ajustes: Ajustes, notificar: bool = True, escribir: Callable[[str], None] = _sin_salida
) -> ResumenEvaluacion:
    with sesion_agente(ajustes) as fuente:
        notificadores, problemas = construir_notificadores(fuente.parametros(), escribir) if notificar else ([], [])
        resumen = MotorAlertas(fuente, notificadores).evaluar(RelojSistema().ahora())
    resumen.errores.extend(problemas)
    return resumen


def evaluar_tras_ejecucion(ejecucion_id: int, ajustes: Ajustes | None = None) -> ResumenEvaluacion:
    return evaluar(ajustes or cargar_ajustes())


def registrar_evento(condiciones: Sequence[Condicion], ajustes: Ajustes | None = None) -> ResumenEvaluacion:
    configuracion = ajustes or cargar_ajustes()
    with sesion_agente(configuracion) as fuente:
        notificadores, problemas = construir_notificadores(fuente.parametros(), _sin_salida)
        resumen = MotorAlertas(fuente, notificadores).registrar_evento(condiciones, RelojSistema().ahora())
    resumen.errores.extend(problemas)
    return resumen


def estados_de_filtro(estado: str | None) -> list[EstadoAlerta] | None:
    texto = (estado or FILTRO_VIGENTES).strip().upper()
    if texto == FILTRO_VIGENTES:
        return [EstadoAlerta.ABIERTA, EstadoAlerta.RECONOCIDA]
    if texto == FILTRO_TODAS:
        return None
    try:
        return [EstadoAlerta(texto)]
    except ValueError as error:
        raise FiltroInvalido(
            f"El estado {estado!r} no es válido.", "Use vigentes, todas, ABIERTA, RECONOCIDA o RESUELTA."
        ) from error


def severidad_de_filtro(severidad: str | None) -> SeveridadAlerta | None:
    if not severidad:
        return None
    try:
        return SeveridadAlerta(severidad.strip().upper())
    except ValueError as error:
        raise FiltroInvalido(
            f"La severidad {severidad!r} no es válida.", "Use ALERTA, ADVERTENCIA o RECOMENDACION."
        ) from error


def listar(
    ajustes: Ajustes, estado: str | None = None, severidad: str | None = None, limite: int = LIMITE_POR_DEFECTO
) -> list[VistaAlerta]:
    estados = estados_de_filtro(estado)
    nivel = severidad_de_filtro(severidad)
    with conexion_repositorio(ajustes) as conexion:
        alertas = repositorio_alertas.listar(conexion, estados, nivel.value if nivel else None, limite)
    return [vista_alerta(a) for a in alertas]


def obtener(ajustes: Ajustes, alerta_id: int) -> VistaAlerta:
    with conexion_repositorio(ajustes) as conexion:
        alerta = repositorio_alertas.obtener(conexion, alerta_id)
    if alerta is None:
        raise RecursoNoEncontrado(f"No existe la alerta {alerta_id}.")
    return vista_alerta(alerta)


def reconocer(ajustes: Ajustes, alerta_id: int) -> VistaAlerta:
    with conexion_repositorio(ajustes) as conexion:
        alerta = repositorio_alertas.obtener(conexion, alerta_id)
        if alerta is None:
            raise RecursoNoEncontrado(f"No existe la alerta {alerta_id}.")
        if not repositorio_alertas.reconocer_abierta(conexion, alerta_id):
            raise OperacionNoPermitida(
                f"La alerta {alerta_id} está {alerta.estado.value}; solo se puede reconocer una alerta ABIERTA."
            )
        actualizada = repositorio_alertas.obtener(conexion, alerta_id)
    assert actualizada is not None
    return vista_alerta(actualizada)


def resolver(ajustes: Ajustes, alerta_id: int) -> VistaAlerta:
    with conexion_repositorio(ajustes) as conexion:
        alerta = repositorio_alertas.obtener(conexion, alerta_id)
        if alerta is None:
            raise RecursoNoEncontrado(f"No existe la alerta {alerta_id}.")
        if not repositorio_alertas.resolver_vigente(conexion, alerta_id):
            raise OperacionNoPermitida(f"La alerta {alerta_id} ya está {alerta.estado.value}.")
        actualizada = repositorio_alertas.obtener(conexion, alerta_id)
    assert actualizada is not None
    return vista_alerta(actualizada)


def _parametros(ajustes: Ajustes) -> dict[str, str]:
    with sesion_agente(ajustes) as fuente:
        return fuente.parametros()


def estado_correo(ajustes: Ajustes) -> EstadoCorreo:
    parametros = _parametros(ajustes)
    activo = any(c in ("email", "correo") for c in canales(parametros))
    clave = bool(os.environ.get(VARIABLE_CLAVE_SMTP))
    try:
        configuracion = configuracion_desde_parametros(parametros)
    except ConfiguracionCorreoIncompleta as error:
        return EstadoCorreo(canal_activo=activo, configurado=False, clave_definida=clave, problema=str(error))
    return EstadoCorreo(
        canal_activo=activo,
        configurado=True,
        servidor=configuracion.servidor,
        puerto=configuracion.puerto,
        remitente=configuracion.remitente,
        destinatarios=configuracion.destinatarios,
        severidad_minima=configuracion.severidad_minima.value,
        clave_definida=clave,
    )


def probar_correo(ajustes: Ajustes) -> ResultadoPruebaCorreo:
    parametros = _parametros(ajustes)
    try:
        configuracion = configuracion_desde_parametros(parametros)
    except ConfiguracionCorreoIncompleta as error:
        raise OperacionNoPermitida(str(error), "Complételo en Sistema → Parámetros globales.") from error
    try:
        NotificadorEmail(configuracion).enviar_prueba()
    except (smtplib.SMTPAuthenticationError, smtplib.SMTPSenderRefused) as error:
        if not os.environ.get(VARIABLE_CLAVE_SMTP):
            raise OperacionNoPermitida(
                f"El servidor {configuracion.servidor} exige autenticación y {VARIABLE_CLAVE_SMTP} no está definida "
                "en este proceso.",
                f"Defina {VARIABLE_CLAVE_SMTP} en el archivo .env y reinicie el programa (la web y el agente leen el "
                ".env solo al arrancar).",
            ) from error
        raise OperacionNoPermitida(
            f"El servidor {configuracion.servidor} rechazó las credenciales.",
            f"Revise {VARIABLE_CLAVE_SMTP} (con Gmail debe ser una contraseña de aplicación) y el usuario.",
        ) from error
    except (smtplib.SMTPException, OSError) as error:
        raise OperacionNoPermitida(
            f"No se pudo enviar el correo por {configuracion.servidor}:{configuracion.puerto} ({error}).",
            "Revise el servidor, el puerto, el cifrado TLS y la conexión de red.",
        ) from error
    return ResultadoPruebaCorreo(
        enviado_en=RelojSistema().ahora(), servidor=configuracion.servidor, destinatarios=configuracion.destinatarios
    )


VARIABLE_CONFIGURACION_EQUIPO = "CLOUDCR_NOTIFICACIONES"
CLAVES_CONFIGURACION_EQUIPO = {
    "servidor": "notificacion.email.servidor",
    "puerto": "notificacion.email.puerto",
    "tls": "notificacion.email.tls",
    "remitente": "notificacion.email.remitente",
    "destinatarios": "notificacion.email.destinatarios",
    "severidad_minima": "notificacion.email.severidad_minima",
    "canales": "notificacion.canales",
}


def archivo_configuracion_equipo() -> Path | None:
    candidatos: list[Path] = []
    configurado = os.environ.get(VARIABLE_CONFIGURACION_EQUIPO)
    if configurado:
        candidatos.append(Path(configurado))
    candidatos.append(Path.cwd() / "config" / "notificaciones.yaml")
    candidatos.append(Path(__file__).resolve().parents[3] / "config" / "notificaciones.yaml")
    return next((c for c in candidatos if c.is_file()), None)


def _texto_de_parametro(valor: object) -> str:
    if isinstance(valor, bool):
        return "true" if valor else "false"
    if isinstance(valor, list):
        return json.dumps([str(v) for v in valor])
    return str(valor)


def _equivalentes(actual: str, deseado: str) -> bool:
    if actual == deseado:
        return True
    try:
        return bool(json.loads(actual) == json.loads(deseado))
    except json.JSONDecodeError:
        return False


def _valores_de_configuracion(archivo: Path) -> dict[str, str]:
    try:
        datos = yaml.safe_load(archivo.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as error:
        raise OperacionNoPermitida(
            f"No se pudo leer {archivo}: {error}", "Revise el formato del archivo YAML."
        ) from error
    if not isinstance(datos, dict):
        raise OperacionNoPermitida(f"{archivo} no tiene el formato esperado.", "Debe ser un mapa clave: valor.")
    desconocidas = sorted(set(datos) - set(CLAVES_CONFIGURACION_EQUIPO))
    if desconocidas:
        raise OperacionNoPermitida(
            f"{archivo} tiene claves desconocidas: {', '.join(desconocidas)}.",
            f"Use solo: {', '.join(CLAVES_CONFIGURACION_EQUIPO)}.",
        )
    return {CLAVES_CONFIGURACION_EQUIPO[k]: _texto_de_parametro(v) for k, v in datos.items()}


def cargar_configuracion_del_equipo(ajustes: Ajustes, sobrescribir: bool = False) -> ResultadoConfiguracionCorreo:
    archivo = archivo_configuracion_equipo()
    if archivo is None:
        raise RecursoNoEncontrado(
            "No se encontró config/notificaciones.yaml.",
            f"Cree el archivo o defina {VARIABLE_CONFIGURACION_EQUIPO} con su ruta.",
        )
    deseados = _valores_de_configuracion(archivo)
    actuales = _parametros(ajustes)
    resultado = ResultadoConfiguracionCorreo(archivo=str(archivo))
    for clave, valor in deseados.items():
        actual = actuales.get(clave, "").strip()
        inicial = administracion.PARAMETROS_INICIALES.get(clave, "")
        igual = _equivalentes(actual, valor)
        if actual and actual != inicial and not igual and not sobrescribir:
            resultado.conservados.append(clave)
            continue
        if not igual:
            administracion.asignar_parametro(ajustes, clave, valor)
        resultado.aplicados.append(clave)
    return resultado
