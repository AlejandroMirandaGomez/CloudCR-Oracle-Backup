from datetime import datetime
from typing import Any

import oracledb
import pytest

from cloudcr_backup.domain.enums import EstadoEjecucion, EstadoPrueba, LogMode
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
from cloudcr_backup.execution.destino import consulta_de
from cloudcr_backup.presentacion.operaciones import AYUDA_OBJETIVO, ETIQUETA_ESCENARIO
from cloudcr_backup.recovery import diagnostico, puntos
from cloudcr_backup.recovery.procedimientos import PASOS_ESCENARIO, PLANTILLAS, SolicitudProcedimiento, generar
from cloudcr_backup.repository.ejecuciones import EjecucionDetallada
from cloudcr_backup.repository.piezas import PiezaRegistrada
from cloudcr_backup.strategy.yaml_io import cargar_estrategia_yaml
from tests.unit.oracle_falso import ConexionConFallaPorTexto
from tests.unit.test_constructor import ESTRATEGIAS

DANADO_PDB = ArchivoDanado(
    file_id=14,
    ruta="C:\\ORADATA\\XE\\XEPDB1\\VENTAS01.DBF",
    tablespace="VENTAS",
    contenedor="XEPDB1",
    estado="OFFLINE",
    error="FILE NOT FOUND",
    cambio=123,
    origen="V$RECOVER_FILE",
)
DANADO_RAIZ = ArchivoDanado(
    file_id=7,
    ruta="C:\\ORADATA\\XE\\USERS01.DBF",
    tablespace="USERS",
    contenedor="CDB$ROOT",
    estado="OFFLINE",
    origen="V$DATAFILE",
)


def solicitud(escenario: Escenario, **cambios: Any) -> SolicitudProcedimiento:
    base: dict[str, Any] = {"bd": "XE", "escenario": escenario, "log_mode": LogMode.ARCHIVELOG}
    base.update(cambios)
    return SolicitudProcedimiento(**base)


def test_diagnostico_combina_recover_file_y_datafiles_fuera_de_linea() -> None:
    def consulta(sql: str, parametros: dict[str, Any]) -> list[tuple[Any, ...]]:
        if "v$recover_file" in sql:
            return [(14, "C:\\X\\VENTAS01.DBF", "VENTAS", "XEPDB1", "OFFLINE", "FILE NOT FOUND", 123)]
        return [
            (14, "C:\\X\\VENTAS01.DBF", "VENTAS", "XEPDB1", "RECOVER"),
            (7, "C:\\X\\USERS01.DBF", "USERS", "CDB$ROOT", "OFFLINE"),
        ]

    archivos = diagnostico.archivos_danados(consulta)
    assert [a.file_id for a in archivos] == [7, 14]
    assert archivos[1].origen == "V$RECOVER_FILE"
    assert archivos[1].error == "FILE NOT FOUND"
    assert archivos[1].identificador_tablespace == "XEPDB1:VENTAS"
    assert archivos[0].identificador_tablespace == "USERS"
    assert archivos[0].pdb is None


def test_plan_de_datafile_identifica_el_archivo_sin_que_el_usuario_lo_escriba() -> None:
    procedimiento = generar(solicitud(Escenario.DATAFILE, danados=[DANADO_PDB]))
    assert procedimiento.posible
    assert procedimiento.objetivo is not None
    assert procedimiento.objetivo.startswith("14")
    assert procedimiento.script == (
        "ALTER PLUGGABLE DATABASE XEPDB1 CLOSE IMMEDIATE;\nRESTORE DATAFILE 14;\nRECOVER DATAFILE 14;\n"
        "ALTER PLUGGABLE DATABASE XEPDB1 OPEN;\n"
    )
    assert any("V$RECOVER_FILE" in paso for paso in procedimiento.pasos)
    assert any("nunca se ejecuta solo" in paso for paso in procedimiento.pasos)


def test_plan_de_datafile_de_la_raiz_lo_pone_fuera_de_linea() -> None:
    procedimiento = generar(solicitud(Escenario.DATAFILE, danados=[DANADO_RAIZ]))
    assert procedimiento.script is not None
    assert procedimiento.script.startswith("ALTER DATABASE DATAFILE 7 OFFLINE;\n")


def test_plan_de_tablespace_y_pdb_desde_el_diagnostico() -> None:
    tablespace = generar(solicitud(Escenario.TABLESPACE, danados=[DANADO_PDB]))
    assert tablespace.objetivo == "XEPDB1:VENTAS"
    assert "RESTORE TABLESPACE XEPDB1:VENTAS;" in (tablespace.script or "")
    raiz = generar(solicitud(Escenario.TABLESPACE, objetivo="users"))
    assert (raiz.script or "").startswith("ALTER TABLESPACE USERS OFFLINE IMMEDIATE;")
    pdb = generar(solicitud(Escenario.PDB, danados=[DANADO_PDB]))
    assert pdb.script == (
        "ALTER PLUGGABLE DATABASE XEPDB1 CLOSE IMMEDIATE;\nRESTORE PLUGGABLE DATABASE XEPDB1;\n"
        "RECOVER PLUGGABLE DATABASE XEPDB1;\nALTER PLUGGABLE DATABASE XEPDB1 OPEN;\n"
    )


def test_sin_diagnostico_ni_objetivo_lo_explica() -> None:
    procedimiento = generar(solicitud(Escenario.DATAFILE))
    assert not procedimiento.posible
    assert "--objetivo" in procedimiento.motivo
    assert procedimiento.script is None


def test_escenarios_que_exigen_archivelog_se_explican_en_noarchivelog() -> None:
    for escenario in (Escenario.PDB, Escenario.TABLESPACE, Escenario.DATAFILE, Escenario.PUNTO_EN_TIEMPO):
        procedimiento = generar(solicitud(escenario, log_mode=LogMode.NOARCHIVELOG, danados=[DANADO_PDB]))
        assert not procedimiento.posible
        assert "total-noarchivelog" in procedimiento.motivo


SCRIPT_TOTAL_CON_CONTROLFILE = (
    "STARTUP FORCE NOMOUNT;\nSET DBID 3114375768;\nRUN {\n"
    "  SET CONTROLFILE AUTOBACKUP FORMAT FOR DEVICE TYPE DISK TO 'C:\\backups\\XE\\%F';\n"
    "  RESTORE CONTROLFILE FROM AUTOBACKUP;\n}\nALTER DATABASE MOUNT;\n"
    "RESTORE DATABASE;\nRECOVER DATABASE NOREDO;\nALTER DATABASE OPEN RESETLOGS;\n"
)


def test_total_noarchivelog() -> None:
    procedimiento = generar(solicitud(Escenario.TOTAL_NOARCHIVELOG, log_mode=LogMode.NOARCHIVELOG))
    assert procedimiento.script == (
        "STARTUP FORCE MOUNT;\nRESTORE DATABASE;\nRECOVER DATABASE NOREDO;\nALTER DATABASE OPEN RESETLOGS;\n"
    )
    assert procedimiento.avisos == []
    assert procedimiento.objetivo is None
    assert generar(solicitud(Escenario.TOTAL_NOARCHIVELOG)).avisos


def test_total_noarchivelog_sin_control_file_cuando_la_instancia_no_monta() -> None:
    sin_conexion = generar(
        solicitud(
            Escenario.TOTAL_NOARCHIVELOG,
            log_mode=LogMode.NOARCHIVELOG,
            sin_conexion=True,
            dbid=3114375768,
            destino_autobackup="C:\\backups\\XE",
        )
    )
    assert sin_conexion.script == SCRIPT_TOTAL_CON_CONTROLFILE
    assert sin_conexion.objetivo == "incluye la restauración del control file"
    assert sin_conexion.avisos == []
    assert any("ORA-00205" in paso for paso in sin_conexion.pasos)
    forzado = generar(
        solicitud(
            Escenario.TOTAL_NOARCHIVELOG,
            log_mode=LogMode.NOARCHIVELOG,
            objetivo=" ControlFile ",
            dbid=3114375768,
            destino_autobackup="C:\\backups\\XE",
        )
    )
    assert forzado.script == SCRIPT_TOTAL_CON_CONTROLFILE
    con_pieza = generar(
        solicitud(
            Escenario.TOTAL_NOARCHIVELOG,
            log_mode=LogMode.NOARCHIVELOG,
            sin_conexion=True,
            dbid=1,
            pieza_controlfile="C:\\b\\c.bkp",
        )
    )
    assert "RESTORE CONTROLFILE FROM 'C:\\b\\c.bkp';" in (con_pieza.script or "")
    assert "RESTORE CONTROLFILE FROM AUTOBACKUP;" not in (con_pieza.script or "")
    en_archivelog = generar(
        solicitud(Escenario.TOTAL_NOARCHIVELOG, sin_conexion=True, dbid=1, destino_autobackup="C:\\backups\\XE")
    )
    assert en_archivelog.avisos


def test_total_noarchivelog_sin_control_file_exige_dbid_y_destino() -> None:
    sin_dbid = generar(solicitud(Escenario.TOTAL_NOARCHIVELOG, sin_conexion=True, destino_autobackup="C:\\b"))
    assert not sin_dbid.posible
    assert sin_dbid.script is None
    assert "DBID" in sin_dbid.motivo and "control file" in sin_dbid.motivo
    sin_destino = generar(solicitud(Escenario.TOTAL_NOARCHIVELOG, objetivo="controlfile", dbid=1))
    assert not sin_destino.posible
    assert "autobackup" in sin_destino.motivo
    desconocido = generar(
        solicitud(Escenario.TOTAL_NOARCHIVELOG, objetivo="spfile", dbid=1, destino_autobackup="C:\\b")
    )
    assert not desconocido.posible
    assert "controlfile" in desconocido.motivo


def test_controlfile_con_pieza_o_autobackup() -> None:
    con_pieza = generar(
        solicitud(
            Escenario.CONTROLFILE,
            dbid=3114375768,
            destino_autobackup="C:\\backups\\XE",
            pieza_controlfile="C:\\b\\c.bkp",
        )
    )
    assert con_pieza.script == (
        "STARTUP FORCE NOMOUNT;\nSET DBID 3114375768;\nRUN {\n"
        "  SET CONTROLFILE AUTOBACKUP FORMAT FOR DEVICE TYPE DISK TO 'C:\\backups\\XE\\%F';\n"
        "  RESTORE CONTROLFILE FROM 'C:\\b\\c.bkp';\n}\nALTER DATABASE MOUNT;\n"
        "RESTORE DATABASE;\nRECOVER DATABASE;\nALTER DATABASE OPEN RESETLOGS;\n"
    )
    autobackup = generar(solicitud(Escenario.CONTROLFILE, dbid=1, destino_autobackup="C:\\backups\\XE"))
    assert autobackup.script == (
        "STARTUP FORCE NOMOUNT;\nSET DBID 1;\nRUN {\n"
        "  SET CONTROLFILE AUTOBACKUP FORMAT FOR DEVICE TYPE DISK TO 'C:\\backups\\XE\\%F';\n"
        "  RESTORE CONTROLFILE FROM AUTOBACKUP;\n}\nALTER DATABASE MOUNT;\n"
        "RESTORE DATABASE;\nRECOVER DATABASE;\nALTER DATABASE OPEN RESETLOGS;\n"
    )
    assert any("RESTORE DATABASE" in paso for paso in PASOS_ESCENARIO[Escenario.CONTROLFILE])
    assert not generar(solicitud(Escenario.CONTROLFILE)).posible


def test_punto_en_tiempo() -> None:
    procedimiento = generar(solicitud(Escenario.PUNTO_EN_TIEMPO, hasta=datetime(2026, 10, 4, 13, 0)))
    assert "SET UNTIL TIME \"TO_DATE('2026-10-04 13:00:00', 'YYYY-MM-DD HH24:MI:SS')\";" in (procedimiento.script or "")
    assert not generar(solicitud(Escenario.PUNTO_EN_TIEMPO)).posible


def test_objetivo_invalido_se_rechaza() -> None:
    assert not generar(solicitud(Escenario.TABLESPACE, objetivo="X; DROP")).posible
    assert not generar(solicitud(Escenario.DATAFILE, objetivo="abc")).posible


def _ejecucion(
    id_: int, estrategia: str, estado: EstadoEjecucion, fin: datetime, prueba: EstadoPrueba
) -> EjecucionDetallada:
    return EjecucionDetallada(
        id=id_,
        bd_id=1,
        bd_nombre="XE",
        estrategia_id=1,
        estrategia_codigo=estrategia,
        estrategia_nombre="x",
        tarea_id=1,
        tarea_codigo="T1",
        tipo_respaldo="INCREMENTAL_N0",
        modo_respaldo="CONSISTENTE",
        estado=estado,
        estado_prueba=prueba,
        programada_para=fin,
        inicio=fin,
        fin=fin,
        duracion_segundos=1,
        tamano_bytes=1,
        archivos_generados=1,
        ubicacion="C:\\b",
        zona_horaria="America/Costa_Rica",
        mensaje_rman=None,
        agente=None,
        script_id=1,
    )


def _pieza(id_: int, ejecucion: int, nombre: str) -> PiezaRegistrada:
    return PiezaRegistrada(
        id=id_,
        ejecucion_id=ejecucion,
        nombre_archivo=nombre,
        tamano_bytes=10,
        tag="EST002_T1_X",
        vence_en=None,
        obsoleta=False,
        estrategia_id=1,
        estrategia_codigo="EST002",
        tarea_codigo="T1",
        fin=None,
    )


def test_puntos_de_recuperacion_solo_con_respaldos_correctos() -> None:
    est002 = cargar_estrategia_yaml(ESTRATEGIAS / "est002.yaml")
    ejecuciones = [
        _ejecucion(1, "EST002", EstadoEjecucion.EXITOSA, datetime(2026, 10, 1), EstadoPrueba.OK),
        _ejecucion(2, "EST002", EstadoEjecucion.FALLIDA, datetime(2026, 10, 2), EstadoPrueba.NO_APLICA),
        _ejecucion(3, "EST002", EstadoEjecucion.EXITOSA, datetime(2026, 10, 3), EstadoPrueba.PENDIENTE),
    ]
    piezas = [
        _pieza(1, 1, "C:\\b\\XE_EST002_T1_1.BKP"),
        _pieza(2, 1, "C:\\b\\C-3114375768-20261001-00"),
        _pieza(3, 2, "C:\\b\\x.bkp"),
        _pieza(4, 3, "C:\\b\\XE_EST002_T1_3.BKP"),
    ]
    resultado = puntos.construir("XE", LogMode.NOARCHIVELOG, ejecuciones, piezas, {"EST002": est002})
    assert [p.ejecucion_id for p in resultado.puntos] == [3, 1]
    assert resultado.puntos[1].controlfile == "C:\\b\\C-3114375768-20261001-00"
    assert resultado.puntos[1].base_completa
    assert resultado.recuperable_desde == datetime(2026, 10, 1)
    assert any("NOARCHIVELOG" in aviso for aviso in resultado.avisos)


def test_sin_puntos_lo_avisa() -> None:
    resultado = puntos.construir("XE", LogMode.ARCHIVELOG, [], [], {})
    assert resultado.puntos == []
    assert "ningún punto" in resultado.avisos[0]


def test_datafile_indicado_a_mano_de_una_pdb_cierra_la_pdb() -> None:
    procedimiento = generar(
        solicitud(Escenario.DATAFILE, objetivo="12", contenedor_de_datafile={12: "XEPDB1", 7: "CDB$ROOT"})
    )
    assert (procedimiento.script or "").startswith("ALTER PLUGGABLE DATABASE XEPDB1 CLOSE IMMEDIATE;")
    raiz = generar(solicitud(Escenario.DATAFILE, objetivo="7", contenedor_de_datafile={7: "CDB$ROOT"}))
    assert (raiz.script or "").startswith("ALTER DATABASE DATAFILE 7 OFFLINE;")


DANADO_SYSTEM = ArchivoDanado(
    file_id=1,
    ruta="C:\\ORADATA\\XE\\SYSTEM01.DBF",
    tablespace="SYSTEM",
    contenedor="CDB$ROOT",
    estado="OFFLINE",
    error="FILE NOT FOUND",
    origen="V$RECOVER_FILE",
)
MIEMBRO_ACTUAL = MiembroRedoDanado(
    grupo=2, miembro="C:\\ORADATA\\XE\\REDO02B.LOG", estado_miembro="INVALID", estado_grupo="CURRENT", secuencia=41
)
MIEMBRO_INACTIVO = MiembroRedoDanado(
    grupo=3, miembro="C:\\ORADATA\\XE\\REDO03B.LOG", estado_miembro="INVALID", estado_grupo="INACTIVE", secuencia=39
)


def test_los_ocho_escenarios_de_clase_estan_completos() -> None:
    assert len(Escenario) == 11
    for escenario in Escenario:
        assert escenario in PLANTILLAS
        assert PASOS_ESCENARIO[escenario]
        assert ETIQUETA_ESCENARIO[escenario]
        assert AYUDA_OBJETIVO[escenario]
    for nombre in (
        "PERDIDA_DATAFILE_NO_CRITICO",
        "PERDIDA_DATAFILE_CRITICO",
        "PERDIDA_CONTROL_FILE",
        "PERDIDA_MIEMBRO_REDOLOG",
        "PERDIDA_GRUPO_REDOLOG_CURRENT",
        "CORRUPCION_DE_BLOQUE",
        "PERDIDA_SPFILE",
        "PERDIDA_TOTAL_SIN_ARCHIVELOG",
    ):
        assert any(nombre in etiqueta for etiqueta in ETIQUETA_ESCENARIO.values()), nombre


def test_archivo_critico_solo_en_la_raiz() -> None:
    assert DANADO_SYSTEM.critico
    assert DANADO_SYSTEM.model_copy(update={"tablespace": "UNDOTBS1"}).critico
    assert not DANADO_SYSTEM.model_copy(update={"contenedor": "XEPDB1"}).critico
    assert not DANADO_RAIZ.critico
    assert DANADO_SYSTEM.model_dump()["critico"] is True


def test_datafile_critico_no_se_deja_offline_y_se_recupera_montado() -> None:
    rechazado = generar(solicitud(Escenario.DATAFILE, danados=[DANADO_SYSTEM]))
    assert not rechazado.posible
    assert "datafile-critico" in rechazado.motivo
    assert not generar(solicitud(Escenario.DATAFILE, objetivo="3", criticos=frozenset({3}))).posible
    assert not generar(solicitud(Escenario.TABLESPACE, objetivo="system")).posible
    assert not generar(
        solicitud(Escenario.TABLESPACE, objetivo="UNDO_XE", tablespaces_criticos=frozenset({"UNDO_XE"}))
    ).posible
    assert generar(solicitud(Escenario.TABLESPACE, objetivo="XEPDB1:SYSTEM")).posible
    procedimiento = generar(solicitud(Escenario.DATAFILE_CRITICO, danados=[DANADO_RAIZ, DANADO_SYSTEM]))
    assert procedimiento.posible
    assert procedimiento.script == (
        "STARTUP FORCE MOUNT;\nRESTORE DATAFILE 1;\nRECOVER DATAFILE 1;\nALTER DATABASE OPEN;\n"
    )
    assert procedimiento.avisos == []
    no_critico = generar(solicitud(Escenario.DATAFILE_CRITICO, objetivo="7", danados=[DANADO_RAIZ]))
    assert no_critico.posible
    assert "menos invasivo" in no_critico.avisos[0]
    assert not generar(solicitud(Escenario.DATAFILE_CRITICO, log_mode=LogMode.NOARCHIVELOG, objetivo="1")).posible


def test_miembro_de_redolog_deja_el_grupo_inactivo_segun_su_estado() -> None:
    actual = generar(solicitud(Escenario.MIEMBRO_REDOLOG, miembros_redo=[MIEMBRO_ACTUAL], hay_respaldo=False))
    assert actual.script == (
        "ALTER SYSTEM SWITCH LOGFILE;\nALTER SYSTEM CHECKPOINT;\n"
        "ALTER DATABASE DROP LOGFILE MEMBER 'C:\\ORADATA\\XE\\REDO02B.LOG';\n"
        "ALTER DATABASE ADD LOGFILE MEMBER 'C:\\ORADATA\\XE\\REDO02B.LOG' REUSE TO GROUP 2;\n"
    )
    activo = MIEMBRO_INACTIVO.model_copy(update={"estado_grupo": "ACTIVE"})
    en_uso = generar(solicitud(Escenario.MIEMBRO_REDOLOG, miembros_redo=[activo]))
    assert en_uso.script == (
        "ALTER SYSTEM CHECKPOINT;\n"
        "ALTER DATABASE DROP LOGFILE MEMBER 'C:\\ORADATA\\XE\\REDO03B.LOG';\n"
        "ALTER DATABASE ADD LOGFILE MEMBER 'C:\\ORADATA\\XE\\REDO03B.LOG' REUSE TO GROUP 3;\n"
    )
    inactivo = generar(solicitud(Escenario.MIEMBRO_REDOLOG, miembros_redo=[MIEMBRO_INACTIVO]))
    assert inactivo.script == (
        "ALTER DATABASE DROP LOGFILE MEMBER 'C:\\ORADATA\\XE\\REDO03B.LOG';\n"
        "ALTER DATABASE ADD LOGFILE MEMBER 'C:\\ORADATA\\XE\\REDO03B.LOG' REUSE TO GROUP 3;\n"
    )
    assert inactivo.avisos == []


def test_miembro_de_redolog_avisa_del_archivado_solo_si_el_grupo_no_esta_inactivo() -> None:
    actual = generar(solicitud(Escenario.MIEMBRO_REDOLOG, miembros_redo=[MIEMBRO_ACTUAL]))
    assert any("ARCHIVED = YES" in aviso for aviso in actual.avisos)
    sin_archivado = generar(
        solicitud(Escenario.MIEMBRO_REDOLOG, log_mode=LogMode.NOARCHIVELOG, miembros_redo=[MIEMBRO_ACTUAL])
    )
    assert sin_archivado.avisos == []


def test_miembro_de_redolog_sin_restaurar() -> None:
    inactivo = generar(
        solicitud(Escenario.MIEMBRO_REDOLOG, log_mode=LogMode.NOARCHIVELOG, miembros_redo=[MIEMBRO_INACTIVO])
    )
    assert inactivo.posible
    manual = generar(solicitud(Escenario.MIEMBRO_REDOLOG, objetivo="4:C:\\R\\REDO04B.LOG"))
    assert "TO GROUP 4;" in (manual.script or "")
    assert (manual.script or "").startswith("ALTER SYSTEM CHECKPOINT;")
    assert "ORA-01609" in manual.avisos[0]
    por_ruta = generar(
        solicitud(Escenario.MIEMBRO_REDOLOG, objetivo="c:\\oradata\\xe\\redo02b.log", miembros_redo=[MIEMBRO_ACTUAL])
    )
    assert "TO GROUP 2;" in (por_ruta.script or "")
    assert not generar(solicitud(Escenario.MIEMBRO_REDOLOG, objetivo="C:\\R\\X.LOG")).posible
    assert not generar(solicitud(Escenario.MIEMBRO_REDOLOG, objetivo="2:C:\\R\\X'; DROP")).posible
    assert not generar(solicitud(Escenario.MIEMBRO_REDOLOG)).posible
    perdido = MIEMBRO_ACTUAL.model_copy(update={"grupo_perdido": True})
    sin_copia = generar(solicitud(Escenario.MIEMBRO_REDOLOG, miembros_redo=[perdido]))
    assert not sin_copia.posible
    assert "grupo-redolog-actual" in sin_copia.motivo


def test_grupo_redolog_actual_es_recuperacion_incompleta_hasta_la_secuencia() -> None:
    perdido = MIEMBRO_ACTUAL.model_copy(update={"grupo_perdido": True})
    procedimiento = generar(solicitud(Escenario.GRUPO_REDOLOG_ACTUAL, miembros_redo=[perdido]))
    assert procedimiento.script == (
        "STARTUP FORCE MOUNT;\nRUN {\n  SET UNTIL SEQUENCE 41 THREAD 1;\n  RESTORE DATABASE;\n  RECOVER DATABASE;\n}\n"
        "ALTER DATABASE OPEN RESETLOGS;\n"
    )
    assert any("UNTIL CANCEL" in paso for paso in procedimiento.pasos)
    deducido = generar(
        solicitud(Escenario.GRUPO_REDOLOG_ACTUAL, redo_actual=GrupoRedoActual(grupo=1, hilo=1, secuencia=7))
    )
    assert "SET UNTIL SEQUENCE 7 THREAD 1;" in (deducido.script or "")
    assert "Confirme" in deducido.avisos[0]
    assert "SET UNTIL SEQUENCE 99 THREAD 2;" in (
        generar(solicitud(Escenario.GRUPO_REDOLOG_ACTUAL, objetivo="2:99")).script or ""
    )
    assert "SET UNTIL SEQUENCE 99 THREAD 1;" in (
        generar(solicitud(Escenario.GRUPO_REDOLOG_ACTUAL, objetivo="99")).script or ""
    )
    assert not generar(solicitud(Escenario.GRUPO_REDOLOG_ACTUAL, objetivo="ayer")).posible
    assert not generar(solicitud(Escenario.GRUPO_REDOLOG_ACTUAL, objetivo="0")).posible
    assert not generar(solicitud(Escenario.GRUPO_REDOLOG_ACTUAL)).posible
    assert not generar(solicitud(Escenario.GRUPO_REDOLOG_ACTUAL, log_mode=LogMode.NOARCHIVELOG, objetivo="9")).posible


def test_corrupcion_de_bloque() -> None:
    lista = generar(solicitud(Escenario.CORRUPCION_BLOQUE, bloques=[BloqueCorrupto(file_id=7, bloque=131, bloques=2)]))
    assert lista.script == "VALIDATE DATABASE;\nRECOVER CORRUPTION LIST;\nVALIDATE DATABASE;\n"
    assert lista.objetivo == "2 bloques en V$DATABASE_BLOCK_CORRUPTION"
    uno = generar(solicitud(Escenario.CORRUPCION_BLOQUE, objetivo="7 : 131"))
    assert uno.script == "RECOVER DATAFILE 7 BLOCK 131;\nVALIDATE DATAFILE 7;\n"
    assert not generar(solicitud(Escenario.CORRUPCION_BLOQUE, log_mode=LogMode.NOARCHIVELOG, objetivo="7:131")).posible
    assert not generar(solicitud(Escenario.CORRUPCION_BLOQUE, objetivo="7")).posible
    assert not generar(solicitud(Escenario.CORRUPCION_BLOQUE, objetivo="0:1")).posible
    assert not generar(solicitud(Escenario.CORRUPCION_BLOQUE)).posible


def test_spfile_desde_autobackup_o_pieza() -> None:
    autobackup = generar(solicitud(Escenario.SPFILE, dbid=3114375768, destino_autobackup="C:\\backups\\XE"))
    assert autobackup.script == (
        "STARTUP FORCE NOMOUNT;\nSET DBID 3114375768;\nRUN {\n"
        "  SET CONTROLFILE AUTOBACKUP FORMAT FOR DEVICE TYPE DISK TO 'C:\\backups\\XE\\%F';\n"
        "  RESTORE SPFILE FROM AUTOBACKUP;\n}\nSTARTUP FORCE NOMOUNT;\nALTER DATABASE MOUNT;\nALTER DATABASE OPEN;\n"
    )
    pieza = generar(solicitud(Escenario.SPFILE, dbid=1, pieza_controlfile="C:\\b\\C-1-20261011-00"))
    assert "RESTORE SPFILE FROM 'C:\\b\\C-1-20261011-00';" in (pieza.script or "")
    assert generar(
        solicitud(Escenario.SPFILE, log_mode=LogMode.NOARCHIVELOG, dbid=1, destino_autobackup="C:\\b")
    ).posible
    sin_dbid = generar(solicitud(Escenario.SPFILE))
    assert not sin_dbid.posible
    assert "SPFILE" in sin_dbid.motivo


def existe_siempre(ruta: str) -> bool:
    return True


def test_diagnostico_de_bloques_y_redo_logs() -> None:
    def consulta(sql: str, parametros: dict[str, Any]) -> list[tuple[Any, ...]]:
        if "v$database_block_corruption" in sql:
            return [(7, 131, 2, "CHECKSUM", "C:\\X\\USERS01.DBF", "USERS", "CDB$ROOT")]
        return [
            (1, "C:\\R\\REDO01A.LOG", None, "INACTIVE", 1, 40),
            (1, "C:\\R\\REDO01B.LOG", "INVALID", "INACTIVE", 1, 40),
            (2, "C:\\R\\REDO02A.LOG", "INVALID", "CURRENT", 1, 41),
            (2, "C:\\R\\REDO02B.LOG", "INVALID", "CURRENT", 1, 41),
            (3, "C:\\R\\REDO03A.LOG", "STALE", "UNUSED", 1, 0),
        ]

    bloques = diagnostico.bloques_corruptos(consulta)
    assert bloques == [
        BloqueCorrupto(
            file_id=7,
            bloque=131,
            bloques=2,
            tipo="CHECKSUM",
            ruta="C:\\X\\USERS01.DBF",
            tablespace="USERS",
            contenedor="CDB$ROOT",
        )
    ]
    miembros, actual, grupos = diagnostico.redo_logs(consulta, existe_siempre)
    assert [(m.grupo, m.grupo_perdido, m.actual) for m in miembros] == [
        (1, False, False),
        (2, True, True),
        (2, True, True),
    ]
    assert actual == GrupoRedoActual(grupo=2, hilo=1, secuencia=41)
    assert grupos == [
        GrupoRedo(grupo=1, estado="INACTIVE", hilo=1, secuencia=40),
        GrupoRedo(grupo=2, estado="CURRENT", hilo=1, secuencia=41),
        GrupoRedo(grupo=3, estado="UNUSED", hilo=1, secuencia=0),
    ]


def test_sugerencias_del_diagnostico() -> None:
    momento = datetime(2026, 10, 11, 9, 0)
    perdido = MIEMBRO_ACTUAL.model_copy(update={"grupo_perdido": True})
    completo = Diagnostico(
        bd="XE",
        generado_en=momento,
        log_mode=LogMode.ARCHIVELOG,
        archivos=[DANADO_SYSTEM, DANADO_RAIZ],
        bloques=[BloqueCorrupto(file_id=7, bloque=1)],
        miembros_redo=[perdido, MIEMBRO_INACTIVO],
    )
    assert diagnostico.sugerir(completo) == [
        Escenario.DATAFILE_CRITICO,
        Escenario.DATAFILE,
        Escenario.GRUPO_REDOLOG_ACTUAL,
        Escenario.MIEMBRO_REDOLOG,
        Escenario.CORRUPCION_BLOQUE,
    ]
    sin_archivado = completo.model_copy(update={"log_mode": LogMode.NOARCHIVELOG})
    assert diagnostico.sugerir(sin_archivado)[-1] is Escenario.TOTAL_NOARCHIVELOG
    assert Escenario.DATAFILE not in diagnostico.sugerir(sin_archivado)
    caida = Diagnostico(bd="XE", generado_en=momento, sin_conexion=True)
    assert diagnostico.sugerir(caida) == [Escenario.CONTROLFILE, Escenario.SPFILE]
    assert not caida.sin_danos
    assert diagnostico.sugerir(Diagnostico(bd="XE", generado_en=momento)) == []
    assert diagnostico.resumen(completo).startswith("Datafiles dañados: 1 (SYSTEM), 7 (USERS)")
    assert diagnostico.resumen(Diagnostico(bd="XE", generado_en=momento)) == "Sin daños."


PDB_CERRADA = {"XEPDB1": "MOUNTED"}
PDB_ABIERTA = {"XEPDB1": "READ WRITE"}
CIERRE_XEPDB1 = "ALTER PLUGGABLE DATABASE XEPDB1 CLOSE IMMEDIATE;\n"


def test_con_la_pdb_ya_cerrada_ningun_script_la_vuelve_a_cerrar() -> None:
    datafile = generar(solicitud(Escenario.DATAFILE, danados=[DANADO_PDB], estado_pdbs=PDB_CERRADA))
    assert datafile.script == ("RESTORE DATAFILE 14;\nRECOVER DATAFILE 14;\nALTER PLUGGABLE DATABASE XEPDB1 OPEN;\n")
    tablespace = generar(solicitud(Escenario.TABLESPACE, danados=[DANADO_PDB], estado_pdbs=PDB_CERRADA))
    assert tablespace.script == (
        "RESTORE TABLESPACE XEPDB1:VENTAS;\nRECOVER TABLESPACE XEPDB1:VENTAS;\nALTER PLUGGABLE DATABASE XEPDB1 OPEN;\n"
    )
    pdb = generar(solicitud(Escenario.PDB, danados=[DANADO_PDB], estado_pdbs=PDB_CERRADA))
    assert pdb.script == (
        "RESTORE PLUGGABLE DATABASE XEPDB1;\nRECOVER PLUGGABLE DATABASE XEPDB1;\n"
        "ALTER PLUGGABLE DATABASE XEPDB1 OPEN;\n"
    )
    for procedimiento in (datafile, tablespace, pdb):
        assert CIERRE_XEPDB1 not in (procedimiento.script or "")
        assert any("MOUNTED" in aviso for aviso in procedimiento.avisos)


def test_con_la_pdb_abierta_o_de_estado_desconocido_el_script_la_cierra() -> None:
    for estados in (PDB_ABIERTA, {}, {"OTRA": "MOUNTED"}, {"xepdb1": "read write"}):
        for escenario in (Escenario.DATAFILE, Escenario.TABLESPACE, Escenario.PDB):
            procedimiento = generar(solicitud(escenario, danados=[DANADO_PDB], estado_pdbs=estados))
            assert (procedimiento.script or "").startswith(CIERRE_XEPDB1), (escenario, estados)
            assert not any("MOUNTED" in aviso for aviso in procedimiento.avisos)
    en_minusculas = generar(solicitud(Escenario.DATAFILE, danados=[DANADO_PDB], estado_pdbs={"xepdb1": "mounted"}))
    assert CIERRE_XEPDB1 not in (en_minusculas.script or "")


def test_el_datafile_de_la_raiz_no_depende_del_estado_de_las_pdb() -> None:
    procedimiento = generar(solicitud(Escenario.DATAFILE, danados=[DANADO_RAIZ], estado_pdbs=PDB_CERRADA))
    assert (procedimiento.script or "").startswith("ALTER DATABASE DATAFILE 7 OFFLINE;")


def test_el_system_de_una_pdb_se_recupera_con_el_escenario_datafile_y_la_pdb_cerrada() -> None:
    system_pdb = ArchivoDanado(
        file_id=11,
        ruta="C:\\ORADATA\\XE\\XEPDB1\\SYSTEM01.DBF",
        tablespace="SYSTEM",
        contenedor="XEPDB1",
        estado="OFFLINE",
        error="FILE NOT FOUND",
        origen="V$RECOVER_FILE",
    )
    assert not system_pdb.critico
    procedimiento = generar(solicitud(Escenario.DATAFILE, danados=[system_pdb], estado_pdbs=PDB_CERRADA))
    assert procedimiento.script == (
        "RESTORE DATAFILE 11;\nRECOVER DATAFILE 11;\nALTER PLUGGABLE DATABASE XEPDB1 OPEN;\n"
    )
    assert any("PDB cerrada" in paso for paso in PASOS_ESCENARIO[Escenario.DATAFILE])
    rechazado = generar(solicitud(Escenario.DATAFILE, danados=[DANADO_SYSTEM]))
    assert "PDB cerrada" in rechazado.motivo


def faltante(grupo: int, ruta: str, estado_grupo: str, secuencia: int, perdido: bool = False) -> MiembroRedoDanado:
    return MiembroRedoDanado(
        grupo=grupo,
        miembro=ruta,
        estado_miembro="FALTANTE",
        estado_grupo=estado_grupo,
        secuencia=secuencia,
        grupo_perdido=perdido,
    )


def test_un_miembro_ausente_en_disco_cuenta_como_danado_aunque_no_este_invalid() -> None:
    def consulta(sql: str, parametros: dict[str, Any]) -> list[tuple[Any, ...]]:
        return [
            (1, "C:\\R\\REDO01A.LOG", None, "INACTIVE", 1, 40),
            (1, "C:\\R\\REDO01B.LOG", None, "INACTIVE", 1, 40),
            (2, "C:\\R\\REDO02A.LOG", None, "CURRENT", 1, 41),
            (2, "C:\\R\\REDO02B.LOG", None, "CURRENT", 1, 41),
        ]

    consultadas: list[str] = []

    def existe(ruta: str) -> bool:
        consultadas.append(ruta)
        return ruta != "C:\\R\\REDO02B.LOG"

    miembros, actual, grupos = diagnostico.redo_logs(consulta, existe)
    assert len(consultadas) == 4
    assert [(m.grupo, m.miembro, m.estado_miembro, m.grupo_perdido) for m in miembros] == [
        (2, "C:\\R\\REDO02B.LOG", "FALTANTE", False)
    ]
    assert actual == GrupoRedoActual(grupo=2, hilo=1, secuencia=41)
    assert [(g.grupo, g.estado) for g in grupos] == [(1, "INACTIVE"), (2, "CURRENT")]
    completo = Diagnostico(
        bd="XE", generado_en=datetime(2026, 10, 11, 9, 0), log_mode=LogMode.ARCHIVELOG, miembros_redo=miembros
    )
    assert diagnostico.sugerir(completo) == [Escenario.MIEMBRO_REDOLOG]
    assert not completo.sin_danos
    assert "Redo logs dañados o ausentes: grupo 2" in diagnostico.resumen(completo)


def test_un_miembro_invalid_que_tambien_falta_conserva_el_estado_invalid() -> None:
    def consulta(sql: str, parametros: dict[str, Any]) -> list[tuple[Any, ...]]:
        return [
            (2, "C:\\R\\REDO02A.LOG", "INVALID", "INACTIVE", 1, 39),
            (2, "C:\\R\\REDO02B.LOG", None, "INACTIVE", 1, 39),
        ]

    miembros, _, _ = diagnostico.redo_logs(consulta, lambda ruta: False)
    assert [(m.estado_miembro, m.grupo_perdido) for m in miembros] == [("INVALID", True), ("FALTANTE", True)]


def test_un_grupo_current_con_todos_los_miembros_ausentes_sugiere_el_grupo_actual() -> None:
    def consulta(sql: str, parametros: dict[str, Any]) -> list[tuple[Any, ...]]:
        return [
            (1, "C:\\R\\REDO01A.LOG", None, "INACTIVE", 1, 40),
            (2, "C:\\R\\REDO02A.LOG", None, "CURRENT", 1, 41),
            (2, "C:\\R\\REDO02B.LOG", None, "CURRENT", 1, 41),
        ]

    miembros, actual, grupos = diagnostico.redo_logs(consulta, lambda ruta: "REDO01" in ruta)
    assert [(m.grupo, m.grupo_perdido, m.actual) for m in miembros] == [(2, True, True), (2, True, True)]
    resultado = Diagnostico(
        bd="XE",
        generado_en=datetime(2026, 10, 11, 9, 0),
        log_mode=LogMode.ARCHIVELOG,
        miembros_redo=miembros,
        redo_actual=actual,
        grupos_redo=grupos,
    )
    assert diagnostico.sugerir(resultado) == [Escenario.GRUPO_REDOLOG_ACTUAL]
    procedimiento = generar(
        solicitud(Escenario.GRUPO_REDOLOG_ACTUAL, miembros_redo=miembros, redo_actual=actual, grupos_redo=grupos)
    )
    assert "SET UNTIL SEQUENCE 41 THREAD 1;" in (procedimiento.script or "")
    assert "CLEAR UNARCHIVED LOGFILE GROUP 2;" in procedimiento.avisos[0]


def test_el_estado_del_grupo_se_toma_del_diagnostico_cuando_el_miembro_se_indica_a_mano() -> None:
    grupos = [
        GrupoRedo(grupo=2, estado="CURRENT", hilo=1, secuencia=41),
        GrupoRedo(grupo=3, estado="ACTIVE", hilo=1, secuencia=40),
        GrupoRedo(grupo=4, estado="INACTIVE", hilo=1, secuencia=39),
    ]
    actual = generar(solicitud(Escenario.MIEMBRO_REDOLOG, objetivo="2:C:\\R\\REDO02B.LOG", grupos_redo=grupos))
    assert (actual.script or "").startswith("ALTER SYSTEM SWITCH LOGFILE;\nALTER SYSTEM CHECKPOINT;\n")
    assert not any("ORA-01609" in aviso for aviso in actual.avisos)
    activo = generar(solicitud(Escenario.MIEMBRO_REDOLOG, objetivo="3:C:\\R\\REDO03B.LOG", grupos_redo=grupos))
    assert (activo.script or "").startswith("ALTER SYSTEM CHECKPOINT;\nALTER DATABASE DROP")
    inactivo = generar(solicitud(Escenario.MIEMBRO_REDOLOG, objetivo="4:C:\\R\\REDO04B.LOG", grupos_redo=grupos))
    assert (inactivo.script or "").startswith("ALTER DATABASE DROP")
    assert inactivo.avisos == []
    desconocido = generar(solicitud(Escenario.MIEMBRO_REDOLOG, objetivo="9:C:\\R\\REDO09B.LOG", grupos_redo=grupos))
    assert "ORA-01609" in desconocido.avisos[0]


def test_un_miembro_ausente_se_elige_solo_del_diagnostico() -> None:
    procedimiento = generar(
        solicitud(Escenario.MIEMBRO_REDOLOG, miembros_redo=[faltante(2, "C:\\ORADATA\\XE\\REDO02B.LOG", "CURRENT", 41)])
    )
    assert procedimiento.posible
    assert (procedimiento.script or "").startswith("ALTER SYSTEM SWITCH LOGFILE;\n")
    sin_dato = generar(solicitud(Escenario.MIEMBRO_REDOLOG, objetivo="C:\\R\\REDO02B.LOG"))
    assert "dañado ni ausente" in sin_dato.motivo


def test_el_grupo_actual_avisa_de_los_pasos_que_no_se_incluyen_en_el_script() -> None:
    perdido = MIEMBRO_ACTUAL.model_copy(update={"grupo_perdido": True})
    procedimiento = generar(solicitud(Escenario.GRUPO_REDOLOG_ACTUAL, miembros_redo=[perdido]))
    assert procedimiento.avisos[0].startswith("Antes de aprobar, el DBA puede intentar ALTER DATABASE CLEAR UNARCHIVED")
    assert "GROUP 2;" in procedimiento.avisos[0] and "ORA-01624" in procedimiento.avisos[0]
    assert "RENAME FILE" in procedimiento.avisos[1] and "RESETLOGS" in procedimiento.avisos[1]
    assert len(procedimiento.avisos) == 2
    assert "CLEAR" not in (procedimiento.script or "") and "RENAME" not in (procedimiento.script or "")
    manual = generar(solicitud(Escenario.GRUPO_REDOLOG_ACTUAL, objetivo="41"))
    assert "GROUP <número del grupo>;" in manual.avisos[0]
    con_grupos = generar(
        solicitud(
            Escenario.GRUPO_REDOLOG_ACTUAL,
            objetivo="1:41",
            grupos_redo=[GrupoRedo(grupo=2, estado="CURRENT", hilo=1, secuencia=41)],
        )
    )
    assert "GROUP 2;" in con_grupos.avisos[0]


def sin_v_containers(respuestas: list[Any]) -> ConexionConFallaPorTexto:
    return ConexionConFallaPorTexto(
        "v$containers", oracledb.DatabaseError("ORA-01219: database or pluggable database not open"), respuestas
    )


PDBS_DE_LA_INSTANCIA = [EstadoPdb(con_id=3, nombre="CLIENTEPDB", modo="MOUNTED")]


def test_si_v_containers_falla_los_archivos_se_consultan_sin_ese_join() -> None:
    conexion = sin_v_containers(
        [
            [(17, "C:\\X\\SYSTEM01.DBF", "SYSTEM", 3, "OFFLINE", "FILE NOT FOUND", 9)],
            [(5, "C:\\X\\USERS01.DBF", "USERS", 1, "OFFLINE")],
        ]
    )
    avisos: list[str] = []
    archivos = diagnostico.archivos_danados(consulta_de(conexion), PDBS_DE_LA_INSTANCIA, avisos)
    assert [(a.file_id, a.contenedor, a.estado) for a in archivos] == [
        (5, "CDB$ROOT", "OFFLINE"),
        (17, "CLIENTEPDB", "OFFLINE"),
    ]
    assert all("v$containers" not in sql.lower() for sql, _ in conexion.ejecutados)
    assert len(conexion.ejecutados) == 2
    assert len(avisos) == 1 and "V$CONTAINERS no respondió" in avisos[0] and "ORA-01219" in avisos[0]


def test_si_no_se_conoce_el_nombre_de_la_pdb_el_contenedor_queda_vacio_con_un_aviso() -> None:
    conexion = sin_v_containers([[(17, "C:\\X\\A1_01.DBF", "A1", 4, "OFFLINE", None, 9)], []])
    avisos: list[str] = []
    [archivo] = diagnostico.archivos_danados(consulta_de(conexion), PDBS_DE_LA_INSTANCIA, avisos)
    assert archivo.contenedor is None
    assert any("CON_ID 4" in aviso for aviso in avisos)


def test_los_bloques_corruptos_tambien_se_consultan_sin_v_containers() -> None:
    conexion = sin_v_containers([[(17, 131, 1, "CHECKSUM", "C:\\X\\A1_01.DBF", "A1", 3)]])
    [bloque] = diagnostico.bloques_corruptos(consulta_de(conexion), PDBS_DE_LA_INSTANCIA)
    assert (bloque.file_id, bloque.bloque, bloque.contenedor) == (17, 131, "CLIENTEPDB")


def test_si_la_instancia_no_esta_disponible_no_se_reintenta_sin_v_containers() -> None:
    llamadas: list[str] = []

    def consulta(sql: str, parametros: dict[str, Any]) -> list[tuple[Any, ...]]:
        llamadas.append(sql)
        raise RuntimeError("ORA-01034: ORACLE not available")

    with pytest.raises(RuntimeError, match="ORA-01034"):
        diagnostico.archivos_danados(consulta)
    assert len(llamadas) == 1


def test_codigos_que_indican_instancia_no_disponible_o_base_no_montada() -> None:
    for texto in (
        "ORA-01034: ORACLE not available",
        "ORA-12560: TNS:protocol adapter error",
        "ORA-01507: database not mounted",
    ):
        assert diagnostico.instancia_no_disponible(RuntimeError(texto)), texto
    for texto in (
        "ORA-00942: table or view does not exist",
        "ORA-01219: database not open",
        "ORA-01031: insufficient privileges",
    ):
        assert not diagnostico.instancia_no_disponible(RuntimeError(texto)), texto


def test_archivo_existe_distingue_ausente_de_no_verificable(tmp_path: Any) -> None:
    presente = tmp_path / "REDO01.LOG"
    presente.write_bytes(b"")
    assert diagnostico.archivo_existe(str(presente))
    assert not diagnostico.archivo_existe(str(tmp_path / "REDO02.LOG"))
    assert not diagnostico.archivo_existe(str(presente / "REDO03.LOG"))
    assert diagnostico.archivo_existe("+DATA/XE/ONLINELOG/group_1.262.1")


def test_el_estado_de_las_pdb_se_lee_de_v_pdbs() -> None:
    def consulta(sql: str, parametros: dict[str, Any]) -> list[tuple[Any, ...]]:
        assert "v$pdbs" in sql
        return [(2, "PDB$SEED", "READ ONLY"), (3, "CLIENTEPDB", "mounted")]

    pdbs = diagnostico.estado_pdbs(consulta)
    assert pdbs == [
        EstadoPdb(con_id=2, nombre="PDB$SEED", modo="READ ONLY"),
        EstadoPdb(con_id=3, nombre="CLIENTEPDB", modo="MOUNTED"),
    ]
    assert [p.cerrada for p in pdbs] == [False, True]


def test_un_diagnostico_incompleto_no_cuenta_como_sano() -> None:
    incompleto = Diagnostico(bd="XE", generado_en=datetime(2026, 10, 11, 9, 0), fallo_consulta=True)
    assert not incompleto.sin_danos
    assert diagnostico.sugerir(incompleto) == []
    assert "no se pudo completar" in diagnostico.resumen(incompleto)
