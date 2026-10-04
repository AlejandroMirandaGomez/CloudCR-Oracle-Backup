import os
import re
from pathlib import Path

from cloudcr_backup.domain.errores import RecursoNoEncontrado
from cloudcr_backup.domain.evidencias import CatalogoEvidencias, EvidenciaEsperada

VARIABLE_CARPETA = "CLOUDCR_EVIDENCIAS_DIR"
PREFIJOS_IGNORADOS = ("procedimiento",)
IDENTIFICADOR = re.compile(r"^E\d+$")
LIMITE_ARCHIVOS_POR_EVIDENCIA = 40

ESPERADAS: tuple[tuple[str, str, str], ...] = (
    ("E1", "Explorador con la base en NOARCHIVELOG y la observación ARCH_001", "Josué"),
    ("E2", "Script generado, hash y aprobación; rechazo por script alterado", "Juan"),
    ("E3", "Ejecución exitosa con piezas en disco y evidencia.json", "Juan"),
    ("E4", "Ejecución fallida real, clasificada correctamente", "Juan"),
    ("E5", "Recomendación ARCH_002 aplicada: script v1 frente a v2", "Luis"),
    ("E6", "Ejecuciones automáticas del agente", "Alejandro"),
    ("E7", "Ocurrencia NO_EJECUTADA, alerta y correo al DBA", "Alejandro"),
    ("E8", "Historial con la columna Pruebas exportado a HTML", "Alejandro"),
    ("E9", "Informe de retención y puntos de recuperación", "Juan"),
    ("E10", "Afinamiento de redo y archivado: situación final", "Alejandro"),
)


def carpeta_evidencias() -> Path | None:
    candidatas: list[Path] = []
    configurada = os.environ.get(VARIABLE_CARPETA)
    if configurada:
        candidatas.append(Path(configurada))
    candidatas.append(Path.cwd() / "docs" / "evidencias")
    candidatas.append(Path(__file__).resolve().parents[3] / "docs" / "evidencias")
    return next((c for c in candidatas if c.is_dir()), None)


def _identificadores(nombre: str) -> set[str]:
    if nombre.lower().startswith(PREFIJOS_IGNORADOS):
        return set()
    return {parte for parte in Path(nombre).stem.split("_") if IDENTIFICADOR.match(parte)}


def _archivos_de(entrada: Path) -> list[Path]:
    if entrada.is_dir():
        return sorted(p for p in entrada.rglob("*") if p.is_file())[:LIMITE_ARCHIVOS_POR_EVIDENCIA]
    return [entrada]


def catalogo(carpeta: Path | None = None) -> CatalogoEvidencias:
    base = carpeta or carpeta_evidencias()
    por_id: dict[str, list[str]] = {identificador: [] for identificador, _, _ in ESPERADAS}
    if base is not None:
        for entrada in sorted(base.iterdir()):
            for identificador in _identificadores(entrada.name):
                if identificador in por_id:
                    por_id[identificador].extend(
                        p.relative_to(base).as_posix() for p in _archivos_de(entrada)
                    )
    evidencias = [
        EvidenciaEsperada(id=i, titulo=t, responsable=r, archivos=sorted(set(por_id[i]))) for i, t, r in ESPERADAS
    ]
    return CatalogoEvidencias(carpeta=str(base) if base is not None else None, evidencias=evidencias)


def ruta_de_archivo(relativa: str, carpeta: Path | None = None) -> Path:
    base = (carpeta or carpeta_evidencias())
    if base is None:
        raise RecursoNoEncontrado("No se encontró la carpeta docs/evidencias.")
    base = base.resolve()
    candidata = (base / relativa).resolve()
    if not candidata.is_relative_to(base) or not candidata.is_file():
        raise RecursoNoEncontrado(f"No existe el archivo de evidencia {relativa!r}.")
    return candidata
