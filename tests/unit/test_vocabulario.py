from cloudcr_backup.domain.enums import TipoRespaldo
from cloudcr_backup.strategy.vocabulario import equivalencia_de, etiqueta_doble, todas_las_equivalencias


def test_incremental_n0_usa_las_dos_etiquetas_exactas() -> None:
    assert etiqueta_doble(TipoRespaldo.INCREMENTAL_N0) == "Incremental nivel 0 (total+)"


def test_completo_referencia_backup_database() -> None:
    equivalencia = equivalencia_de(TipoRespaldo.COMPLETO)
    assert equivalencia.clausula_rman == "BACKUP DATABASE"


def test_incremental_n1_diferencial_y_acumulativo_usan_clausulas_distintas() -> None:
    diferencial = equivalencia_de(TipoRespaldo.INCREMENTAL_N1_DIFERENCIAL)
    acumulativo = equivalencia_de(TipoRespaldo.INCREMENTAL_N1_ACUMULATIVO)
    assert diferencial.clausula_rman == "BACKUP INCREMENTAL LEVEL 1"
    assert acumulativo.clausula_rman == "BACKUP INCREMENTAL LEVEL 1 CUMULATIVE"
    assert diferencial.clausula_rman != acumulativo.clausula_rman


def test_todas_las_equivalencias_cubren_los_cinco_tipos_de_respaldo() -> None:
    assert {e.tipo for e in todas_las_equivalencias()} == set(TipoRespaldo)


def test_archivelog_no_duplica_la_etiqueta_cuando_coincide() -> None:
    assert etiqueta_doble(TipoRespaldo.ARCHIVELOG) == "Archived logs"
