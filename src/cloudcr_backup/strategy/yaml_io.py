from pathlib import Path

import yaml
from pydantic import ValidationError

from cloudcr_backup.domain.estrategia import Estrategia


class EstrategiaYamlInvalida(ValueError):
    pass


def _mensaje_legible(error: ValidationError) -> str:
    lineas = [f"{'.'.join(str(parte) for parte in err['loc'])}: {err['msg']}" for err in error.errors()]
    return "La estrategia tiene campos inválidos:\n" + "\n".join(lineas)


def estrategia_a_yaml(estrategia: Estrategia) -> str:
    datos = estrategia.model_dump(mode="json", exclude_none=True)
    return yaml.safe_dump(datos, allow_unicode=True, sort_keys=False)


def estrategia_desde_yaml(contenido: str) -> Estrategia:
    try:
        datos = yaml.safe_load(contenido)
    except yaml.YAMLError as error:
        raise EstrategiaYamlInvalida(f"El YAML no se pudo interpretar: {error}") from error
    if not isinstance(datos, dict):
        raise EstrategiaYamlInvalida(
            "El YAML debe describir una estrategia (un mapa de campos), no una lista ni un valor suelto."
        )
    try:
        return Estrategia.model_validate(datos)
    except ValidationError as error:
        raise EstrategiaYamlInvalida(_mensaje_legible(error)) from error


def guardar_estrategia_yaml(estrategia: Estrategia, ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(estrategia_a_yaml(estrategia), encoding="utf-8")


def cargar_estrategia_yaml(ruta: Path) -> Estrategia:
    if not ruta.exists():
        raise EstrategiaYamlInvalida(f"No existe el archivo {ruta}.")
    return estrategia_desde_yaml(ruta.read_text(encoding="utf-8"))
