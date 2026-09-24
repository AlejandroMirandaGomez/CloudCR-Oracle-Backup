import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from fastapi import Request

from cloudcr_backup.oracle.discovery import InstanciaDescubierta, descubrir_instancias
from cloudcr_backup.oracle.explorador import Exploracion, explorar_local, resolver_instancia

TTL_DESCUBRIMIENTO_SEGUNDOS = 30


class ProveedorExploracion(Protocol):
    def descubrir(self, refrescar: bool = False) -> list[InstanciaDescubierta]: ...

    def explorar(self, sid: str, oracle_home: Path | None, refrescar: bool) -> tuple[Exploracion, float]: ...


@dataclass
class EntradaCache:
    exploracion: Exploracion
    obtenida_en: float


class ServicioExploracion:
    def __init__(self, ttl_segundos: int) -> None:
        self._ttl = ttl_segundos
        self._cache: dict[str, EntradaCache] = {}
        self._candado_exploracion = threading.Lock()
        self._candado_descubrimiento = threading.Lock()
        self._descubiertas: list[InstanciaDescubierta] | None = None
        self._descubiertas_en = 0.0

    def descubrir(self, refrescar: bool = False) -> list[InstanciaDescubierta]:
        with self._candado_descubrimiento:
            vencido = time.monotonic() - self._descubiertas_en >= TTL_DESCUBRIMIENTO_SEGUNDOS
            if self._descubiertas is None or refrescar or vencido:
                self._descubiertas = descubrir_instancias()
                self._descubiertas_en = time.monotonic()
            return list(self._descubiertas)

    def explorar(self, sid: str, oracle_home: Path | None, refrescar: bool) -> tuple[Exploracion, float]:
        clave = sid.upper()
        with self._candado_exploracion:
            entrada = self._cache.get(clave)
            vigente = entrada is not None and time.monotonic() - entrada.obtenida_en < self._ttl
            if entrada is None or refrescar or not vigente:
                instancia = resolver_instancia(self.descubrir(), sid, oracle_home)
                entrada = EntradaCache(explorar_local(instancia), time.monotonic())
                self._cache[clave] = entrada
            return entrada.exploracion, time.monotonic() - entrada.obtenida_en


def obtener_servicio(request: Request) -> ProveedorExploracion:
    servicio: ProveedorExploracion = request.app.state.servicio
    return servicio
