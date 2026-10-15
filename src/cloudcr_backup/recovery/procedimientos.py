import re
from dataclasses import dataclass, field
from datetime import datetime

from cloudcr_backup.domain.enums import LogMode
from cloudcr_backup.domain.recuperacion import (
    ArchivoDanado,
    BloqueCorrupto,
    Escenario,
    GrupoRedo,
    GrupoRedoActual,
    MiembroRedoDanado,
    Procedimiento,
    tablespace_critico,
)
from cloudcr_backup.rman import nombres
from cloudcr_backup.rman.render import ScriptNoAscii, renderizar

RAIZ = "CDB$ROOT"
PATRON_NOMBRE = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]{0,127}$")
PATRON_GRUPO_Y_RUTA = re.compile(r"^(\d+):(.+)$")
PATRON_PAR_NUMEROS = re.compile(r"^(\d+)\s*:\s*(\d+)$")
CARACTERES_PROHIBIDOS_RUTA = frozenset("'\";\r\n")
LARGO_MAXIMO_RUTA = 400
FORMATO_HASTA = "%Y-%m-%d %H:%M:%S"
MODO_PDB_CERRADA = "MOUNTED"
OBJETIVO_SIN_CONTROLFILE = "controlfile"
ESTADOS_REDO_SIN_CHECKPOINT = frozenset({"INACTIVE", "UNUSED"})
ESTADOS_REDO_SIN_ARCHIVAR = frozenset({"CURRENT", "ACTIVE"})
REQUIEREN_ARCHIVELOG = frozenset(
    {
        Escenario.PDB,
        Escenario.TABLESPACE,
        Escenario.DATAFILE,
        Escenario.DATAFILE_CRITICO,
        Escenario.GRUPO_REDOLOG_ACTUAL,
        Escenario.CORRUPCION_BLOQUE,
        Escenario.PUNTO_EN_TIEMPO,
    }
)
REQUIEREN_AUTOBACKUP = frozenset({Escenario.CONTROLFILE, Escenario.SPFILE})
PLANTILLAS = {
    Escenario.PDB: "recuperacion/pdb.rman.j2",
    Escenario.TABLESPACE: "recuperacion/tablespace.rman.j2",
    Escenario.DATAFILE: "recuperacion/datafile.rman.j2",
    Escenario.DATAFILE_CRITICO: "recuperacion/datafile_critico.rman.j2",
    Escenario.CONTROLFILE: "recuperacion/controlfile.rman.j2",
    Escenario.MIEMBRO_REDOLOG: "recuperacion/miembro_redolog.rman.j2",
    Escenario.GRUPO_REDOLOG_ACTUAL: "recuperacion/grupo_redolog_actual.rman.j2",
    Escenario.CORRUPCION_BLOQUE: "recuperacion/corrupcion_bloque.rman.j2",
    Escenario.SPFILE: "recuperacion/spfile.rman.j2",
    Escenario.TOTAL_NOARCHIVELOG: "recuperacion/total_noarchivelog.rman.j2",
    Escenario.PUNTO_EN_TIEMPO: "recuperacion/punto_en_tiempo.rman.j2",
}

PASO_DIAGNOSTICO = (
    "Identificar qué archivo falta o está dañado con V$RECOVER_FILE, V$DATAFILE, V$DATABASE_BLOCK_CORRUPTION y "
    "V$LOGFILE ('cloudcr recuperacion diagnostico')."
)
PASO_REVISAR = "Revisar el script generado y confirmar que existe un respaldo válido (columna Pruebas en OK)."
PASO_EJECUTAR = (
    "Aprobarlo y ejecutarlo desde la herramienta (nunca se ejecuta solo), o aplicarlo a mano con 'rman target /' y "
    "'CMDFILE=' bajo la responsabilidad del DBA."
)
PASO_REDO = (
    "RECOVER aplica los cambios desde el respaldo: primero los archived redo logs y al final los redo logs online, "
    "hasta dejar el archivo sincronizado con el resto de la base (media recovery)."
)
PASO_RESPALDO_NUEVO = (
    "Abrir con RESETLOGS: se inicia una nueva encarnación y hay que hacer un respaldo completo de inmediato."
)
PASO_CONTROLFILE_DESDE_AUTOBACKUP = (
    "Arrancar la instancia sin montar (STARTUP FORCE NOMOUNT, que la reinicia aunque haya quedado a medio arrancar) e "
    "indicar el DBID de la base."
)
PASO_RESTAURAR_CONTROLFILE = (
    "Restaurar el control file desde la pieza respaldada por la estrategia o desde el autobackup."
)
AVISO_EN_LINEA_PDB = (
    "RMAN no puede cambiar de contenedor, así que el script no pone el tablespace en línea: si había quedado "
    "OFFLINE, CloudCR lo hace al terminar la ejecución. Si aplica el script a mano, ejecute "
    "'ALTER TABLESPACE <nombre> ONLINE;' dentro de la PDB."
)

PASOS_ESCENARIO = {
    Escenario.PDB: [
        "Cerrar solo la PDB afectada si está abierta; el resto de la CDB sigue en servicio. Si ya está cerrada "
        "(MOUNTED, como queda al perder su SYSTEM o su UNDO), no hace falta cerrarla.",
        "Restaurar sus datafiles desde el último respaldo y recuperarla.",
        PASO_REDO,
        "Abrir la PDB.",
    ],
    Escenario.TABLESPACE: [
        "Dejar fuera de servicio el tablespace (o cerrar su PDB si pertenece a una y está abierta).",
        "Restaurar sus datafiles desde el respaldo y recuperarlo.",
        PASO_REDO,
        "Volver a ponerlo en línea.",
    ],
    Escenario.DATAFILE: [
        "Dejar fuera de línea solo el datafile dañado (o cerrar su PDB si pertenece a una y está abierta). El SYSTEM "
        "y el UNDO de una PDB se recuperan con la PDB cerrada: al perderlos la PDB queda en MOUNTED y no hace falta "
        "cerrarla otra vez.",
        "Restaurarlo por su número de archivo (file#) y recuperarlo.",
        PASO_REDO,
        "Volver a ponerlo en línea (o abrir la PDB).",
    ],
    Escenario.DATAFILE_CRITICO: [
        "Un datafile de SYSTEM o UNDO del contenedor raíz no se puede dejar OFFLINE con la base abierta: hay que "
        "detener la instancia (STARTUP FORCE MOUNT la reinicia y la deja montada).",
        "Restaurar el datafile por su número (file#) y recuperarlo con la base montada.",
        PASO_REDO,
        "Abrir la base (ALTER DATABASE OPEN). No hace falta RESETLOGS: la recuperación es completa.",
    ],
    Escenario.CONTROLFILE: [
        PASO_CONTROLFILE_DESDE_AUTOBACKUP,
        PASO_RESTAURAR_CONTROLFILE,
        "Montar la base, restaurar los datafiles (RESTORE DATABASE) y recuperarla con los archived y online redo "
        "logs disponibles (RECOVER DATABASE).",
        PASO_RESPALDO_NUEVO,
    ],
    Escenario.MIEMBRO_REDOLOG: [
        "El grupo sigue funcionando con su otro miembro (multiplexación): la base no se cae y no hay que "
        "restaurar ni recuperar nada.",
        "Dejar el grupo INACTIVE: si es el CURRENT, cambiar de log (SWITCH LOGFILE) y hacer un CHECKPOINT; si está "
        "ACTIVE, basta el CHECKPOINT; si ya está INACTIVE no hace falta nada.",
        "Quitar el miembro dañado del grupo (DROP LOGFILE MEMBER).",
        "Volver a crearlo en la misma ruta (ADD LOGFILE MEMBER ... REUSE TO GROUP).",
    ],
    Escenario.GRUPO_REDOLOG_ACTUAL: [
        "Se perdieron todos los miembros del grupo CURRENT: su redo no existe en ningún lado y la recuperación "
        "solo puede ser incompleta (se pierden las transacciones de ese log).",
        "Reiniciar la instancia en MOUNT.",
        "Fijar el límite con SET UNTIL SEQUENCE (la secuencia del grupo perdido, que no se aplica). Es el equivalente "
        "RMAN de RECOVER DATABASE UNTIL CANCEL de SQL*Plus: RMAN no admite UNTIL CANCEL.",
        "Restaurar la base completa y aplicar los archived logs hasta la secuencia anterior.",
        PASO_RESPALDO_NUEVO + " RESETLOGS vuelve a crear los redo logs online perdidos.",
    ],
    Escenario.CORRUPCION_BLOQUE: [
        "El datafile sigue en línea: solo se reparan los bloques dañados (block media recovery).",
        "Con una lista de bloques, validar la base (VALIDATE DATABASE) para refrescar V$DATABASE_BLOCK_CORRUPTION y "
        "recuperar todos los bloques de la lista (RECOVER CORRUPTION LIST); con un bloque indicado, recuperarlo "
        "(RECOVER DATAFILE n BLOCK b).",
        "RMAN toma la copia del bloque del respaldo y le aplica el redo hasta dejarlo al día.",
        "Validar de nuevo (VALIDATE DATABASE, o VALIDATE DATAFILE n si se indicó el bloque) y volver a "
        "diagnosticar: la vista V$DATABASE_BLOCK_CORRUPTION debe quedar vacía.",
    ],
    Escenario.SPFILE: [
        "Arrancar la instancia en NOMOUNT: sin SPFILE, RMAN la levanta con un archivo de parámetros mínimo.",
        "Indicar el DBID y restaurar el SPFILE desde la pieza de autobackup (va junto con el control file).",
        "Reiniciar la instancia (STARTUP FORCE NOMOUNT) para que lea el SPFILE restaurado.",
        "Montar y abrir la base: los datafiles y el control file no se tocaron, no hay que recuperar nada.",
    ],
    Escenario.TOTAL_NOARCHIVELOG: [
        "Reiniciar la instancia y montarla (STARTUP FORCE MOUNT, que sirve también si ya estaba caída).",
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
PASOS_TOTAL_SIN_CONTROLFILE = [
    "Se perdió también el control file: la instancia no monta (ORA-00205). " + PASO_CONTROLFILE_DESDE_AUTOBACKUP,
    PASO_RESTAURAR_CONTROLFILE + " Luego montar la base.",
    "Restaurar la base completa desde el último respaldo consistente (en frío).",
    "RECOVER DATABASE NOREDO: en NOARCHIVELOG no hay redo que aplicar; se pierden los cambios posteriores al respaldo.",
    "Abrir con RESETLOGS y hacer un respaldo nuevo.",
]
AVISO_GRUPO_ACTUAL_SIN_LIMPIAR = (
    "Antes de aprobar, el DBA puede intentar ALTER DATABASE CLEAR UNARCHIVED LOGFILE GROUP {grupo}; con un grupo "
    "CURRENT perdido normalmente falla con ORA-01624 y entonces este procedimiento es el camino. CloudCR no lo "
    "incluye en el script porque un error detendría RMAN."
)
AVISO_GRUPO_ACTUAL_RENOMBRAR = (
    "Si el disco de los redo ya no existe, cambie sus rutas con ALTER DATABASE RENAME FILE (con la base montada) "
    "antes de ejecutar este procedimiento, porque abre con RESETLOGS."
)
AVISO_MIEMBRO_SIN_ARCHIVAR = (
    "Con la base en ARCHIVELOG, Oracle exige que el grupo ya esté archivado (ARCHIVED = YES en V$LOG) para quitar un "
    "miembro. El cambio de log y el checkpoint del script dejan el grupo INACTIVE, pero si RMAN se detiene en el "
    "DROP porque el grupo aún no se archivó, espere a que se archive y genere un procedimiento nuevo."
)


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
    criticos: frozenset[int] = frozenset()
    tablespaces_criticos: frozenset[str] = frozenset()
    bloques: list[BloqueCorrupto] = field(default_factory=list)
    miembros_redo: list[MiembroRedoDanado] = field(default_factory=list)
    redo_actual: GrupoRedoActual | None = None
    grupos_redo: list[GrupoRedo] = field(default_factory=list)
    estado_pdbs: dict[str, str] = field(default_factory=dict)
    sin_conexion: bool = False


@dataclass(frozen=True)
class Objetivo:
    variables: dict[str, object]
    descripcion: str | None = None
    avisos: list[str] = field(default_factory=list)


def _imposible(solicitud: SolicitudProcedimiento, motivo: str, objetivo: str | None = None) -> Procedimiento:
    return Procedimiento(
        bd=solicitud.bd, escenario=solicitud.escenario, posible=False, motivo=motivo, objetivo=objetivo
    )


def _nombre_valido(texto: str) -> bool:
    return all(PATRON_NOMBRE.match(parte) for parte in texto.split(":")) and texto.count(":") <= 1


def _ruta_valida(ruta: str) -> bool:
    return 0 < len(ruta) <= LARGO_MAXIMO_RUTA and not any(c in CARACTERES_PROHIBIDOS_RUTA for c in ruta)


def _es_critico(solicitud: SolicitudProcedimiento, numero: int, archivo: ArchivoDanado | None) -> bool:
    return numero in solicitud.criticos or (archivo is not None and archivo.critico)


def _pdb_abierta(solicitud: SolicitudProcedimiento, pdb: str) -> bool:
    modos = {nombre.upper(): modo.upper() for nombre, modo in solicitud.estado_pdbs.items()}
    return modos.get(pdb.upper()) != MODO_PDB_CERRADA


def _avisos_de_pdb(pdb: str | None, abierta: bool, con_paso_en_linea: bool) -> list[str]:
    avisos: list[str] = []
    if pdb is None:
        return avisos
    if con_paso_en_linea:
        avisos.append(AVISO_EN_LINEA_PDB)
    if not abierta:
        avisos.append(
            f"La PDB {pdb} ya está cerrada (MOUNTED), como queda al perder su SYSTEM o su UNDO: el script no la cierra "
            "de nuevo; restaura, recupera y abre la PDB."
        )
    return avisos


def _numero_datafile(solicitud: SolicitudProcedimiento) -> int | str:
    try:
        return int(solicitud.objetivo or "")
    except ValueError:
        return f"El datafile debe indicarse por su número (file#), no {solicitud.objetivo!r}."


def _objetivo_datafile(solicitud: SolicitudProcedimiento) -> Objetivo | str:
    if solicitud.objetivo:
        numero = _numero_datafile(solicitud)
        if isinstance(numero, str):
            return numero
        archivo = next((a for a in solicitud.danados if a.file_id == numero), None)
        contenedor = solicitud.contenedor_de_datafile.get(numero)
        pdb = archivo.pdb if archivo else (contenedor if contenedor not in (None, RAIZ) else None)
        descripcion = str(numero)
    else:
        if not solicitud.danados:
            return "El diagnóstico no encontró archivos dañados en V$RECOVER_FILE; indique el datafile con --objetivo."
        archivo = solicitud.danados[0]
        numero, pdb, descripcion = archivo.file_id, archivo.pdb, f"{archivo.file_id} ({archivo.ruta})"
    if pdb is None and _es_critico(solicitud, numero, archivo):
        return (
            f"El datafile {numero} pertenece a SYSTEM o UNDO del contenedor raíz: Oracle no permite dejarlo OFFLINE "
            "con la base abierta. Use el escenario datafile-critico, que lo recupera con la base montada. El SYSTEM y "
            "el UNDO de una PDB, en cambio, se recuperan con este escenario y la PDB cerrada."
        )
    abierta = _pdb_abierta(solicitud, pdb) if pdb else True
    variables: dict[str, object] = {"datafile": numero, "pdb": pdb, "pdb_abierta": abierta}
    return Objetivo(variables, descripcion, _avisos_de_pdb(pdb, abierta, con_paso_en_linea=True))


def _objetivo_datafile_critico(solicitud: SolicitudProcedimiento) -> Objetivo | str:
    if solicitud.objetivo:
        numero = _numero_datafile(solicitud)
        if isinstance(numero, str):
            return numero
        archivo = next((a for a in solicitud.danados if a.file_id == numero), None)
        descripcion = str(numero)
    else:
        if not solicitud.danados:
            return "El diagnóstico no encontró archivos dañados en V$RECOVER_FILE; indique el datafile con --objetivo."
        archivo = next((a for a in solicitud.danados if _es_critico(solicitud, a.file_id, a)), solicitud.danados[0])
        numero, descripcion = archivo.file_id, f"{archivo.file_id} ({archivo.ruta})"
    avisos = []
    if not _es_critico(solicitud, numero, archivo):
        avisos.append(
            f"El datafile {numero} no figura como SYSTEM o UNDO del contenedor raíz: el escenario datafile lo "
            "recupera sin detener la instancia, que es menos invasivo."
        )
    return Objetivo({"datafile": numero}, descripcion, avisos)


def _objetivo_tablespace(solicitud: SolicitudProcedimiento) -> Objetivo | str:
    identificador = solicitud.objetivo.strip().upper() if solicitud.objetivo else None
    if identificador is None:
        candidato = next((a.identificador_tablespace for a in solicitud.danados if a.tablespace), None)
        if candidato is None:
            return "El diagnóstico no encontró tablespaces dañados; indique el tablespace con --objetivo (PDB:TS)."
        identificador = candidato.upper()
    if not _nombre_valido(identificador):
        return f"El tablespace {identificador!r} no es un identificador válido."
    pdb = identificador.split(":", 1)[0] if ":" in identificador else None
    if pdb is None and (tablespace_critico(identificador) or identificador in solicitud.tablespaces_criticos):
        return (
            f"El tablespace {identificador} es SYSTEM o UNDO del contenedor raíz: Oracle no permite dejarlo OFFLINE "
            "con la base abierta. Use el escenario datafile-critico con el número de su datafile dañado."
        )
    abierta = _pdb_abierta(solicitud, pdb) if pdb else True
    variables: dict[str, object] = {"tablespace": identificador, "pdb": pdb, "pdb_abierta": abierta}
    return Objetivo(variables, identificador, _avisos_de_pdb(pdb, abierta, con_paso_en_linea=True))


def _objetivo_pdb(solicitud: SolicitudProcedimiento) -> Objetivo | str:
    pdb = solicitud.objetivo.strip().upper() if solicitud.objetivo else None
    if pdb is None:
        pdb = next((a.pdb.upper() for a in solicitud.danados if a.pdb), None)
        if pdb is None:
            return "El diagnóstico no encontró una PDB con archivos dañados; indique la PDB con --objetivo."
    if not _nombre_valido(pdb) or ":" in pdb:
        return f"La PDB {pdb!r} no es un nombre válido."
    abierta = _pdb_abierta(solicitud, pdb)
    return Objetivo({"pdb": pdb, "pdb_abierta": abierta}, pdb, _avisos_de_pdb(pdb, abierta, con_paso_en_linea=False))


def _objetivo_autobackup(solicitud: SolicitudProcedimiento) -> Objetivo | str:
    que = "el SPFILE" if solicitud.escenario is Escenario.SPFILE else "el control file"
    if solicitud.dbid is None:
        return f"Se necesita el DBID de la base para restaurar {que}."
    if solicitud.destino_autobackup is None and solicitud.pieza_controlfile is None:
        return "No hay pieza de control file registrada ni destino de autobackup conocido."
    formato = nombres.formato_autobackup(solicitud.destino_autobackup or "")
    return Objetivo({"dbid": solicitud.dbid, "pieza": solicitud.pieza_controlfile, "formato_autobackup": formato})


def _miembro_indicado(solicitud: SolicitudProcedimiento, texto: str) -> MiembroRedoDanado | str:
    coincidencia = PATRON_GRUPO_Y_RUTA.match(texto)
    grupo = int(coincidencia.group(1)) if coincidencia else None
    ruta = (coincidencia.group(2) if coincidencia else texto).strip()
    if not _ruta_valida(ruta):
        return (
            f"La ruta del miembro {ruta!r} no es válida: sin comillas ni punto y coma, hasta {LARGO_MAXIMO_RUTA} "
            "caracteres."
        )
    conocido = next((m for m in solicitud.miembros_redo if m.miembro.upper() == ruta.upper()), None)
    if conocido is not None and (grupo is None or grupo == conocido.grupo):
        return conocido
    if grupo is None:
        return (
            f"El diagnóstico no informa el miembro {ruta!r} como dañado ni ausente; indíquelo como "
            "GRUPO:RUTA, por ejemplo 2:C:\\ORADATA\\XE\\REDO02B.LOG."
        )
    del_grupo = next((g for g in solicitud.grupos_redo if g.grupo == grupo), None)
    if del_grupo is None:
        return MiembroRedoDanado(grupo=grupo, miembro=ruta, estado_miembro="INVALID", estado_grupo="DESCONOCIDO")
    return MiembroRedoDanado(
        grupo=grupo,
        miembro=ruta,
        estado_miembro="INVALID",
        estado_grupo=del_grupo.estado,
        hilo=del_grupo.hilo,
        secuencia=del_grupo.secuencia,
    )


def _objetivo_miembro_redolog(solicitud: SolicitudProcedimiento) -> Objetivo | str:
    if solicitud.objetivo:
        elegido = _miembro_indicado(solicitud, solicitud.objetivo.strip())
        if isinstance(elegido, str):
            return elegido
    else:
        if not solicitud.miembros_redo:
            return (
                "El diagnóstico no encontró miembros de redo log dañados ni ausentes en V$LOGFILE; indique el miembro "
                "con --objetivo (GRUPO:RUTA)."
            )
        elegido = next((m for m in solicitud.miembros_redo if not m.grupo_perdido), solicitud.miembros_redo[0])
    if elegido.grupo_perdido:
        return (
            f"Todos los miembros del grupo {elegido.grupo} están dañados: no queda una copia válida de la que seguir "
            "escribiendo. Si es el grupo CURRENT use el escenario grupo-redolog-actual."
        )
    avisos = []
    if elegido.estado_grupo == "DESCONOCIDO":
        avisos.append(
            f"No se sabe si el grupo {elegido.grupo} es el CURRENT. Si lo es, RMAN se detendrá con ORA-01609: "
            "diagnostique de nuevo para que el script incluya el cambio de log."
        )
    estado = elegido.estado_grupo.upper()
    if solicitud.log_mode is LogMode.ARCHIVELOG and estado in ESTADOS_REDO_SIN_ARCHIVAR:
        avisos.append(AVISO_MIEMBRO_SIN_ARCHIVAR)
    variables: dict[str, object] = {
        "grupo": elegido.grupo,
        "miembro": elegido.miembro,
        "cambiar_log": elegido.actual,
        "punto_de_control": estado not in ESTADOS_REDO_SIN_CHECKPOINT,
    }
    return Objetivo(variables, f"grupo {elegido.grupo}: {elegido.miembro}", avisos)


def _objetivo_grupo_redolog_actual(solicitud: SolicitudProcedimiento) -> Objetivo | str:
    texto = (solicitud.objetivo or "").strip()
    avisos = []
    grupo: int | None = None
    if texto:
        par = PATRON_PAR_NUMEROS.match(texto)
        if par:
            hilo, secuencia = int(par.group(1)), int(par.group(2))
        elif texto.isdigit():
            hilo, secuencia = 1, int(texto)
        else:
            return f"Indique la secuencia (SEQUENCE#) del grupo perdido como número o HILO:SECUENCIA, no {texto!r}."
        grupo = next((g.grupo for g in solicitud.grupos_redo if g.hilo == hilo and g.secuencia == secuencia), None)
    else:
        perdido = next((m for m in solicitud.miembros_redo if m.grupo_perdido and m.actual), None)
        if perdido is not None and perdido.secuencia is not None:
            hilo, secuencia, grupo = perdido.hilo, perdido.secuencia, perdido.grupo
        elif solicitud.redo_actual is not None:
            actual = solicitud.redo_actual
            hilo, secuencia, grupo = actual.hilo, actual.secuencia, actual.grupo
            avisos.append(
                f"El diagnóstico no marca el grupo {actual.grupo} como perdido; se usa su secuencia porque "
                "es el grupo CURRENT según V$LOG. Confirme que es el grupo que se perdió."
            )
        else:
            return (
                "El diagnóstico no pudo leer V$LOG; indique la secuencia del grupo CURRENT perdido con --objetivo "
                "(SEQUENCE#, o HILO:SECUENCIA)."
            )
    if secuencia < 1 or hilo < 1:
        return "La secuencia y el hilo deben ser mayores que cero."
    descripcion = f"hasta la secuencia {secuencia} (hilo {hilo}), sin aplicarla"
    avisos.append(AVISO_GRUPO_ACTUAL_SIN_LIMPIAR.format(grupo=grupo if grupo is not None else "<número del grupo>"))
    avisos.append(AVISO_GRUPO_ACTUAL_RENOMBRAR)
    return Objetivo({"secuencia": secuencia, "hilo": hilo}, descripcion, avisos)


def _objetivo_corrupcion_bloque(solicitud: SolicitudProcedimiento) -> Objetivo | str:
    texto = (solicitud.objetivo or "").strip()
    if texto:
        par = PATRON_PAR_NUMEROS.match(texto)
        if par is None:
            return f"Indique el bloque como FILE#:BLOQUE, por ejemplo 7:131, no {texto!r}."
        datafile, bloque = int(par.group(1)), int(par.group(2))
        if datafile < 1 or bloque < 1:
            return "El número de datafile y de bloque deben ser mayores que cero."
        return Objetivo({"datafile": datafile, "bloque": bloque}, f"datafile {datafile}, bloque {bloque}")
    if not solicitud.bloques:
        return (
            "El diagnóstico no encontró bloques en V$DATABASE_BLOCK_CORRUPTION; indique FILE#:BLOQUE con --objetivo "
            "(la vista se llena al leer el bloque dañado o con VALIDATE DATABASE)."
        )
    total = sum(b.bloques for b in solicitud.bloques)
    return Objetivo({"datafile": None, "bloque": None}, f"{total} bloques en V$DATABASE_BLOCK_CORRUPTION")


def _objetivo_total_noarchivelog(solicitud: SolicitudProcedimiento) -> Objetivo | str:
    texto = (solicitud.objetivo or "").strip().lower()
    if texto and texto != OBJETIVO_SIN_CONTROLFILE:
        return (
            f"El escenario total-noarchivelog solo admite {OBJETIVO_SIN_CONTROLFILE!r} como objetivo (para incluir "
            f"también la restauración del control file), no {texto!r}."
        )
    if not (solicitud.sin_conexion or texto == OBJETIVO_SIN_CONTROLFILE):
        return Objetivo({"sin_controlfile": False})
    autobackup = _objetivo_autobackup(solicitud)
    if isinstance(autobackup, str):
        return "Esta variante de la pérdida total también restaura el control file. " + autobackup
    descripcion = "incluye la restauración del control file"
    return Objetivo({**autobackup.variables, "sin_controlfile": True}, descripcion)


def _contexto(solicitud: SolicitudProcedimiento) -> Objetivo | str:
    escenario = solicitud.escenario
    if escenario is Escenario.DATAFILE:
        return _objetivo_datafile(solicitud)
    if escenario is Escenario.DATAFILE_CRITICO:
        return _objetivo_datafile_critico(solicitud)
    if escenario is Escenario.TABLESPACE:
        return _objetivo_tablespace(solicitud)
    if escenario is Escenario.PDB:
        return _objetivo_pdb(solicitud)
    if escenario in REQUIEREN_AUTOBACKUP:
        return _objetivo_autobackup(solicitud)
    if escenario is Escenario.MIEMBRO_REDOLOG:
        return _objetivo_miembro_redolog(solicitud)
    if escenario is Escenario.GRUPO_REDOLOG_ACTUAL:
        return _objetivo_grupo_redolog_actual(solicitud)
    if escenario is Escenario.CORRUPCION_BLOQUE:
        return _objetivo_corrupcion_bloque(solicitud)
    if escenario is Escenario.TOTAL_NOARCHIVELOG:
        return _objetivo_total_noarchivelog(solicitud)
    if escenario is Escenario.PUNTO_EN_TIEMPO:
        if solicitud.hasta is None:
            return "Indique el momento objetivo con --hasta 'AAAA-MM-DD HH:MM'."
        texto = solicitud.hasta.strftime(FORMATO_HASTA)
        return Objetivo({"hasta": texto}, texto)
    return Objetivo({})


def _pasos_del_escenario(escenario: Escenario, variables: dict[str, object]) -> list[str]:
    if escenario is Escenario.TOTAL_NOARCHIVELOG and variables.get("sin_controlfile"):
        return PASOS_TOTAL_SIN_CONTROLFILE
    return PASOS_ESCENARIO[escenario]


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
    try:
        script = renderizar(PLANTILLAS[escenario], **contexto.variables)
    except ScriptNoAscii as error:
        return _imposible(solicitud, str(error), contexto.descripcion)
    avisos = list(contexto.avisos)
    if not solicitud.hay_respaldo and escenario is not Escenario.MIEMBRO_REDOLOG:
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
        objetivo=contexto.descripcion,
        pasos=[PASO_DIAGNOSTICO, *_pasos_del_escenario(escenario, contexto.variables), PASO_REVISAR, PASO_EJECUTAR],
        script=script,
        avisos=avisos,
    )
