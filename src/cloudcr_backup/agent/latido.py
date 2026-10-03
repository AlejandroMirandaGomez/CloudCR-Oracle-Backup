import os
import re
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from cloudcr_backup.domain.monitoreo import EstadoAgente, EstadoLatido, Latido
from cloudcr_backup.scheduling.reloj import utc_consciente

PREFIJO_ARCHIVO = "latido_"
CARACTERES_NO_VALIDOS = re.compile(r"[^A-Za-z0-9_.-]")
TICKS_PARA_DARLO_POR_DETENIDO = 3


def ruta_latido(carpeta: Path, hostname: str) -> Path:
    return carpeta / f"{PREFIJO_ARCHIVO}{CARACTERES_NO_VALIDOS.sub('_', hostname)}.json"


def escribir(carpeta: Path, latido: Latido) -> Path:
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = ruta_latido(carpeta, latido.hostname)
    temporal = destino.with_name(f"{destino.name}.{os.getpid()}.tmp")
    temporal.write_text(latido.model_dump_json(indent=2), encoding="utf-8")
    os.replace(temporal, destino)
    return destino


def leer_todos(carpeta: Path) -> list[Latido]:
    if not carpeta.is_dir():
        return []
    latidos = []
    for archivo in sorted(carpeta.glob(f"{PREFIJO_ARCHIVO}*.json")):
        try:
            latidos.append(Latido.model_validate_json(archivo.read_text(encoding="utf-8")))
        except (OSError, ValidationError, ValueError):
            continue
    return latidos


def esta_vivo(latido: Latido, ahora: datetime, tick_segundos: int) -> bool:
    if latido.estado is EstadoLatido.DETENIDO:
        return False
    transcurrido = (utc_consciente(ahora) - utc_consciente(latido.ultimo_tick)).total_seconds()
    return transcurrido <= TICKS_PARA_DARLO_POR_DETENIDO * tick_segundos


def estado_de(latido: Latido, ahora: datetime, tick_segundos: int) -> EstadoAgente:
    transcurrido = (utc_consciente(ahora) - utc_consciente(latido.ultimo_tick)).total_seconds()
    return EstadoAgente(
        latido=latido, vivo=esta_vivo(latido, ahora, tick_segundos), segundos_desde_tick=max(0, int(transcurrido))
    )
