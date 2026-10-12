import re
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Any

import oracledb

from cloudcr_backup.domain.errores import ErrorServicio
from cloudcr_backup.domain.recuperacion import Escenario
from cloudcr_backup.execution.destino import BaseDestino, conexion_destino

CIERRE_DE_PDB = re.compile(r"^ALTER PLUGGABLE DATABASE (\S+) CLOSE IMMEDIATE;[ \t\r]*$", re.MULTILINE)
RESTAURA_DATAFILE = re.compile(r"^RESTORE DATAFILE (\d+);[ \t\r]*$", re.MULTILINE)
RESTAURA_TABLESPACE = re.compile(r"^RESTORE TABLESPACE [^:\s]+:(\S+);[ \t\r]*$", re.MULTILINE)
NOMBRE_VALIDO = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]{0,127}$")
ESCENARIOS_CON_PASO_EN_LINEA = frozenset({Escenario.DATAFILE, Escenario.TABLESPACE})
FUERA_DE_LINEA = "OFFLINE"

SQL_TABLESPACE_DEL_DATAFILE = """
    SELECT ts.name FROM v$datafile df JOIN v$tablespace ts ON ts.ts# = df.ts# WHERE df.file# = :archivo
"""
SQL_ESTADO_TABLESPACE = "SELECT status FROM dba_tablespaces WHERE tablespace_name = :tablespace"
SQL_ESTADO_DATAFILE = "SELECT status FROM v$datafile WHERE file# = :archivo"

AbrirConexion = Callable[[BaseDestino], AbstractContextManager[Any]]


@dataclass(frozen=True)
class ObjetoEnLinea:
    pdb: str
    datafile: int | None = None
    tablespace: str | None = None

    @property
    def descripcion(self) -> str:
        if self.tablespace is not None:
            return f"el tablespace {self.pdb}:{self.tablespace}"
        return f"el datafile {self.datafile} de {self.pdb}"


@dataclass(frozen=True)
class ResultadoEnLinea:
    detalle: str = ""
    errores: list[str] = field(default_factory=list)


PonedorEnLinea = Callable[[BaseDestino, ObjetoEnLinea], ResultadoEnLinea]


def objetos_a_poner_en_linea(escenario: Escenario, script: str) -> list[ObjetoEnLinea]:
    if escenario not in ESCENARIOS_CON_PASO_EN_LINEA:
        return []
    cierre = CIERRE_DE_PDB.search(script)
    if cierre is None:
        return []
    pdb = cierre.group(1)
    if escenario is Escenario.DATAFILE:
        return [ObjetoEnLinea(pdb=pdb, datafile=int(numero)) for numero in RESTAURA_DATAFILE.findall(script)]
    return [ObjetoEnLinea(pdb=pdb, tablespace=nombre) for nombre in RESTAURA_TABLESPACE.findall(script)]


def _estado(cursor: Any, sql: str, **parametros: Any) -> str | None:
    cursor.execute(sql, **parametros)
    fila = cursor.fetchone()
    return None if fila is None else str(fila[0]).upper()


def _tablespace_del_datafile(cursor: Any, datafile: int | None) -> str | None:
    if datafile is None:
        return None
    cursor.execute(SQL_TABLESPACE_DEL_DATAFILE, archivo=datafile)
    fila = cursor.fetchone()
    return None if fila is None else str(fila[0])


def _poner_en_linea(cursor: Any, objeto: ObjetoEnLinea) -> str:
    cursor.execute(f"ALTER SESSION SET CONTAINER = {objeto.pdb}")
    tablespace = objeto.tablespace or _tablespace_del_datafile(cursor, objeto.datafile)
    if tablespace is not None and not NOMBRE_VALIDO.match(tablespace):
        raise ValueError(f"El nombre de tablespace {tablespace!r} no es válido.")
    if tablespace is not None and _estado(cursor, SQL_ESTADO_TABLESPACE, tablespace=tablespace) == FUERA_DE_LINEA:
        cursor.execute(f"ALTER TABLESPACE {tablespace} ONLINE")
        return f"Se puso en línea el tablespace {objeto.pdb}:{tablespace}, que había quedado OFFLINE."
    if objeto.datafile is not None and _estado(cursor, SQL_ESTADO_DATAFILE, archivo=objeto.datafile) == FUERA_DE_LINEA:
        cursor.execute(f"ALTER DATABASE DATAFILE {objeto.datafile} ONLINE")
        return f"Se puso en línea el datafile {objeto.datafile} de {objeto.pdb}, que había quedado OFFLINE."
    return f"{objeto.descripcion[0].upper()}{objeto.descripcion[1:]} ya estaba en línea."


def poner_en_linea(
    base: BaseDestino, objeto: ObjetoEnLinea, abrir: AbrirConexion = conexion_destino
) -> ResultadoEnLinea:
    if not NOMBRE_VALIDO.match(objeto.pdb):
        return ResultadoEnLinea(errores=[f"El nombre de PDB {objeto.pdb!r} no es válido: no se puso en línea."])
    try:
        with abrir(base) as conexion:
            cursor = conexion.cursor()
            try:
                return ResultadoEnLinea(detalle=_poner_en_linea(cursor, objeto))
            finally:
                cursor.close()
    except (oracledb.Error, ErrorServicio, ValueError) as error:
        return ResultadoEnLinea(errores=[f"RMAN terminó, pero no se pudo poner en línea {objeto.descripcion}: {error}"])
