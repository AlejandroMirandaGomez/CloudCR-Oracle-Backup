from collections.abc import Callable, Sequence

from cloudcr_backup.alerts.motor import MotorAlertas
from cloudcr_backup.alerts.notificadores.seleccion import construir_notificadores
from cloudcr_backup.config.ajustes import Ajustes, cargar_ajustes
from cloudcr_backup.domain.alertas import Condicion, ResumenEvaluacion, SeveridadAlerta, VistaAlerta
from cloudcr_backup.domain.enums import EstadoAlerta
from cloudcr_backup.domain.errores import OperacionNoPermitida, RecursoNoEncontrado
from cloudcr_backup.repository import alertas as repositorio_alertas
from cloudcr_backup.scheduling.reloj import RelojSistema
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
        raise OperacionNoPermitida(
            f"El estado {estado!r} no es válido.", "Use vigentes, todas, ABIERTA, RECONOCIDA o RESUELTA."
        ) from error


def severidad_de_filtro(severidad: str | None) -> SeveridadAlerta | None:
    if not severidad:
        return None
    try:
        return SeveridadAlerta(severidad.strip().upper())
    except ValueError as error:
        raise OperacionNoPermitida(
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
