from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time

from cloudcr_backup.domain.enums import (
    EstadoEjecucion,
    ModoRespaldo,
    PoliticaOmision,
    TipoFrecuencia,
    TipoRespaldo,
)
from cloudcr_backup.domain.estrategia import Programacion, Ventana
from cloudcr_backup.domain.planificacion import EjecucionPendiente, TareaProgramable

APROBADO_EN = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def tarea_programable(
    tarea_id: int = 3,
    tipo: TipoFrecuencia = TipoFrecuencia.INTERVALO,
    intervalo: int | None = 5,
    horas: list[time] | None = None,
    politica: PoliticaOmision = PoliticaOmision.EJECUTAR_EN_VENTANA,
    ventana: Ventana | None = None,
    aprobado_en: datetime | None = APROBADO_EN,
    fecha_inicio: date | None = None,
    modo: ModoRespaldo = ModoRespaldo.EN_LINEA,
) -> TareaProgramable:
    return TareaProgramable(
        tarea_id=tarea_id,
        bd_id=1,
        bd_nombre="XE",
        estrategia_id=2,
        estrategia_codigo="EST001",
        tarea_codigo=f"T{tarea_id}",
        tipo_respaldo=TipoRespaldo.COMPLETO,
        modo_respaldo=modo,
        programacion=Programacion(
            tipo_frecuencia=tipo,
            intervalo_minutos=intervalo,
            horas=horas or [],
            politica_omision=politica,
            ventana=ventana,
            fecha_inicio=fecha_inicio,
        ),
        script_id=9,
        aprobado_en=aprobado_en,
    )


@dataclass
class EjecucionMemoria:
    id: int
    tarea_id: int
    programada_para: datetime
    estado: EstadoEjecucion
    motivo: str | None = None
    agente: str | None = None
    iniciada: bool = False


@dataclass
class FuenteMemoria:
    tareas: list[TareaProgramable] = field(default_factory=list)
    ejecuciones: list[EjecucionMemoria] = field(default_factory=list)

    def _siguiente_id(self) -> int:
        return len(self.ejecuciones) + 1

    def _existe(self, tarea_id: int, programada_para: datetime) -> bool:
        return any(e.tarea_id == tarea_id and e.programada_para == programada_para for e in self.ejecuciones)

    def tareas_programables(self) -> list[TareaProgramable]:
        return list(self.tareas)

    def ultima_programada_por_tarea(self) -> dict[int, datetime]:
        ultimas: dict[int, datetime] = {}
        for ejecucion in self.ejecuciones:
            actual = ultimas.get(ejecucion.tarea_id)
            if actual is None or ejecucion.programada_para > actual:
                ultimas[ejecucion.tarea_id] = ejecucion.programada_para
        return ultimas

    def reclamar(self, tarea_id: int, programada_para: datetime) -> int | None:
        if self._existe(tarea_id, programada_para):
            return None
        ejecucion = EjecucionMemoria(self._siguiente_id(), tarea_id, programada_para, EstadoEjecucion.PROGRAMADA)
        self.ejecuciones.append(ejecucion)
        return ejecucion.id

    def registrar_no_ejecutada(self, tarea_id: int, programada_para: datetime, motivo: str) -> bool:
        if self._existe(tarea_id, programada_para):
            return False
        self.ejecuciones.append(
            EjecucionMemoria(self._siguiente_id(), tarea_id, programada_para, EstadoEjecucion.NO_EJECUTADA, motivo)
        )
        return True

    def programadas_sin_iniciar(self, antes_de: datetime) -> list[EjecucionPendiente]:
        return [
            EjecucionPendiente(e.id, e.tarea_id, e.programada_para)
            for e in self.ejecuciones
            if e.estado is EstadoEjecucion.PROGRAMADA and not e.iniciada and e.programada_para < antes_de
        ]

    def marcar_no_ejecutada(self, ejecucion_id: int, motivo: str) -> bool:
        for ejecucion in self.ejecuciones:
            if ejecucion.id == ejecucion_id and ejecucion.estado is EstadoEjecucion.PROGRAMADA:
                ejecucion.estado = EstadoEjecucion.NO_EJECUTADA
                ejecucion.motivo = motivo
                return True
        return False

    def por_estado(self, estado: EstadoEjecucion) -> list[EjecucionMemoria]:
        return [e for e in self.ejecuciones if e.estado is estado]
