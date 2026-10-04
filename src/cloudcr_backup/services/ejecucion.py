from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.domain.ejecucion import ResultadoEjecucion
from cloudcr_backup.domain.enums import EstadoScript
from cloudcr_backup.domain.errores import OperacionNoPermitida
from cloudcr_backup.domain.scripts import SimulacionEjecucion
from cloudcr_backup.execution import pipeline, preflight
from cloudcr_backup.execution.destino import BaseDestino, perfil_actual
from cloudcr_backup.execution.pipeline import medir_carpeta
from cloudcr_backup.execution.preflight import EntradaPreflight
from cloudcr_backup.execution.runner import InvocacionRman, comando, linea_de_comando
from cloudcr_backup.repository import bases_datos as repositorio_bases_datos
from cloudcr_backup.repository import ejecuciones as repositorio_ejecuciones
from cloudcr_backup.repository import scripts as repositorio_scripts
from cloudcr_backup.rman import aprobacion, nombres
from cloudcr_backup.scheduling.reloj import RelojSistema, utc_ingenuo
from cloudcr_backup.services import resolucion
from cloudcr_backup.services.cliente_oracle import preparar_cliente_oracle
from cloudcr_backup.services.scripts import ruta_archivo
from cloudcr_backup.services.sesion import conexion_repositorio

SUGERENCIA_APROBAR = "Genere y apruebe el script con 'cloudcr script generar' y 'cloudcr script aprobar'."


def _momento_actual() -> datetime:
    return utc_ingenuo(RelojSistema().ahora()).replace(microsecond=0)


def programar_ahora(ajustes: Ajustes, bd: str | None, codigo: str, tarea: str) -> int:
    preparar_cliente_oracle()
    with conexion_repositorio(ajustes) as conexion:
        resuelta = resolucion.una_tarea(conexion, bd, codigo, tarea)
        if repositorio_scripts.obtener_vigente(conexion, resuelta.tarea_id) is None:
            raise OperacionNoPermitida(
                f"La tarea {resuelta.estrategia.codigo}/{resuelta.tarea.codigo} no tiene un script APROBADO.",
                SUGERENCIA_APROBAR,
            )
        reclamada = repositorio_ejecuciones.reclamar(conexion, resuelta.tarea_id, _momento_actual())
    if reclamada is None:
        raise OperacionNoPermitida(
            "Ya existe una ejecución de esa tarea para este mismo segundo.", "Espere un momento y vuelva a intentarlo."
        )
    return reclamada.id


def ejecutar(ajustes: Ajustes, ejecucion_id: int) -> ResultadoEjecucion:
    return pipeline.ejecutar(ejecucion_id, ajustes)


def ejecutar_ahora(ajustes: Ajustes, bd: str | None, codigo: str, tarea: str) -> ResultadoEjecucion:
    return ejecutar(ajustes, programar_ahora(ajustes, bd, codigo, tarea))


def verificar(ajustes: Ajustes, ejecucion_id: int) -> ResultadoEjecucion:
    return pipeline.verificar_ejecucion(ejecucion_id, ajustes)


def simular(ajustes: Ajustes, bd: str | None, codigo: str, tarea: str) -> SimulacionEjecucion:
    preparar_cliente_oracle()
    with conexion_repositorio(ajustes) as conexion:
        resuelta = resolucion.una_tarea(conexion, bd, codigo, tarea)
        script = repositorio_scripts.obtener_vigente(conexion, resuelta.tarea_id)
        if script is None:
            raise OperacionNoPermitida(
                f"La tarea {resuelta.estrategia.codigo}/{resuelta.tarea.codigo} no tiene un script APROBADO.",
                SUGERENCIA_APROBAR,
            )
        completo = repositorio_scripts.obtener(conexion, script.id) or script
        log_mode_al_generar = repositorio_bases_datos.log_mode_al_crear_script(conexion, resuelta.base.id, script.id)
    base = BaseDestino(oracle_home=Path(resuelta.base.oracle_home), sid=resuelta.base.nombre)
    error_conexion = None
    log_mode_actual = None
    try:
        log_mode_actual = perfil_actual(base).log_mode
    except Exception as error:
        error_conexion = f"{type(error).__name__}: {error}"
    archivo = ruta_archivo(ajustes, resuelta, completo.version)
    carpeta = medir_carpeta(resuelta.tarea.destino.ruta)
    resultado = preflight.evaluar(
        EntradaPreflight(
            estado_script=EstadoScript.APROBADO,
            hash_registrado=completo.hash_sha256,
            contenido_registrado=completo.contenido,
            bytes_en_disco=archivo.read_bytes() if archivo.is_file() else None,
            acepto_caida=completo.acepto_caida,
            modo=aprobacion.modo_de_script(completo.contenido),
            log_mode_actual=log_mode_actual,
            log_mode_al_generar=log_mode_al_generar,
            destino=resuelta.tarea.destino.ruta,
            destino_escribible=carpeta.escribible,
            libre_bytes=carpeta.libre_bytes,
            error_conexion=error_conexion,
        )
    )
    local = RelojSistema().ahora().astimezone(ZoneInfo(resuelta.tarea.programacion.zona_horaria))
    tag = nombres.tag(resuelta.estrategia.codigo, resuelta.tarea.codigo, local)
    command_id = nombres.command_id(0)
    carpeta_ejecucion = ajustes.rutas.ejecuciones / "<id>"
    sufijo = resuelta.tarea.codigo if len(resuelta.estrategia.tareas) > 1 else None
    invocacion = InvocacionRman(
        oracle_home=base.oracle_home,
        sid=base.sid,
        script=carpeta_ejecucion / nombres.nombre_script(resuelta.estrategia.codigo, resuelta.base.nombre, sufijo),
        log=carpeta_ejecucion / nombres.nombre_log(resuelta.estrategia.codigo, resuelta.base.nombre, sufijo),
        argumentos=(tag, command_id),
    )
    return SimulacionEjecucion(
        bd=resuelta.base.nombre,
        estrategia=resuelta.estrategia.codigo,
        tarea=resuelta.tarea.codigo,
        script_id=completo.id,
        version=completo.version,
        archivo=str(archivo),
        contenido=completo.contenido,
        comando=linea_de_comando(comando(invocacion)),
        tag=tag,
        command_id=command_id,
        aprobado=resultado.aprobado,
        problemas=[str(p) for p in resultado.problemas],
    )
