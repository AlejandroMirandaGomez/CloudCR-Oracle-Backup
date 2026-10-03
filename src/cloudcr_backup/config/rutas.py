import os
import sys
from dataclasses import dataclass
from pathlib import Path


def directorio_trabajo_predeterminado() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "cloudcr"
        return Path.home() / "AppData" / "Local" / "cloudcr"
    base = os.environ.get("XDG_DATA_HOME")
    if base:
        return Path(base) / "cloudcr"
    return Path.home() / ".local" / "share" / "cloudcr"


@dataclass(frozen=True)
class RutasTrabajo:
    base: Path

    @property
    def scripts(self) -> Path:
        return self.base / "scripts"

    @property
    def estrategias(self) -> Path:
        return self.base / "estrategias"

    @property
    def ejecuciones(self) -> Path:
        return self.base / "ejecuciones"

    @property
    def recuperacion(self) -> Path:
        return self.base / "recuperacion"

    @property
    def buzon(self) -> Path:
        return self.base / "buzon"

    @property
    def logs(self) -> Path:
        return self.base / "logs"

    @property
    def agente(self) -> Path:
        return self.base / "agente"

    def asegurar(self) -> None:
        for ruta in (
            self.scripts,
            self.estrategias,
            self.ejecuciones,
            self.recuperacion,
            self.buzon,
            self.logs,
            self.agente,
        ):
            ruta.mkdir(parents=True, exist_ok=True)
