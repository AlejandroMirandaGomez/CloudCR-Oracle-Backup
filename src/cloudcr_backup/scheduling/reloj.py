from datetime import UTC, datetime
from typing import Protocol


class Reloj(Protocol):
    def ahora(self) -> datetime: ...


class RelojSistema:
    def ahora(self) -> datetime:
        return datetime.now(UTC)


class RelojFijo:
    def __init__(self, momento: datetime) -> None:
        self._momento = utc_consciente(momento)

    def ahora(self) -> datetime:
        return self._momento

    def fijar(self, momento: datetime) -> None:
        self._momento = utc_consciente(momento)


def utc_consciente(momento: datetime) -> datetime:
    if momento.tzinfo is None:
        return momento.replace(tzinfo=UTC)
    return momento.astimezone(UTC)


def utc_ingenuo(momento: datetime) -> datetime:
    return utc_consciente(momento).replace(tzinfo=None)
