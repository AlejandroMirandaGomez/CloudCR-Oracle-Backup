import ctypes
import os
import re
import sys
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from cloudcr_backup.domain.monitoreo import EstadoAgente, EstadoLatido, Latido
from cloudcr_backup.scheduling.reloj import utc_consciente

PREFIJO_ARCHIVO = "latido_"
CARACTERES_NO_VALIDOS = re.compile(r"[^A-Za-z0-9_.-]")
TICKS_PARA_DARLO_POR_DETENIDO = 3
WINDOWS_CONSULTAR_PROCESO = 0x1000
WINDOWS_PROCESO_ACTIVO = 259
WINDOWS_ACCESO_DENEGADO = 5


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


def _proceso_existe_en_windows(pid: int) -> bool:
    if sys.platform != "win32":
        return False
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    manejador = kernel32.OpenProcess(WINDOWS_CONSULTAR_PROCESO, False, pid)
    if not manejador:
        return ctypes.get_last_error() == WINDOWS_ACCESO_DENEGADO
    try:
        codigo_salida = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(manejador, ctypes.byref(codigo_salida)):
            return True
        return codigo_salida.value == WINDOWS_PROCESO_ACTIVO
    finally:
        kernel32.CloseHandle(manejador)


def _proceso_existe_en_posix(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def proceso_existe(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        return _proceso_existe_en_windows(pid)
    return _proceso_existe_en_posix(pid)


def esta_vivo(latido: Latido, ahora: datetime, tick_segundos: int, hostname_local: str | None = None) -> bool:
    if latido.estado is EstadoLatido.DETENIDO:
        return False
    transcurrido = (utc_consciente(ahora) - utc_consciente(latido.ultimo_tick)).total_seconds()
    if transcurrido > TICKS_PARA_DARLO_POR_DETENIDO * tick_segundos:
        return False
    es_de_esta_maquina = hostname_local is not None and latido.hostname.casefold() == hostname_local.casefold()
    return proceso_existe(latido.pid) if es_de_esta_maquina else True


def estado_de(latido: Latido, ahora: datetime, tick_segundos: int, hostname_local: str | None = None) -> EstadoAgente:
    transcurrido = (utc_consciente(ahora) - utc_consciente(latido.ultimo_tick)).total_seconds()
    return EstadoAgente(
        latido=latido,
        vivo=esta_vivo(latido, ahora, tick_segundos, hostname_local),
        segundos_desde_tick=max(0, int(transcurrido)),
    )
