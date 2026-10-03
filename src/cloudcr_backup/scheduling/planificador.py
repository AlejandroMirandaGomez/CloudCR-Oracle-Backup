from collections.abc import Collection
from datetime import datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from cloudcr_backup.domain.enums import PoliticaOmision
from cloudcr_backup.domain.planificacion import (
    EjecucionPendiente,
    EjecucionReclamada,
    OcurrenciaPerdida,
    ResultadoPlanificacion,
    TareaProgramable,
)
from cloudcr_backup.scheduling.recurrencia import ProgramacionInvalida, construir_regla
from cloudcr_backup.scheduling.reloj import utc_consciente
from cloudcr_backup.scheduling.ventana import misma_instancia

MOTIVO_AGENTE_DETENIDO = "No ejecutada: el agente estaba detenido o sin capacidad cuando correspondía."
MOTIVO_OMITIR = "No ejecutada: se perdió la hora programada y la política de omisión es OMITIR."
MOTIVO_FUERA_DE_VENTANA = "No ejecutada: se perdió la hora programada y ya pasó su ventana de respaldo."
MOTIVO_SIN_VENTANA = (
    "No ejecutada: se perdió la hora programada y la tarea no tiene ventana de respaldo para recuperarla."
)
MOTIVO_HUERFANA = "No ejecutada: fue reclamada por un agente que se detuvo antes de iniciarla."

GRACIA_POR_DEFECTO = timedelta(minutes=15)
HORIZONTE_POR_DEFECTO = timedelta(hours=24)


class FuentePlanificador(Protocol):
    def tareas_programables(self) -> list[TareaProgramable]: ...

    def ultima_programada_por_tarea(self) -> dict[int, datetime]: ...

    def reclamar(self, tarea_id: int, programada_para: datetime) -> int | None: ...

    def registrar_no_ejecutada(self, tarea_id: int, programada_para: datetime, motivo: str) -> bool: ...

    def programadas_sin_iniciar(self, antes_de: datetime) -> list[EjecucionPendiente]: ...

    def marcar_no_ejecutada(self, ejecucion_id: int, motivo: str) -> bool: ...


class Planificador:
    def __init__(
        self,
        fuente: FuentePlanificador,
        gracia: timedelta = GRACIA_POR_DEFECTO,
        horizonte: timedelta = HORIZONTE_POR_DEFECTO,
    ) -> None:
        self._fuente = fuente
        self._gracia = gracia
        self._horizonte = horizonte

    def desde_para(self, tarea: TareaProgramable, ultima: datetime | None, ahora: datetime) -> datetime:
        referencias = [utc_consciente(m) for m in (ultima, tarea.aprobado_en) if m is not None]
        desde = max(referencias) if referencias else ahora - self._gracia
        return max(desde, ahora - self._horizonte)

    def reclamar_vencidas(self, ahora: datetime, excluir: Collection[int] = ()) -> ResultadoPlanificacion:
        ahora = utc_consciente(ahora)
        reclamadas: list[EjecucionReclamada] = []
        no_ejecutadas: list[OcurrenciaPerdida] = []
        errores: list[str] = []
        ultimas = self._fuente.ultima_programada_por_tarea()
        for tarea in self._fuente.tareas_programables():
            try:
                self._planificar(tarea, ultimas.get(tarea.tarea_id), ahora, reclamadas, no_ejecutadas)
            except (ProgramacionInvalida, ValueError) as error:
                errores.append(f"{tarea.etiqueta}: {error}")
        huerfanas = self._cerrar_huerfanas(ahora, excluir)
        return ResultadoPlanificacion(
            reclamadas=reclamadas, no_ejecutadas=no_ejecutadas, huerfanas=huerfanas, errores=errores
        )

    def ocurrencias_perdidas(self, ahora: datetime) -> list[OcurrenciaPerdida]:
        ahora = utc_consciente(ahora)
        ultimas = self._fuente.ultima_programada_por_tarea()
        perdidas: list[OcurrenciaPerdida] = []
        for tarea in self._fuente.tareas_programables():
            try:
                regla = construir_regla(tarea.programacion)
            except ProgramacionInvalida:
                continue
            desde = self.desde_para(tarea, ultimas.get(tarea.tarea_id), ahora)
            for momento in regla.ocurrencias_entre(desde, ahora - self._gracia):
                perdidas.append(OcurrenciaPerdida(tarea.tarea_id, momento, MOTIVO_AGENTE_DETENIDO))
        return perdidas

    def proxima_ejecucion(self, tarea: TareaProgramable, ahora: datetime) -> datetime | None:
        try:
            proximas = construir_regla(tarea.programacion).proximas(utc_consciente(ahora), 1)
        except ProgramacionInvalida:
            return None
        return proximas[0] if proximas else None

    def _planificar(
        self,
        tarea: TareaProgramable,
        ultima: datetime | None,
        ahora: datetime,
        reclamadas: list[EjecucionReclamada],
        no_ejecutadas: list[OcurrenciaPerdida],
    ) -> None:
        regla = construir_regla(tarea.programacion)
        pendientes = regla.ocurrencias_entre(self.desde_para(tarea, ultima, ahora), ahora)
        if not pendientes:
            return
        for momento in pendientes[:-1]:
            self._no_ejecutada(tarea, momento, MOTIVO_AGENTE_DETENIDO, no_ejecutadas)
        ultima_ocurrencia = pendientes[-1]
        if ahora - ultima_ocurrencia <= self._gracia:
            self._reclamar(tarea, ultima_ocurrencia, False, reclamadas)
            return
        motivo = self._motivo_para_no_recuperar(tarea, ultima_ocurrencia, ahora, regla.zona)
        if motivo is None:
            self._reclamar(tarea, ultima_ocurrencia, True, reclamadas)
        else:
            self._no_ejecutada(tarea, ultima_ocurrencia, motivo, no_ejecutadas)

    def _motivo_para_no_recuperar(
        self, tarea: TareaProgramable, ocurrencia: datetime, ahora: datetime, zona: ZoneInfo
    ) -> str | None:
        programacion = tarea.programacion
        politica = programacion.politica_omision
        if politica is PoliticaOmision.EJECUTAR_SIEMPRE:
            return None
        if politica is PoliticaOmision.OMITIR:
            return MOTIVO_OMITIR
        if programacion.ventana is None:
            return MOTIVO_SIN_VENTANA
        if misma_instancia(programacion.ventana, ocurrencia, ahora, zona):
            return None
        return MOTIVO_FUERA_DE_VENTANA

    def _reclamar(
        self, tarea: TareaProgramable, momento: datetime, tardia: bool, reclamadas: list[EjecucionReclamada]
    ) -> None:
        ejecucion_id = self._fuente.reclamar(tarea.tarea_id, momento)
        if ejecucion_id is not None:
            reclamadas.append(EjecucionReclamada(ejecucion_id, tarea.tarea_id, momento, tardia))

    def _no_ejecutada(
        self, tarea: TareaProgramable, momento: datetime, motivo: str, no_ejecutadas: list[OcurrenciaPerdida]
    ) -> None:
        if self._fuente.registrar_no_ejecutada(tarea.tarea_id, momento, motivo):
            no_ejecutadas.append(OcurrenciaPerdida(tarea.tarea_id, momento, motivo))

    def _cerrar_huerfanas(self, ahora: datetime, excluir: Collection[int]) -> list[EjecucionPendiente]:
        cerradas = []
        for pendiente in self._fuente.programadas_sin_iniciar(ahora - self._gracia):
            if pendiente.ejecucion_id in excluir:
                continue
            if self._fuente.marcar_no_ejecutada(pendiente.ejecucion_id, MOTIVO_HUERFANA):
                cerradas.append(pendiente)
        return cerradas
