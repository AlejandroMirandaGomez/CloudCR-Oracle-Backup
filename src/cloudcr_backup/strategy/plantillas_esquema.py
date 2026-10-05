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
    que_hace: str
    ideal_para: str
    nota: str
    rotulo_dia: str
    rotulo_hora_principal: str
    constructor: Callable[[ParametrosEsquema], list[Tarea]]
    rotulo_hora_n1: str = ""

    @property
    def descripcion(self) -> str:
        return self.que_hace


ROTULO_DIA_NIVEL_0 = "Día del nivel 0"
ROTULO_HORA_NIVEL_0 = "Hora del nivel 0"
ROTULO_HORA_N1_DIFERENCIAL = "Hora del nivel 1 diferencial (diario)"
ROTULO_HORA_N1_ACUMULATIVO = "Hora del nivel 1 acumulativo (diario)"

_ESQUEMAS: dict[EsquemaPredefinido, DescripcionEsquema] = {
    EsquemaPredefinido.COMPLETO_SEMANAL: DescripcionEsquema(
        esquema=EsquemaPredefinido.COMPLETO_SEMANAL,
        nombre="Completo semanal",
        que_hace=(
            "Un solo tipo de respaldo: una copia completa de la base una vez por semana, el día y la hora que elija."
        ),
        ideal_para="Prioridad baja o bases pequeñas. Restaurar es simple, porque solo se necesita esa copia.",
        nota=(
            "Es la copia que más tiempo y espacio consume. Si la base falla, se pierden los cambios desde la última "
            "copia, hasta 7 días. No sirve como base para respaldos incrementales."
        ),
        rotulo_dia="Día del respaldo completo",
        rotulo_hora_principal="Hora del respaldo completo",
        constructor=_completo_semanal,
    ),
    EsquemaPredefinido.N0_SEMANAL_N1_DIFERENCIAL_DIARIO: DescripcionEsquema(
        esquema=EsquemaPredefinido.N0_SEMANAL_N1_DIFERENCIAL_DIARIO,
        nombre="Nivel 0 semanal + nivel 1 diferencial diario",
        que_hace=(
            "Dos tipos de respaldo: una copia base (nivel 0) por semana y, cada día, un nivel 1 diferencial. Este "
            "guarda solo los bloques que cambiaron desde el respaldo anterior."
        ),
        ideal_para="Prioridad media. Los respaldos diarios son pequeños y rápidos.",
        nota=(
            "Para restaurar se necesitan el nivel 0 y todos los nivel 1 posteriores. Si falta uno, los siguientes no "
            "sirven. Se pueden perder hasta 24 horas de cambios."
        ),
        rotulo_dia=ROTULO_DIA_NIVEL_0,
        rotulo_hora_principal=ROTULO_HORA_NIVEL_0,
        rotulo_hora_n1=ROTULO_HORA_N1_DIFERENCIAL,
        constructor=_n0_semanal_n1_diferencial_diario,
    ),
    EsquemaPredefinido.N0_SEMANAL_N1_ACUMULATIVO_DIARIO: DescripcionEsquema(
        esquema=EsquemaPredefinido.N0_SEMANAL_N1_ACUMULATIVO_DIARIO,
        nombre="Nivel 0 semanal + nivel 1 acumulativo diario",
        que_hace=(
            "Dos tipos de respaldo: un nivel 0 por semana y, cada día, un nivel 1 acumulativo. Este guarda todo lo "
            "que cambió desde el último nivel 0."
        ),
        ideal_para=(
            "Cuando importa más la restauración que el tamaño: solo se necesitan el nivel 0 y el último acumulativo."
        ),
        nota=(
            "Los respaldos diarios crecen cada día hasta el siguiente nivel 0, así que el último de la semana es el "
            "más grande. Se pueden perder hasta 24 horas de cambios."
        ),
        rotulo_dia=ROTULO_DIA_NIVEL_0,
        rotulo_hora_principal=ROTULO_HORA_NIVEL_0,
        rotulo_hora_n1=ROTULO_HORA_N1_ACUMULATIVO,
        constructor=_n0_semanal_n1_acumulativo_diario,
    ),
    EsquemaPredefinido.N0_N1_ACUMULATIVO_CON_ARCHIVELOGS: DescripcionEsquema(
        esquema=EsquemaPredefinido.N0_N1_ACUMULATIVO_CON_ARCHIVELOGS,
        nombre="Nivel 0 + nivel 1 acumulativo + archived logs",
        que_hace=(
            "Tres tipos de respaldo: un nivel 0 semanal, un nivel 1 acumulativo diario y el respaldo de los archived "
            "logs cada cierto intervalo (240 minutos por defecto)."
        ),
        ideal_para="Prioridad alta. Permite recuperar a un punto en el tiempo, no solo al momento de un respaldo.",
        nota=(
            "Solo funciona con la base en ARCHIVELOG. Cuanto más corto el intervalo, menos cambios quedan sin "
            "respaldar; redúzcalo si necesita perder menos de 4 horas."
        ),
        rotulo_dia=ROTULO_DIA_NIVEL_0,
        rotulo_hora_principal=ROTULO_HORA_NIVEL_0,
        rotulo_hora_n1=ROTULO_HORA_N1_ACUMULATIVO,
        constructor=_n0_n1_acumulativo_con_archivelogs,
    ),
    EsquemaPredefinido.CONSISTENTE_NOARCHIVELOG: DescripcionEsquema(
        esquema=EsquemaPredefinido.CONSISTENTE_NOARCHIVELOG,
        nombre="Consistente para NOARCHIVELOG",
        que_hace=(
            "Un solo tipo de respaldo: un nivel 0 semanal en modo consistente. Apaga la base, copia con la base "
            "montada y la vuelve a abrir."
        ),
        ideal_para="Bases que no están en ARCHIVELOG, donde un respaldo con la base abierta no sirve para recuperar.",
        nota=(
            "La base queda fuera de servicio mientras dura el respaldo. Solo se puede volver al momento de la copia y "
            "todo lo posterior se pierde. Si es posible, conviene pasar la base a ARCHIVELOG."
        ),
        rotulo_dia="Día del respaldo consistente",
        rotulo_hora_principal="Hora del respaldo consistente",
        constructor=_consistente_para_noarchivelog,
    ),
}


def tareas_de(esquema: EsquemaPredefinido, parametros: ParametrosEsquema) -> list[Tarea]:
    return _ESQUEMAS[esquema].constructor(parametros)


def todos_los_esquemas() -> list[DescripcionEsquema]:
    return list(_ESQUEMAS.values())
