from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from cloudcr_backup.domain.estrategia import Ventana
from cloudcr_backup.scheduling.reloj import utc_consciente


@dataclass(frozen=True)
class InstanciaVentana:
    apertura: datetime
    cierre: datetime

    def contiene(self, momento: datetime) -> bool:
        return self.apertura <= utc_consciente(momento) <= self.cierre


def hora_local(momento: datetime, zona: ZoneInfo) -> datetime:
    return utc_consciente(momento).astimezone(zona)


def contiene(ventana: Ventana, momento: datetime, zona: ZoneInfo) -> bool:
    return ventana.contiene(hora_local(momento, zona).time())


def _localizar(local: datetime, zona: ZoneInfo) -> datetime:
    return local.replace(tzinfo=zona).astimezone(zona)


def instancia_de(ventana: Ventana, momento: datetime, zona: ZoneInfo) -> InstanciaVentana | None:
    local = hora_local(momento, zona)
    if not ventana.contiene(local.time()):
        return None
    dia_apertura = local.date()
    if ventana.cruza_medianoche and local.time() <= ventana.fin and not local.time() >= ventana.inicio:
        dia_apertura -= timedelta(days=1)
    apertura = datetime.combine(dia_apertura, ventana.inicio)
    dia_cierre = dia_apertura + timedelta(days=1) if ventana.cruza_medianoche else dia_apertura
    cierre = datetime.combine(dia_cierre, ventana.fin)
    return InstanciaVentana(apertura=_localizar(apertura, zona), cierre=_localizar(cierre, zona))


def misma_instancia(ventana: Ventana, primero: datetime, segundo: datetime, zona: ZoneInfo) -> bool:
    instancia = instancia_de(ventana, primero, zona)
    return instancia is not None and instancia.contiene(segundo)
