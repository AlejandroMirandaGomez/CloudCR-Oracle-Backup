from collections.abc import Callable
from dataclasses import dataclass
from datetime import time
from enum import StrEnum

from cloudcr_backup.domain.enums import DiaSemana, ModoRespaldo, PoliticaOmision, TipoFrecuencia, TipoRespaldo
from cloudcr_backup.domain.estrategia import Como, Destino, Programacion, Tarea, Ventana


@dataclass(frozen=True)
class ParametrosEsquema:
    destino: Destino
    dia_n0: DiaSemana
    hora_n0: time
    hora_n1: time
    intervalo_archivelog_minutos: int = 240
    ventana: Ventana | None = None
    politica_omision: PoliticaOmision = PoliticaOmision.EJECUTAR_EN_VENTANA


def _tarea_n0(parametros: ParametrosEsquema, modo: ModoRespaldo = ModoRespaldo.AUTO) -> Tarea:
    return Tarea(
        codigo="T1",
        como=Como(tipo_respaldo=TipoRespaldo.INCREMENTAL_N0, modo_respaldo=modo),
        programacion=Programacion(
            tipo_frecuencia=TipoFrecuencia.SEMANAL,
            horas=[parametros.hora_n0],
            dias_semana=[parametros.dia_n0],
            ventana=parametros.ventana,
            politica_omision=parametros.politica_omision,
        ),
        destino=parametros.destino,
    )


def _tarea_n1(parametros: ParametrosEsquema, tipo: TipoRespaldo) -> Tarea:
    return Tarea(
        codigo="T2",
        como=Como(tipo_respaldo=tipo, modo_respaldo=ModoRespaldo.AUTO),
        programacion=Programacion(
            tipo_frecuencia=TipoFrecuencia.DIARIA,
            horas=[parametros.hora_n1],
            ventana=parametros.ventana,
            politica_omision=parametros.politica_omision,
        ),
        destino=parametros.destino,
    )


def _tarea_archivelog(parametros: ParametrosEsquema) -> Tarea:
    return Tarea(
        codigo="T3",
        como=Como(tipo_respaldo=TipoRespaldo.ARCHIVELOG, modo_respaldo=ModoRespaldo.EN_LINEA),
        programacion=Programacion(
            tipo_frecuencia=TipoFrecuencia.INTERVALO,
            intervalo_minutos=parametros.intervalo_archivelog_minutos,
            politica_omision=parametros.politica_omision,
        ),
        destino=parametros.destino,
    )


def _completo_semanal(parametros: ParametrosEsquema) -> list[Tarea]:
    return [
        Tarea(
            codigo="T1",
            como=Como(tipo_respaldo=TipoRespaldo.COMPLETO, modo_respaldo=ModoRespaldo.AUTO),
            programacion=Programacion(
                tipo_frecuencia=TipoFrecuencia.SEMANAL,
                horas=[parametros.hora_n0],
                dias_semana=[parametros.dia_n0],
                ventana=parametros.ventana,
                politica_omision=parametros.politica_omision,
            ),
            destino=parametros.destino,
        )
    ]


def _n0_semanal_n1_diferencial_diario(parametros: ParametrosEsquema) -> list[Tarea]:
    return [_tarea_n0(parametros), _tarea_n1(parametros, TipoRespaldo.INCREMENTAL_N1_DIFERENCIAL)]


def _n0_semanal_n1_acumulativo_diario(parametros: ParametrosEsquema) -> list[Tarea]:
    return [_tarea_n0(parametros), _tarea_n1(parametros, TipoRespaldo.INCREMENTAL_N1_ACUMULATIVO)]


def _n0_n1_acumulativo_con_archivelogs(parametros: ParametrosEsquema) -> list[Tarea]:
    return [*_n0_semanal_n1_acumulativo_diario(parametros), _tarea_archivelog(parametros)]


def _consistente_para_noarchivelog(parametros: ParametrosEsquema) -> list[Tarea]:
    return [_tarea_n0(parametros, modo=ModoRespaldo.CONSISTENTE)]


class EsquemaPredefinido(StrEnum):
    COMPLETO_SEMANAL = "COMPLETO_SEMANAL"
    N0_SEMANAL_N1_DIFERENCIAL_DIARIO = "N0_SEMANAL_N1_DIFERENCIAL_DIARIO"
    N0_SEMANAL_N1_ACUMULATIVO_DIARIO = "N0_SEMANAL_N1_ACUMULATIVO_DIARIO"
    N0_N1_ACUMULATIVO_CON_ARCHIVELOGS = "N0_N1_ACUMULATIVO_CON_ARCHIVELOGS"
    CONSISTENTE_NOARCHIVELOG = "CONSISTENTE_NOARCHIVELOG"


@dataclass(frozen=True)
class DescripcionEsquema:
    esquema: EsquemaPredefinido
    nombre: str
    descripcion: str
    constructor: Callable[[ParametrosEsquema], list[Tarea]]


_ESQUEMAS: dict[EsquemaPredefinido, DescripcionEsquema] = {
    EsquemaPredefinido.COMPLETO_SEMANAL: DescripcionEsquema(
        esquema=EsquemaPredefinido.COMPLETO_SEMANAL,
        nombre="Completo semanal",
        descripcion="Un respaldo completo cada semana. Simple, pero el más costoso en tiempo y espacio.",
        constructor=_completo_semanal,
    ),
    EsquemaPredefinido.N0_SEMANAL_N1_DIFERENCIAL_DIARIO: DescripcionEsquema(
        esquema=EsquemaPredefinido.N0_SEMANAL_N1_DIFERENCIAL_DIARIO,
        nombre="Nivel 0 semanal + nivel 1 diferencial diario",
        descripcion="Reduce el tamaño de los respaldos diarios frente al completo semanal.",
        constructor=_n0_semanal_n1_diferencial_diario,
    ),
    EsquemaPredefinido.N0_SEMANAL_N1_ACUMULATIVO_DIARIO: DescripcionEsquema(
        esquema=EsquemaPredefinido.N0_SEMANAL_N1_ACUMULATIVO_DIARIO,
        nombre="Nivel 0 semanal + nivel 1 acumulativo diario",
        descripcion="Simplifica la recuperación frente al diferencial, a costa de respaldos diarios más grandes.",
        constructor=_n0_semanal_n1_acumulativo_diario,
    ),
    EsquemaPredefinido.N0_N1_ACUMULATIVO_CON_ARCHIVELOGS: DescripcionEsquema(
        esquema=EsquemaPredefinido.N0_N1_ACUMULATIVO_CON_ARCHIVELOGS,
        nombre="Nivel 0 + nivel 1 acumulativo + archived logs",
        descripcion="El esquema anterior más el respaldo periódico de archived logs, para prioridad alta.",
        constructor=_n0_n1_acumulativo_con_archivelogs,
    ),
    EsquemaPredefinido.CONSISTENTE_NOARCHIVELOG: DescripcionEsquema(
        esquema=EsquemaPredefinido.CONSISTENTE_NOARCHIVELOG,
        nombre="Consistente para NOARCHIVELOG",
        descripcion="Respaldo consistente (con caída del servicio) para bases que todavía no están en ARCHIVELOG.",
        constructor=_consistente_para_noarchivelog,
    ),
}


def tareas_de(esquema: EsquemaPredefinido, parametros: ParametrosEsquema) -> list[Tarea]:
    return _ESQUEMAS[esquema].constructor(parametros)


def todos_los_esquemas() -> list[DescripcionEsquema]:
    return list(_ESQUEMAS.values())
