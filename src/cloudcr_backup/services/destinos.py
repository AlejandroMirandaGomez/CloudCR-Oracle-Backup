import os
import shutil
import stat
import string
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

MAXIMO_CARPETAS_LISTADAS = 500
MAXIMO_LARGO_NOMBRE_CARPETA = 100
CARACTERES_PROHIBIDOS_EN_NOMBRE = frozenset('\\/:*?"<>|')
ES_WINDOWS = sys.platform == "win32"


class ErrorDestino(ValueError):
    def __init__(self, mensaje: str, tipo: str) -> None:
        super().__init__(mensaje)
        self.tipo = tipo


@dataclass(frozen=True)
class Carpeta:
    nombre: str
    ruta: str


@dataclass(frozen=True)
class ListadoCarpetas:
    ruta: str
    padre: str | None
    carpetas: list[Carpeta]
    truncado: bool
    separador: str
    solicitada_existe: bool = True


@dataclass(frozen=True)
class EstadoDestino:
    escribible: bool
    libre_bytes: int | None
    total_bytes: int | None


def ruta_es_absoluta(ruta: str) -> bool:
    if ES_WINDOWS:
        return PureWindowsPath(ruta).is_absolute()
    return PurePosixPath(ruta).is_absolute()


def normalizar_ruta(ruta: str) -> str:
    texto = ruta.strip()
    if ES_WINDOWS:
        return str(PureWindowsPath(texto))
    return str(PurePosixPath(texto))


def _unidades_windows() -> list[str]:
    if sys.platform != "win32":
        return []
    import ctypes

    mascara = ctypes.windll.kernel32.GetLogicalDrives()
    return [f"{letra}:\\" for indice, letra in enumerate(string.ascii_uppercase) if mascara & (1 << indice)]


def raices() -> list[Carpeta]:
    if ES_WINDOWS:
        return [Carpeta(nombre=unidad, ruta=unidad) for unidad in _unidades_windows()]
    return [Carpeta(nombre="/", ruta="/")]


def _carpeta_existente(ruta: str) -> Path:
    texto = ruta.strip()
    if not ruta_es_absoluta(texto):
        raise ErrorDestino("La ruta debe ser absoluta, por ejemplo C:\\backups\\XE.", "invalido")
    camino = Path(os.path.normpath(texto))
    try:
        existe = camino.is_dir()
    except OSError:
        existe = False
    if not existe:
        raise ErrorDestino(f"La carpeta {texto} no existe.", "no_existe")
    return camino


def _es_oculta(entrada: os.DirEntry[str]) -> bool:
    if entrada.name.startswith("$"):
        return True
    if sys.platform != "win32":
        return entrada.name.startswith(".")
    try:
        atributos = entrada.stat(follow_symlinks=False).st_file_attributes
    except OSError:
        return True
    return bool(atributos & (stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM))


def _subcarpetas(camino: Path) -> list[Carpeta]:
    encontradas = []
    try:
        with os.scandir(camino) as entradas:
            for entrada in entradas:
                try:
                    if entrada.is_dir() and not _es_oculta(entrada):
                        encontradas.append(Carpeta(nombre=entrada.name, ruta=str(camino / entrada.name)))
                except OSError:
                    continue
    except PermissionError as error:
        raise ErrorDestino(f"No hay permiso para leer {camino}.", "sin_permiso") from error
    except OSError as error:
        raise ErrorDestino(f"No se pudo leer {camino}: {error.strerror or error}", "no_existe") from error
    return sorted(encontradas, key=lambda carpeta: carpeta.nombre.casefold())


def _carpeta_mas_cercana(ruta: str) -> Path | None:
    texto = ruta.strip()
    if not ruta_es_absoluta(texto):
        return None
    actual = Path(os.path.normpath(texto))
    while True:
        try:
            if actual.is_dir():
                return actual
        except OSError:
            pass
        if actual.parent == actual:
            return None
        actual = actual.parent


def _listado_de_unidades(solicitada_existe: bool) -> ListadoCarpetas:
    return ListadoCarpetas(
        ruta="",
        padre=None,
        carpetas=raices(),
        truncado=False,
        separador=os.sep,
        solicitada_existe=solicitada_existe,
    )


def listar_carpetas(ruta: str | None, cercana: bool = False) -> ListadoCarpetas:
    if not ruta or not ruta.strip():
        return _listado_de_unidades(solicitada_existe=True)
    if cercana:
        camino = _carpeta_mas_cercana(ruta)
        if camino is None:
            return _listado_de_unidades(solicitada_existe=False)
        solicitada_existe = Path(os.path.normpath(ruta.strip())) == camino
    else:
        camino = _carpeta_existente(ruta)
        solicitada_existe = True
    subcarpetas = _subcarpetas(camino)
    padre = camino.parent
    return ListadoCarpetas(
        ruta=str(camino),
        padre=str(padre) if padre != camino else "",
        carpetas=subcarpetas[:MAXIMO_CARPETAS_LISTADAS],
        truncado=len(subcarpetas) > MAXIMO_CARPETAS_LISTADAS,
        separador=os.sep,
        solicitada_existe=solicitada_existe,
    )


def _validar_nombre_carpeta(nombre: str) -> str:
    limpio = nombre.strip()
    if not limpio or limpio in {".", ".."}:
        raise ErrorDestino("Escriba un nombre para la carpeta.", "invalido")
    if len(limpio) > MAXIMO_LARGO_NOMBRE_CARPETA:
        raise ErrorDestino(f"El nombre no puede superar {MAXIMO_LARGO_NOMBRE_CARPETA} caracteres.", "invalido")
    if any(caracter in CARACTERES_PROHIBIDOS_EN_NOMBRE or ord(caracter) < 32 for caracter in limpio):
        raise ErrorDestino('El nombre no puede contener \\ / : * ? " < > |', "invalido")
    if limpio.endswith("."):
        raise ErrorDestino("El nombre no puede terminar en punto.", "invalido")
    return limpio


def crear_carpeta(padre: str, nombre: str) -> Carpeta:
    limpio = _validar_nombre_carpeta(nombre)
    base = _carpeta_existente(padre)
    nueva = base / limpio
    try:
        nueva.mkdir()
    except FileExistsError as error:
        raise ErrorDestino(f"Ya existe una carpeta llamada {limpio} en {base}.", "existe") from error
    except PermissionError as error:
        raise ErrorDestino(f"No hay permiso para crear carpetas en {base}.", "sin_permiso") from error
    except OSError as error:
        raise ErrorDestino(f"No se pudo crear la carpeta: {error.strerror or error}", "invalido") from error
    return Carpeta(nombre=limpio, ruta=str(nueva))


def _es_escribible(camino: Path) -> bool:
    try:
        if not camino.is_dir():
            return False
        with tempfile.TemporaryFile(dir=camino):
            return True
    except OSError:
        return False


def _ancestro_existente(camino: Path) -> Path | None:
    actual = camino
    while True:
        try:
            if actual.exists():
                return actual
        except OSError:
            return None
        if actual.parent == actual:
            return None
        actual = actual.parent


def inspeccionar_destino(ruta: str) -> EstadoDestino:
    camino = Path(os.path.normpath(ruta))
    libre: int | None = None
    total: int | None = None
    ancla = _ancestro_existente(camino)
    if ancla is not None:
        try:
            uso = shutil.disk_usage(ancla)
        except OSError:
            uso = None
        if uso is not None:
            libre, total = uso.free, uso.total
    return EstadoDestino(escribible=_es_escribible(camino), libre_bytes=libre, total_bytes=total)
