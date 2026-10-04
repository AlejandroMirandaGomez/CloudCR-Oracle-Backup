import logging
from collections.abc import Callable
from pathlib import Path

import oracledb

from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.domain.enums import EstadoScript, Severidad
from cloudcr_backup.domain.errores import OperacionNoPermitida, RecursoNoEncontrado
from cloudcr_backup.domain.hallazgos import Hallazgo
from cloudcr_backup.domain.perfil_bd import PerfilBD
from cloudcr_backup.domain.scripts import FilaExplicacion, VistaScript
from cloudcr_backup.execution.destino import BaseDestino, perfil_actual
from cloudcr_backup.repository import bases_datos as repositorio_bases_datos
from cloudcr_backup.repository import parametros as repositorio_parametros
from cloudcr_backup.repository import scripts as repositorio_scripts
from cloudcr_backup.repository.scripts import ScriptRman
from cloudcr_backup.rman import aprobacion, nombres
from cloudcr_backup.rman.aprobacion import AprobacionRechazada
from cloudcr_backup.rman.constructor import ScriptNoGenerable, SolicitudScript, construir, explicar
from cloudcr_backup.rman.render import bytes_ascii
from cloudcr_backup.services import resolucion
from cloudcr_backup.services.cliente_oracle import preparar_cliente_oracle
from cloudcr_backup.services.resolucion import TareaResuelta
from cloudcr_backup.services.sesion import conexion_repositorio

REGISTRO = logging.getLogger("cloudcr.scripts")
PARAMETRO_FORMATO = "respaldo.formato_pieza"
ESTADOS_REUTILIZABLES = (EstadoScript.BORRADOR, EstadoScript.APROBADO)

ObtenerPerfil = Callable[[BaseDestino], PerfilBD]


def ruta_archivo(ajustes: Ajustes, resuelta: TareaResuelta, version: int) -> Path:
    return (
        ajustes.rutas.scripts
        / nombres.segmento(resuelta.base.nombre)
        / nombres.segmento(resuelta.estrategia.codigo)
        / nombres.archivo_script_aprobado(resuelta.tarea.codigo, version)
    )


def _escribir(ruta: Path, contenido: str) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(bytes_ascii(contenido))


def _intacto(ruta: Path, hash_sha256: str) -> bool | None:
    if not ruta.is_file():
        return None
    return aprobacion.script_intacto(ruta.read_bytes(), hash_sha256)


def _perfil(
    conexion: oracledb.Connection, resuelta: TareaResuelta, obtener: ObtenerPerfil, avisos: list[str]
) -> PerfilBD:
    base = BaseDestino(oracle_home=Path(resuelta.base.oracle_home), sid=resuelta.base.nombre)
    try:
        perfil = obtener(base)
    except Exception as error:
        guardado = repositorio_bases_datos.ultimo_perfil(conexion, resuelta.base.id)
        if guardado is None:
            raise OperacionNoPermitida(
                f"No se pudo inspeccionar la base {resuelta.base.nombre} ({error}) y no hay un perfil guardado.",
                "Inicie la instancia o ejecute 'cloudcr db inspeccionar' cuando esté disponible.",
            ) from error
        avisos.append(
            f"No se pudo inspeccionar la base en vivo ({error}); se usó el último perfil guardado "
            f"({guardado.capturado_en:%Y-%m-%d %H:%M})."
        )
        return guardado
    repositorio_bases_datos.guardar_perfil(conexion, resuelta.base.id, perfil)
    return perfil


def _hallazgos_de_tarea(resuelta: TareaResuelta, perfil: PerfilBD, parametros: dict[str, str]) -> list[Hallazgo]:
    from cloudcr_backup.validation import motor, reglas  # noqa: F401
    from cloudcr_backup.validation.contexto import ContextoValidacion

    otras = {t.codigo for t in resuelta.estrategia.tareas if t.codigo != resuelta.tarea.codigo}
    hallazgos = motor.validar(ContextoValidacion(estrategia=resuelta.estrategia, perfil=perfil, parametros=parametros))
    return [h for h in hallazgos if h.sujeto not in otras]


def vista(
    ajustes: Ajustes,
    resuelta: TareaResuelta,
    script: ScriptRman,
    perfil: PerfilBD | None = None,
    nueva: bool = False,
    avisos: list[str] | None = None,
    parametros: dict[str, str] | None = None,
) -> VistaScript:
    ruta = ruta_archivo(ajustes, resuelta, script.version)
    explicacion: list[FilaExplicacion] = []
    hallazgos: list[Hallazgo] = []
    if perfil is not None:
        solicitud = SolicitudScript(
            estrategia=resuelta.estrategia,
            tarea=resuelta.tarea,
            log_mode=perfil.log_mode,
            es_cdb=perfil.es_cdb,
            formato_pieza=(parametros or {}).get(PARAMETRO_FORMATO) or nombres.FORMATO_PIEZA_POR_DEFECTO,
        )
        try:
            explicacion = [FilaExplicacion(campo=c, clausula=v) for c, v in explicar(solicitud, construir(solicitud))]
        except ScriptNoGenerable:
            explicacion = []
        hallazgos = _hallazgos_de_tarea(resuelta, perfil, parametros or {})
    return VistaScript(
        bd=resuelta.base.nombre,
        estrategia=resuelta.estrategia.codigo,
        tarea=resuelta.tarea.codigo,
        tarea_id=resuelta.tarea_id,
        script_id=script.id,
        version=script.version,
        estado=script.estado,
        hash_sha256=script.hash_sha256,
        contenido=script.contenido,
        modo=aprobacion.modo_de_script(script.contenido),
        acepto_caida=script.acepto_caida,
        aprobado_por=script.aprobado_por,
        aprobado_en=script.aprobado_en,
        creado_en=script.creado_en,
        motivo_rechazo=script.motivo_rechazo,
        archivo=str(ruta),
        archivo_intacto=_intacto(ruta, script.hash_sha256),
        nueva=nueva,
        explicacion=explicacion,
        hallazgos=hallazgos,
        avisos=avisos or [],
    )


def _generar_tarea(
    ajustes: Ajustes,
    conexion: oracledb.Connection,
    resuelta: TareaResuelta,
    perfil: PerfilBD,
    parametros: dict[str, str],
    avisos: list[str],
) -> VistaScript:
    solicitud = SolicitudScript(
        estrategia=resuelta.estrategia,
        tarea=resuelta.tarea,
        log_mode=perfil.log_mode,
        es_cdb=perfil.es_cdb,
        formato_pieza=parametros.get(PARAMETRO_FORMATO) or nombres.FORMATO_PIEZA_POR_DEFECTO,
    )
    try:
        generado = construir(solicitud)
    except ScriptNoGenerable as error:
        raise OperacionNoPermitida(f"{resuelta.estrategia.codigo}/{resuelta.tarea.codigo}: {error}") from error
    hash_nuevo = aprobacion.calcular_hash(generado.contenido)
    existentes = repositorio_scripts.listar(conexion, resuelta.tarea_id)
    igual = next((s for s in existentes if s.hash_sha256 == hash_nuevo and s.estado in ESTADOS_REUTILIZABLES), None)
    if igual is not None:
        ruta = ruta_archivo(ajustes, resuelta, igual.version)
        if not ruta.is_file():
            _escribir(ruta, igual.contenido)
        return vista(
            ajustes,
            resuelta,
            igual,
            perfil,
            False,
            [*avisos, "El script no cambió: se conserva la versión."],
            parametros,
        )
    for anterior in existentes:
        if anterior.estado is EstadoScript.BORRADOR:
            repositorio_scripts.marcar_obsoleto(conexion, anterior.id)
    nuevo = repositorio_scripts.guardar_borrador(conexion, resuelta.tarea_id, generado.contenido)
    _escribir(ruta_archivo(ajustes, resuelta, nuevo.version), nuevo.contenido)
    guardado = repositorio_scripts.obtener(conexion, nuevo.id) or nuevo
    return vista(ajustes, resuelta, guardado, perfil, True, avisos, parametros)


def generar(
    ajustes: Ajustes,
    bd: str | None,
    codigo: str,
    tarea: str | None = None,
    obtener_perfil: ObtenerPerfil = perfil_actual,
) -> list[VistaScript]:
    preparar_cliente_oracle()
    with conexion_repositorio(ajustes) as conexion:
        resueltas = resolucion.tareas(conexion, bd, codigo, tarea)
        avisos: list[str] = []
        perfil = _perfil(conexion, resueltas[0], obtener_perfil, avisos)
        parametros = repositorio_parametros.listar(conexion)
        return [_generar_tarea(ajustes, conexion, r, perfil, parametros, avisos) for r in resueltas]


def _elegir(conexion: oracledb.Connection, resuelta: TareaResuelta, version: int | None) -> ScriptRman:
    existentes = repositorio_scripts.listar(conexion, resuelta.tarea_id)
    if not existentes:
        raise RecursoNoEncontrado(
            f"La tarea {resuelta.estrategia.codigo}/{resuelta.tarea.codigo} no tiene scripts generados.",
            "Genérelo con 'cloudcr script generar'.",
        )
    if version is not None:
        elegido = next((s for s in existentes if s.version == version), None)
        if elegido is None:
            raise RecursoNoEncontrado(f"No existe la versión {version} del script de {resuelta.tarea.codigo}.")
        return elegido
    vigente = next((s for s in existentes if s.estado is EstadoScript.APROBADO), None)
    borrador = next((s for s in existentes if s.estado is EstadoScript.BORRADOR), None)
    return borrador or vigente or existentes[0]


def ver(ajustes: Ajustes, bd: str | None, codigo: str, tarea: str, version: int | None = None) -> VistaScript:
    with conexion_repositorio(ajustes) as conexion:
        resuelta = resolucion.una_tarea(conexion, bd, codigo, tarea)
        script = _elegir(conexion, resuelta, version)
        perfil = repositorio_bases_datos.ultimo_perfil(conexion, resuelta.base.id)
        parametros = repositorio_parametros.listar(conexion)
    return vista(ajustes, resuelta, script, perfil, parametros=parametros)


def listar(ajustes: Ajustes, bd: str | None, codigo: str) -> list[VistaScript]:
    with conexion_repositorio(ajustes) as conexion:
        resultado = []
        for resuelta in resolucion.tareas(conexion, bd, codigo, None):
            resultado += [vista(ajustes, resuelta, s) for s in repositorio_scripts.listar(conexion, resuelta.tarea_id)]
    return resultado


def aprobar(
    ajustes: Ajustes,
    bd: str | None,
    codigo: str,
    tarea: str,
    aprobado_por: str,
    acepto_caida: bool = False,
    version: int | None = None,
) -> VistaScript:
    with conexion_repositorio(ajustes) as conexion:
        resuelta = resolucion.una_tarea(conexion, bd, codigo, tarea)
        script = _elegir(conexion, resuelta, version)
        try:
            aprobacion.validar_aprobacion(script.estado, script.contenido, script.hash_sha256, acepto_caida)
        except AprobacionRechazada as error:
            raise OperacionNoPermitida(error.mensaje, error.sugerencia) from error
        ruta = ruta_archivo(ajustes, resuelta, script.version)
        if _intacto(ruta, script.hash_sha256) is False:
            raise OperacionNoPermitida(
                f"El archivo {ruta} fue modificado después de generarse: su SHA-256 no coincide con el registrado.",
                "No se aprueba un script distinto del generado. Vuelva a generarlo con 'cloudcr script generar'.",
            )
        perfil = repositorio_bases_datos.ultimo_perfil(conexion, resuelta.base.id)
        parametros = repositorio_parametros.listar(conexion)
        if perfil is not None:
            errores = [h for h in _hallazgos_de_tarea(resuelta, perfil, parametros) if h.severidad is Severidad.ERROR]
            if errores:
                detalle = "; ".join(f"{h.codigo}: {h.mensaje}" for h in errores)
                raise OperacionNoPermitida(
                    f"La validación tiene errores bloqueantes: {detalle}",
                    "Corrija la estrategia (o el modo de archivado) y genere el script de nuevo.",
                )
        for anterior in repositorio_scripts.listar(conexion, resuelta.tarea_id):
            if anterior.estado is EstadoScript.APROBADO and anterior.id != script.id:
                repositorio_scripts.marcar_obsoleto(conexion, anterior.id)
        repositorio_scripts.aprobar(conexion, script.id, aprobado_por, acepto_caida)
        if not ruta.is_file():
            _escribir(ruta, script.contenido)
        aprobado = repositorio_scripts.obtener(conexion, script.id) or script
    return vista(ajustes, resuelta, aprobado, perfil, parametros=parametros)


def rechazar(
    ajustes: Ajustes, bd: str | None, codigo: str, tarea: str, motivo: str, version: int | None = None
) -> VistaScript:
    if not motivo.strip():
        raise OperacionNoPermitida("Indique el motivo del rechazo.")
    with conexion_repositorio(ajustes) as conexion:
        resuelta = resolucion.una_tarea(conexion, bd, codigo, tarea)
        script = _elegir(conexion, resuelta, version)
        try:
            aprobacion.validar_transicion(script.estado, EstadoScript.RECHAZADO)
        except AprobacionRechazada as error:
            raise OperacionNoPermitida(error.mensaje, error.sugerencia) from error
        repositorio_scripts.rechazar(conexion, script.id, motivo.strip()[:1000])
        rechazado = repositorio_scripts.obtener(conexion, script.id) or script
    return vista(ajustes, resuelta, rechazado)
