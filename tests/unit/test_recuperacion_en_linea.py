from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import oracledb

from cloudcr_backup.domain.recuperacion import Escenario
from cloudcr_backup.execution.destino import BaseDestino
from cloudcr_backup.recovery.en_linea import AbrirConexion, ObjetoEnLinea, objetos_a_poner_en_linea, poner_en_linea
from tests.unit.oracle_falso import ConexionFalsa

BASE = BaseDestino(oracle_home=Path(r"C:\oracle"), sid="XE")
SCRIPT_DATAFILE_PDB = (
    "ALTER PLUGGABLE DATABASE CLIENTEPDB CLOSE IMMEDIATE;\nRESTORE DATAFILE 17;\nRECOVER DATAFILE 17;\n"
    "ALTER PLUGGABLE DATABASE CLIENTEPDB OPEN;\n"
)
SCRIPT_TABLESPACE_PDB = (
    "ALTER PLUGGABLE DATABASE CLIENTEPDB CLOSE IMMEDIATE;\nRESTORE TABLESPACE CLIENTEPDB:A1;\n"
    "RECOVER TABLESPACE CLIENTEPDB:A1;\nALTER PLUGGABLE DATABASE CLIENTEPDB OPEN;\n"
)
SCRIPT_DATAFILE_PDB_CERRADA = "RESTORE DATAFILE 17;\nRECOVER DATAFILE 17;\nALTER PLUGGABLE DATABASE CLIENTEPDB OPEN;\n"
SCRIPT_TABLESPACE_PDB_CERRADA = (
    "RESTORE TABLESPACE CLIENTEPDB:A1;\nRECOVER TABLESPACE CLIENTEPDB:A1;\nALTER PLUGGABLE DATABASE CLIENTEPDB OPEN;\n"
)
SCRIPT_DATAFILE_RAIZ = (
    "ALTER DATABASE DATAFILE 7 OFFLINE;\nRESTORE DATAFILE 7;\nRECOVER DATAFILE 7;\nALTER DATABASE DATAFILE 7 ONLINE;\n"
)
DATAFILE_17 = ObjetoEnLinea(pdb="CLIENTEPDB", datafile=17)
TABLESPACE_A1 = ObjetoEnLinea(pdb="CLIENTEPDB", tablespace="A1")


def conexion_que_responde(*respuestas: object, errores: list[Exception | None] | None = None) -> ConexionFalsa:
    conexion = ConexionFalsa(list(respuestas))
    conexion.errores = deque(errores or [])
    return conexion


def abrir_con(conexion: ConexionFalsa) -> AbrirConexion:
    @contextmanager
    def abrir(base: BaseDestino) -> Iterator[ConexionFalsa]:
        yield conexion

    return abrir


def sentencias(conexion: ConexionFalsa) -> list[str]:
    return [sql for sql, _ in conexion.ejecutados]


def test_el_script_de_un_datafile_de_pdb_indica_que_datafile_poner_en_linea() -> None:
    assert objetos_a_poner_en_linea(Escenario.DATAFILE, SCRIPT_DATAFILE_PDB) == [DATAFILE_17]


def test_el_script_de_un_tablespace_de_pdb_indica_que_tablespace_poner_en_linea() -> None:
    assert objetos_a_poner_en_linea(Escenario.TABLESPACE, SCRIPT_TABLESPACE_PDB) == [TABLESPACE_A1]


def test_una_pdb_que_ya_estaba_cerrada_tambien_tiene_paso_en_linea() -> None:
    assert objetos_a_poner_en_linea(Escenario.DATAFILE, SCRIPT_DATAFILE_PDB_CERRADA) == [DATAFILE_17]
    assert objetos_a_poner_en_linea(Escenario.TABLESPACE, SCRIPT_TABLESPACE_PDB_CERRADA) == [TABLESPACE_A1]


def test_los_scripts_de_la_raiz_ya_se_ponen_en_linea_solos() -> None:
    assert objetos_a_poner_en_linea(Escenario.DATAFILE, SCRIPT_DATAFILE_RAIZ) == []


def test_otros_escenarios_no_tienen_paso_en_linea() -> None:
    assert objetos_a_poner_en_linea(Escenario.PDB, SCRIPT_DATAFILE_PDB) == []
    assert objetos_a_poner_en_linea(Escenario.CORRUPCION_BLOQUE, "RECOVER CORRUPTION LIST;\n") == []


def test_tolera_finales_de_linea_de_windows() -> None:
    assert objetos_a_poner_en_linea(Escenario.DATAFILE, SCRIPT_DATAFILE_PDB.replace("\n", "\r\n")) == [DATAFILE_17]


def test_un_tablespace_fuera_de_linea_se_pone_en_linea_dentro_de_la_pdb() -> None:
    conexion = conexion_que_responde(("OFFLINE",))
    resultado = poner_en_linea(BASE, TABLESPACE_A1, abrir_con(conexion))
    assert resultado.errores == []
    assert "CLIENTEPDB:A1" in resultado.detalle and "OFFLINE" in resultado.detalle
    assert sentencias(conexion) == [
        "ALTER SESSION SET CONTAINER = CLIENTEPDB",
        "SELECT status FROM dba_tablespaces WHERE tablespace_name = :tablespace",
        "ALTER TABLESPACE A1 ONLINE",
    ]


def test_un_datafile_cuyo_tablespace_esta_fuera_de_linea_pone_en_linea_el_tablespace() -> None:
    conexion = conexion_que_responde(("A1",), ("OFFLINE",))
    resultado = poner_en_linea(BASE, DATAFILE_17, abrir_con(conexion))
    assert resultado.errores == []
    assert "CLIENTEPDB:A1" in resultado.detalle
    assert sentencias(conexion)[-1] == "ALTER TABLESPACE A1 ONLINE"
    assert conexion.ejecutados[1][1] == {"archivo": 17}


def test_un_datafile_fuera_de_linea_en_un_tablespace_en_linea_pone_en_linea_el_datafile() -> None:
    conexion = conexion_que_responde(("A1",), ("ONLINE",), ("OFFLINE",))
    resultado = poner_en_linea(BASE, DATAFILE_17, abrir_con(conexion))
    assert resultado.errores == []
    assert "datafile 17" in resultado.detalle
    assert sentencias(conexion)[-1] == "ALTER DATABASE DATAFILE 17 ONLINE"


def test_si_ya_esta_en_linea_no_cambia_nada() -> None:
    conexion = conexion_que_responde(("A1",), ("ONLINE",), ("ONLINE",))
    resultado = poner_en_linea(BASE, DATAFILE_17, abrir_con(conexion))
    assert resultado.errores == []
    assert "ya estaba en línea" in resultado.detalle
    assert not any(sql.startswith("ALTER TABLESPACE") or "DATAFILE 17 ONLINE" in sql for sql in sentencias(conexion))


def test_un_error_de_oracle_se_informa_sin_lanzar_excepcion() -> None:
    fallo = oracledb.DatabaseError("ORA-01113: file needs recovery")
    conexion = conexion_que_responde(("OFFLINE",), errores=[None, None, fallo])
    resultado = poner_en_linea(BASE, TABLESPACE_A1, abrir_con(conexion))
    assert resultado.detalle == ""
    [error] = resultado.errores
    assert "pero no se pudo poner en línea el tablespace CLIENTEPDB:A1" in error and "ORA-01113" in error


def test_un_nombre_de_pdb_invalido_no_llega_a_oracle() -> None:
    conexion = conexion_que_responde()
    resultado = poner_en_linea(BASE, ObjetoEnLinea(pdb="X; DROP USER y", datafile=1), abrir_con(conexion))
    assert resultado.errores
    assert conexion.ejecutados == []


def test_un_nombre_de_tablespace_invalido_no_se_ejecuta() -> None:
    conexion = conexion_que_responde(("A1; DROP USER y",))
    resultado = poner_en_linea(BASE, DATAFILE_17, abrir_con(conexion))
    assert resultado.errores
    assert not any(sql.startswith("ALTER TABLESPACE") for sql in sentencias(conexion))
