from pathlib import Path

from cloudcr_backup.oracle.discovery import (
    InstanciaDescubierta,
    combinar,
    oracle_home_desde_image_path,
    parsear_oratab,
    servicio_en_ejecucion,
    sids_desde_procesos,
)

SALIDA_SC_ESPANOL = """
NOMBRE_SERVICIO: OracleServiceXE
        TIPO               : 10  WIN32_OWN_PROCESS
        ESTADO             : 4  RUNNING
                                (STOPPABLE, PAUSABLE, ACCEPTS_SHUTDOWN)
"""

SALIDA_SC_DETENIDO = """
SERVICE_NAME: OracleServiceORCL
        TYPE               : 10  WIN32_OWN_PROCESS
        STATE              : 1  STOPPED
"""


def test_servicio_en_ejecucion_con_salida_en_espanol() -> None:
    assert servicio_en_ejecucion(SALIDA_SC_ESPANOL)


def test_servicio_detenido() -> None:
    assert not servicio_en_ejecucion(SALIDA_SC_DETENIDO)


def test_oracle_home_desde_image_path_con_comillas() -> None:
    ruta = oracle_home_desde_image_path('"d:\\oracle\\product\\19c\\dbhome_1\\bin\\ORACLE.EXE" ORCL')
    assert ruta == Path("d:\\oracle\\product\\19c\\dbhome_1")


def test_oracle_home_desde_image_path_sin_bin() -> None:
    assert oracle_home_desde_image_path("C:\\otro\\programa.exe XE") is None


def test_parsear_oratab_ignora_comentarios_y_comodines() -> None:
    contenido = "# comentario\n\nORCL:/u01/app/oracle/product/19c/dbhome_1:Y\n*:/u01/app/oracle:N\nPROD:/u01/19c:N\n"
    instancias = parsear_oratab(contenido)
    assert [(i.sid, i.oracle_home) for i in instancias] == [
        ("ORCL", Path("/u01/app/oracle/product/19c/dbhome_1")),
        ("PROD", Path("/u01/19c")),
    ]


def test_sids_desde_procesos() -> None:
    comandos = ["ora_pmon_ORCL ", "/usr/bin/python app.py", "db_pmon_PROD", "ora_smon_ORCL"]
    assert sids_desde_procesos(comandos) == {"ORCL", "PROD"}


def test_combinar_une_origenes_y_prioriza_en_ejecucion() -> None:
    registro = InstanciaDescubierta(sid="XE", oracle_home=Path("C:/home"), en_ejecucion=False, origenes=("registro",))
    servicio = InstanciaDescubierta(sid="xe", oracle_home=None, en_ejecucion=True, origenes=("servicio",))
    detenida = InstanciaDescubierta(sid="ORCL", oracle_home=None, en_ejecucion=False, origenes=("servicio",))
    resultado = combinar([detenida, registro, servicio])
    assert [i.sid for i in resultado] == ["XE", "ORCL"]
    assert resultado[0].en_ejecucion
    assert resultado[0].oracle_home == Path("C:/home")
    assert resultado[0].origenes == ("registro", "servicio")
