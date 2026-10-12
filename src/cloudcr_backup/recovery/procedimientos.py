import re
from dataclasses import dataclass, field
from datetime import datetime

from cloudcr_backup.domain.enums import LogMode
from cloudcr_backup.domain.recuperacion import (
    ArchivoDanado,
    BloqueCorrupto,
    Escenario,
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
AVISO_EN_LINEA_PDB = (
    "RMAN no puede cambiar de contenedor, así que el script no pone el tablespace en línea: si había quedado "
    "OFFLINE, CloudCR lo hace al terminar la ejecución. Si aplica el script a mano, ejecute "
    "'ALTER TABLESPACE <nombre> ONLINE;' dentro de la PDB."
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
    Escenario.DATAFILE_CRITICO: [
        "Un datafile de SYSTEM o UNDO del contenedor raíz no se puede dejar OFFLINE con la base abierta: hay que "
        "detener la instancia (STARTUP FORCE MOUNT la reinicia y la deja montada).",
        "Restaurar el datafile por su número (file#) y recuperarlo con la base montada.",
        PASO_REDO,
        "Abrir la base (ALTER DATABASE OPEN). No hace falta RESETLOGS: la recuperación es completa.",
    ],
    Escenario.CONTROLFILE: [
        "Arrancar la instancia sin montar (NOMOUNT) e indicar el DBID de la base.",
        "Restaurar el control file desde la pieza respaldada por la estrategia o desde el autobackup.",
        "Montar la base y recuperarla con los archived y online redo logs disponibles.",
        PASO_RESPALDO_NUEVO,
    ],
    Escenario.MIEMBRO_REDOLOG: [
        "El grupo sigue funcionando con su otro miembro (multiplexación): la base no se cae y no hay que "
        "restaurar ni recuperar nada.",
        "Si el grupo es el CURRENT, cambiar de log (SWITCH LOGFILE); luego un CHECKPOINT deja el grupo INACTIVE.",
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
        "Recuperar el bloque indicado (RECOVER DATAFILE n BLOCK b) o todos los de V$DATABASE_BLOCK_CORRUPTION "
        "(RECOVER CORRUPTION LIST).",
        "RMAN toma la copia del bloque del respaldo y le aplica el redo hasta dejarlo al día.",
        "Volver a diagnosticar: la vista V$DATABASE_BLOCK_CORRUPTION debe quedar vacía.",
    ],
    Escenario.SPFILE: [
        "Arrancar la instancia en NOMOUNT: sin SPFILE, RMAN la levanta con un archivo de parámetros mínimo.",
        "Indicar el DBID y restaurar el SPFILE desde la pieza de autobackup (va junto con el control file).",
        "Reiniciar la instancia (STARTUP FORCE NOMOUNT) para que lea el SPFILE restaurado.",
        "Montar y abrir la base: los datafiles y el control file no se tocaron, no hay que recuperar nada.",
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
    criticos: frozenset[int] = frozenset()
    tablespaces_criticos: frozenset[str] = frozenset()
    bloques: list[BloqueCorrupto] = field(default_factory=list)
    miembros_redo: list[MiembroRedoDanado] = field(default_factory=list)
    redo_actual: GrupoRedoActual | None = None


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
            "con la base abierta. Use el escenario datafile-critico, que lo recupera con la base montada."
        )
    return Objetivo({"datafile": numero, "pdb": pdb}, descripcion, [AVISO_EN_LINEA_PDB] if pdb else [])


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
    return Objetivo({"tablespace": identificador, "pdb": pdb}, identificador, [AVISO_EN_LINEA_PDB] if pdb else [])


def _objetivo_pdb(solicitud: SolicitudProcedimiento) -> Objetivo | str:
    pdb = solicitud.objetivo.strip().upper() if solicitud.objetivo else None
    if pdb is None:
        pdb = next((a.pdb.upper() for a in solicitud.danados if a.pdb), None)
        if pdb is None:
            return "El diagnóstico no encontró una PDB con archivos dañados; indique la PDB con --objetivo."
    if not _nombre_valido(pdb) or ":" in pdb:
        return f"La PDB {pdb!r} no es un nombre válido."
    return Objetivo({"pdb": pdb}, pdb)


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
            f"El diagnóstico no informa el miembro {ruta!r} como INVALID en V$LOGFILE; indíquelo como "
            "GRUPO:RUTA, por ejemplo 2:C:\\ORADATA\\XE\\REDO02B.LOG."
        )
    return MiembroRedoDanado(grupo=grupo, miembro=ruta, estado_miembro="INVALID", estado_grupo="DESCONOCIDO")


def _objetivo_miembro_redolog(solicitud: SolicitudProcedimiento) -> Objetivo | str:
    if solicitud.objetivo:
        elegido = _miembro_indicado(solicitud, solicitud.objetivo.strip())
        if isinstance(elegido, str):
            return elegido
    else:
        if not solicitud.miembros_redo:
            return (
                "El diagnóstico no encontró miembros de redo log inválidos en V$LOGFILE; indique el miembro con "
                "--objetivo (GRUPO:RUTA)."
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
    variables: dict[str, object] = {"grupo": elegido.grupo, "miembro": elegido.miembro, "actual": elegido.actual}
    return Objetivo(variables, f"grupo {elegido.grupo}: {elegido.miembro}", avisos)


def _objetivo_grupo_redolog_actual(solicitud: SolicitudProcedimiento) -> Objetivo | str:
    texto = (solicitud.objetivo or "").strip()
    avisos = []
    if texto:
        par = PATRON_PAR_NUMEROS.match(texto)
        if par:
            hilo, secuencia = int(par.group(1)), int(par.group(2))
        elif texto.isdigit():
            hilo, secuencia = 1, int(texto)
        else:
            return f"Indique la secuencia (SEQUENCE#) del grupo perdido como número o HILO:SECUENCIA, no {texto!r}."
    else:
        perdido = next((m for m in solicitud.miembros_redo if m.grupo_perdido and m.actual), None)
        if perdido is not None and perdido.secuencia is not None:
            hilo, secuencia = perdido.hilo, perdido.secuencia
        elif solicitud.redo_actual is not None:
            hilo, secuencia = solicitud.redo_actual.hilo, solicitud.redo_actual.secuencia
            avisos.append(
                f"V$LOGFILE no marca el grupo {solicitud.redo_actual.grupo} como perdido; se usa su secuencia porque "
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
    if escenario is Escenario.PUNTO_EN_TIEMPO:
        if solicitud.hasta is None:
            return "Indique el momento objetivo con --hasta 'AAAA-MM-DD HH:MM'."
        texto = solicitud.hasta.strftime(FORMATO_HASTA)
        return Objetivo({"hasta": texto}, texto)
    return Objetivo({})


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
        pasos=[PASO_DIAGNOSTICO, *PASOS_ESCENARIO[escenario], PASO_REVISAR, PASO_EJECUTAR],
        script=script,
        avisos=avisos,
    )
