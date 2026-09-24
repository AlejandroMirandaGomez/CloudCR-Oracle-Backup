import os
import re
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path

PREFIJO_SERVICIO_WINDOWS = "OracleService"
PATRON_SERVICIO_EN_EJECUCION = re.compile(r":\s*4\s+RUNNING")
PATRON_PMON = re.compile(r"(?:ora|db)_pmon_(\w+)")
ENTORNO_INICIAL = {variable: os.environ.get(variable) for variable in ("ORACLE_SID", "ORACLE_HOME")}


@dataclass(frozen=True)
class InstanciaDescubierta:
    sid: str
    oracle_home: Path | None
    en_ejecucion: bool
    origenes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def clave(self) -> str:
        return self.sid.upper()


def combinar(candidatas: Iterable[InstanciaDescubierta]) -> list[InstanciaDescubierta]:
    por_sid: dict[str, InstanciaDescubierta] = {}
    for candidata in candidatas:
        existente = por_sid.get(candidata.clave)
        if existente is None:
            por_sid[candidata.clave] = candidata
            continue
        por_sid[candidata.clave] = replace(
            existente,
            oracle_home=existente.oracle_home or candidata.oracle_home,
            en_ejecucion=existente.en_ejecucion or candidata.en_ejecucion,
            origenes=tuple(dict.fromkeys(existente.origenes + candidata.origenes)),
        )
    return sorted(por_sid.values(), key=lambda i: (not i.en_ejecucion, i.clave))


def oracle_home_desde_image_path(image_path: str) -> Path | None:
    texto = image_path.strip()
    ejecutable = texto[1:].split('"', 1)[0] if texto.startswith('"') else texto.split(" ", 1)[0]
    ruta = Path(ejecutable)
    if ruta.parent.name.lower() != "bin":
        return None
    return ruta.parent.parent


def servicio_en_ejecucion(salida_sc_query: str) -> bool:
    return PATRON_SERVICIO_EN_EJECUCION.search(salida_sc_query) is not None


def parsear_oratab(contenido: str) -> list[InstanciaDescubierta]:
    instancias = []
    for linea in contenido.splitlines():
        limpia = linea.strip()
        if not limpia or limpia.startswith("#"):
            continue
        partes = limpia.split(":")
        if len(partes) < 2 or not partes[0] or partes[0] == "*":
            continue
        instancias.append(
            InstanciaDescubierta(sid=partes[0], oracle_home=Path(partes[1]), en_ejecucion=False, origenes=("oratab",))
        )
    return instancias


def sids_desde_procesos(lineas_comando: Iterable[str]) -> set[str]:
    sids = set()
    for linea in lineas_comando:
        coincidencia = PATRON_PMON.search(linea)
        if coincidencia:
            sids.add(coincidencia.group(1))
    return sids


def desde_entorno() -> list[InstanciaDescubierta]:
    sid = ENTORNO_INICIAL["ORACLE_SID"]
    if not sid:
        return []
    home = ENTORNO_INICIAL["ORACLE_HOME"]
    return [
        InstanciaDescubierta(
            sid=sid, oracle_home=Path(home) if home else None, en_ejecucion=False, origenes=("entorno",)
        )
    ]


def _desde_windows() -> list[InstanciaDescubierta]:
    if sys.platform != "win32":
        return []
    import winreg

    instancias: list[InstanciaDescubierta] = []
    try:
        oracle = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\ORACLE")
    except OSError:
        oracle = None
    if oracle is not None:
        indice = 0
        while True:
            try:
                subclave = winreg.EnumKey(oracle, indice)
            except OSError:
                break
            indice += 1
            if not subclave.upper().startswith("KEY_"):
                continue
            with winreg.OpenKey(oracle, subclave) as clave_home:
                valores = _valores_registro(clave_home)
            sid = valores.get("ORACLE_SID")
            home = valores.get("ORACLE_HOME")
            if sid:
                instancias.append(
                    InstanciaDescubierta(
                        sid=sid, oracle_home=Path(home) if home else None, en_ejecucion=False, origenes=("registro",)
                    )
                )
    servicios = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Services")
    indice = 0
    while True:
        try:
            nombre = winreg.EnumKey(servicios, indice)
        except OSError:
            break
        indice += 1
        if not nombre.startswith(PREFIJO_SERVICIO_WINDOWS) or nombre == PREFIJO_SERVICIO_WINDOWS:
            continue
        with winreg.OpenKey(servicios, nombre) as clave_servicio:
            image_path = _valores_registro(clave_servicio).get("ImagePath", "")
        instancias.append(
            InstanciaDescubierta(
                sid=nombre.removeprefix(PREFIJO_SERVICIO_WINDOWS),
                oracle_home=oracle_home_desde_image_path(image_path),
                en_ejecucion=_estado_servicio_windows(nombre),
                origenes=("servicio",),
            )
        )
    return instancias


def _valores_registro(clave: object) -> dict[str, str]:
    import winreg

    valores: dict[str, str] = {}
    indice = 0
    while True:
        try:
            nombre, valor, _ = winreg.EnumValue(clave, indice)  # type: ignore[arg-type]
        except OSError:
            break
        indice += 1
        if isinstance(valor, str):
            valores[nombre] = valor
    return valores


def _estado_servicio_windows(nombre_servicio: str) -> bool:
    try:
        resultado = subprocess.run(
            ["sc", "query", nombre_servicio], capture_output=True, text=True, timeout=10, errors="replace"
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return servicio_en_ejecucion(resultado.stdout)


def _desde_linux() -> list[InstanciaDescubierta]:
    if sys.platform == "win32":
        return []
    instancias: list[InstanciaDescubierta] = []
    oratab = Path("/etc/oratab")
    if oratab.exists():
        instancias.extend(parsear_oratab(oratab.read_text(encoding="utf-8", errors="replace")))
    comandos = []
    proc = Path("/proc")
    if proc.exists():
        for entrada in proc.iterdir():
            if entrada.name.isdigit():
                try:
                    comandos.append((entrada / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace"))
                except OSError:
                    continue
    for sid in sids_desde_procesos(comandos):
        instancias.append(InstanciaDescubierta(sid=sid, oracle_home=None, en_ejecucion=True, origenes=("proceso",)))
    return instancias


def descubrir_instancias() -> list[InstanciaDescubierta]:
    return combinar([*_desde_windows(), *_desde_linux(), *desde_entorno()])
