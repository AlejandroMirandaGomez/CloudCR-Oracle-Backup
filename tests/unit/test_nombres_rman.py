from datetime import datetime

from cloudcr_backup.rman import nombres


def test_tag_tiene_el_formato_de_la_clase() -> None:
    assert nombres.tag("EST001", "T1", datetime(2026, 9, 30, 15, 0)) == "EST001_T1_2609301500"


def test_tag_nunca_supera_30_caracteres_y_conserva_la_marca() -> None:
    tag = nombres.tag("ESTRATEGIA-MUY-LARGA-DE-PRUEBA", "TAREA_LARGA", datetime(2026, 10, 4, 1, 5))
    assert len(tag) <= nombres.LARGO_MAXIMO_TAG
    assert tag.endswith("_2610040105")
    assert tag.replace("_", "").isalnum()


def test_command_id() -> None:
    assert nombres.command_id(42) == "CLOUDCR_42"


def test_formato_de_pieza_en_windows_y_linux() -> None:
    assert nombres.formato_pieza("C:\\backups\\XE\\", "EST004", "T1") == "C:\\backups\\XE\\%d_EST004_T1_%T_%U.bkp"
    assert nombres.formato_pieza("/u01/backups/", "est001", "t1") == "/u01/backups/%d_EST001_T1_%T_%U.bkp"
    assert nombres.formato_autobackup("C:\\") == "C:\\%F"


def test_convencion_de_nombres_del_profesor() -> None:
    assert nombres.nombre_script("EST001", "XE") == "EST001.XE.RMAN"
    assert nombres.nombre_log("EST001", "XE") == "EST001.XE.LOG"
    assert nombres.nombre_script("EST004", "xe", "T2", 3) == "EST004.XE.T2.V3.RMAN"
    assert nombres.archivo_script_aprobado("T1", 2) == "T1_v2.rman"


def test_tag_de_una_ejecucion_manual_lleva_los_segundos() -> None:
    assert nombres.tag("EST001", "T1", datetime(2026, 10, 4, 13, 5, 12)) == "EST001_T1_261004130512"
    assert len(nombres.tag("ESTRATEGIA-LARGUISIMA", "T10", datetime(2026, 10, 4, 13, 5, 12))) <= 30
