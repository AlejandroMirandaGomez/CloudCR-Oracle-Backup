from cloudcr_backup.domain.enums import Compresion
from cloudcr_backup.oracle.capacidades import capacidades_de


def test_xe_solo_admite_ninguna_y_basic_con_un_canal() -> None:
    capacidades = capacidades_de("XE")
    assert capacidades.compresiones_soportadas == {Compresion.NINGUNA, Compresion.BASIC}
    assert capacidades.canales_maximos == 1
    assert capacidades.block_change_tracking is False


def test_enterprise_admite_todas_las_compresiones_y_mas_canales() -> None:
    capacidades = capacidades_de("EE")
    assert capacidades.compresiones_soportadas == set(Compresion)
    assert capacidades.canales_maximos > 1
    assert capacidades.block_change_tracking is True


def test_edicion_desconocida_usa_el_perfil_mas_restrictivo() -> None:
    assert capacidades_de("DESCONOCIDA") == capacidades_de("XE")


def test_la_busqueda_no_distingue_mayusculas() -> None:
    assert capacidades_de("xe") == capacidades_de("XE")
