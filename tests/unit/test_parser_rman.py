from pathlib import Path

from cloudcr_backup.execution.parser import analizar

LOGS = Path(__file__).resolve().parents[1] / "fixtures" / "rman_logs"

EXITO_CON_ADVERTENCIA = """
Recovery Manager: Release 21.0.0.0.0 - Production on Sun Oct 4 03:10:00 2026
connected to target database: XE (DBID=3114375768)

RMAN> RUN {
2>   BACKUP ARCHIVELOG ALL NOT BACKED UP 1 TIMES TAG 'EST004_T3_2610040310';
3> }
channel c1: starting piece 1 at 2026-10-04 03:10:05
channel c1: finished piece 1 at 2026-10-04 03:10:09
piece handle=C:\\BACKUPS\\XE\\XE_EST004_T3_20261004_014K2V3B_1_1.BKP tag=EST004_T3_2610040310 comment=NONE
piece handle=C:\\BACKUPS\\XE\\XE_EST004_T3_20261004_014K2V3B_1_1.BKP tag=EST004_T3_2610040310 comment=NONE
RMAN-08137: WARNING: archived log not deleted, needed for standby or upstream capture process
Finished Control File and SPFILE Autobackup at 2026-10-04 03:10:12
piece handle=C:\\BACKUPS\\XE\\C-3114375768-20261004-00 comment=NONE

Recovery Manager complete.
"""


def test_el_log_real_de_noarchivelog_tiene_pila_de_error_aunque_diga_complete() -> None:
    log = analizar((LOGS / "fallo_rman06817_noarchivelog.log").read_text(encoding="utf-8"))
    assert log.completo
    assert log.conectado
    assert log.tiene_pila_error
    assert [e.codigo for e in log.errores] == ["RMAN-03002", "RMAN-06817"]
    assert log.primer_error is not None
    assert log.primer_error.codigo == "RMAN-06817"
    assert "NOARCHIVELOG" in log.primer_error.texto
    assert log.piezas == []


def test_ignora_el_eco_del_script_y_los_separadores() -> None:
    log = analizar("RMAN> BACKUP DATABASE TAG 'ORA-01234: falso';\nRMAN-00571: =====\nRMAN-00569: === PILA ===\n")
    assert log.errores == []


def test_extrae_piezas_sin_repetir_y_separa_advertencias() -> None:
    log = analizar(EXITO_CON_ADVERTENCIA)
    assert [p.handle for p in log.piezas] == [
        "C:\\BACKUPS\\XE\\XE_EST004_T3_20261004_014K2V3B_1_1.BKP",
        "C:\\BACKUPS\\XE\\C-3114375768-20261004-00",
    ]
    assert log.piezas[0].tag == "EST004_T3_2610040310"
    assert log.piezas[1].tag is None
    assert log.errores == []
    assert [a.codigo for a in log.advertencias] == ["RMAN-08137"]
    assert not log.tiene_pila_error


def test_codigos_de_advertencia_configurables() -> None:
    texto = "RMAN-06059: expected archived log not found\n"
    assert [e.codigo for e in analizar(texto).errores] == ["RMAN-06059"]
    configurado = analizar(texto, codigos_advertencia=["RMAN-06059"])
    assert configurado.errores == []
    assert [a.codigo for a in configurado.advertencias] == ["RMAN-06059"]


def test_mensajes_que_empiezan_con_warning_son_advertencias() -> None:
    log = analizar(EXITO_CON_ADVERTENCIA, codigos_advertencia=[])
    assert log.errores == []
    assert [a.codigo for a in log.advertencias] == ["RMAN-08137"]


def test_tolera_fin_de_linea_windows() -> None:
    log = analizar("connected to target database: XE\r\nRecovery Manager complete.\r\n")
    assert log.completo
    assert log.conectado


def test_el_log_real_del_respaldo_consistente_es_limpio_y_lista_las_piezas() -> None:
    log = analizar((LOGS / "exito_est002_consistente.log").read_text(encoding="utf-8"))
    assert log.completo
    assert log.errores == []
    assert log.advertencias == []
    assert not log.tiene_pila_error
    assert len(log.piezas) == 6
    assert all(p.tag == "EST002_T1_2610041008" for p in log.piezas[:5])
    assert log.piezas[5].handle.endswith("C-3114375768-20261004-00")


def test_el_log_real_de_reapertura_solo_trae_el_error_de_base_ya_abierta() -> None:
    log = analizar((LOGS / "asegurar_apertura_ya_abierta.log").read_text(encoding="utf-8"))
    assert {e.codigo for e in log.errores} <= {"RMAN-03002", "ORA-01531"}


def test_el_log_real_de_verificacion_con_pieza_borrada_trae_rman_06160() -> None:
    texto = (LOGS / "verificacion_pieza_expirada.log").read_text(encoding="utf-8", errors="replace")
    log = analizar(texto)
    assert "found to be 'EXPIRED'" in texto
    assert "RMAN-06160" in {e.codigo for e in log.errores}
