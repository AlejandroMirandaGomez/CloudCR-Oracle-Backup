from datetime import datetime
from typing import Any

from cloudcr_backup.domain.enums import EstadoEjecucion, EstadoPrueba, LogMode
from cloudcr_backup.domain.recuperacion import ArchivoDanado, Escenario
from cloudcr_backup.recovery import diagnostico, puntos
from cloudcr_backup.recovery.procedimientos import SolicitudProcedimiento, generar
from cloudcr_backup.repository.ejecuciones import EjecucionDetallada
from cloudcr_backup.repository.piezas import PiezaRegistrada
from cloudcr_backup.strategy.yaml_io import cargar_estrategia_yaml
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
    assert any("nunca lo ejecuta" in paso for paso in procedimiento.pasos)


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


def test_total_noarchivelog() -> None:
    procedimiento = generar(solicitud(Escenario.TOTAL_NOARCHIVELOG, log_mode=LogMode.NOARCHIVELOG))
    assert procedimiento.script == (
        "SHUTDOWN IMMEDIATE;\nSTARTUP MOUNT;\nRESTORE DATABASE;\nRECOVER DATABASE NOREDO;\n"
        "ALTER DATABASE OPEN RESETLOGS;\n"
    )
    assert procedimiento.avisos == []
    assert generar(solicitud(Escenario.TOTAL_NOARCHIVELOG)).avisos


def test_controlfile_con_pieza_o_autobackup() -> None:
    con_pieza = generar(
        solicitud(
            Escenario.CONTROLFILE,
            dbid=3114375768,
            destino_autobackup="C:\\backups\\XE",
            pieza_controlfile="C:\\b\\c.bkp",
        )
    )
    assert "SET DBID 3114375768;" in (con_pieza.script or "")
    assert "RESTORE CONTROLFILE FROM 'C:\\b\\c.bkp';" in (con_pieza.script or "")
    autobackup = generar(solicitud(Escenario.CONTROLFILE, dbid=1, destino_autobackup="C:\\backups\\XE"))
    assert "SET CONTROLFILE AUTOBACKUP FORMAT FOR DEVICE TYPE DISK TO 'C:\\backups\\XE\\%F';" in (
        autobackup.script or ""
    )
    assert "RESTORE CONTROLFILE FROM AUTOBACKUP;" in (autobackup.script or "")
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
