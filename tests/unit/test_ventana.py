from datetime import datetime, time
from zoneinfo import ZoneInfo

from cloudcr_backup.domain.estrategia import Ventana
from cloudcr_backup.scheduling.ventana import contiene, instancia_de, misma_instancia

COSTA_RICA = ZoneInfo("America/Costa_Rica")
NOCTURNA = Ventana(inicio=time(22, 30), fin=time(2, 0))
DIURNA = Ventana(inicio=time(12, 30), fin=time(22, 0))


def _cr(dia: int, hora: int, minuto: int = 0) -> datetime:
    return datetime(2026, 10, dia, hora, minuto, tzinfo=COSTA_RICA)


def test_ventana_que_cruza_medianoche() -> None:
    assert contiene(NOCTURNA, _cr(2, 23, 45), COSTA_RICA)
    assert contiene(NOCTURNA, _cr(3, 1, 0), COSTA_RICA)
    assert not contiene(NOCTURNA, _cr(3, 3, 0), COSTA_RICA)


def test_ventana_normal() -> None:
    assert contiene(DIURNA, _cr(2, 13, 0), COSTA_RICA)
    assert not contiene(DIURNA, _cr(2, 23, 0), COSTA_RICA)
    assert not contiene(DIURNA, _cr(2, 8, 0), COSTA_RICA)


def test_bordes_exactos_son_inclusivos() -> None:
    assert contiene(NOCTURNA, _cr(2, 22, 30), COSTA_RICA)
    assert contiene(NOCTURNA, _cr(3, 2, 0), COSTA_RICA)
    assert not contiene(NOCTURNA, _cr(3, 2, 1), COSTA_RICA)
    assert not contiene(NOCTURNA, _cr(2, 22, 29), COSTA_RICA)
    assert contiene(DIURNA, _cr(2, 12, 30), COSTA_RICA)
    assert contiene(DIURNA, _cr(2, 22, 0), COSTA_RICA)


def test_se_evalua_en_la_zona_de_la_programacion() -> None:
    utc = ZoneInfo("UTC")
    assert contiene(NOCTURNA, datetime(2026, 10, 3, 5, 45, tzinfo=utc), COSTA_RICA)
    assert not contiene(NOCTURNA, datetime(2026, 10, 3, 9, 0, tzinfo=utc), COSTA_RICA)


def test_la_madrugada_pertenece_a_la_ventana_que_abrio_el_dia_anterior() -> None:
    instancia = instancia_de(NOCTURNA, _cr(3, 1, 0), COSTA_RICA)
    assert instancia is not None
    assert instancia.apertura == _cr(2, 22, 30)
    assert instancia.cierre == _cr(3, 2, 0)


def test_la_noche_abre_una_ventana_que_cierra_al_dia_siguiente() -> None:
    instancia = instancia_de(NOCTURNA, _cr(2, 23, 45), COSTA_RICA)
    assert instancia is not None
    assert instancia.apertura == _cr(2, 22, 30)
    assert instancia.cierre == _cr(3, 2, 0)


def test_fuera_de_la_ventana_no_hay_instancia() -> None:
    assert instancia_de(NOCTURNA, _cr(3, 3, 0), COSTA_RICA) is None


def test_misma_instancia() -> None:
    assert misma_instancia(NOCTURNA, _cr(2, 23, 0), _cr(3, 1, 30), COSTA_RICA)
    assert not misma_instancia(NOCTURNA, _cr(2, 23, 0), _cr(3, 23, 0), COSTA_RICA)
    assert misma_instancia(DIURNA, _cr(2, 13, 0), _cr(2, 21, 0), COSTA_RICA)
    assert not misma_instancia(DIURNA, _cr(2, 13, 0), _cr(3, 13, 0), COSTA_RICA)
