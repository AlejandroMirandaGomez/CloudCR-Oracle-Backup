import logging
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from cloudcr_backup.config.ajustes import Ajustes, cargar_ajustes
from cloudcr_backup.domain.ejecucion import Evidencia
from cloudcr_backup.domain.errores import RepositorioNoDisponible
from cloudcr_backup.execution.persistencia import persistir, repositorio

REGISTRO = logging.getLogger("cloudcr.buzon")
FORMATO_MARCA = "%Y%m%dT%H%M%S%f"
SUFIJO = ".json"
SUFIJO_DANADO = ".danado"

Persistidor = Callable[[Evidencia], None]


def nombre_archivo(evidencia: Evidencia, momento: datetime) -> str:
    return f"{momento.astimezone(UTC).strftime(FORMATO_MARCA)}_{evidencia.ejecucion_id}{SUFIJO}"


def depositar(carpeta: Path, evidencia: Evidencia, momento: datetime | None = None) -> Path:
    carpeta.mkdir(parents=True, exist_ok=True)
    for anterior in carpeta.glob(f"*_{evidencia.ejecucion_id}{SUFIJO}"):
        anterior.unlink(missing_ok=True)
    destino = carpeta / nombre_archivo(evidencia, momento or datetime.now(UTC))
    temporal = destino.with_suffix(".tmp")
    temporal.write_text(evidencia.model_dump_json(indent=2), encoding="utf-8")
    os.replace(temporal, destino)
    return destino


def pendientes(carpeta: Path) -> list[Path]:
    if not carpeta.is_dir():
        return []
    return sorted(archivo for archivo in carpeta.glob(f"*{SUFIJO}") if archivo.is_file())


def vaciar(carpeta: Path, persistidor: Persistidor) -> int:
    sincronizadas = 0
    for archivo in pendientes(carpeta):
        try:
            evidencia = Evidencia.model_validate_json(archivo.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError):
            REGISTRO.exception("El archivo %s del buzón no es una evidencia válida; se aparta", archivo)
            archivo.replace(archivo.with_suffix(SUFIJO_DANADO))
            continue
        try:
            persistidor(evidencia)
        except RepositorioNoDisponible as error:
            REGISTRO.warning("El buzón queda pendiente: %s", error.mensaje)
            break
        archivo.unlink(missing_ok=True)
        sincronizadas += 1
    return sincronizadas


def persistidor_repositorio(ajustes: Ajustes) -> Persistidor:
    def guardar(evidencia: Evidencia) -> None:
        with repositorio(ajustes) as conexion:
            persistir(conexion, evidencia)

    return guardar


def sincronizar(ajustes: Ajustes | None = None) -> int:
    configuracion = ajustes or cargar_ajustes()
    carpeta = configuracion.rutas.buzon
    if not pendientes(carpeta):
        return 0
    return vaciar(carpeta, persistidor_repositorio(configuracion))
