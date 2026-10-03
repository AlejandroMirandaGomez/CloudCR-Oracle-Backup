from cloudcr_backup.domain.enums import Severidad
from cloudcr_backup.domain.hallazgos import Hallazgo
from cloudcr_backup.domain.perfil_bd import PerfilBD, RitmoCambioLog
from cloudcr_backup.oracle.observaciones import observar


def _red_003(perfil: PerfilBD) -> list[Hallazgo]:
    return [h for h in observar(perfil) if h.codigo == "RED_003"]


def _con_ritmo(perfil: PerfilBD, cambios: int, horas: float) -> PerfilBD:
    return perfil.model_copy(update={"ritmo_cambio_log": RitmoCambioLog(cambios=cambios, horas_observadas=horas)})


def test_fixture_real_solo_informa_falta_de_datos(perfil_xe: PerfilBD) -> None:
    hallazgos = _red_003(perfil_xe)
    assert [h.severidad for h in hallazgos] == [Severidad.INFORMATIVA]
    assert "No hay datos suficientes" in hallazgos[0].mensaje
    assert hallazgos[0].sujeto == "redo"


def test_menos_de_dos_grupos_es_advertencia(perfil_xe: PerfilBD) -> None:
    perfil = _con_ritmo(perfil_xe.model_copy(update={"redo_grupos": perfil_xe.redo_grupos[:1]}), 49, 24)
    hallazgos = _red_003(perfil)
    assert [h.severidad for h in hallazgos] == [Severidad.ADVERTENCIA]
    assert "al menos 2" in hallazgos[0].mensaje


def test_dos_o_mas_grupos_no_advierte(perfil_xe: PerfilBD) -> None:
    perfil = _con_ritmo(perfil_xe, 49, 24)
    assert all(h.severidad is not Severidad.ADVERTENCIA for h in _red_003(perfil))


def test_grupos_de_tamanos_distintos_es_recomendacion(perfil_xe: PerfilBD) -> None:
    grupos = [perfil_xe.redo_grupos[0].model_copy(update={"bytes": 52428800}), *perfil_xe.redo_grupos[1:]]
    perfil = _con_ritmo(perfil_xe.model_copy(update={"redo_grupos": grupos}), 49, 24)
    hallazgos = _red_003(perfil)
    assert [h.severidad for h in hallazgos] == [Severidad.RECOMENDACION]
    assert "mismo tamaño" in hallazgos[0].mensaje
    assert "grupo 1: 50 MB" in hallazgos[0].mensaje


def test_grupos_del_mismo_tamano_no_recomiendan(perfil_xe: PerfilBD) -> None:
    assert _red_003(_con_ritmo(perfil_xe, 49, 24)) == []


def test_log_switch_demasiado_frecuente(perfil_xe: PerfilBD) -> None:
    hallazgos = _red_003(_con_ritmo(perfil_xe, 241, 24))
    assert [h.severidad for h in hallazgos] == [Severidad.RECOMENDACION]
    assert "cada 6 minutos" in hallazgos[0].mensaje
    assert "Aumentar el tamaño" in (hallazgos[0].accion_sugerida or "")


def test_log_switch_demasiado_espaciado(perfil_xe: PerfilBD) -> None:
    hallazgos = _red_003(_con_ritmo(perfil_xe, 13, 24))
    assert [h.severidad for h in hallazgos] == [Severidad.RECOMENDACION]
    assert "cada 120 minutos" in hallazgos[0].mensaje
    assert "Reducir" in (hallazgos[0].accion_sugerida or "")


def test_log_switch_dentro_del_rango_no_genera_hallazgo(perfil_xe: PerfilBD) -> None:
    assert _red_003(_con_ritmo(perfil_xe, 49, 24)) == []
    assert _red_003(_con_ritmo(perfil_xe, 97, 24)) == []


def test_pocos_cambios_no_alcanzan_para_medir(perfil_xe: PerfilBD) -> None:
    hallazgos = _red_003(_con_ritmo(perfil_xe, 3, 2))
    assert [h.severidad for h in hallazgos] == [Severidad.INFORMATIVA]


def test_ritmo_promedio() -> None:
    assert RitmoCambioLog(cambios=49, horas_observadas=24).minutos_promedio == 30
    assert RitmoCambioLog(cambios=1, horas_observadas=24).minutos_promedio is None
    assert RitmoCambioLog(cambios=5, horas_observadas=0).minutos_promedio is None
