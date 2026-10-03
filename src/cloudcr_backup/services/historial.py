import json
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import oracledb

from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.domain.errores import FiltroInvalido, OperacionNoPermitida, RecursoNoEncontrado
from cloudcr_backup.domain.historial import (
    ArchivoExportado,
    ConsultaHistorial,
    DetalleEjecucion,
    LogRman,
    PaginaHistorial,
    PiezaRespaldo,
    VerificacionEjecucion,
)
from cloudcr_backup.presentacion.historial import construir_tabla
from cloudcr_backup.reports import evidencia as reporte_evidencia
from cloudcr_backup.reports import historial as reporte_historial
from cloudcr_backup.reports.historial import TIPO_CONTENIDO, FormatoHistorial
from cloudcr_backup.repository import bases_datos as repositorio_bases_datos
from cloudcr_backup.repository import ejecuciones as repositorio_ejecuciones
from cloudcr_backup.repository.ejecuciones import FiltrosHistorial
from cloudcr_backup.scheduling.reloj import RelojSistema, utc_ingenuo
from cloudcr_backup.services.conversiones import fila_historial, momento_utc
from cloudcr_backup.services.sesion import conexion_repositorio

ARCHIVO_EVIDENCIA = "evidencia.json"
ARCHIVO_LOG_RMAN = "rman.log"
LINEAS_LOG = 15
LIMITE_EXPORTACION = 5000
LIMITE_MAXIMO_PAGINA = 500


def formato_de(texto: str) -> FormatoHistorial:
    try:
        return FormatoHistorial(texto.strip().lower())
    except ValueError as error:
        raise FiltroInvalido(f"El formato {texto!r} no existe.", "Use csv, md o html.") from error


def _filtros(conexion: oracledb.Connection, ajustes: Ajustes, consulta: ConsultaHistorial) -> FiltrosHistorial:
    bd_id = None
    if consulta.bd:
        bd = repositorio_bases_datos.obtener(conexion, consulta.bd.strip().upper())
        if bd is None:
            raise RecursoNoEncontrado(
                f"No hay ninguna base de datos registrada con el nombre {consulta.bd}.",
                "Use 'cloudcr db listar' para ver las registradas.",
            )
        bd_id = bd.id
    zona = ZoneInfo(ajustes.zona_horaria)
    desde = utc_ingenuo(datetime.combine(consulta.desde, time.min, zona)) if consulta.desde else None
    hasta = utc_ingenuo(datetime.combine(consulta.hasta, time.max, zona)) if consulta.hasta else None
    if desde is not None and hasta is not None and desde > hasta:
        raise FiltroInvalido("La fecha 'desde' es posterior a 'hasta'.")
    return FiltrosHistorial(
        bd_id=bd_id,
        estrategia_codigo=consulta.estrategia.strip().upper() if consulta.estrategia else None,
        estado=consulta.estado,
        desde=desde,
        hasta=hasta,
    )


def consultar(ajustes: Ajustes, consulta: ConsultaHistorial) -> PaginaHistorial:
    limite = min(max(consulta.limite, 1), LIMITE_MAXIMO_PAGINA)
    consulta = consulta.model_copy(update={"limite": limite, "pagina": max(consulta.pagina, 1)})
    with conexion_repositorio(ajustes) as conexion:
        filtros = _filtros(conexion, ajustes, consulta)
        total = repositorio_ejecuciones.contar_historial(conexion, filtros)
        filas = repositorio_ejecuciones.historial_detallado(conexion, filtros, limite, consulta.desplazamiento)
    return PaginaHistorial(
        filas=[fila_historial(f) for f in filas], total=total, pagina=consulta.pagina, limite=limite
    )


def _leer_log(ruta: Path) -> LogRman:
    if not ruta.is_file():
        return LogRman(ruta=str(ruta), existe=False)
    try:
        lineas = ruta.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return LogRman(ruta=str(ruta), existe=False)
    if len(lineas) <= LINEAS_LOG * 2:
        return LogRman(ruta=str(ruta), existe=True, primeras_lineas=lineas)
    return LogRman(
        ruta=str(ruta), existe=True, primeras_lineas=lineas[:LINEAS_LOG], ultimas_lineas=lineas[-LINEAS_LOG:]
    )


def _evidencia(ajustes: Ajustes, ejecucion_id: int) -> tuple[Path, dict[str, object] | None]:
    ruta = ajustes.rutas.ejecuciones / str(ejecucion_id) / ARCHIVO_EVIDENCIA
    if not ruta.is_file():
        return ruta, None
    try:
        contenido = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ruta, None
    return ruta, contenido if isinstance(contenido, dict) else {"contenido": contenido}


def detalle(ajustes: Ajustes, ejecucion_id: int) -> DetalleEjecucion:
    with conexion_repositorio(ajustes) as conexion:
        registro = repositorio_ejecuciones.detalle(conexion, ejecucion_id)
        if registro is None:
            raise RecursoNoEncontrado(
                f"No existe la ejecución {ejecucion_id}.", "Use 'cloudcr historial' para ver los ids."
            )
        piezas = repositorio_ejecuciones.piezas(conexion, ejecucion_id)
        verificaciones = repositorio_ejecuciones.verificaciones(conexion, ejecucion_id)
    ruta_evidencia, evidencia = _evidencia(ajustes, ejecucion_id)
    avisos = []
    if evidencia is None:
        avisos.append(
            f"Todavía no existe {ruta_evidencia}: se muestra solo lo registrado en EJECUCION "
            "(la evidencia la genera el pipeline de ejecución)."
        )
    ruta_log = evidencia.get("log_rman") if evidencia else None
    log = _leer_log(Path(str(ruta_log)) if ruta_log else ruta_evidencia.parent / ARCHIVO_LOG_RMAN)
    return DetalleEjecucion(
        fila=fila_historial(registro.ejecucion),
        script_id=registro.ejecucion.script_id,
        script_version=registro.script_version,
        script_hash=registro.script_hash,
        script_aprobado_por=registro.script_aprobado_por,
        script_aprobado_en=momento_utc(registro.script_aprobado_en),
        errores=registro.errores,
        advertencias=registro.advertencias,
        piezas=[
            PiezaRespaldo(
                nombre_archivo=p.nombre_archivo,
                tamano_bytes=p.tamano_bytes,
                tag=p.tag,
                vence_en=momento_utc(p.vence_en),
                obsoleta=p.obsoleta,
            )
            for p in piezas
        ],
        verificaciones=[
            VerificacionEjecucion(
                tipo_prueba=v.tipo_prueba,
                resultado=v.resultado,
                detalle=v.detalle,
                ejecutada_en=momento_utc(v.ejecutada_en),
            )
            for v in verificaciones
        ],
        evidencia=evidencia,
        ruta_evidencia=str(ruta_evidencia) if evidencia is not None else None,
        log_rman=log if log.existe or ruta_log else None,
        avisos=avisos,
    )


def describir_filtros(consulta: ConsultaHistorial) -> str:
    partes = [
        f"BD {consulta.bd.upper()}" if consulta.bd else None,
        f"estrategia {consulta.estrategia.upper()}" if consulta.estrategia else None,
        f"estado {consulta.estado.value}" if consulta.estado else None,
        f"desde {consulta.desde.isoformat()}" if consulta.desde else None,
        f"hasta {consulta.hasta.isoformat()}" if consulta.hasta else None,
    ]
    texto = ", ".join(p for p in partes if p)
    return texto or "ninguno"


def exportar(ajustes: Ajustes, consulta: ConsultaHistorial, formato: str) -> ArchivoExportado:
    elegido = formato_de(formato)
    pagina = consultar(ajustes, consulta.model_copy(update={"limite": LIMITE_EXPORTACION, "pagina": 1}))
    tabla = construir_tabla(pagina.filas)
    ahora = RelojSistema().ahora().astimezone(ZoneInfo(ajustes.zona_horaria))
    contenido = reporte_historial.exportar(tabla, elegido, describir_filtros(consulta), ahora)
    return ArchivoExportado(
        nombre=reporte_historial.nombre_archivo(elegido, ahora),
        tipo_contenido=TIPO_CONTENIDO[elegido],
        contenido=contenido.encode("utf-8"),
    )


def exportar_evidencia(ajustes: Ajustes, ejecucion_id: int, formato: str) -> ArchivoExportado:
    elegido = formato_de(formato)
    if elegido is FormatoHistorial.CSV:
        raise OperacionNoPermitida("La evidencia de una ejecución se exporta en md o html.")
    ahora = RelojSistema().ahora().astimezone(ZoneInfo(ajustes.zona_horaria))
    contenido = reporte_evidencia.exportar(detalle(ajustes, ejecucion_id), elegido, ahora)
    return ArchivoExportado(
        nombre=f"evidencia-ejecucion-{ejecucion_id}.{elegido.value}",
        tipo_contenido=TIPO_CONTENIDO[elegido],
        contenido=contenido.encode("utf-8"),
    )
