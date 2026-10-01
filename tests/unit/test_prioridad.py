from cloudcr_backup.domain.enums import Prioridad
from cloudcr_backup.strategy.prioridad import criterio_de, todos_los_criterios


def test_prioridad_alta_exige_rpo_y_rto_mas_estrictos_que_media() -> None:
    alta = criterio_de(Prioridad.ALTA)
    media = criterio_de(Prioridad.MEDIA)
    assert alta.rpo_horas < media.rpo_horas
    assert alta.rto_horas < media.rto_horas
    assert alta.recencia_maxima_horas < media.recencia_maxima_horas


def test_prioridad_media_exige_mas_que_baja() -> None:
    media = criterio_de(Prioridad.MEDIA)
    baja = criterio_de(Prioridad.BAJA)
    assert media.rpo_horas < baja.rpo_horas
    assert media.rto_horas < baja.rto_horas
    assert media.recencia_maxima_horas < baja.recencia_maxima_horas


def test_todos_los_criterios_cubren_las_tres_prioridades() -> None:
    criterios = todos_los_criterios()
    assert {c.prioridad for c in criterios} == set(Prioridad)


def test_cada_criterio_tiene_esquema_y_descripcion() -> None:
    for criterio in todos_los_criterios():
        assert criterio.esquema_sugerido
        assert criterio.descripcion
