import os
import shutil
import sys
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path

import typer

from cloudcr_backup.config.ajustes import cargar_ajustes
from cloudcr_backup.oracle.connection import ErrorConexionOracle
from cloudcr_backup.oracle.discovery import descubrir_instancias
from cloudcr_backup.presentacion.terminal import consola
from cloudcr_backup.repository import esquema as repositorio_esquema
from cloudcr_backup.repository.conexion import RepositorioNoConfigurado, abrir_repositorio

app = typer.Typer(add_completion=False)

MODULOS_REQUERIDOS = ("oracledb", "pydantic", "typer", "fastapi", "yaml", "dateutil", "questionary", "dotenv")


@dataclass(frozen=True)
class Diagnostico:
    nombre: str
    ok: bool
    detalle: str
    sugerencia: str | None = None


def _verificar_python() -> Diagnostico:
    version = sys.version_info
    ok = version >= (3, 11)
    return Diagnostico(
        "Python",
        ok,
        f"{version.major}.{version.minor}.{version.micro}",
        None if ok else "Se requiere Python 3.11 o superior.",
    )


def _verificar_dependencias() -> Diagnostico:
    faltantes = []
    for modulo in MODULOS_REQUERIDOS:
        try:
            import_module(modulo)
        except ImportError:
            faltantes.append(modulo)
    if faltantes:
        return Diagnostico(
            "Dependencias", False, f"Faltan: {', '.join(faltantes)}", 'Ejecute: pip install -e ".[dev]"'
        )
    return Diagnostico("Dependencias", True, "Todas instaladas")


def _verificar_config() -> Diagnostico:
    ajustes = cargar_ajustes()
    if not ajustes.repositorio_dsn:
        return Diagnostico(
            "Configuración",
            False,
            "No hay CLOUDCR_REPOSITORIO_DSN configurado",
            "Copie .env.example a .env y complételo.",
        )
    return Diagnostico("Configuración", True, f"DSN del repositorio: {ajustes.repositorio_dsn}")


def _verificar_instancias() -> Diagnostico:
    instancias = descubrir_instancias()
    if not instancias:
        return Diagnostico("Instancias Oracle", False, "No se encontró ninguna instancia en esta máquina")
    return Diagnostico("Instancias Oracle", True, ", ".join(i.sid for i in instancias))


def _verificar_rman() -> Diagnostico:
    oracle_home = os.environ.get("ORACLE_HOME")
    candidatos = [Path(oracle_home) / "bin" / "rman.exe"] if oracle_home else []
    desde_path = shutil.which("rman")
    if desde_path:
        candidatos.append(Path(desde_path))
    if any(ruta.exists() for ruta in candidatos):
        return Diagnostico("rman.exe", True, "Encontrado")
    return Diagnostico(
        "rman.exe",
        False,
        "No se encontró rman en el PATH ni en ORACLE_HOME",
        "Verifique que ORACLE_HOME esté configurado y apunte a una instalación válida.",
    )


def _verificar_destino() -> Diagnostico:
    destino = cargar_ajustes().destino_defecto
    if destino is None:
        return Diagnostico("Destino de respaldo", False, "No hay CLOUDCR_DESTINO_DEFECTO configurado")
    try:
        destino.mkdir(parents=True, exist_ok=True)
        prueba = destino / ".cloudcr_prueba_escritura"
        prueba.write_text("ok", encoding="utf-8")
        prueba.unlink()
    except OSError as error:
        return Diagnostico("Destino de respaldo", False, f"No se pudo escribir en {destino}: {error}")
    libres_gb = shutil.disk_usage(destino).free / (1024**3)
    return Diagnostico("Destino de respaldo", True, f"{destino} escribible, {libres_gb:.1f} GB libres")


def _verificar_repositorio() -> Diagnostico:
    try:
        conexion = abrir_repositorio(cargar_ajustes())
    except RepositorioNoConfigurado as error:
        return Diagnostico("Repositorio", False, str(error))
    except ErrorConexionOracle as error:
        return Diagnostico("Repositorio", False, str(error), error.sugerencia)
    info = repositorio_esquema.estado(conexion)
    if not info.instalado:
        return Diagnostico(
            "Esquema del repositorio",
            False,
            "El esquema no está instalado o está incompleto",
            "Ejecute 'cloudcr repo instalar'.",
        )
    return Diagnostico("Esquema del repositorio", True, f"{len(info.tablas)} tablas instaladas")


@app.command(name="doctor", help="Diagnostica el entorno: Python, dependencias, configuración, Oracle y destino.")
def doctor() -> None:
    diagnosticos = [
        _verificar_python(),
        _verificar_dependencias(),
        _verificar_config(),
        _verificar_instancias(),
        _verificar_rman(),
        _verificar_destino(),
        _verificar_repositorio(),
    ]
    salida = consola()
    salida.print("\n[bold]Diagnóstico de CloudCR Oracle Backup[/]\n", markup=True)
    hay_fallos = False
    for diagnostico in diagnosticos:
        if diagnostico.ok:
            salida.print(f"[green]✓[/] {diagnostico.nombre}: {diagnostico.detalle}", markup=True)
            continue
        hay_fallos = True
        salida.print(f"[red]✗[/] {diagnostico.nombre}: {diagnostico.detalle}", markup=True)
        if diagnostico.sugerencia:
            salida.print(f"    [yellow]Sugerencia:[/] {diagnostico.sugerencia}", markup=True)
    if hay_fallos:
        raise typer.Exit(1)
