from pathlib import Path

import pytest

from cloudcr_backup.domain.enums import (
    Compresion,
    LogMode,
    ModoRespaldo,
    Prioridad,
    TipoObjeto,
    TipoRespaldo,
)
from cloudcr_backup.domain.estrategia import Estrategia, ObjetoAlcance, Tarea
from cloudcr_backup.rman.constructor import ScriptNoGenerable, SolicitudScript, construir, modo_efectivo
from cloudcr_backup.strategy.yaml_io import cargar_estrategia_yaml

RAIZ = Path(__file__).resolve().parents[2]
ESTRATEGIAS = RAIZ / "config" / "estrategias"
ORO = RAIZ / "tests" / "fixtures" / "scripts_oro"


def estrategia(codigo: str) -> Estrategia:
    return cargar_estrategia_yaml(ESTRATEGIAS / f"{codigo.lower()}.yaml")


def tarea_de(est: Estrategia, codigo: str) -> Tarea:
    tarea = est.tarea(codigo)
    assert tarea is not None
    return tarea


def con_compresion(tarea: Tarea, compresion: Compresion) -> Tarea:
    opciones = tarea.como.opciones.model_copy(update={"compresion": compresion})
    return tarea.model_copy(update={"como": tarea.como.model_copy(update={"opciones": opciones})})


def oro(nombre: str) -> bytes:
    return (ORO / nombre).read_bytes()


def generar(est: Estrategia, tarea: Tarea, log_mode: LogMode, es_cdb: bool = True) -> str:
    return construir(SolicitudScript(estrategia=est, tarea=tarea, log_mode=log_mode, es_cdb=es_cdb)).contenido


def test_est004_t1_es_identico_al_oro() -> None:
    est = estrategia("EST004")
    tarea = con_compresion(tarea_de(est, "T1"), Compresion.BASIC)
    assert generar(est, tarea, LogMode.ARCHIVELOG).encode("ascii") == oro("est004_t1.rman")


def test_est001_t1_es_identico_al_oro() -> None:
    est = estrategia("EST001")
    assert generar(est, tarea_de(est, "T1"), LogMode.ARCHIVELOG).encode("ascii") == oro("est001_t1.rman")


def test_est002_t1_es_identico_al_oro() -> None:
    est = estrategia("EST002")
    assert generar(est, tarea_de(est, "T1"), LogMode.NOARCHIVELOG).encode("ascii") == oro("est002_t1.rman")


def test_est004_t3_es_identico_al_oro() -> None:
    est = estrategia("EST004")
    assert generar(est, tarea_de(est, "T3"), LogMode.ARCHIVELOG).encode("ascii") == oro("est004_t3.rman")


def test_los_scripts_son_ascii_con_fin_de_linea_unix_y_sin_bom() -> None:
    est = estrategia("EST002")
    contenido = generar(est, tarea_de(est, "T1"), LogMode.NOARCHIVELOG).encode("ascii")
    assert b"\r" not in contenido
    assert not contenido.startswith(b"\xef\xbb\xbf")
    assert contenido.endswith(b"}\nALTER DATABASE OPEN;\nALTER PLUGGABLE DATABASE ALL OPEN;\n")


def test_nunca_usa_configure_y_el_tag_y_el_command_id_son_variables() -> None:
    for codigo, tarea, modo in (("EST004", "T1", LogMode.ARCHIVELOG), ("EST002", "T1", LogMode.NOARCHIVELOG)):
        est = estrategia(codigo)
        contenido = generar(est, tarea_de(est, tarea), modo)
        assert "CONFIGURE" not in contenido
        assert "SET COMMAND ID TO '&2';" in contenido
        assert "TAG '&1'" in contenido


def test_modo_auto_resuelve_segun_log_mode() -> None:
    est = estrategia("EST004")
    como = tarea_de(est, "T1").como
    assert modo_efectivo(como, LogMode.ARCHIVELOG) is ModoRespaldo.EN_LINEA
    assert modo_efectivo(como, LogMode.NOARCHIVELOG) is ModoRespaldo.CONSISTENTE


def test_auto_en_noarchivelog_genera_un_respaldo_consistente_sin_plus_archivelog() -> None:
    est = estrategia("EST004")
    resultado = construir(SolicitudScript(estrategia=est, tarea=tarea_de(est, "T1"), log_mode=LogMode.NOARCHIVELOG))
    assert resultado.modo is ModoRespaldo.CONSISTENTE
    assert resultado.requiere_caida
    assert resultado.contenido.startswith("SHUTDOWN IMMEDIATE;\nSTARTUP MOUNT;\n")
    assert "PLUS ARCHIVELOG" not in resultado.contenido


def test_algoritmo_de_compresion_explicito_va_antes_del_run() -> None:
    est = estrategia("EST001")
    tarea = con_compresion(tarea_de(est, "T1"), Compresion.MEDIUM)
    contenido = generar(est, tarea, LogMode.ARCHIVELOG)
    assert contenido.index("SET COMPRESSION ALGORITHM 'MEDIUM';") < contenido.index("RUN {")
    assert "BACKUP AS COMPRESSED BACKUPSET INCREMENTAL LEVEL 1 CUMULATIVE TABLESPACE" in contenido


def test_completo_parcial_omite_solo_lectura() -> None:
    est = estrategia("EST003")
    tarea = tarea_de(est, "T1")
    opciones = tarea.como.opciones.model_copy(update={"omitir_solo_lectura": True})
    tarea = tarea.model_copy(update={"como": tarea.como.model_copy(update={"opciones": opciones})})
    contenido = generar(est, tarea, LogMode.ARCHIVELOG)
    assert "  BACKUP TABLESPACE XEPDB1:RRHH SKIP READONLY TAG '&1';\n" in contenido
    assert "CONTROLFILE" not in contenido.replace("CONTROLFILE AUTOBACKUP", "")


def test_pdb_domina_sus_tablespaces_y_hay_una_sentencia_por_grupo() -> None:
    est = estrategia("EST001").model_copy(
        update={
            "alcance": [
                ObjetoAlcance(tipo=TipoObjeto.TABLESPACE, identificador="xepdb1:ventas", prioridad=Prioridad.ALTA),
                ObjetoAlcance(tipo=TipoObjeto.PDB, identificador="XEPDB1", prioridad=Prioridad.ALTA),
                ObjetoAlcance(tipo=TipoObjeto.TABLESPACE, identificador="USERS", prioridad=Prioridad.MEDIA),
                ObjetoAlcance(tipo=TipoObjeto.DATAFILE, identificador="7", prioridad=Prioridad.MEDIA),
                ObjetoAlcance(tipo=TipoObjeto.ARCHIVELOG, identificador="", prioridad=Prioridad.MEDIA),
            ]
        }
    )
    contenido = generar(est, tarea_de(est, "T1"), LogMode.ARCHIVELOG)
    assert (
        "  BACKUP INCREMENTAL LEVEL 1 CUMULATIVE PLUGGABLE DATABASE XEPDB1 TAG '&1' PLUS ARCHIVELOG;\n"
        "  BACKUP INCREMENTAL LEVEL 1 CUMULATIVE TABLESPACE USERS TAG '&1';\n"
        "  BACKUP INCREMENTAL LEVEL 1 CUMULATIVE DATAFILE 7 TAG '&1';\n"
    ) in contenido
    assert "VENTAS" not in contenido


def test_varios_canales_se_asignan_y_liberan() -> None:
    est = estrategia("EST004")
    tarea = tarea_de(est, "T2")
    opciones = tarea.como.opciones.model_copy(update={"canales": 2})
    tarea = tarea.model_copy(update={"como": tarea.como.model_copy(update={"opciones": opciones})})
    contenido = generar(est, tarea, LogMode.ARCHIVELOG)
    assert "ALLOCATE CHANNEL c2 DEVICE TYPE DISK" in contenido
    assert "RELEASE CHANNEL c2;" in contenido
    assert "BACKUP INCREMENTAL LEVEL 1 DATABASE TAG '&1' PLUS ARCHIVELOG;" in contenido


def test_archivelog_en_noarchivelog_no_se_puede_generar() -> None:
    est = estrategia("EST004")
    with pytest.raises(ScriptNoGenerable, match="NOARCHIVELOG"):
        generar(est, tarea_de(est, "T3"), LogMode.NOARCHIVELOG)


def test_alcance_vacio_no_se_puede_generar() -> None:
    est = estrategia("EST001").model_copy(update={"alcance": []})
    with pytest.raises(ScriptNoGenerable, match="alcance"):
        generar(est, tarea_de(est, "T1"), LogMode.ARCHIVELOG)


def test_destino_no_ascii_no_se_puede_generar() -> None:
    est = estrategia("EST001")
    tarea = tarea_de(est, "T1")
    tarea = tarea.model_copy(update={"destino": tarea.destino.model_copy(update={"ruta": "C:\\respaldos\\año"})})
    with pytest.raises(ScriptNoGenerable, match="ASCII"):
        generar(est, tarea, LogMode.ARCHIVELOG)


def test_bd_no_cdb_no_abre_pdbs_tras_el_consistente() -> None:
    est = estrategia("EST002")
    contenido = generar(est, tarea_de(est, "T1"), LogMode.NOARCHIVELOG, es_cdb=False)
    assert contenido.endswith("}\nALTER DATABASE OPEN;\n")


def test_datafile_invalido_no_se_puede_generar() -> None:
    est = estrategia("EST001").model_copy(
        update={"alcance": [ObjetoAlcance(tipo=TipoObjeto.DATAFILE, identificador="x", prioridad=Prioridad.ALTA)]}
    )
    with pytest.raises(ScriptNoGenerable, match="file#"):
        generar(est, tarea_de(est, "T1"), LogMode.ARCHIVELOG)


def test_tipo_completo_no_lleva_nivel() -> None:
    est = estrategia("EST002")
    tarea = tarea_de(est, "T1")
    tarea = tarea.model_copy(update={"como": tarea.como.model_copy(update={"tipo_respaldo": TipoRespaldo.COMPLETO})})
    contenido = generar(est, tarea, LogMode.NOARCHIVELOG)
    assert "  BACKUP DATABASE TAG '&1';\n" in contenido
