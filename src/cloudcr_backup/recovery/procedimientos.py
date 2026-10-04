import re
from dataclasses import dataclass, field
from datetime import datetime

from cloudcr_backup.domain.enums import LogMode
from cloudcr_backup.domain.recuperacion import ArchivoDanado, Escenario, Procedimiento
from cloudcr_backup.rman import nombres
from cloudcr_backup.rman.render import ScriptNoAscii, renderizar

RAIZ = "CDB$ROOT"
PATRON_NOMBRE = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]{0,127}$")
FORMATO_HASTA = "%Y-%m-%d %H:%M:%S"
REQUIEREN_ARCHIVELOG = frozenset({Escenario.PDB, Escenario.TABLESPACE, Escenario.DATAFILE, Escenario.PUNTO_EN_TIEMPO})
PLANTILLAS = {
    Escenario.PDB: "recuperacion/pdb.rman.j2",
    Escenario.TABLESPACE: "recuperacion/tablespace.rman.j2",
    Escenario.DATAFILE: "recuperacion/datafile.rman.j2",
    Escenario.CONTROLFILE: "recuperacion/controlfile.rman.j2",
    Escenario.TOTAL_NOARCHIVELOG: "recuperacion/total_noarchivelog.rman.j2",
    Escenario.PUNTO_EN_TIEMPO: "recuperacion/punto_en_tiempo.rman.j2",
}

PASO_DIAGNOSTICO = (
    "Identificar qué archivo falta o está dañado con V$RECOVER_FILE y V$DATAFILE ('cloudcr recuperacion diagnostico')."
)
PASO_REVISAR = "Revisar el script generado y confirmar que existe un respaldo válido (columna Pruebas en OK)."
PASO_EJECUTAR = (
    "Ejecutarlo manualmente con 'rman target /' y 'CMDFILE=' sobre una base de PRUEBAS: la herramienta "
    "genera el procedimiento pero nunca lo ejecuta."
)
PASO_REDO = (
    "RECOVER aplica los cambios desde el respaldo: primero los archived redo logs y al final los redo logs online, "
    "hasta dejar el archivo sincronizado con el resto de la base (media recovery)."
)

PASOS_ESCENARIO = {
    Escenario.PDB: [
        "Cerrar solo la PDB afectada; el resto de la CDB sigue en servicio.",
        "Restaurar sus datafiles desde el último respaldo y recuperarla.",
        PASO_REDO,
        "Abrir la PDB.",
    ],
    Escenario.TABLESPACE: [
        "Dejar fuera de servicio el tablespace (o cerrar su PDB si pertenece a una).",
        "Restaurar sus datafiles desde el respaldo y recuperarlo.",
        PASO_REDO,
        "Volver a ponerlo en línea.",
    ],
    Escenario.DATAFILE: [
        "Dejar fuera de línea solo el datafile dañado (o cerrar su PDB si pertenece a una).",
        "Restaurarlo por su número de archivo (file#) y recuperarlo.",
        PASO_REDO,
        "Volver a ponerlo en línea.",
    ],
    Escenario.CONTROLFILE: [
        "Arrancar la instancia sin montar (NOMOUNT) e indicar el DBID de la base.",
        "Restaurar el control file desde la pieza respaldada por la estrategia o desde el autobackup.",
        "Montar la base y recuperarla con los archived y online redo logs disponibles.",
        "Abrir con RESETLOGS: se inicia una nueva encarnación y hay que hacer un respaldo completo de inmediato.",
    ],
    Escenario.TOTAL_NOARCHIVELOG: [
        "Apagar la base con SHUTDOWN IMMEDIATE y montarla.",
        "Restaurar la base completa desde el último respaldo consistente (en frío).",
        "RECOVER DATABASE NOREDO: en NOARCHIVELOG no hay redo que aplicar; se pierden los cambios posteriores "
        "al respaldo.",
        "Abrir con RESETLOGS y hacer un respaldo nuevo.",
    ],
    Escenario.PUNTO_EN_TIEMPO: [
        "Apagar la base y montarla.",
        "Fijar el momento objetivo con SET UNTIL TIME.",
        "Restaurar la base completa y aplicar redo solo hasta ese momento (recuperación incompleta).",
        "Abrir con RESETLOGS y hacer un respaldo nuevo.",
    ],
}


@dataclass(frozen=True)
class SolicitudProcedimiento:
    bd: str
    escenario: Escenario
    log_mode: LogMode
    dbid: int | None = None
    destino_autobackup: str | None = None
    objetivo: str | None = None
    hasta: datetime | None = None
    pieza_controlfile: str | None = None
    danados: list[ArchivoDanado] = field(default_factory=list)
    contenedor_de_datafile: dict[int, str] = field(default_factory=dict)
    hay_respaldo: bool = True


def _imposible(solicitud: SolicitudProcedimiento, motivo: str, objetivo: str | None = None) -> Procedimiento:
    return Procedimiento(
        bd=solicitud.bd, escenario=solicitud.escenario, posible=False, motivo=motivo, objetivo=objetivo
    )


def _nombre_valido(texto: str) -> bool:
    return all(PATRON_NOMBRE.match(parte) for parte in texto.split(":")) and texto.count(":") <= 1


def _objetivo_datafile(solicitud: SolicitudProcedimiento) -> tuple[dict[str, object], str] | str:
    if solicitud.objetivo:
        try:
            numero = int(solicitud.objetivo)
        except ValueError:
            return f"El datafile debe indicarse por su número (file#), no {solicitud.objetivo!r}."
        archivo = next((a for a in solicitud.danados if a.file_id == numero), None)
        contenedor = solicitud.contenedor_de_datafile.get(numero)
        pdb = archivo.pdb if archivo else (contenedor if contenedor not in (None, RAIZ) else None)
        return {"datafile": numero, "pdb": pdb}, str(numero)
    if not solicitud.danados:
        return "El diagnóstico no encontró archivos dañados en V$RECOVER_FILE; indique el datafile con --objetivo."
    archivo = solicitud.danados[0]
    return {"datafile": archivo.file_id, "pdb": archivo.pdb}, f"{archivo.file_id} ({archivo.ruta})"


def _objetivo_tablespace(solicitud: SolicitudProcedimiento) -> tuple[dict[str, object], str] | str:
    identificador = solicitud.objetivo.strip().upper() if solicitud.objetivo else None
    if identificador is None:
        candidato = next((a.identificador_tablespace for a in solicitud.danados if a.tablespace), None)
        if candidato is None:
            return "El diagnóstico no encontró tablespaces dañados; indique el tablespace con --objetivo (PDB:TS)."
        identificador = candidato.upper()
    if not _nombre_valido(identificador):
        return f"El tablespace {identificador!r} no es un identificador válido."
    pdb = identificador.split(":", 1)[0] if ":" in identificador else None
    return {"tablespace": identificador, "pdb": pdb}, identificador


def _objetivo_pdb(solicitud: SolicitudProcedimiento) -> tuple[dict[str, object], str] | str:
    pdb = solicitud.objetivo.strip().upper() if solicitud.objetivo else None
    if pdb is None:
        pdb = next((a.pdb.upper() for a in solicitud.danados if a.pdb), None)
        if pdb is None:
            return "El diagnóstico no encontró una PDB con archivos dañados; indique la PDB con --objetivo."
    if not _nombre_valido(pdb) or ":" in pdb:
        return f"La PDB {pdb!r} no es un nombre válido."
    return {"pdb": pdb}, pdb


def _contexto(solicitud: SolicitudProcedimiento) -> tuple[dict[str, object], str | None] | str:
    escenario = solicitud.escenario
    if escenario is Escenario.DATAFILE:
        return _objetivo_datafile(solicitud)
    if escenario is Escenario.TABLESPACE:
        return _objetivo_tablespace(solicitud)
    if escenario is Escenario.PDB:
        return _objetivo_pdb(solicitud)
    if escenario is Escenario.CONTROLFILE:
        if solicitud.dbid is None:
            return "Se necesita el DBID de la base para restaurar el control file."
        if solicitud.destino_autobackup is None and solicitud.pieza_controlfile is None:
            return "No hay pieza de control file registrada ni destino de autobackup conocido."
        formato = nombres.formato_autobackup(solicitud.destino_autobackup or "")
        return {"dbid": solicitud.dbid, "pieza": solicitud.pieza_controlfile, "formato_autobackup": formato}, None
    if escenario is Escenario.PUNTO_EN_TIEMPO:
        if solicitud.hasta is None:
            return "Indique el momento objetivo con --hasta 'AAAA-MM-DD HH:MM'."
        texto = solicitud.hasta.strftime(FORMATO_HASTA)
        return {"hasta": texto}, texto
    return {}, None


def generar(solicitud: SolicitudProcedimiento) -> Procedimiento:
    escenario = solicitud.escenario
    if escenario in REQUIEREN_ARCHIVELOG and solicitud.log_mode is not LogMode.ARCHIVELOG:
        return _imposible(
            solicitud,
            f"El escenario {escenario.value} necesita la base en ARCHIVELOG para aplicar redo después de restaurar; "
            f"{solicitud.bd} está en NOARCHIVELOG. Con este modo solo se puede volver al último respaldo consistente "
            "(escenario total-noarchivelog), perdiendo los cambios posteriores.",
        )
    contexto = _contexto(solicitud)
    if isinstance(contexto, str):
        return _imposible(solicitud, contexto)
    variables, objetivo = contexto
    try:
        script = renderizar(PLANTILLAS[escenario], **variables)
    except ScriptNoAscii as error:
        return _imposible(solicitud, str(error), objetivo)
    avisos = []
    if not solicitud.hay_respaldo:
        avisos.append("No hay respaldos registrados para esta base: el procedimiento no tendría desde dónde restaurar.")
    if escenario is Escenario.TOTAL_NOARCHIVELOG and solicitud.log_mode is LogMode.ARCHIVELOG:
        avisos.append(
            "La base está en ARCHIVELOG: considere un escenario de recuperación completa (pdb, tablespace o datafile) "
            "en lugar de volver a un respaldo en frío."
        )
    return Procedimiento(
        bd=solicitud.bd,
        escenario=escenario,
        posible=True,
        motivo="Procedimiento generado; no se ejecuta automáticamente.",
        objetivo=objetivo,
        pasos=[PASO_DIAGNOSTICO, *PASOS_ESCENARIO[escenario], PASO_REVISAR, PASO_EJECUTAR],
        script=script,
        avisos=avisos,
    )
