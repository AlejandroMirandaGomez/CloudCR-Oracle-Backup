from dataclasses import dataclass, field

from cloudcr_backup.domain.enums import Compresion, LogMode, ModoRespaldo, TipoRespaldo
from cloudcr_backup.domain.estrategia import Como, Estrategia, Tarea
from cloudcr_backup.rman import nombres
from cloudcr_backup.rman.objetos import AlcanceInvalido, EspecificacionAlcance, especificacion_de
from cloudcr_backup.rman.render import ScriptNoAscii, renderizar

PLANTILLA_RESPALDO = "respaldo.rman.j2"
VARIABLE_TAG = "&1"
VARIABLE_COMMAND_ID = "&2"
CANALES_MAXIMOS = 8

NIVEL_POR_TIPO = {
    TipoRespaldo.COMPLETO: "",
    TipoRespaldo.INCREMENTAL_N0: " INCREMENTAL LEVEL 0",
    TipoRespaldo.INCREMENTAL_N1_DIFERENCIAL: " INCREMENTAL LEVEL 1",
    TipoRespaldo.INCREMENTAL_N1_ACUMULATIVO: " INCREMENTAL LEVEL 1 CUMULATIVE",
}

ALGORITMOS_EXPLICITOS = (Compresion.LOW, Compresion.MEDIUM, Compresion.HIGH)


class ScriptNoGenerable(ValueError):
    pass


@dataclass(frozen=True)
class SolicitudScript:
    estrategia: Estrategia
    tarea: Tarea
    log_mode: LogMode
    es_cdb: bool = True
    formato_pieza: str = nombres.FORMATO_PIEZA_POR_DEFECTO


@dataclass(frozen=True)
class ScriptGenerado:
    contenido: str
    modo: ModoRespaldo
    log_mode: LogMode
    sentencias: list[str] = field(default_factory=list)
    previas: list[str] = field(default_factory=list)
    posteriores: list[str] = field(default_factory=list)

    @property
    def requiere_caida(self) -> bool:
        return self.modo is ModoRespaldo.CONSISTENTE


def modo_efectivo(como: Como, log_mode: LogMode) -> ModoRespaldo:
    if como.modo_respaldo is not ModoRespaldo.AUTO:
        return como.modo_respaldo
    return ModoRespaldo.EN_LINEA if log_mode is LogMode.ARCHIVELOG else ModoRespaldo.CONSISTENTE


def _prefijo_compresion(compresion: Compresion) -> str:
    return "" if compresion is Compresion.NINGUNA else " AS COMPRESSED BACKUPSET"


def _etiqueta() -> str:
    return f" TAG '{VARIABLE_TAG}'"


def _sentencia_archivelog(compresion: Compresion) -> str:
    return f"BACKUP{_prefijo_compresion(compresion)} ARCHIVELOG ALL NOT BACKED UP 1 TIMES{_etiqueta()};"


def _sentencias_datos(
    especificacion: EspecificacionAlcance, tarea: Tarea, modo: ModoRespaldo
) -> list[str]:
    opciones = tarea.como.opciones
    prefijo = f"BACKUP{_prefijo_compresion(opciones.compresion)}{NIVEL_POR_TIPO[tarea.como.tipo_respaldo]}"
    omitir = " SKIP READONLY" if opciones.omitir_solo_lectura else ""
    con_archivelog = especificacion.archivelog and modo is ModoRespaldo.EN_LINEA
    sentencias = []
    for indice, clausula in enumerate(especificacion.clausulas()):
        plus = " PLUS ARCHIVELOG" if con_archivelog and indice == 0 else ""
        sentencias.append(f"{prefijo} {clausula}{omitir}{_etiqueta()}{plus};")
    if not sentencias and con_archivelog:
        sentencias.append(_sentencia_archivelog(opciones.compresion))
    if especificacion.controlfile:
        sentencias.append(f"BACKUP CURRENT CONTROLFILE{_etiqueta()};")
    if especificacion.spfile:
        sentencias.append(f"BACKUP SPFILE{_etiqueta()};")
    return sentencias


def _sentencias(solicitud: SolicitudScript, modo: ModoRespaldo) -> list[str]:
    tarea = solicitud.tarea
    try:
        especificacion = especificacion_de(solicitud.estrategia.alcance)
    except AlcanceInvalido as error:
        raise ScriptNoGenerable(str(error)) from error
    if tarea.como.tipo_respaldo is TipoRespaldo.ARCHIVELOG:
        if solicitud.log_mode is not LogMode.ARCHIVELOG:
            raise ScriptNoGenerable(
                f"La tarea {tarea.codigo} respalda archived logs, pero la base está en NOARCHIVELOG: "
                "no hay archived logs que respaldar."
            )
        return [_sentencia_archivelog(tarea.como.opciones.compresion)]
    if especificacion.vacia:
        raise ScriptNoGenerable(f"La estrategia {solicitud.estrategia.codigo} no tiene nada en su alcance.")
    sentencias = _sentencias_datos(especificacion, tarea, modo)
    if not sentencias:
        raise ScriptNoGenerable(
            f"El alcance de {solicitud.estrategia.codigo} solo tiene archived logs y la tarea {tarea.codigo} "
            "no se ejecuta en línea: no queda nada que respaldar."
        )
    return sentencias


def _previas(modo: ModoRespaldo, compresion: Compresion) -> list[str]:
    lineas = ["SHUTDOWN IMMEDIATE;", "STARTUP MOUNT;"] if modo is ModoRespaldo.CONSISTENTE else []
    if compresion in ALGORITMOS_EXPLICITOS:
        lineas.append(f"SET COMPRESSION ALGORITHM '{compresion.value}';")
    return lineas


def _posteriores(modo: ModoRespaldo, es_cdb: bool) -> list[str]:
    if modo is not ModoRespaldo.CONSISTENTE:
        return []
    lineas = ["ALTER DATABASE OPEN;"]
    if es_cdb:
        lineas.append("ALTER PLUGGABLE DATABASE ALL OPEN;")
    return lineas


def construir(solicitud: SolicitudScript) -> ScriptGenerado:
    tarea = solicitud.tarea
    estrategia = solicitud.estrategia
    canales = tarea.como.opciones.canales
    if not 1 <= canales <= CANALES_MAXIMOS:
        raise ScriptNoGenerable(f"La tarea {tarea.codigo} pide {canales} canales; se admiten de 1 a {CANALES_MAXIMOS}.")
    modo = modo_efectivo(tarea.como, solicitud.log_mode)
    sentencias = _sentencias(solicitud, modo)
    previas = _previas(modo, tarea.como.opciones.compresion)
    posteriores = _posteriores(modo, solicitud.es_cdb)
    try:
        contenido = renderizar(
            PLANTILLA_RESPALDO,
            previas=previas,
            posteriores=posteriores,
            sentencias=sentencias,
            canales=[f"c{numero}" for numero in range(1, canales + 1)],
            formato_pieza=nombres.formato_pieza(
                tarea.destino.ruta, estrategia.codigo, tarea.codigo, solicitud.formato_pieza
            ),
            formato_autobackup=nombres.formato_autobackup(tarea.destino.ruta),
        )
    except ScriptNoAscii as error:
        raise ScriptNoGenerable(str(error)) from error
    return ScriptGenerado(
        contenido=contenido,
        modo=modo,
        log_mode=solicitud.log_mode,
        sentencias=sentencias,
        previas=previas,
        posteriores=posteriores,
    )
