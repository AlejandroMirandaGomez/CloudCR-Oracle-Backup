import os
from pathlib import Path

from cloudcr_backup.domain.ejecucion import Evidencia

ARCHIVO_EVIDENCIA = "evidencia.json"


def carpeta_ejecucion(base_ejecuciones: Path, ejecucion_id: int) -> Path:
    return base_ejecuciones / str(ejecucion_id)


def escribir(carpeta: Path, evidencia: Evidencia) -> Path:
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / ARCHIVO_EVIDENCIA
    temporal = carpeta / f".{ARCHIVO_EVIDENCIA}.tmp"
    temporal.write_text(evidencia.model_dump_json(indent=2), encoding="utf-8")
    os.replace(temporal, destino)
    return destino


def leer(ruta: Path) -> Evidencia:
    return Evidencia.model_validate_json(ruta.read_text(encoding="utf-8"))
