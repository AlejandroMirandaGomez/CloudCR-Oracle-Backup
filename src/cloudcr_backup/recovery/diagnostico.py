from typing import Any

from cloudcr_backup.domain.enums import LogMode
from cloudcr_backup.domain.recuperacion import (
    ArchivoDanado,
    BloqueCorrupto,
    Diagnostico,
    Escenario,
    GrupoRedoActual,
    MiembroRedoDanado,
)
from cloudcr_backup.execution.correlator import Consulta

ORIGEN_RECOVER_FILE = "V$RECOVER_FILE"
ORIGEN_DATAFILE = "V$DATAFILE"
ESTADOS_MIEMBRO_DANADO = frozenset({"INVALID"})

SQL_RECOVER_FILE = """
    SELECT rf.file#, df.name, ts.name, ct.name, rf.online_status, rf.error, rf.change#
    FROM v$recover_file rf
    JOIN v$datafile df ON df.file# = rf.file#
    LEFT JOIN v$tablespace ts ON ts.ts# = df.ts# AND ts.con_id = df.con_id
    LEFT JOIN v$containers ct ON ct.con_id = df.con_id
    ORDER BY rf.file#
"""

SQL_DATAFILES_NO_DISPONIBLES = """
    SELECT df.file#, df.name, ts.name, ct.name, df.status
    FROM v$datafile df
    LEFT JOIN v$tablespace ts ON ts.ts# = df.ts# AND ts.con_id = df.con_id
    LEFT JOIN v$containers ct ON ct.con_id = df.con_id
    WHERE df.status NOT IN ('ONLINE', 'SYSTEM')
    ORDER BY df.file#
"""

SQL_BLOQUES_CORRUPTOS = """
    SELECT bc.file#, bc.block#, bc.blocks, bc.corruption_type, df.name, ts.name, ct.name
    FROM v$database_block_corruption bc
    LEFT JOIN v$datafile df ON df.file# = bc.file#
    LEFT JOIN v$tablespace ts ON ts.ts# = df.ts# AND ts.con_id = df.con_id
    LEFT JOIN v$containers ct ON ct.con_id = df.con_id
    ORDER BY bc.file#, bc.block#
"""

SQL_MIEMBROS_REDO = """
    SELECT lf.group#, lf.member, lf.status, lg.status, lg.thread#, lg.sequence#
    FROM v$logfile lf
    JOIN v$log lg ON lg.group# = lf.group#
    ORDER BY lf.group#, lf.member
"""


def _texto(valor: Any) -> str | None:
    if valor is None:
        return None
    texto = str(valor).strip()
    return texto or None


def archivos_danados(consulta: Consulta) -> list[ArchivoDanado]:
    archivos: dict[int, ArchivoDanado] = {}
    for file_id, ruta, tablespace, contenedor, estado, error, cambio in consulta(SQL_RECOVER_FILE, {}):
        archivos[int(file_id)] = ArchivoDanado(
            file_id=int(file_id),
            ruta=str(ruta),
            tablespace=_texto(tablespace),
            contenedor=_texto(contenedor),
            estado=str(estado),
            error=_texto(error),
            cambio=None if cambio is None else int(cambio),
            origen=ORIGEN_RECOVER_FILE,
        )
    for file_id, ruta, tablespace, contenedor, estado in consulta(SQL_DATAFILES_NO_DISPONIBLES, {}):
        if int(file_id) in archivos:
            continue
        archivos[int(file_id)] = ArchivoDanado(
            file_id=int(file_id),
            ruta=str(ruta),
            tablespace=_texto(tablespace),
            contenedor=_texto(contenedor),
            estado=str(estado),
            origen=ORIGEN_DATAFILE,
        )
    return [archivos[clave] for clave in sorted(archivos)]


def bloques_corruptos(consulta: Consulta) -> list[BloqueCorrupto]:
    return [
        BloqueCorrupto(
            file_id=int(file_id),
            bloque=int(bloque),
            bloques=int(bloques or 1),
            tipo=_texto(tipo),
            ruta=_texto(ruta),
            tablespace=_texto(tablespace),
            contenedor=_texto(contenedor),
        )
        for file_id, bloque, bloques, tipo, ruta, tablespace, contenedor in consulta(SQL_BLOQUES_CORRUPTOS, {})
    ]


def redo_logs(consulta: Consulta) -> tuple[list[MiembroRedoDanado], GrupoRedoActual | None]:
    por_grupo: dict[int, list[MiembroRedoDanado]] = {}
    for grupo, miembro, estado_miembro, estado_grupo, hilo, secuencia in consulta(SQL_MIEMBROS_REDO, {}):
        por_grupo.setdefault(int(grupo), []).append(
            MiembroRedoDanado(
                grupo=int(grupo),
                miembro=str(miembro),
                estado_miembro=(_texto(estado_miembro) or "").upper(),
                estado_grupo=(_texto(estado_grupo) or "").upper(),
                hilo=int(hilo or 1),
                secuencia=None if secuencia is None else int(secuencia),
            )
        )
    danados = []
    actual = None
    for miembros in por_grupo.values():
        invalidos = [m for m in miembros if m.estado_miembro in ESTADOS_MIEMBRO_DANADO]
        perdido = len(invalidos) == len(miembros)
        danados += [m.model_copy(update={"grupo_perdido": perdido}) for m in invalidos]
        primero = miembros[0]
        if actual is None and primero.actual and primero.secuencia is not None:
            actual = GrupoRedoActual(grupo=primero.grupo, hilo=primero.hilo, secuencia=primero.secuencia)
    return danados, actual


def sugerir(diagnostico: Diagnostico) -> list[Escenario]:
    if diagnostico.sin_conexion:
        return [Escenario.CONTROLFILE, Escenario.SPFILE]
    sugeridos: list[Escenario] = []
    if any(a.critico for a in diagnostico.archivos):
        sugeridos.append(Escenario.DATAFILE_CRITICO)
    if any(not a.critico for a in diagnostico.archivos):
        sugeridos.append(Escenario.DATAFILE)
    if any(m.grupo_perdido and m.actual for m in diagnostico.miembros_redo):
        sugeridos.append(Escenario.GRUPO_REDOLOG_ACTUAL)
    if any(not m.grupo_perdido for m in diagnostico.miembros_redo):
        sugeridos.append(Escenario.MIEMBRO_REDOLOG)
    if diagnostico.bloques:
        sugeridos.append(Escenario.CORRUPCION_BLOQUE)
    restauran = {Escenario.DATAFILE_CRITICO, Escenario.DATAFILE, Escenario.GRUPO_REDOLOG_ACTUAL}
    if diagnostico.log_mode is LogMode.NOARCHIVELOG and restauran.intersection(sugeridos):
        sugeridos = [e for e in sugeridos if e not in restauran] + [Escenario.TOTAL_NOARCHIVELOG]
    return sugeridos


def resumen(diagnostico: Diagnostico) -> str:
    if diagnostico.sin_conexion:
        return "No se pudo consultar la instancia (caída, sin control file o sin SPFILE)."
    partes = []
    if diagnostico.archivos:
        archivos = ", ".join(f"{a.file_id} ({a.identificador_tablespace or a.ruta})" for a in diagnostico.archivos)
        partes.append(f"datafiles dañados: {archivos}")
    if diagnostico.bloques:
        partes.append(f"{sum(b.bloques for b in diagnostico.bloques)} bloques corruptos")
    if diagnostico.miembros_redo:
        miembros = ", ".join(f"grupo {m.grupo} ({m.miembro})" for m in diagnostico.miembros_redo)
        partes.append(f"redo logs inválidos: {miembros}")
    if not partes:
        return "Sin daños."
    texto = "; ".join(partes)
    return texto[0].upper() + texto[1:] + "."
