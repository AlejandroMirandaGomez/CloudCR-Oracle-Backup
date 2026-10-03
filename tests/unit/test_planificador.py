from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from cloudcr_backup.domain.enums import EstadoEjecucion, PoliticaOmision, TipoFrecuencia
from cloudcr_backup.domain.estrategia import Ventana
from cloudcr_backup.scheduling.planificador import (
    MOTIVO_AGENTE_DETENIDO,
    MOTIVO_FUERA_DE_VENTANA,
    MOTIVO_HUERFANA,
    MOTIVO_OMITIR,
    MOTIVO_SIN_VENTANA,
    Planificador,
)
from tests.unit.fuentes_falsas import EjecucionMemoria, FuenteMemoria, tarea_programable

COSTA_RICA = ZoneInfo("America/Costa_Rica")
GRACIA = timedelta(minutes=15)


def _cr(dia: int, hora: int, minuto: int = 0) -> datetime:
    return datetime(2026, 10, dia, hora, minuto, tzinfo=COSTA_RICA)


def _diaria(hora: int, **cambios: object) -> FuenteMemoria:
    tarea = tarea_programable(tipo=TipoFrecuencia.DIARIA, intervalo=None, horas=[time(hora, 0)], **cambios)  # type: ignore[arg-type]
    fuente = FuenteMemoria(tareas=[tarea])
    fuente.ejecuciones.append(
        EjecucionMemoria(99, tarea.tarea_id, _cr(1, hora).astimezone(UTC), EstadoEjecucion.EXITOSA)
    )
    return fuente


def test_tick_normal_reclama_la_ocurrencia_que_acaba_de_vencer() -> None:
    fuente = _diaria(13)
    resultado = Planificador(fuente, GRACIA).reclamar_vencidas(_cr(2, 13) + timedelta(seconds=20))
    assert [r.programada_para for r in resultado.reclamadas] == [_cr(2, 13)]
    assert not resultado.reclamadas[0].tardia
    assert resultado.no_ejecutadas == []


def test_antes_de_la_hora_no_reclama_nada() -> None:
    fuente = _diaria(13)
    assert Planificador(fuente, GRACIA).reclamar_vencidas(_cr(2, 12, 59)).reclamadas == []


def test_ocurrencia_dentro_de_la_gracia_se_ejecuta_sin_marcarse_tardia() -> None:
    fuente = _diaria(13)
    resultado = Planificador(fuente, GRACIA).reclamar_vencidas(_cr(2, 13, 14))
    assert len(resultado.reclamadas) == 1
    assert not resultado.reclamadas[0].tardia


def test_dos_ticks_seguidos_no_reclaman_dos_veces() -> None:
    fuente = _diaria(13)
    planificador = Planificador(fuente, GRACIA)
    assert len(planificador.reclamar_vencidas(_cr(2, 13, 0) + timedelta(seconds=5)).reclamadas) == 1
    assert planificador.reclamar_vencidas(_cr(2, 13, 0) + timedelta(seconds=35)).reclamadas == []


def test_dos_agentes_contra_la_misma_fuente_no_duplican() -> None:
    fuente = _diaria(13)
    momento = _cr(2, 13, 1)
    primero = Planificador(fuente, GRACIA).reclamar_vencidas(momento)
    segundo = Planificador(fuente, GRACIA).reclamar_vencidas(momento)
    assert len(primero.reclamadas) == 1
    assert segundo.reclamadas == []
    assert len(fuente.por_estado(EstadoEjecucion.PROGRAMADA)) == 1


def test_doble_reclamo_de_la_misma_ocurrencia_devuelve_none() -> None:
    fuente = FuenteMemoria()
    assert fuente.reclamar(3, _cr(2, 13)) is not None
    assert fuente.reclamar(3, _cr(2, 13)) is None


def test_agente_detenido_registra_no_ejecutadas_y_reclama_la_ultima() -> None:
    tarea = tarea_programable(intervalo=5)
    fuente = FuenteMemoria(tareas=[tarea])
    fuente.ejecuciones.append(EjecucionMemoria(99, 3, _cr(2, 10, 0).astimezone(UTC), EstadoEjecucion.EXITOSA))
    resultado = Planificador(fuente, GRACIA).reclamar_vencidas(_cr(2, 10, 21))
    assert [o.programada_para for o in resultado.no_ejecutadas] == [_cr(2, 10, 5), _cr(2, 10, 10), _cr(2, 10, 15)]
    assert {o.motivo for o in resultado.no_ejecutadas} == {MOTIVO_AGENTE_DETENIDO}
    assert [r.programada_para for r in resultado.reclamadas] == [_cr(2, 10, 20)]


def test_politica_ejecutar_siempre_recupera_tarde() -> None:
    fuente = _diaria(13, politica=PoliticaOmision.EJECUTAR_SIEMPRE)
    resultado = Planificador(fuente, GRACIA).reclamar_vencidas(_cr(2, 16))
    assert resultado.reclamadas[0].tardia
    assert resultado.no_ejecutadas == []


def test_politica_omitir_registra_no_ejecutada() -> None:
    fuente = _diaria(13, politica=PoliticaOmision.OMITIR)
    resultado = Planificador(fuente, GRACIA).reclamar_vencidas(_cr(2, 16))
    assert resultado.reclamadas == []
    assert [o.motivo for o in resultado.no_ejecutadas] == [MOTIVO_OMITIR]


def test_ejecutar_en_ventana_recupera_dentro_de_la_misma_ventana() -> None:
    ventana = Ventana(inicio=time(12, 30), fin=time(22, 0))
    fuente = _diaria(13, ventana=ventana)
    resultado = Planificador(fuente, GRACIA).reclamar_vencidas(_cr(2, 16))
    assert resultado.reclamadas[0].tardia


def test_ejecutar_en_ventana_fuera_de_la_ventana_no_ejecuta() -> None:
    ventana = Ventana(inicio=time(12, 30), fin=time(14, 0))
    fuente = _diaria(13, ventana=ventana)
    resultado = Planificador(fuente, GRACIA).reclamar_vencidas(_cr(2, 16))
    assert resultado.reclamadas == []
    assert [o.motivo for o in resultado.no_ejecutadas] == [MOTIVO_FUERA_DE_VENTANA]


def test_ventana_nocturna_recupera_en_la_madrugada() -> None:
    ventana = Ventana(inicio=time(22, 30), fin=time(2, 0))
    fuente = _diaria(23, ventana=ventana)
    resultado = Planificador(fuente, GRACIA).reclamar_vencidas(_cr(3, 1, 30))
    assert [r.programada_para for r in resultado.reclamadas] == [_cr(2, 23)]
    assert resultado.reclamadas[0].tardia


def test_ejecutar_en_ventana_sin_ventana_no_ejecuta() -> None:
    fuente = _diaria(13)
    resultado = Planificador(fuente, GRACIA).reclamar_vencidas(_cr(2, 16))
    assert [o.motivo for o in resultado.no_ejecutadas] == [MOTIVO_SIN_VENTANA]


def test_huerfanas_viejas_pasan_a_no_ejecutadas() -> None:
    fuente = FuenteMemoria()
    fuente.ejecuciones.append(EjecucionMemoria(1, 3, _cr(2, 9, 0).astimezone(UTC), EstadoEjecucion.PROGRAMADA))
    fuente.ejecuciones.append(EjecucionMemoria(2, 3, _cr(2, 9, 55).astimezone(UTC), EstadoEjecucion.PROGRAMADA))
    resultado = Planificador(fuente, GRACIA).reclamar_vencidas(_cr(2, 10))
    assert [h.ejecucion_id for h in resultado.huerfanas] == [1]
    assert fuente.ejecuciones[0].motivo == MOTIVO_HUERFANA
    assert fuente.ejecuciones[1].estado is EstadoEjecucion.PROGRAMADA


def test_las_huerfanas_en_la_cola_local_no_se_tocan() -> None:
    fuente = FuenteMemoria()
    fuente.ejecuciones.append(EjecucionMemoria(1, 3, _cr(2, 9, 0).astimezone(UTC), EstadoEjecucion.PROGRAMADA))
    resultado = Planificador(fuente, GRACIA).reclamar_vencidas(_cr(2, 10), excluir={1})
    assert resultado.huerfanas == []
    assert fuente.ejecuciones[0].estado is EstadoEjecucion.PROGRAMADA


def test_la_aprobacion_posterior_corta_las_perdidas() -> None:
    tarea = tarea_programable(intervalo=5, aprobado_en=_cr(2, 10, 12).astimezone(UTC))
    fuente = FuenteMemoria(tareas=[tarea])
    fuente.ejecuciones.append(EjecucionMemoria(99, 3, _cr(2, 9, 0).astimezone(UTC), EstadoEjecucion.EXITOSA))
    resultado = Planificador(fuente, GRACIA).reclamar_vencidas(_cr(2, 10, 21))
    assert [o.programada_para for o in resultado.no_ejecutadas] == [_cr(2, 10, 15)]
    assert [r.programada_para for r in resultado.reclamadas] == [_cr(2, 10, 20)]


def test_el_horizonte_limita_cuanto_se_mira_hacia_atras() -> None:
    tarea = tarea_programable(intervalo=60, aprobado_en=_cr(1, 0).astimezone(UTC))
    fuente = FuenteMemoria(tareas=[tarea])
    resultado = Planificador(fuente, GRACIA, horizonte=timedelta(hours=3)).reclamar_vencidas(_cr(5, 12, 1))
    assert len(resultado.no_ejecutadas) == 2
    assert len(resultado.reclamadas) == 1


def test_sin_fecha_de_aprobacion_mira_solo_la_gracia() -> None:
    tarea = tarea_programable(intervalo=5, aprobado_en=None)
    fuente = FuenteMemoria(tareas=[tarea])
    resultado = Planificador(fuente, GRACIA).reclamar_vencidas(_cr(2, 10, 1))
    assert [o.programada_para for o in resultado.no_ejecutadas] == [_cr(2, 9, 50), _cr(2, 9, 55)]
    assert [r.programada_para for r in resultado.reclamadas] == [_cr(2, 10)]


def test_programacion_invalida_no_detiene_a_las_demas() -> None:
    mala = tarea_programable(tarea_id=4, tipo=TipoFrecuencia.DIARIA, intervalo=None)
    buena = tarea_programable(tarea_id=3, intervalo=5)
    fuente = FuenteMemoria(tareas=[mala, buena])
    fuente.ejecuciones.append(EjecucionMemoria(99, 3, _cr(2, 9, 55).astimezone(UTC), EstadoEjecucion.EXITOSA))
    resultado = Planificador(fuente, GRACIA).reclamar_vencidas(_cr(2, 10) + timedelta(seconds=10))
    assert len(resultado.reclamadas) == 1
    assert len(resultado.errores) == 1
    assert "T4" in resultado.errores[0]


def test_ocurrencias_perdidas_solo_cuenta_las_vencidas_sin_reclamar() -> None:
    tarea = tarea_programable(intervalo=5)
    fuente = FuenteMemoria(tareas=[tarea])
    fuente.ejecuciones.append(EjecucionMemoria(99, 3, _cr(2, 10, 0).astimezone(UTC), EstadoEjecucion.EXITOSA))
    perdidas = Planificador(fuente, GRACIA).ocurrencias_perdidas(_cr(2, 10, 31))
    assert [p.programada_para for p in perdidas] == [_cr(2, 10, 5), _cr(2, 10, 10), _cr(2, 10, 15)]
    assert fuente.ejecuciones[1:] == []


def test_proxima_ejecucion() -> None:
    tarea = tarea_programable(tipo=TipoFrecuencia.DIARIA, intervalo=None, horas=[time(13, 0), time(21, 0)])
    planificador = Planificador(FuenteMemoria(tareas=[tarea]), GRACIA)
    assert planificador.proxima_ejecucion(tarea, _cr(2, 14)) == _cr(2, 21)
    invalida = tarea_programable(tipo=TipoFrecuencia.DIARIA, intervalo=None)
    assert planificador.proxima_ejecucion(invalida, _cr(2, 14)) is None
