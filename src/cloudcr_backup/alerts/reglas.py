from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cloudcr_backup.alerts.instantanea import EstrategiaMonitoreada, Instantanea, TareaMonitoreada
from cloudcr_backup.domain.alertas import CodigoAlerta, Condicion, SeveridadAlerta
from cloudcr_backup.domain.enums import EstadoEjecucion, EstadoPrueba, LogMode, ModoRespaldo, TipoRespaldo
from cloudcr_backup.scheduling.recurrencia import ProgramacionInvalida, construir_regla
from cloudcr_backup.scheduling.reloj import utc_consciente
from cloudcr_backup.strategy.prioridad import criterio_de

ReglaAlerta = Callable[[Instantanea], Iterator[Condicion]]

PARAMETRO_DISCO_USO_PCT = "alertas.disco_uso_pct"
PARAMETRO_RECENCIA = "alertas.recencia_horas.{prioridad}"
PARAMETRO_ARCHIVELOGS_MAXIMO = "alertas.archivelogs_max"
DISCO_USO_PCT_POR_DEFECTO = 85.0
ARCHIVELOGS_MAXIMO_POR_DEFECTO = 100
LARGO_EXTRACTO_RMAN = 300
ZONA_POR_DEFECTO = "America/Costa_Rica"


@dataclass(frozen=True)
class DescripcionAlerta:
    titulo: str
    accion: str


CATALOGO: dict[str, DescripcionAlerta] = {
    CodigoAlerta.BD_NOARCHIVELOG: DescripcionAlerta(
        "Base en NOARCHIVELOG",
        "Evaluar activar ARCHIVELOG (decisión del DBA) y volver a inspeccionar con 'cloudcr db inspeccionar'.",
    ),
    CodigoAlerta.ESTRATEGIA_SIN_PROGRAMACION: DescripcionAlerta(
        "Estrategia activa sin programación utilizable",
        "Agregue tareas o complete su programación (horas, días o intervalo) y vuelva a validar.",
    ),
    CodigoAlerta.RESPALDO_NO_EJECUTADO: DescripcionAlerta(
        "Respaldo no ejecutado",
        "Verifique que el agente esté corriendo ('cloudcr agente estado') y revise el motivo en el historial.",
    ),
    CodigoAlerta.EJECUCION_FALLIDA: DescripcionAlerta(
        "La última ejecución falló",
        "Revise el log de RMAN con 'cloudcr historial mostrar <id>' y corrija la causa antes de la próxima hora.",
    ),
    CodigoAlerta.EJECUCION_BLOQUEADA: DescripcionAlerta(
        "La última ejecución quedó bloqueada",
        "Revise el motivo del bloqueo en el historial (preflight) y resuélvalo.",
    ),
    CodigoAlerta.VERIFICACION_FALLIDA: DescripcionAlerta(
        "La verificación del respaldo falló",
        "Revise el resultado de la verificación (RESTORE VALIDATE) y repita el respaldo.",
    ),
    CodigoAlerta.ESPACIO_INSUFICIENTE: DescripcionAlerta(
        "Poco espacio en el destino",
        "Libere espacio en el destino, ejecute la purga de respaldos obsoletos o cambie el destino de la tarea.",
    ),
    CodigoAlerta.SIN_RESPALDO_RECIENTE: DescripcionAlerta(
        "Sin respaldo reciente",
        "Revise el historial de la estrategia y que el agente esté corriendo; ejecute un respaldo si hace falta.",
    ),
    CodigoAlerta.MODO_ARCHIVADO_CAMBIO: DescripcionAlerta(
        "Cambió el modo de archivado",
        "Regenere y apruebe de nuevo el script RMAN de la tarea para el modo de archivado actual.",
    ),
    CodigoAlerta.RETENCION_VENCIDA: DescripcionAlerta(
        "Piezas de respaldo vencidas",
        "Ejecute la purga de respaldos obsoletos (decisión del DBA) o active la purga automática.",
    ),
    CodigoAlerta.ARCHIVELOG_ACUMULADO: DescripcionAlerta(
        "Archived logs sin respaldar",
        "Programe o ejecute una tarea de respaldo de archived logs.",
    ),
    CodigoAlerta.SCRIPT_ALTERADO: DescripcionAlerta(
        "El script RMAN fue alterado",
        "El contenido no coincide con el hash aprobado: revise quién lo cambió y vuelva a aprobarlo.",
    ),
    CodigoAlerta.BASE_NO_REABIERTA: DescripcionAlerta(
        "La base no se reabrió",
        "Abra la base manualmente (ALTER DATABASE OPEN) y revise el log del respaldo consistente.",
    ),
}


def descripcion(codigo: str) -> DescripcionAlerta | None:
    return CATALOGO.get(codigo)


def _accion(codigo: CodigoAlerta) -> str:
    return CATALOGO[codigo].accion


def _entero(parametros: dict[str, str], clave: str, defecto: int) -> int:
    try:
        return int(parametros[clave])
    except (KeyError, ValueError):
        return defecto


def _flotante(parametros: dict[str, str], clave: str, defecto: float) -> float:
    try:
        return float(parametros[clave])
    except (KeyError, ValueError):
        return defecto


def _zona(nombre: str) -> ZoneInfo:
    try:
        return ZoneInfo(nombre)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(ZONA_POR_DEFECTO)


def hora_local(momento: datetime, zona_horaria: str) -> str:
    return utc_consciente(momento).astimezone(_zona(zona_horaria)).strftime("%Y-%m-%d %H:%M")


def _tamano(cantidad: int) -> str:
    unidades = ("B", "KB", "MB", "GB", "TB")
    valor = float(cantidad)
    indice = 0
    while valor >= 1024 and indice < len(unidades) - 1:
        valor /= 1024
        indice += 1
    return f"{valor:.1f} {unidades[indice]}" if indice >= 2 else f"{valor:.0f} {unidades[indice]}"


def _condicion_tarea(
    codigo: CodigoAlerta,
    estrategia: EstrategiaMonitoreada,
    tarea: TareaMonitoreada,
    severidad: SeveridadAlerta,
    mensaje: str,
    ejecucion_id: int | None = None,
) -> Condicion:
    return Condicion(
        codigo_regla=codigo.value,
        sujeto=estrategia.sujeto(tarea),
        severidad=severidad,
        mensaje=mensaje,
        accion_sugerida=_accion(codigo),
        bd_id=estrategia.bd_id,
        estrategia_id=estrategia.estrategia_id,
        tarea_id=tarea.tarea_id,
        ejecucion_id=ejecucion_id,
        alcance=estrategia.alcance,
    )


def _tareas_con_script(instantanea: Instantanea) -> Iterator[tuple[EstrategiaMonitoreada, TareaMonitoreada]]:
    for estrategia in instantanea.estrategias:
        for tarea in estrategia.tareas:
            if tarea.script is not None:
                yield estrategia, tarea


def bd_noarchivelog(instantanea: Instantanea) -> Iterator[Condicion]:
    for base in instantanea.bases:
        if base.perfil is None or base.perfil.log_mode is not LogMode.NOARCHIVELOG:
            continue
        yield Condicion(
            codigo_regla=CodigoAlerta.BD_NOARCHIVELOG.value,
            sujeto=base.nombre,
            severidad=SeveridadAlerta.ADVERTENCIA,
            mensaje=(
                f"La base {base.nombre} está en NOARCHIVELOG: solo admite respaldos consistentes (con la base "
                "detenida) y no permite recuperar hasta un punto en el tiempo."
            ),
            accion_sugerida=_accion(CodigoAlerta.BD_NOARCHIVELOG),
            bd_id=base.bd_id,
        )


def estrategia_sin_programacion(instantanea: Instantanea) -> Iterator[Condicion]:
    for estrategia in instantanea.estrategias:
        if not estrategia.tareas:
            problema = "no tiene tareas"
        else:
            invalidas = []
            for tarea in estrategia.tareas:
                try:
                    construir_regla(tarea.programacion)
                except ProgramacionInvalida as error:
                    invalidas.append(f"{tarea.codigo} ({error})")
            if len(invalidas) < len(estrategia.tareas):
                continue
            problema = "ninguna de sus tareas tiene una programación utilizable: " + "; ".join(invalidas)
        yield Condicion(
            codigo_regla=CodigoAlerta.ESTRATEGIA_SIN_PROGRAMACION.value,
            sujeto=estrategia.sujeto(),
            severidad=SeveridadAlerta.ADVERTENCIA,
            mensaje=f"La estrategia activa {estrategia.codigo} de {estrategia.bd_nombre} {problema}.",
            accion_sugerida=_accion(CodigoAlerta.ESTRATEGIA_SIN_PROGRAMACION),
            bd_id=estrategia.bd_id,
            estrategia_id=estrategia.estrategia_id,
            alcance=estrategia.alcance,
        )


def respaldo_no_ejecutado(instantanea: Instantanea) -> Iterator[Condicion]:
    for estrategia, tarea in _tareas_con_script(instantanea):
        zona = tarea.programacion.zona_horaria
        ultima = tarea.ultima_terminal
        if ultima is not None and ultima.estado is EstadoEjecucion.NO_EJECUTADA:
            motivo = f" Motivo: {ultima.mensaje}" if ultima.mensaje else ""
            yield _condicion_tarea(
                CodigoAlerta.RESPALDO_NO_EJECUTADO,
                estrategia,
                tarea,
                SeveridadAlerta.ALERTA,
                f"El respaldo de {estrategia.sujeto(tarea)} programado para las "
                f"{hora_local(ultima.programada_para, zona)} no se ejecutó.{motivo}",
                ultima.ejecucion_id,
            )
        elif tarea.ocurrencias_perdidas:
            primera = tarea.ocurrencias_perdidas[0]
            yield _condicion_tarea(
                CodigoAlerta.RESPALDO_NO_EJECUTADO,
                estrategia,
                tarea,
                SeveridadAlerta.ALERTA,
                f"{estrategia.sujeto(tarea)} tiene {len(tarea.ocurrencias_perdidas)} ocurrencia(s) vencidas sin "
                f"reclamar desde las {hora_local(primera, zona)}: el agente parece detenido.",
            )


def _ejecucion_con_estado(codigo: CodigoAlerta, estado: EstadoEjecucion, verbo: str) -> ReglaAlerta:
    def regla(instantanea: Instantanea) -> Iterator[Condicion]:
        for estrategia, tarea in _tareas_con_script(instantanea):
            ultima = tarea.ultima_concluyente
            if ultima is None or ultima.estado is not estado:
                continue
            detalle = f" RMAN: {ultima.mensaje[:LARGO_EXTRACTO_RMAN]}" if ultima.mensaje else ""
            yield _condicion_tarea(
                codigo,
                estrategia,
                tarea,
                SeveridadAlerta.ALERTA,
                f"La ejecución {ultima.ejecucion_id} de {estrategia.sujeto(tarea)} "
                f"({hora_local(ultima.programada_para, tarea.programacion.zona_horaria)}) {verbo}.{detalle}",
                ultima.ejecucion_id,
            )

    return regla


ejecucion_fallida = _ejecucion_con_estado(CodigoAlerta.EJECUCION_FALLIDA, EstadoEjecucion.FALLIDA, "falló")
ejecucion_bloqueada = _ejecucion_con_estado(
    CodigoAlerta.EJECUCION_BLOQUEADA, EstadoEjecucion.BLOQUEADA, "quedó bloqueada antes de iniciar RMAN"
)


def verificacion_fallida(instantanea: Instantanea) -> Iterator[Condicion]:
    for estrategia, tarea in _tareas_con_script(instantanea):
        ultima = tarea.ultima_concluyente
        if ultima is None or ultima.estado_prueba is not EstadoPrueba.FALLIDA:
            continue
        yield _condicion_tarea(
            CodigoAlerta.VERIFICACION_FALLIDA,
            estrategia,
            tarea,
            SeveridadAlerta.ALERTA,
            f"La verificación del respaldo {ultima.ejecucion_id} de {estrategia.sujeto(tarea)} falló: "
            "el respaldo podría no servir para restaurar.",
            ultima.ejecucion_id,
        )


def espacio_insuficiente(instantanea: Instantanea) -> Iterator[Condicion]:
    umbral = _flotante(instantanea.parametros, PARAMETRO_DISCO_USO_PCT, DISCO_USO_PCT_POR_DEFECTO)
    for estrategia, tarea in _tareas_con_script(instantanea):
        uso = instantanea.uso_disco.get(tarea.destino_ruta)
        if uso is None or uso.total_bytes == 0:
            continue
        estimado = tarea.tamano_ultimo_exito
        if estimado is not None and uso.libres_bytes < estimado:
            yield _condicion_tarea(
                CodigoAlerta.ESPACIO_INSUFICIENTE,
                estrategia,
                tarea,
                SeveridadAlerta.ALERTA,
                f"El destino {tarea.destino_ruta} tiene {_tamano(uso.libres_bytes)} libres y el último respaldo "
                f"de {estrategia.sujeto(tarea)} ocupó {_tamano(estimado)}: el próximo probablemente no cabe.",
            )
        elif uso.porcentaje_uso > umbral:
            yield _condicion_tarea(
                CodigoAlerta.ESPACIO_INSUFICIENTE,
                estrategia,
                tarea,
                SeveridadAlerta.ADVERTENCIA,
                f"El destino {tarea.destino_ruta} está al {uso.porcentaje_uso:.0f} % "
                f"(umbral {umbral:.0f} %); quedan {_tamano(uso.libres_bytes)} libres.",
            )


def sin_respaldo_reciente(instantanea: Instantanea) -> Iterator[Condicion]:
    for estrategia in instantanea.estrategias:
        aprobaciones = [
            utc_consciente(t.script.aprobado_en)
            for t in estrategia.tareas
            if t.script is not None and t.script.aprobado_en is not None
        ]
        if not aprobaciones:
            continue
        defecto = int(criterio_de(estrategia.prioridad).recencia_maxima_horas)
        clave = PARAMETRO_RECENCIA.format(prioridad=estrategia.prioridad.value)
        limite_horas = _entero(instantanea.parametros, clave, defecto)
        referencias = [min(aprobaciones)]
        if estrategia.ultimo_exito is not None:
            referencias.append(utc_consciente(estrategia.ultimo_exito))
        referencia = max(referencias)
        horas = (utc_consciente(instantanea.ahora) - referencia).total_seconds() / 3600
        if horas <= limite_horas:
            continue
        zona = estrategia.tareas[0].programacion.zona_horaria
        ultimo = (
            f"el último respaldo correcto fue el {hora_local(estrategia.ultimo_exito, zona)}"
            if estrategia.ultimo_exito is not None
            else "todavía no hay ningún respaldo correcto"
        )
        yield Condicion(
            codigo_regla=CodigoAlerta.SIN_RESPALDO_RECIENTE.value,
            sujeto=estrategia.sujeto(),
            severidad=SeveridadAlerta.ALERTA,
            mensaje=(
                f"La estrategia {estrategia.codigo} de {estrategia.bd_nombre} (prioridad {estrategia.prioridad}) "
                f"lleva {horas:.0f} h sin respaldo correcto ({ultimo}); el máximo es {limite_horas} h."
            ),
            accion_sugerida=_accion(CodigoAlerta.SIN_RESPALDO_RECIENTE),
            bd_id=estrategia.bd_id,
            estrategia_id=estrategia.estrategia_id,
            alcance=estrategia.alcance,
        )


def modo_archivado_cambio(instantanea: Instantanea) -> Iterator[Condicion]:
    for estrategia, tarea in _tareas_con_script(instantanea):
        base = instantanea.base(estrategia.bd_id)
        assert tarea.script is not None
        anterior = tarea.script.log_mode_al_crear
        if base is None or base.perfil is None or anterior is None or anterior is base.perfil.log_mode:
            continue
        actual = base.perfil.log_mode
        if actual is LogMode.ARCHIVELOG:
            yield _condicion_tarea(
                CodigoAlerta.MODO_ARCHIVADO_CAMBIO,
                estrategia,
                tarea,
                SeveridadAlerta.ADVERTENCIA,
                f"El script de {estrategia.sujeto(tarea)} se generó con la base en NOARCHIVELOG y ahora está en "
                "ARCHIVELOG: regenérelo para aprovechar el respaldo en línea (sin detener la base).",
            )
            continue
        depende_de_archivado = (
            tarea.tipo_respaldo is TipoRespaldo.ARCHIVELOG or tarea.modo_respaldo is not ModoRespaldo.CONSISTENTE
        )
        if depende_de_archivado:
            yield _condicion_tarea(
                CodigoAlerta.MODO_ARCHIVADO_CAMBIO,
                estrategia,
                tarea,
                SeveridadAlerta.ALERTA,
                f"El script de {estrategia.sujeto(tarea)} se generó con la base en ARCHIVELOG y ahora está en "
                "NOARCHIVELOG: el respaldo en línea o de archived logs va a fallar.",
            )


def retencion_vencida(instantanea: Instantanea) -> Iterator[Condicion]:
    for estrategia in instantanea.estrategias:
        if estrategia.purga_automatica or estrategia.piezas_vencidas <= 0:
            continue
        yield Condicion(
            codigo_regla=CodigoAlerta.RETENCION_VENCIDA.value,
            sujeto=estrategia.sujeto(),
            severidad=SeveridadAlerta.RECOMENDACION,
            mensaje=(
                f"La estrategia {estrategia.codigo} de {estrategia.bd_nombre} tiene {estrategia.piezas_vencidas} "
                "pieza(s) de respaldo fuera de su retención y no tiene purga automática."
            ),
            accion_sugerida=_accion(CodigoAlerta.RETENCION_VENCIDA),
            bd_id=estrategia.bd_id,
            estrategia_id=estrategia.estrategia_id,
            alcance=estrategia.alcance,
        )


def archivelog_acumulado(instantanea: Instantanea) -> Iterator[Condicion]:
    maximo = _entero(instantanea.parametros, PARAMETRO_ARCHIVELOGS_MAXIMO, ARCHIVELOGS_MAXIMO_POR_DEFECTO)
    for base in instantanea.bases:
        perfil = base.perfil
        if perfil is None or perfil.log_mode is not LogMode.ARCHIVELOG:
            continue
        if perfil.archivelogs_sin_respaldo <= maximo:
            continue
        yield Condicion(
            codigo_regla=CodigoAlerta.ARCHIVELOG_ACUMULADO.value,
            sujeto=base.nombre,
            severidad=SeveridadAlerta.ADVERTENCIA,
            mensaje=(
                f"La base {base.nombre} tiene {perfil.archivelogs_sin_respaldo} archived logs sin respaldar "
                f"(máximo {maximo}) según la última inspección."
            ),
            accion_sugerida=_accion(CodigoAlerta.ARCHIVELOG_ACUMULADO),
            bd_id=base.bd_id,
        )


REGLAS: dict[CodigoAlerta, ReglaAlerta] = {
    CodigoAlerta.BD_NOARCHIVELOG: bd_noarchivelog,
    CodigoAlerta.ESTRATEGIA_SIN_PROGRAMACION: estrategia_sin_programacion,
    CodigoAlerta.RESPALDO_NO_EJECUTADO: respaldo_no_ejecutado,
    CodigoAlerta.EJECUCION_FALLIDA: ejecucion_fallida,
    CodigoAlerta.EJECUCION_BLOQUEADA: ejecucion_bloqueada,
    CodigoAlerta.VERIFICACION_FALLIDA: verificacion_fallida,
    CodigoAlerta.ESPACIO_INSUFICIENTE: espacio_insuficiente,
    CodigoAlerta.SIN_RESPALDO_RECIENTE: sin_respaldo_reciente,
    CodigoAlerta.MODO_ARCHIVADO_CAMBIO: modo_archivado_cambio,
    CodigoAlerta.RETENCION_VENCIDA: retencion_vencida,
    CodigoAlerta.ARCHIVELOG_ACUMULADO: archivelog_acumulado,
}

CODIGOS_DE_EVENTO = frozenset({CodigoAlerta.SCRIPT_ALTERADO.value, CodigoAlerta.BASE_NO_REABIERTA.value})
