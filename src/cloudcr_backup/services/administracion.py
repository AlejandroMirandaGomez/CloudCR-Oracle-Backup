import os
import shutil
import sys
from importlib import import_module
from pathlib import Path

from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.domain.administracion import (
    ComprobacionEntorno,
    EstadoRepositorio,
    ParametroRepositorio,
    TablaRepositorio,
)
from cloudcr_backup.domain.errores import ErrorServicio, OperacionNoPermitida, RecursoNoEncontrado
from cloudcr_backup.oracle.discovery import descubrir_instancias
from cloudcr_backup.repository import esquema as repositorio_esquema
from cloudcr_backup.repository import parametros as repositorio_parametros
from cloudcr_backup.services.sesion import conexion_repositorio

MODULOS_REQUERIDOS = ("oracledb", "pydantic", "typer", "fastapi", "yaml", "dateutil", "questionary", "dotenv")
LARGO_MAXIMO_CLAVE = 100
LARGO_MAXIMO_VALOR = 4000

PARAMETROS_INICIALES = {
    "agente.tick_segundos": "30",
    "agente.gracia_omision_min": "15",
    "rman.nls_lang": "AMERICAN_AMERICA.AL32UTF8",
    "rman.timeout_max_min": "120",
    "rman.codigos_advertencia": '["RMAN-08137","RMAN-08138","RMAN-06207","RMAN-06208","RMAN-06214"]',
    "respaldo.formato_pieza": "%d_{estrategia}_{tarea}_%T_%U.bkp",
    "verificacion.automatica": "true",
    "alertas.eval_minutos": "5",
    "alertas.disco_uso_pct": "85",
    "alertas.recencia_horas.ALTA": "24",
    "alertas.recencia_horas.MEDIA": "72",
    "alertas.recencia_horas.BAJA": "192",
    "notificacion.canales": '["consola"]',
}


def comprobar_python() -> ComprobacionEntorno:
    version = sys.version_info
    ok = version >= (3, 11)
    return ComprobacionEntorno(
        nombre="Python",
        ok=ok,
        detalle=f"{version.major}.{version.minor}.{version.micro}",
        sugerencia=None if ok else "Se requiere Python 3.11 o superior.",
    )


def comprobar_dependencias() -> ComprobacionEntorno:
    faltantes = []
    for modulo in MODULOS_REQUERIDOS:
        try:
            import_module(modulo)
        except ImportError:
            faltantes.append(modulo)
    if faltantes:
        return ComprobacionEntorno(
            nombre="Dependencias",
            ok=False,
            detalle=f"Faltan: {', '.join(faltantes)}",
            sugerencia='Ejecute: pip install -e ".[dev]"',
        )
    return ComprobacionEntorno(nombre="Dependencias", ok=True, detalle="Todas instaladas")


def comprobar_configuracion(ajustes: Ajustes) -> ComprobacionEntorno:
    if not ajustes.repositorio_dsn:
        return ComprobacionEntorno(
            nombre="Configuración",
            ok=False,
            detalle="No hay CLOUDCR_REPOSITORIO_DSN configurado",
            sugerencia="Copie .env.example a .env y complételo.",
        )
    return ComprobacionEntorno(
        nombre="Configuración", ok=True, detalle=f"DSN del repositorio: {ajustes.repositorio_dsn}"
    )


def comprobar_instancias() -> ComprobacionEntorno:
    instancias = descubrir_instancias()
    if not instancias:
        return ComprobacionEntorno(
            nombre="Instancias Oracle", ok=False, detalle="No se encontró ninguna instancia en esta máquina"
        )
    return ComprobacionEntorno(nombre="Instancias Oracle", ok=True, detalle=", ".join(i.sid for i in instancias))


def _candidatos_rman() -> list[Path]:
    candidatos = []
    oracle_home = os.environ.get("ORACLE_HOME")
    if oracle_home:
        candidatos.append(Path(oracle_home) / "bin" / "rman.exe")
    for instancia in descubrir_instancias():
        if instancia.oracle_home is not None:
            candidatos.append(instancia.oracle_home / "bin" / "rman.exe")
            candidatos.append(instancia.oracle_home / "bin" / "rman")
    desde_path = shutil.which("rman")
    if desde_path:
        candidatos.append(Path(desde_path))
    return candidatos


def comprobar_rman() -> ComprobacionEntorno:
    encontrado = next((ruta for ruta in _candidatos_rman() if ruta.exists()), None)
    if encontrado is not None:
        return ComprobacionEntorno(nombre="rman.exe", ok=True, detalle=f"Encontrado en {encontrado}")
    return ComprobacionEntorno(
        nombre="rman.exe",
        ok=False,
        detalle="No se encontró rman en el PATH ni en ORACLE_HOME",
        sugerencia="Verifique que ORACLE_HOME esté configurado y apunte a una instalación válida.",
    )


def comprobar_destino(ajustes: Ajustes) -> ComprobacionEntorno:
    destino = ajustes.destino_defecto
    if destino is None:
        return ComprobacionEntorno(
            nombre="Destino de respaldo", ok=False, detalle="No hay CLOUDCR_DESTINO_DEFECTO configurado"
        )
    try:
        destino.mkdir(parents=True, exist_ok=True)
        prueba = destino / ".cloudcr_prueba_escritura"
        prueba.write_text("ok", encoding="utf-8")
        prueba.unlink()
    except OSError as error:
        return ComprobacionEntorno(
            nombre="Destino de respaldo", ok=False, detalle=f"No se pudo escribir en {destino}: {error}"
        )
    libres_gb = shutil.disk_usage(destino).free / (1024**3)
    return ComprobacionEntorno(
        nombre="Destino de respaldo", ok=True, detalle=f"{destino} escribible, {libres_gb:.1f} GB libres"
    )


def comprobar_repositorio(ajustes: Ajustes) -> ComprobacionEntorno:
    try:
        estado = estado_repositorio(ajustes)
    except ErrorServicio as error:
        return ComprobacionEntorno(nombre="Repositorio", ok=False, detalle=error.mensaje, sugerencia=error.sugerencia)
    if not estado.instalado:
        return ComprobacionEntorno(
            nombre="Esquema del repositorio",
            ok=False,
            detalle="El esquema no está instalado o está incompleto",
            sugerencia="Ejecute 'cloudcr repo instalar'.",
        )
    return ComprobacionEntorno(
        nombre="Esquema del repositorio", ok=True, detalle=f"{len(estado.tablas)} tablas instaladas"
    )


def comprobar_entorno(ajustes: Ajustes) -> list[ComprobacionEntorno]:
    return [
        comprobar_python(),
        comprobar_dependencias(),
        comprobar_configuracion(ajustes),
        comprobar_instancias(),
        comprobar_rman(),
        comprobar_destino(ajustes),
        comprobar_repositorio(ajustes),
    ]


def estado_repositorio(ajustes: Ajustes) -> EstadoRepositorio:
    with conexion_repositorio(ajustes) as conexion:
        info = repositorio_esquema.estado(conexion)
    return EstadoRepositorio(
        instalado=info.instalado,
        esperadas=len(repositorio_esquema.TABLAS),
        tablas=[TablaRepositorio(nombre=nombre, filas=filas) for nombre, filas in sorted(info.tablas.items())],
    )


def cargar_parametros_iniciales(ajustes: Ajustes) -> int:
    cargados = 0
    with conexion_repositorio(ajustes) as conexion:
        for clave, valor in PARAMETROS_INICIALES.items():
            if repositorio_parametros.obtener(conexion, clave) is None:
                repositorio_parametros.asignar(conexion, clave, valor)
                cargados += 1
    return cargados


def instalar_repositorio(ajustes: Ajustes) -> EstadoRepositorio:
    with conexion_repositorio(ajustes) as conexion:
        if repositorio_esquema.estado(conexion).instalado:
            raise OperacionNoPermitida(
                "El repositorio ya está instalado: volver a instalarlo borraría las 12 tablas y todos sus datos.",
                "Si de verdad quiere empezar de cero, use 'cloudcr repo instalar' en la terminal.",
            )
        repositorio_esquema.instalar(conexion)
    cargar_parametros_iniciales(ajustes)
    return estado_repositorio(ajustes)


def parametros(ajustes: Ajustes) -> list[ParametroRepositorio]:
    with conexion_repositorio(ajustes) as conexion:
        guardados = repositorio_parametros.listar(conexion)
    claves = sorted({*guardados, *PARAMETROS_INICIALES})
    return [
        ParametroRepositorio(
            clave=clave,
            valor=guardados.get(clave, PARAMETROS_INICIALES.get(clave, "")),
            inicial=PARAMETROS_INICIALES.get(clave),
        )
        for clave in claves
    ]


def _validar_parametro(clave: str, valor: str) -> tuple[str, str]:
    clave_limpia = clave.strip()
    if not clave_limpia:
        raise OperacionNoPermitida("Indique la clave del parámetro.")
    if len(clave_limpia) > LARGO_MAXIMO_CLAVE or any(c.isspace() for c in clave_limpia):
        raise OperacionNoPermitida(
            f"La clave {clave_limpia!r} no es válida.",
            f"Use hasta {LARGO_MAXIMO_CLAVE} caracteres sin espacios, por ejemplo 'agente.tick_segundos'.",
        )
    if len(valor) > LARGO_MAXIMO_VALOR:
        raise OperacionNoPermitida(f"El valor es demasiado largo (máximo {LARGO_MAXIMO_VALOR} caracteres).")
    return clave_limpia, valor.strip()


def asignar_parametro(ajustes: Ajustes, clave: str, valor: str) -> ParametroRepositorio:
    clave_limpia, valor_limpio = _validar_parametro(clave, valor)
    with conexion_repositorio(ajustes) as conexion:
        repositorio_parametros.asignar(conexion, clave_limpia, valor_limpio)
    return ParametroRepositorio(clave=clave_limpia, valor=valor_limpio, inicial=PARAMETROS_INICIALES.get(clave_limpia))


def restablecer_parametro(ajustes: Ajustes, clave: str) -> ParametroRepositorio:
    clave_limpia = clave.strip()
    if clave_limpia not in PARAMETROS_INICIALES:
        raise RecursoNoEncontrado(f"{clave_limpia} no es uno de los parámetros iniciales conocidos.")
    return asignar_parametro(ajustes, clave_limpia, PARAMETROS_INICIALES[clave_limpia])
