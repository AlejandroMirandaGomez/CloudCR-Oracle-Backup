from datetime import datetime, timedelta
from pathlib import Path

import pytest

from cloudcr_backup.domain.estrategia import Retencion
from cloudcr_backup.repository.piezas import PiezaRegistrada
from cloudcr_backup.retention import politica
from cloudcr_backup.retention.politica import PoliticaNoDefinida, PurgaNoPermitida

ORO = Path(__file__).resolve().parents[1] / "fixtures" / "scripts_oro"
AHORA = datetime(2026, 10, 4, 12, 0)

REPORTE = r"""
RMAN retention policy will be applied to the command
Report of obsolete backups and copies
Type                 Key    Completion Time    Filename/Handle
-------------------- ------ ------------------ --------------------
Backup Set           3      2026-09-01 02:00:10
  Backup Piece       3      2026-09-01 02:00:10 C:\BACKUPS\XE\XE_EST004_T1_20260901_03_1_1.BKP
Archive Log          12     2026-09-02 10:00:00 C:\APP\ARCH\ARC0000000012_1.0001
"""


def pieza(id_: int, ejecucion: int, fin: datetime, vence: datetime | None, ruta: str = "") -> PiezaRegistrada:
    return PiezaRegistrada(
        id=id_, ejecucion_id=ejecucion, nombre_archivo=ruta or rf"C:\B\{id_}.BKP", tamano_bytes=100, tag="T",
        vence_en=vence, obsoleta=False, estrategia_id=1, estrategia_codigo="EST004", tarea_codigo="T1", fin=fin,
    )


def test_script_de_informe_es_identico_al_oro() -> None:
    contenido = politica.script(Retencion(ventana_dias=30, archived_logs_dias=7))
    assert contenido.encode("ascii") == (ORO / "retencion_informe.rman").read_bytes()
    assert "DELETE" not in contenido
    assert "CONFIGURE" not in contenido


def test_script_de_purga_es_identico_al_oro_y_solo_con_purga_automatica() -> None:
    con_purga = Retencion(ventana_dias=30, archived_logs_dias=7, purga_automatica=True)
    assert politica.script(con_purga, purgar=True).encode("ascii") == (ORO / "retencion_purga.rman").read_bytes()
    with pytest.raises(PurgaNoPermitida, match="nunca los borra"):
        politica.script(Retencion(ventana_dias=30), purgar=True)


def test_redundancia_y_sin_politica() -> None:
    assert politica.script(Retencion(redundancia=2)) == "CROSSCHECK BACKUP;\nREPORT OBSOLETE REDUNDANCY 2;\n"
    with pytest.raises(PoliticaNoDefinida):
        politica.script(Retencion())
    with pytest.raises(PoliticaNoDefinida):
        politica.clausula(Retencion(ventana_dias=1, redundancia=1))


def test_describir() -> None:
    assert "solo informe" in politica.describir(Retencion(ventana_dias=30))
    assert "sin límite" in politica.describir(Retencion())
    assert "purga automática" in politica.describir(Retencion(redundancia=2, purga_automatica=True))


def test_vence_en() -> None:
    assert politica.vence_en(AHORA, Retencion(ventana_dias=30)) == AHORA + timedelta(days=30)
    assert politica.vence_en(AHORA, Retencion(redundancia=2)) is None


def test_lee_las_rutas_obsoletas_del_reporte_de_rman() -> None:
    assert politica.obsoletas_de_reporte(REPORTE) == [
        r"C:\BACKUPS\XE\XE_EST004_T1_20260901_03_1_1.BKP",
        r"C:\APP\ARCH\ARC0000000012_1.0001",
    ]


def test_vencidas_por_ventana() -> None:
    piezas = [pieza(1, 10, AHORA - timedelta(days=40), AHORA - timedelta(days=10)), pieza(2, 11, AHORA, AHORA)]
    resultado = politica.vencidas(piezas, Retencion(ventana_dias=30), AHORA + timedelta(seconds=1))
    assert [p.pieza_id for p in resultado] == [1, 2]
    assert politica.vencidas(piezas, Retencion(ventana_dias=30), AHORA)[0].pieza_id == 1


def test_vencidas_por_redundancia_conserva_las_ultimas_ejecuciones() -> None:
    piezas = [pieza(i, i, AHORA - timedelta(days=i), None) for i in range(1, 5)]
    resultado = politica.vencidas(piezas, Retencion(redundancia=2), AHORA)
    assert sorted(p.ejecucion_id for p in resultado) == [3, 4]


def test_vencidas_segun_rman() -> None:
    ruta = r"C:\BACKUPS\XE\XE_EST004_T1_20260901_03_1_1.BKP"
    piezas = [pieza(1, 1, AHORA, None, ruta.lower())]
    resultado = politica.vencidas(piezas, Retencion(), AHORA, politica.obsoletas_de_reporte(REPORTE))
    assert resultado[0].obsoleta_rman


LOGS = Path(__file__).resolve().parents[1] / "fixtures" / "rman_logs"


def test_report_obsolete_real_de_la_xe() -> None:
    from cloudcr_backup.execution.parser import analizar

    texto = (LOGS / "report_obsolete_redundancia.log").read_text(encoding="utf-8")
    assert politica.obsoletas_de_reporte(texto) == [
        r"C:\BACKUPS\XE\XE_EST002_T1_20261004_04541AE5_4_1_1.BKP",
        r"C:\BACKUPS\XE\XE_EST002_T1_20261004_05541AE7_5_1_1.BKP",
    ]
    ventana = (LOGS / "report_obsolete_ventana_sin_obsoletos.log").read_text(encoding="utf-8")
    assert politica.obsoletas_de_reporte(ventana) == []
    analizado = analizar(ventana)
    assert analizado.errores == []
    assert [a.codigo for a in analizado.advertencias] == ["RMAN-07553"]
