import os
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from cloudcr_backup.rman.render import bytes_ascii

NLS_LANG_POR_DEFECTO = "AMERICAN_AMERICA.AL32UTF8"
TIMEOUT_POR_DEFECTO_SEGUNDOS = 120 * 60
ES_WINDOWS = sys.platform == "win32"


@dataclass(frozen=True)
class InvocacionRman:
    oracle_home: Path
    sid: str
    script: Path
    log: Path
    argumentos: tuple[str, ...] = ()
    timeout_segundos: int = TIMEOUT_POR_DEFECTO_SEGUNDOS
    nls_lang: str = NLS_LANG_POR_DEFECTO
    agregar_al_log: bool = False
    conectar_destino: bool = True


@dataclass(frozen=True)
class ResultadoRman:
    codigo_salida: int | None
    agotado: bool
    duracion_segundos: float
    salida: str = ""
    comando: list[str] = field(default_factory=list)
    error_lanzamiento: str | None = None

    @property
    def lanzado(self) -> bool:
        return self.error_lanzamiento is None


Lanzador = Callable[[InvocacionRman], ResultadoRman]


def ejecutable_rman(oracle_home: Path) -> Path:
    return oracle_home / "bin" / ("rman.exe" if ES_WINDOWS else "rman")


def entorno(invocacion: InvocacionRman, base: dict[str, str] | None = None) -> dict[str, str]:
    variables = dict(os.environ if base is None else base)
    variables["ORACLE_HOME"] = str(invocacion.oracle_home)
    variables["ORACLE_SID"] = invocacion.sid
    variables["NLS_LANG"] = invocacion.nls_lang
    variables["NLS_DATE_FORMAT"] = "YYYY-MM-DD HH24:MI:SS"
    return variables


def comando(invocacion: InvocacionRman) -> list[str]:
    partes = [str(ejecutable_rman(invocacion.oracle_home))]
    if invocacion.conectar_destino:
        partes += ["target", "/"]
    carpeta = invocacion.script.parent
    partes += [f"cmdfile={_relativa(invocacion.script, carpeta)}", f"log={_relativa(invocacion.log, carpeta)}"]
    if invocacion.agregar_al_log:
        partes.append("append")
    if invocacion.argumentos:
        partes += ["using", *invocacion.argumentos]
    return partes


class RutaNoAdmitida(ValueError):
    pass


def _relativa(ruta: Path, carpeta: Path) -> str:
    texto = os.path.relpath(ruta, carpeta)
    if any(caracter in texto for caracter in " '\"	"):
        raise RutaNoAdmitida(
            f"RMAN no admite la ruta {texto!r} como argumento (tiene espacios o comillas); "
            "use nombres de archivo sin espacios dentro de la carpeta del script."
        )
    return texto


def _citar(parte: str) -> str:
    if " " in parte and "=" not in parte:
        return f'"{parte}"'
    return parte


def linea_de_comando(partes: list[str]) -> str:
    return " ".join(_citar(parte) for parte in partes)


def escribir_script(ruta: Path, contenido: str) -> bytes:
    datos = bytes_ascii(contenido)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(datos)
    return datos


def lanzar(invocacion: InvocacionRman) -> ResultadoRman:
    partes = comando(invocacion)
    invocacion.log.parent.mkdir(parents=True, exist_ok=True)
    inicio = time.monotonic()
    argumentos: str | list[str] = linea_de_comando(partes) if ES_WINDOWS else partes
    try:
        proceso = subprocess.Popen(
            argumentos,
            env=entorno(invocacion),
            cwd=str(invocacion.script.parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except OSError as error:
        return ResultadoRman(
            codigo_salida=None,
            agotado=False,
            duracion_segundos=0.0,
            comando=partes,
            error_lanzamiento=f"No se pudo iniciar RMAN ({partes[0]}): {error}",
        )
    try:
        salida, _ = proceso.communicate(timeout=invocacion.timeout_segundos)
        agotado = False
    except subprocess.TimeoutExpired:
        proceso.kill()
        salida, _ = proceso.communicate()
        agotado = True
    return ResultadoRman(
        codigo_salida=None if agotado else proceso.returncode,
        agotado=agotado,
        duracion_segundos=time.monotonic() - inicio,
        salida=(salida or b"").decode("utf-8", errors="replace"),
        comando=partes,
    )


def leer_log(ruta: Path) -> str:
    try:
        return ruta.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
