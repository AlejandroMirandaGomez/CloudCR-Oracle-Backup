import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import find_dotenv, load_dotenv
from pydantic import BaseModel, Field

from cloudcr_backup.config.rutas import RutasTrabajo, directorio_trabajo_predeterminado

load_dotenv(find_dotenv(usecwd=True))

VARIABLE_RUTA_CONFIG = "CLOUDCR_CONFIG"
VARIABLE_CLAVE_REPOSITORIO = "CLOUDCR_REPO_CLAVE"
RUTA_CONFIG_PREDETERMINADA = Path.home() / "cloudcr.yaml"
NLS_LANG_PREDETERMINADO = "AMERICAN_AMERICA.AL32UTF8"
ZONA_HORARIA_PREDETERMINADA = "America/Costa_Rica"


class Ajustes(BaseModel):
    repositorio_dsn: str | None = None
    repositorio_usuario: str = "BKP_ADMIN"
    work_dir: Path = Field(default_factory=directorio_trabajo_predeterminado)
    destino_defecto: Path | None = None
    nls_lang: str = NLS_LANG_PREDETERMINADO
    zona_horaria: str = ZONA_HORARIA_PREDETERMINADA

    @property
    def rutas(self) -> RutasTrabajo:
        return RutasTrabajo(self.work_dir)


def _variable_entorno(campo: str) -> str:
    return f"CLOUDCR_{campo.upper()}"


def _env(nombre: str) -> str | None:
    valor = os.environ.get(nombre)
    return valor if valor else None


def _cargar_yaml(ruta: Path) -> dict[str, Any]:
    if not ruta.exists():
        return {}
    contenido = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    return contenido or {}


def cargar_ajustes(ruta_config: Path | None = None, **overrides: Any) -> Ajustes:
    ruta = ruta_config or Path(_env(VARIABLE_RUTA_CONFIG) or str(RUTA_CONFIG_PREDETERMINADA))
    datos = _cargar_yaml(ruta)
    for campo in Ajustes.model_fields:
        valor_env = _env(_variable_entorno(campo))
        if valor_env is not None:
            datos[campo] = valor_env
    for campo, valor in overrides.items():
        if valor is not None:
            datos[campo] = valor
    return Ajustes.model_validate(datos)


def obtener_clave_repositorio() -> str | None:
    return _env(VARIABLE_CLAVE_REPOSITORIO)
