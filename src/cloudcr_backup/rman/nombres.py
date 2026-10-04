import re
from datetime import datetime

LARGO_MAXIMO_TAG = 30
FORMATO_MARCA_TAG = "%y%m%d%H%M"
FORMATO_MARCA_TAG_SEGUNDOS = "%y%m%d%H%M%S"
PREFIJO_COMMAND_ID = "CLOUDCR_"
FORMATO_PIEZA_POR_DEFECTO = "%d_{estrategia}_{tarea}_%T_%U.bkp"
FORMATO_AUTOBACKUP = "%F"
EXTENSION_SCRIPT = "RMAN"
EXTENSION_LOG = "LOG"
PATRON_NO_PERMITIDO = re.compile(r"[^A-Z0-9_]")
PATRON_SEGMENTO = re.compile(r"[^A-Za-z0-9_$#-]")


def limpiar(texto: str) -> str:
    return PATRON_NO_PERMITIDO.sub("_", texto.strip().upper())


def tag(estrategia: str, tarea: str, momento: datetime) -> str:
    marca = momento.strftime(FORMATO_MARCA_TAG_SEGUNDOS if momento.second else FORMATO_MARCA_TAG)
    prefijo = f"{limpiar(estrategia)}_{limpiar(tarea)}"
    espacio = LARGO_MAXIMO_TAG - len(marca) - 1
    return f"{prefijo[:espacio]}_{marca}"


def command_id(ejecucion_id: int) -> str:
    return f"{PREFIJO_COMMAND_ID}{ejecucion_id}"


def separador_de(ruta: str) -> str:
    return "\\" if "\\" in ruta or ruta[1:2] == ":" else "/"


def unir_ruta(directorio: str, nombre: str) -> str:
    separador = separador_de(directorio)
    base = directorio.strip()
    if len(base) > 1:
        base = base.rstrip("\\/")
    if base in ("", "/"):
        return f"{base}{nombre}" if base else nombre
    return f"{base}{separador}{nombre}"


def formato_pieza(destino: str, estrategia: str, tarea: str, patron: str = FORMATO_PIEZA_POR_DEFECTO) -> str:
    nombre = patron.replace("{estrategia}", limpiar(estrategia)).replace("{tarea}", limpiar(tarea))
    return unir_ruta(destino, nombre)


def formato_autobackup(destino: str) -> str:
    return unir_ruta(destino, FORMATO_AUTOBACKUP)


def segmento(texto: str) -> str:
    return PATRON_SEGMENTO.sub("_", texto.strip().upper()) or "_"


def _base_clase(estrategia: str, bd: str, tarea: str | None, version: int | None) -> str:
    partes = [segmento(estrategia), segmento(bd)]
    if tarea:
        partes.append(segmento(tarea))
    if version is not None:
        partes.append(f"V{version}")
    return ".".join(partes)


def nombre_script(estrategia: str, bd: str, tarea: str | None = None, version: int | None = None) -> str:
    return f"{_base_clase(estrategia, bd, tarea, version)}.{EXTENSION_SCRIPT}"


def nombre_log(estrategia: str, bd: str, tarea: str | None = None, version: int | None = None) -> str:
    return f"{_base_clase(estrategia, bd, tarea, version)}.{EXTENSION_LOG}"


def archivo_script_aprobado(tarea: str, version: int) -> str:
    return f"{segmento(tarea)}_v{version}.rman"
