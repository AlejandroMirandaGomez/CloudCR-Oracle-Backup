from typing import Any

from cloudcr_backup.domain.recuperacion import ArchivoDanado
from cloudcr_backup.execution.correlator import Consulta

ORIGEN_RECOVER_FILE = "V$RECOVER_FILE"
ORIGEN_DATAFILE = "V$DATAFILE"

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
