from collections.abc import Iterable
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from cloudcr_backup.domain.enums import DiaSemana, TipoRespaldo
from cloudcr_backup.domain.recuperacion import (
    CalendarioSemanal,
    DiaCalendario,
    FallaDetectada,
    FilaCalendario,
    MarcaCalendario,
    PuntoRecuperacion,
)
from cloudcr_backup.scheduling.reloj import utc_consciente

HORAS_DEL_DIA = 24
DIAS = list(DiaSemana)
SIMBOLO_RESPALDO = {
    TipoRespaldo.COMPLETO: "●",
    TipoRespaldo.INCREMENTAL_N0: "◆",
    TipoRespaldo.INCREMENTAL_N1_DIFERENCIAL: "▲",
    TipoRespaldo.INCREMENTAL_N1_ACUMULATIVO: "■",
    TipoRespaldo.ARCHIVELOG: "·",
}
ETIQUETA_RESPALDO = {
    TipoRespaldo.COMPLETO: "Completo",
    TipoRespaldo.INCREMENTAL_N0: "Incremental nivel 0",
    TipoRespaldo.INCREMENTAL_N1_DIFERENCIAL: "Incremental nivel 1 diferencial",
    TipoRespaldo.INCREMENTAL_N1_ACUMULATIVO: "Incremental nivel 1 acumulativo",
    TipoRespaldo.ARCHIVELOG: "Archived logs",
}
SIMBOLO_FALLA = "⚠"
ETIQUETA_FALLA = "Falla detectada"
LEYENDA = [*((SIMBOLO_RESPALDO[t], ETIQUETA_RESPALDO[t]) for t in TipoRespaldo), (SIMBOLO_FALLA, ETIQUETA_FALLA)]


def lunes_de(dia: date) -> date:
    return dia - timedelta(days=dia.weekday())


def _local(momento: datetime, zona: ZoneInfo) -> datetime:
    return utc_consciente(momento).astimezone(zona)


def _marca_respaldo(punto: PuntoRecuperacion, momento: datetime) -> MarcaCalendario:
    alcance = "base completa" if punto.base_completa else ", ".join(punto.alcance) or "sin alcance registrado"
    return MarcaCalendario(
        momento=momento,
        simbolo=SIMBOLO_RESPALDO[punto.tipo_respaldo],
        etiqueta=ETIQUETA_RESPALDO[punto.tipo_respaldo],
        detalle=(
            f"Ejecución {punto.ejecucion_id} · {punto.estrategia}/{punto.tarea} · {alcance} · "
            f"pruebas {punto.estado_prueba.value} · {momento:%Y-%m-%d %H:%M}"
        ),
        tipo_respaldo=punto.tipo_respaldo,
        ejecucion_id=punto.ejecucion_id,
    )


def _marca_falla(falla: FallaDetectada, momento: datetime) -> MarcaCalendario:
    return MarcaCalendario(
        momento=momento,
        simbolo=SIMBOLO_FALLA,
        etiqueta=ETIQUETA_FALLA,
        detalle=f"Falla detectada en {momento:%Y-%m-%d %H:%M}: {falla.resumen}",
        falla=True,
    )


def construir(
    bd: str,
    puntos: Iterable[PuntoRecuperacion],
    fallas: Iterable[FallaDetectada],
    dia_de_la_semana: date,
    nombre_zona: str,
) -> CalendarioSemanal:
    zona = ZoneInfo(nombre_zona)
    inicio = lunes_de(dia_de_la_semana)
    fin = inicio + timedelta(days=6)
    celdas: list[list[list[MarcaCalendario]]] = [[[] for _ in DIAS] for _ in range(HORAS_DEL_DIA)]
    respaldos = 0
    marcas_falla = []
    for punto in puntos:
        if punto.completado_en is None:
            continue
        momento = _local(punto.completado_en, zona)
        if inicio <= momento.date() <= fin:
            celdas[momento.hour][momento.weekday()].append(_marca_respaldo(punto, momento))
            respaldos += 1
    for falla in fallas:
        momento = _local(falla.detectada_en, zona)
        if inicio <= momento.date() <= fin:
            marca = _marca_falla(falla, momento)
            celdas[momento.hour][momento.weekday()].append(marca)
            marcas_falla.append(marca)
    for fila in celdas:
        for celda in fila:
            celda.sort(key=lambda m: m.momento)
    return CalendarioSemanal(
        bd=bd,
        zona=nombre_zona,
        inicio=inicio,
        fin=fin,
        anterior=inicio - timedelta(days=7),
        siguiente=inicio + timedelta(days=7),
        dias=[DiaCalendario(dia=dia, fecha=inicio + timedelta(days=numero)) for numero, dia in enumerate(DIAS)],
        filas=[FilaCalendario(hora=hora, celdas=celdas[hora]) for hora in range(HORAS_DEL_DIA)],
        respaldos=respaldos,
        fallas=sorted(marcas_falla, key=lambda m: m.momento),
        leyenda=LEYENDA,
    )
