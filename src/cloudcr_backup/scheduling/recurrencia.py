from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dateutil import rrule

from cloudcr_backup.domain.enums import DiaSemana, TipoFrecuencia
from cloudcr_backup.domain.estrategia import Programacion
from cloudcr_backup.scheduling.reloj import utc_consciente

DIAS_DATEUTIL = {
    DiaSemana.LUNES: rrule.MO,
    DiaSemana.MARTES: rrule.TU,
    DiaSemana.MIERCOLES: rrule.WE,
    DiaSemana.JUEVES: rrule.TH,
    DiaSemana.VIERNES: rrule.FR,
    DiaSemana.SABADO: rrule.SA,
    DiaSemana.DOMINGO: rrule.SU,
}

ANCLA_INTERVALO_SIN_FECHA = datetime(2000, 1, 1)
MARGEN_LOCAL = timedelta(days=2)
HORIZONTE_INICIAL = timedelta(days=2)
HORIZONTE_MAXIMO = timedelta(days=366 * 5)
DIA_MES_POR_DEFECTO = 1
HORA_POR_DEFECTO = time(0, 0)
TIPOS_CON_HORAS = (TipoFrecuencia.DIARIA, TipoFrecuencia.SEMANAL, TipoFrecuencia.MENSUAL)


class ProgramacionInvalida(ValueError):
    pass


class ProgramacionIncompleta(ProgramacionInvalida):
    def __init__(self, tipo: TipoFrecuencia, faltantes: list[str]) -> None:
        super().__init__(
            f"La programación de frecuencia {tipo.value} está incompleta: falta {', '.join(faltantes)}."
        )
        self.tipo = tipo
        self.faltantes = faltantes


def campos_faltantes(programacion: Programacion) -> list[str]:
    faltantes = []
    if programacion.tipo_frecuencia in TIPOS_CON_HORAS and not programacion.horas:
        faltantes.append("horas")
    if programacion.tipo_frecuencia is TipoFrecuencia.SEMANAL and not programacion.dias_semana:
        faltantes.append("dias_semana")
    if programacion.tipo_frecuencia is TipoFrecuencia.INTERVALO and programacion.intervalo_minutos is None:
        faltantes.append("intervalo_minutos")
    if programacion.tipo_frecuencia is TipoFrecuencia.UNA_VEZ and programacion.fecha_inicio is None:
        faltantes.append("fecha_inicio")
    return faltantes


def zona_de(programacion: Programacion) -> ZoneInfo:
    try:
        return ZoneInfo(programacion.zona_horaria)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ProgramacionInvalida(f"La zona horaria {programacion.zona_horaria!r} no existe.") from error


@dataclass(frozen=True)
class ReglaRecurrencia:
    programacion: Programacion
    zona: ZoneInfo

    def localizar(self, local: datetime) -> datetime:
        return local.replace(tzinfo=self.zona).astimezone(UTC).astimezone(self.zona)

    def en_ventana(self, momento: datetime) -> bool:
        ventana = self.programacion.ventana
        if ventana is None:
            return True
        return ventana.contiene(momento.astimezone(self.zona).time())

    def ocurrencias_entre(self, desde: datetime, hasta: datetime) -> list[datetime]:
        inicio = utc_consciente(desde)
        fin = utc_consciente(hasta)
        if fin <= inicio:
            return []
        tipo = self.programacion.tipo_frecuencia
        if tipo is TipoFrecuencia.INTERVALO:
            candidatas: list[datetime] = list(self._intervalo(inicio, fin))
        elif tipo is TipoFrecuencia.UNA_VEZ:
            candidatas = [self._unica()]
        else:
            candidatas = self._horas_fijas(inicio, fin)
        unicas = {momento.astimezone(UTC): momento for momento in candidatas if inicio < momento <= fin}
        return [unicas[clave] for clave in sorted(unicas)]

    def proximas(self, despues_de: datetime, cantidad: int) -> list[datetime]:
        if cantidad <= 0:
            return []
        alcance = HORIZONTE_INICIAL
        while alcance < HORIZONTE_MAXIMO:
            ocurrencias = self.ocurrencias_entre(despues_de, despues_de + alcance)
            if len(ocurrencias) >= cantidad:
                return ocurrencias[:cantidad]
            alcance *= 2
        return self.ocurrencias_entre(despues_de, despues_de + HORIZONTE_MAXIMO)[:cantidad]

    def _unica(self) -> datetime:
        fecha = self.programacion.fecha_inicio
        assert fecha is not None
        hora = self.programacion.horas[0] if self.programacion.horas else HORA_POR_DEFECTO
        return self.localizar(datetime.combine(fecha, hora))

    def _ancla_intervalo(self) -> datetime:
        fecha = self.programacion.fecha_inicio
        if fecha is None:
            return self.localizar(ANCLA_INTERVALO_SIN_FECHA).astimezone(UTC)
        hora = self.programacion.horas[0] if self.programacion.horas else HORA_POR_DEFECTO
        return self.localizar(datetime.combine(fecha, hora)).astimezone(UTC)

    def _intervalo(self, desde: datetime, hasta: datetime) -> Iterator[datetime]:
        minutos = self.programacion.intervalo_minutos
        assert minutos is not None
        paso = timedelta(minutes=minutos)
        ancla = self._ancla_intervalo()
        pasos = 0 if desde < ancla else (desde - ancla) // paso + 1
        momento = ancla + pasos * paso
        while momento <= hasta:
            if self.en_ventana(momento):
                yield momento.astimezone(self.zona)
            momento += paso

    def _fecha_arranque(self, desde_local: datetime) -> date:
        arranque = (desde_local - MARGEN_LOCAL).date()
        fecha_inicio = self.programacion.fecha_inicio
        if fecha_inicio is not None and fecha_inicio > arranque:
            return fecha_inicio
        return arranque

    def _regla_para(self, hora: time, arranque: date) -> rrule.rrule:
        inicio = datetime.combine(arranque, hora)
        programacion = self.programacion
        if programacion.tipo_frecuencia is TipoFrecuencia.SEMANAL:
            dias = [DIAS_DATEUTIL[dia] for dia in programacion.dias_semana]
            return rrule.rrule(rrule.WEEKLY, dtstart=inicio, byweekday=dias)
        if programacion.tipo_frecuencia is TipoFrecuencia.MENSUAL:
            dia_mes = programacion.fecha_inicio.day if programacion.fecha_inicio else DIA_MES_POR_DEFECTO
            return rrule.rrule(rrule.MONTHLY, dtstart=inicio, bymonthday=dia_mes)
        return rrule.rrule(rrule.DAILY, dtstart=inicio)

    def _horas_fijas(self, desde: datetime, hasta: datetime) -> list[datetime]:
        desde_local = desde.astimezone(self.zona).replace(tzinfo=None)
        hasta_local = hasta.astimezone(self.zona).replace(tzinfo=None)
        arranque = self._fecha_arranque(desde_local)
        ocurrencias = []
        for hora in sorted(set(self.programacion.horas)):
            regla = self._regla_para(hora, arranque)
            for local in regla.between(desde_local - MARGEN_LOCAL, hasta_local + MARGEN_LOCAL, inc=True):
                ocurrencias.append(self.localizar(local))
        return ocurrencias


def construir_regla(programacion: Programacion) -> ReglaRecurrencia:
    faltantes = campos_faltantes(programacion)
    if faltantes:
        raise ProgramacionIncompleta(programacion.tipo_frecuencia, faltantes)
    if programacion.intervalo_minutos is not None and programacion.intervalo_minutos <= 0:
        raise ProgramacionInvalida("El intervalo debe ser de al menos un minuto.")
    return ReglaRecurrencia(programacion=programacion, zona=zona_de(programacion))


def ocurrencias_entre(programacion: Programacion, desde: datetime, hasta: datetime) -> list[datetime]:
    return construir_regla(programacion).ocurrencias_entre(desde, hasta)


def proximas(programacion: Programacion, despues_de: datetime, cantidad: int) -> list[datetime]:
    return construir_regla(programacion).proximas(despues_de, cantidad)
