import time as cronometro
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from cloudcr_backup.domain.enums import DiaSemana, TipoFrecuencia
from cloudcr_backup.domain.estrategia import Programacion, Ventana
from cloudcr_backup.scheduling.recurrencia import (
    ProgramacionIncompleta,
    ProgramacionInvalida,
    campos_faltantes,
    construir_regla,
    ocurrencias_entre,
    proximas,
)
from cloudcr_backup.strategy.yaml_io import cargar_estrategia_yaml
from cloudcr_backup.validation.reglas.programacion import _campos_faltantes

COSTA_RICA = ZoneInfo("America/Costa_Rica")
NUEVA_YORK = ZoneInfo("America/New_York")
RAIZ = Path(__file__).resolve().parents[2]


def _cr(anio: int, mes: int, dia: int, hora: int = 0, minuto: int = 0) -> datetime:
    return datetime(anio, mes, dia, hora, minuto, tzinfo=COSTA_RICA)


def _horas(ocurrencias: list[datetime]) -> list[str]:
    return [o.strftime("%Y-%m-%d %H:%M") for o in ocurrencias]


def test_est001_t1_da_las_cuatro_horas_de_cada_dia() -> None:
    estrategia = cargar_estrategia_yaml(RAIZ / "config" / "estrategias" / "est001.yaml")
    tarea = estrategia.tarea("T1")
    assert tarea is not None
    ocurrencias = proximas(tarea.programacion, _cr(2026, 10, 2, 8), 10)
    assert _horas(ocurrencias) == [
        "2026-10-02 13:00",
        "2026-10-02 15:00",
        "2026-10-02 18:00",
        "2026-10-02 21:00",
        "2026-10-03 13:00",
        "2026-10-03 15:00",
        "2026-10-03 18:00",
        "2026-10-03 21:00",
        "2026-10-04 13:00",
        "2026-10-04 15:00",
    ]
    assert all(o.tzinfo is not None and o.utcoffset() == timedelta(hours=-6) for o in ocurrencias)


def test_horas_con_minutos_distintos_no_se_cruzan() -> None:
    programacion = Programacion(tipo_frecuencia=TipoFrecuencia.DIARIA, horas=[time(13, 0), time(15, 30)])
    ocurrencias = ocurrencias_entre(programacion, _cr(2026, 10, 2), _cr(2026, 10, 3))
    assert _horas(ocurrencias) == ["2026-10-02 13:00", "2026-10-02 15:30"]


def test_intervalo_es_exclusivo_al_inicio_e_inclusivo_al_final() -> None:
    programacion = Programacion(tipo_frecuencia=TipoFrecuencia.DIARIA, horas=[time(13, 0)])
    assert _horas(ocurrencias_entre(programacion, _cr(2026, 10, 2, 13), _cr(2026, 10, 3, 13))) == [
        "2026-10-03 13:00"
    ]
    primero = ocurrencias_entre(programacion, _cr(2026, 10, 2, 12), _cr(2026, 10, 2, 13))
    segundo = ocurrencias_entre(programacion, _cr(2026, 10, 2, 13), _cr(2026, 10, 2, 14))
    assert len(primero) == 1
    assert segundo == []


def test_semanal_usa_los_dias_indicados() -> None:
    programacion = Programacion(
        tipo_frecuencia=TipoFrecuencia.SEMANAL,
        horas=[time(2, 0)],
        dias_semana=[DiaSemana.LUNES, DiaSemana.JUEVES],
    )
    ocurrencias = ocurrencias_entre(programacion, _cr(2026, 10, 1, 3), _cr(2026, 10, 15, 3))
    assert _horas(ocurrencias) == ["2026-10-05 02:00", "2026-10-08 02:00", "2026-10-12 02:00", "2026-10-15 02:00"]
    assert {o.weekday() for o in ocurrencias} == {0, 3}


def test_mensual_usa_el_dia_de_la_fecha_de_inicio() -> None:
    programacion = Programacion(
        tipo_frecuencia=TipoFrecuencia.MENSUAL, horas=[time(1, 0)], fecha_inicio=date(2026, 1, 15)
    )
    ocurrencias = proximas(programacion, _cr(2026, 10, 2), 3)
    assert _horas(ocurrencias) == ["2026-10-15 01:00", "2026-11-15 01:00", "2026-12-15 01:00"]


def test_mensual_no_empieza_antes_de_la_fecha_de_inicio() -> None:
    programacion = Programacion(
        tipo_frecuencia=TipoFrecuencia.MENSUAL, horas=[time(1, 0)], fecha_inicio=date(2027, 3, 15)
    )
    assert _horas(proximas(programacion, _cr(2026, 10, 2), 1)) == ["2027-03-15 01:00"]


def test_una_vez_genera_una_sola_ocurrencia() -> None:
    programacion = Programacion(
        tipo_frecuencia=TipoFrecuencia.UNA_VEZ, horas=[time(23, 15)], fecha_inicio=date(2026, 10, 4)
    )
    assert _horas(proximas(programacion, _cr(2026, 10, 1), 5)) == ["2026-10-04 23:15"]
    assert proximas(programacion, _cr(2026, 10, 5), 5) == []


def test_una_vez_sin_hora_usa_la_medianoche() -> None:
    programacion = Programacion(tipo_frecuencia=TipoFrecuencia.UNA_VEZ, fecha_inicio=date(2026, 10, 4))
    assert _horas(proximas(programacion, _cr(2026, 10, 1), 1)) == ["2026-10-04 00:00"]


def test_intervalo_de_cinco_minutos() -> None:
    programacion = Programacion(tipo_frecuencia=TipoFrecuencia.INTERVALO, intervalo_minutos=5)
    ocurrencias = ocurrencias_entre(programacion, _cr(2026, 10, 2, 10, 2), _cr(2026, 10, 2, 10, 20))
    assert _horas(ocurrencias) == [
        "2026-10-02 10:05",
        "2026-10-02 10:10",
        "2026-10-02 10:15",
        "2026-10-02 10:20",
    ]


def test_intervalo_con_fecha_de_inicio_usa_esa_ancla() -> None:
    programacion = Programacion(
        tipo_frecuencia=TipoFrecuencia.INTERVALO,
        intervalo_minutos=240,
        fecha_inicio=date(2026, 10, 1),
        horas=[time(1, 30)],
    )
    assert _horas(proximas(programacion, _cr(2026, 10, 1), 3)) == [
        "2026-10-01 01:30",
        "2026-10-01 05:30",
        "2026-10-01 09:30",
    ]


def test_intervalo_respeta_la_ventana() -> None:
    programacion = Programacion(
        tipo_frecuencia=TipoFrecuencia.INTERVALO,
        intervalo_minutos=60,
        ventana=Ventana(inicio=time(22, 30), fin=time(2, 0)),
    )
    ocurrencias = ocurrencias_entre(programacion, _cr(2026, 10, 2, 12), _cr(2026, 10, 3, 12))
    assert _horas(ocurrencias) == [
        "2026-10-02 23:00",
        "2026-10-03 00:00",
        "2026-10-03 01:00",
        "2026-10-03 02:00",
    ]


def test_las_horas_fijas_no_se_filtran_por_la_ventana() -> None:
    programacion = Programacion(
        tipo_frecuencia=TipoFrecuencia.DIARIA,
        horas=[time(12, 0)],
        ventana=Ventana(inicio=time(22, 0), fin=time(2, 0)),
    )
    assert len(ocurrencias_entre(programacion, _cr(2026, 10, 2), _cr(2026, 10, 3))) == 1


@pytest.mark.parametrize(
    ("programacion", "faltantes"),
    [
        (Programacion(tipo_frecuencia=TipoFrecuencia.DIARIA), ["horas"]),
        (Programacion(tipo_frecuencia=TipoFrecuencia.SEMANAL, horas=[time(1, 0)]), ["dias_semana"]),
        (Programacion(tipo_frecuencia=TipoFrecuencia.MENSUAL), ["horas"]),
        (Programacion(tipo_frecuencia=TipoFrecuencia.INTERVALO), ["intervalo_minutos"]),
        (Programacion(tipo_frecuencia=TipoFrecuencia.UNA_VEZ), ["fecha_inicio"]),
    ],
)
def test_programacion_incompleta_lanza_excepcion_legible(programacion: Programacion, faltantes: list[str]) -> None:
    with pytest.raises(ProgramacionIncompleta) as error:
        construir_regla(programacion)
    assert error.value.faltantes == faltantes
    assert "incompleta" in str(error.value)
    assert faltantes[0] in str(error.value)


@pytest.mark.parametrize("tipo", list(TipoFrecuencia))
def test_la_condicion_de_incompleta_coincide_con_prg_002(tipo: TipoFrecuencia) -> None:
    for programacion in (
        Programacion(tipo_frecuencia=tipo),
        Programacion(tipo_frecuencia=tipo, horas=[time(1, 0)]),
        Programacion(tipo_frecuencia=tipo, horas=[time(1, 0)], dias_semana=[DiaSemana.LUNES]),
        Programacion(tipo_frecuencia=tipo, intervalo_minutos=5, fecha_inicio=date(2026, 1, 1)),
    ):
        assert campos_faltantes(programacion) == _campos_faltantes(programacion)


def test_zona_horaria_inexistente() -> None:
    programacion = Programacion(tipo_frecuencia=TipoFrecuencia.DIARIA, horas=[time(1, 0)], zona_horaria="Marte/Olimpo")
    with pytest.raises(ProgramacionInvalida):
        construir_regla(programacion)


def test_intervalo_no_positivo_es_invalido() -> None:
    with pytest.raises(ProgramacionInvalida):
        construir_regla(Programacion(tipo_frecuencia=TipoFrecuencia.INTERVALO, intervalo_minutos=0))


def test_horario_de_verano_respeta_la_hora_de_pared() -> None:
    programacion = Programacion(
        tipo_frecuencia=TipoFrecuencia.DIARIA, horas=[time(13, 0)], zona_horaria="America/New_York"
    )
    antes = datetime(2026, 3, 6, tzinfo=NUEVA_YORK)
    ocurrencias = ocurrencias_entre(programacion, antes, antes + timedelta(days=4))
    assert [o.strftime("%m-%d %H:%M") for o in ocurrencias] == [
        "03-06 13:00",
        "03-07 13:00",
        "03-08 13:00",
        "03-09 13:00",
    ]
    assert [o.astimezone(UTC).hour for o in ocurrencias] == [18, 18, 17, 17]


def test_hora_inexistente_por_horario_de_verano_se_corre_una_hora() -> None:
    programacion = Programacion(
        tipo_frecuencia=TipoFrecuencia.DIARIA, horas=[time(2, 30)], zona_horaria="America/New_York"
    )
    inicio = datetime(2026, 3, 8, tzinfo=NUEVA_YORK)
    ocurrencias = ocurrencias_entre(programacion, inicio, inicio + timedelta(days=1))
    assert [o.strftime("%H:%M") for o in ocurrencias] == ["03:30"]


def test_hora_repetida_por_fin_del_horario_de_verano_corre_una_sola_vez() -> None:
    programacion = Programacion(
        tipo_frecuencia=TipoFrecuencia.DIARIA, horas=[time(1, 30)], zona_horaria="America/New_York"
    )
    inicio = datetime(2026, 11, 1, tzinfo=NUEVA_YORK)
    assert len(ocurrencias_entre(programacion, inicio, inicio + timedelta(days=1))) == 1


def test_intervalo_con_ancla_antigua_es_rapido() -> None:
    programacion = Programacion(
        tipo_frecuencia=TipoFrecuencia.INTERVALO, intervalo_minutos=5, fecha_inicio=date(2015, 1, 1)
    )
    inicio = cronometro.perf_counter()
    ocurrencias = ocurrencias_entre(programacion, _cr(2026, 10, 2), _cr(2026, 10, 3))
    duracion = cronometro.perf_counter() - inicio
    assert len(ocurrencias) == 288
    assert duracion < 0.05


def test_diaria_con_fecha_de_inicio_antigua_es_rapida() -> None:
    programacion = Programacion(
        tipo_frecuencia=TipoFrecuencia.DIARIA, horas=[time(h, 0) for h in range(24)], fecha_inicio=date(2010, 1, 1)
    )
    inicio = cronometro.perf_counter()
    ocurrencias = ocurrencias_entre(programacion, _cr(2026, 10, 2), _cr(2026, 10, 3))
    assert len(ocurrencias) == 24
    assert cronometro.perf_counter() - inicio < 0.05


def test_entradas_en_utc_dan_resultado_en_la_zona_de_la_programacion() -> None:
    programacion = Programacion(tipo_frecuencia=TipoFrecuencia.DIARIA, horas=[time(13, 0)])
    ocurrencias = proximas(programacion, datetime(2026, 10, 2, 12, tzinfo=UTC), 1)
    assert ocurrencias[0].tzinfo == COSTA_RICA
    assert ocurrencias[0].astimezone(UTC) == datetime(2026, 10, 2, 19, tzinfo=UTC)


def test_rango_vacio_o_invertido() -> None:
    programacion = Programacion(tipo_frecuencia=TipoFrecuencia.DIARIA, horas=[time(13, 0)])
    assert ocurrencias_entre(programacion, _cr(2026, 10, 3), _cr(2026, 10, 2)) == []
    assert proximas(programacion, _cr(2026, 10, 3), 0) == []
