import os
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from cloudcr_backup.domain.enums import LogMode
from cloudcr_backup.domain.recuperacion import (
    ArchivoDanado,
    BloqueCorrupto,
    Diagnostico,
    Escenario,
    EstadoPdb,
    GrupoRedo,
    GrupoRedoActual,
    MiembroRedoDanado,
)
from cloudcr_backup.execution.correlator import Consulta

ORIGEN_RECOVER_FILE = "V$RECOVER_FILE"
ORIGEN_DATAFILE = "V$DATAFILE"
ESTADO_MIEMBRO_FALTANTE = "FALTANTE"
ESTADOS_MIEMBRO_DANADO = frozenset({"INVALID", ESTADO_MIEMBRO_FALTANTE})
CONTENEDOR_RAIZ = "CDB$ROOT"
CONEXIONES_DE_LA_RAIZ = (0, 1)
PREFIJO_RUTA_ASM = "+"
CODIGOS_INSTANCIA_NO_DISPONIBLE = ("ORA-01034", "ORA-01033", "ORA-12560", "ORA-27101", "ORA-01507")
POSICION_CONTENEDOR_ARCHIVOS = 3
POSICION_CONTENEDOR_BLOQUES = 6

SQL_PDBS = "SELECT con_id, name, open_mode FROM v$pdbs ORDER BY con_id"

SQL_RECOVER_FILE = """
    SELECT rf.file#, df.name, ts.name, ct.name, rf.online_status, rf.error, rf.change#
    FROM v$recover_file rf
    JOIN v$datafile df ON df.file# = rf.file#
    LEFT JOIN v$tablespace ts ON ts.ts# = df.ts# AND ts.con_id = df.con_id
    LEFT JOIN v$containers ct ON ct.con_id = df.con_id
    ORDER BY rf.file#
"""

SQL_RECOVER_FILE_SIN_CONTENEDORES = """
    SELECT rf.file#, df.name, ts.name, df.con_id, rf.online_status, rf.error, rf.change#
    FROM v$recover_file rf
    JOIN v$datafile df ON df.file# = rf.file#
    LEFT JOIN v$tablespace ts ON ts.ts# = df.ts# AND ts.con_id = df.con_id
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

SQL_DATAFILES_NO_DISPONIBLES_SIN_CONTENEDORES = """
    SELECT df.file#, df.name, ts.name, df.con_id, df.status
    FROM v$datafile df
    LEFT JOIN v$tablespace ts ON ts.ts# = df.ts# AND ts.con_id = df.con_id
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

SQL_BLOQUES_CORRUPTOS_SIN_CONTENEDORES = """
    SELECT bc.file#, bc.block#, bc.blocks, bc.corruption_type, df.name, ts.name, df.con_id
    FROM v$database_block_corruption bc
    LEFT JOIN v$datafile df ON df.file# = bc.file#
    LEFT JOIN v$tablespace ts ON ts.ts# = df.ts# AND ts.con_id = df.con_id
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


def archivo_existe(ruta: str) -> bool:
    if ruta.startswith(PREFIJO_RUTA_ASM):
        return True
    try:
        os.stat(ruta)
    except (FileNotFoundError, NotADirectoryError):
        return False
    except (OSError, ValueError):
        return True
    return True


def instancia_no_disponible(error: BaseException) -> bool:
    texto = str(error)
    return any(codigo in texto for codigo in CODIGOS_INSTANCIA_NO_DISPONIBLE)


def estado_pdbs(consulta: Consulta) -> list[EstadoPdb]:
    return [
        EstadoPdb(con_id=None if con_id is None else int(con_id), nombre=str(nombre), modo=(_texto(modo) or "").upper())
        for con_id, nombre, modo in consulta(SQL_PDBS, {})
    ]


def _nombre_de_contenedor(con_id: Any, nombres: Mapping[int, str], sin_resolver: set[int]) -> str | None:
    if con_id is None:
        return None
    numero = int(con_id)
    if numero in CONEXIONES_DE_LA_RAIZ:
        return CONTENEDOR_RAIZ
    nombre = nombres.get(numero)
    if nombre is None:
        sin_resolver.add(numero)
    return nombre


def _avisar(avisos: list[str] | None, aviso: str) -> None:
    if avisos is not None and aviso not in avisos:
        avisos.append(aviso)


def _filas_con_contenedor(
    consulta: Consulta,
    sql: str,
    sql_sin_contenedores: str,
    posicion: int,
    pdbs: Sequence[EstadoPdb],
    avisos: list[str] | None,
) -> list[tuple[Any, ...]]:
    try:
        return consulta(sql, {})
    except Exception as error:
        if instancia_no_disponible(error):
            raise
        motivo = f"{type(error).__name__}: {error}"
    nombres = {p.con_id: p.nombre for p in pdbs if p.con_id is not None}
    sin_resolver: set[int] = set()
    filas = [
        (*fila[:posicion], _nombre_de_contenedor(fila[posicion], nombres, sin_resolver), *fila[posicion + 1 :])
        for fila in consulta(sql_sin_contenedores, {})
    ]
    _avisar(avisos, f"V$CONTAINERS no respondió ({motivo}); se consultó sin ese JOIN.")
    if sin_resolver:
        numeros = ", ".join(str(n) for n in sorted(sin_resolver))
        _avisar(
            avisos,
            f"No se pudo determinar la PDB de los contenedores con CON_ID {numeros}: el contenedor de esos archivos "
            "queda vacío. Confirme a qué PDB pertenecen antes de aprobar un procedimiento.",
        )
    return filas


def archivos_danados(
    consulta: Consulta, pdbs: Sequence[EstadoPdb] = (), avisos: list[str] | None = None
) -> list[ArchivoDanado]:
    archivos: dict[int, ArchivoDanado] = {}
    filas_recover_file = _filas_con_contenedor(
        consulta, SQL_RECOVER_FILE, SQL_RECOVER_FILE_SIN_CONTENEDORES, POSICION_CONTENEDOR_ARCHIVOS, pdbs, avisos
    )
    for file_id, ruta, tablespace, contenedor, estado, error, cambio in filas_recover_file:
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
    filas_datafile = _filas_con_contenedor(
        consulta,
        SQL_DATAFILES_NO_DISPONIBLES,
        SQL_DATAFILES_NO_DISPONIBLES_SIN_CONTENEDORES,
        POSICION_CONTENEDOR_ARCHIVOS,
        pdbs,
        avisos,
    )
    for file_id, ruta, tablespace, contenedor, estado in filas_datafile:
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


def bloques_corruptos(
    consulta: Consulta, pdbs: Sequence[EstadoPdb] = (), avisos: list[str] | None = None
) -> list[BloqueCorrupto]:
    filas = _filas_con_contenedor(
        consulta,
        SQL_BLOQUES_CORRUPTOS,
        SQL_BLOQUES_CORRUPTOS_SIN_CONTENEDORES,
        POSICION_CONTENEDOR_BLOQUES,
        pdbs,
        avisos,
    )
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
        for file_id, bloque, bloques, tipo, ruta, tablespace, contenedor in filas
    ]


def _estado_del_miembro(estado: Any, ruta: str, existe: Callable[[str], bool]) -> str:
    texto = (_texto(estado) or "").upper()
    if texto in ESTADOS_MIEMBRO_DANADO or existe(ruta):
        return texto
    return ESTADO_MIEMBRO_FALTANTE


def redo_logs(
    consulta: Consulta, existe: Callable[[str], bool]
) -> tuple[list[MiembroRedoDanado], GrupoRedoActual | None, list[GrupoRedo]]:
    por_grupo: dict[int, list[MiembroRedoDanado]] = {}
    for grupo, miembro, estado_miembro, estado_grupo, hilo, secuencia in consulta(SQL_MIEMBROS_REDO, {}):
        ruta = str(miembro)
        por_grupo.setdefault(int(grupo), []).append(
            MiembroRedoDanado(
                grupo=int(grupo),
                miembro=ruta,
                estado_miembro=_estado_del_miembro(estado_miembro, ruta, existe),
                estado_grupo=(_texto(estado_grupo) or "").upper(),
                hilo=int(hilo or 1),
                secuencia=None if secuencia is None else int(secuencia),
            )
        )
    danados = []
    actual = None
    grupos = []
    for miembros in por_grupo.values():
        invalidos = [m for m in miembros if m.estado_miembro in ESTADOS_MIEMBRO_DANADO]
        perdido = len(invalidos) == len(miembros)
        danados += [m.model_copy(update={"grupo_perdido": perdido}) for m in invalidos]
        primero = miembros[0]
        grupos.append(
            GrupoRedo(grupo=primero.grupo, estado=primero.estado_grupo, hilo=primero.hilo, secuencia=primero.secuencia)
        )
        if actual is None and primero.actual and primero.secuencia is not None:
            actual = GrupoRedoActual(grupo=primero.grupo, hilo=primero.hilo, secuencia=primero.secuencia)
    return danados, actual, grupos


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
    if diagnostico.fallo_consulta:
        return "La instancia responde, pero no se pudo completar el diagnóstico."
    partes = []
    if diagnostico.archivos:
        archivos = ", ".join(f"{a.file_id} ({a.identificador_tablespace or a.ruta})" for a in diagnostico.archivos)
        partes.append(f"datafiles dañados: {archivos}")
    if diagnostico.bloques:
        partes.append(f"{sum(b.bloques for b in diagnostico.bloques)} bloques corruptos")
    if diagnostico.miembros_redo:
        miembros = ", ".join(f"grupo {m.grupo} ({m.miembro})" for m in diagnostico.miembros_redo)
        partes.append(f"redo logs dañados o ausentes: {miembros}")
    if not partes:
        return "Sin daños."
    texto = "; ".join(partes)
    return texto[0].upper() + texto[1:] + "."
