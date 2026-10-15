import json
import logging
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from datetime import date, datetime
from pathlib import Path
from typing import TypeVar
from zoneinfo import ZoneInfo

from pydantic import TypeAdapter, ValidationError

from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.domain.alertas import CodigoAlerta, Condicion, SeveridadAlerta
from cloudcr_backup.domain.enums import ContenidoTablespace, EstadoScript, LogMode
from cloudcr_backup.domain.errores import ErrorServicio, FiltroInvalido, OperacionNoPermitida, RecursoNoEncontrado
from cloudcr_backup.domain.perfil_bd import PerfilBD
from cloudcr_backup.domain.recuperacion import (
    CalendarioSemanal,
    Diagnostico,
    Escenario,
    FallaDetectada,
    FallaResuelta,
    Procedimiento,
    PuntosRecuperacion,
    RegistroRecuperacion,
    ResultadoRecuperacion,
    VistaRecuperacion,
    tablespace_critico,
)
from cloudcr_backup.execution import apertura
from cloudcr_backup.execution.correlator import Consulta
from cloudcr_backup.execution.destino import BaseDestino, EstadoApertura, consulta_destino, estado_apertura_destino
from cloudcr_backup.execution.parser import analizar
from cloudcr_backup.execution.runner import InvocacionRman, Lanzador, lanzar, leer_log
from cloudcr_backup.recovery import calendario as calendario_semanal
from cloudcr_backup.recovery import diagnostico as diagnostico_rman
from cloudcr_backup.recovery import puntos as puntos_recuperacion
from cloudcr_backup.recovery.ejecucion import ESCENARIOS_CON_REINICIO, clasificar, motivos_de_fallo
from cloudcr_backup.recovery.en_linea import (
    PonedorEnLinea,
    ResultadoEnLinea,
    objetos_a_poner_en_linea,
    poner_en_linea,
)
from cloudcr_backup.recovery.procedimientos import RAIZ, SolicitudProcedimiento, generar
from cloudcr_backup.repository import alertas as repositorio_alertas
from cloudcr_backup.repository import bases_datos as repositorio_bases_datos
from cloudcr_backup.repository import ejecuciones as repositorio_ejecuciones
from cloudcr_backup.repository import estrategias as repositorio_estrategias
from cloudcr_backup.repository import parametros as repositorio_parametros
from cloudcr_backup.repository import piezas as repositorio_piezas
from cloudcr_backup.repository import recuperaciones as repositorio_recuperaciones
from cloudcr_backup.repository.bases_datos import BaseDatosRegistrada
from cloudcr_backup.repository.conexion import Conexion, ErrorRepositorio
from cloudcr_backup.repository.ejecuciones import FiltrosHistorial
from cloudcr_backup.rman import nombres
from cloudcr_backup.rman.aprobacion import AprobacionRechazada, hash_de_bytes, script_intacto, validar_transicion
from cloudcr_backup.rman.render import bytes_ascii
from cloudcr_backup.scheduling.reloj import RelojSistema, utc_ingenuo
from cloudcr_backup.services import resolucion
from cloudcr_backup.services.cliente_oracle import preparar_cliente_oracle
from cloudcr_backup.services.sesion import conexion_repositorio

REGISTRO = logging.getLogger("cloudcr.recuperacion")

SQL_ESTADO = "SELECT log_mode, open_mode, dbid FROM v$database"
LIMITE_EJECUCIONES = 500
PARAMETRO_NLS = "rman.nls_lang"
NLS_POR_DEFECTO = "AMERICAN_AMERICA.AL32UTF8"
ARCHIVO_FALLAS = "fallas_detectadas.jsonl"
MAXIMO_FALLAS_LEIDAS = 1000
LARGO_MAXIMO_APROBADOR = 100
LINEAS_LOG_VISIBLES = 80
AVISO_SIN_CONEXION = (
    "No se pudo consultar la instancia (no responde o no está montada): puede indicar pérdida del control file, "
    "del SPFILE o que la instancia está caída. Revise el escenario controlfile o spfile según corresponda."
)
AVISO_FALLO_CONSULTA = (
    "La instancia respondió, pero una consulta del diagnóstico falló por otra causa: no se sugiere controlfile ni "
    "spfile. Corrija el error y vuelva a diagnosticar; mientras tanto no se anota ni se cierra ninguna falla."
)
SUGERENCIA_NUEVO = "Genere un procedimiento nuevo desde la pantalla Recuperación ('cloudcr recuperacion plan')."

AbrirConsulta = Callable[[BaseDestino], AbstractContextManager[Consulta]]
ExisteArchivo = Callable[[str], bool]
Notificador = Callable[[Sequence[Condicion], Ajustes], object]
Comprobador = Callable[[BaseDestino], EstadoApertura]
T = TypeVar("T")
ENTRADA_DE_FALLAS: TypeAdapter[FallaDetectada | FallaResuelta] = TypeAdapter(FallaDetectada | FallaResuelta)


def escenario_de(texto: str) -> Escenario:
    try:
        return Escenario(texto.strip().lower())
    except ValueError as error:
        opciones = ", ".join(e.value for e in Escenario)
        raise FiltroInvalido(f"El escenario {texto!r} no existe.", f"Use uno de: {opciones}.") from error


def _base(base: BaseDatosRegistrada) -> BaseDestino:
    return BaseDestino(oracle_home=Path(base.oracle_home), sid=base.nombre)


def _opcional(consultar: Callable[[], T], vista: str, avisos: list[str]) -> T | None:
    try:
        return consultar()
    except Exception as error:
        avisos.append(f"No se pudo consultar {vista}: {type(error).__name__}: {error}")
        return None


def _diagnostico_sin_datos(base: BaseDatosRegistrada, momento: datetime, error: Exception) -> Diagnostico:
    detalle = f"{type(error).__name__}: {error}"
    if not diagnostico_rman.instancia_no_disponible(error):
        return Diagnostico(
            bd=base.nombre,
            generado_en=momento,
            fallo_consulta=True,
            avisos=[f"No se pudo completar el diagnóstico de {base.nombre}: {detalle}", AVISO_FALLO_CONSULTA],
        )
    sin_conexion = Diagnostico(
        bd=base.nombre,
        generado_en=momento,
        sin_conexion=True,
        avisos=[f"No se pudo consultar V$RECOVER_FILE en {base.nombre}: {detalle}", AVISO_SIN_CONEXION],
    )
    return sin_conexion.model_copy(update={"sugeridos": diagnostico_rman.sugerir(sin_conexion)})


def _diagnosticar(
    base: BaseDatosRegistrada, abrir: AbrirConsulta, existe: ExisteArchivo = diagnostico_rman.archivo_existe
) -> Diagnostico:
    momento = RelojSistema().ahora()
    avisos: list[str] = []
    try:
        with abrir(_base(base)) as consulta:
            filas = consulta(SQL_ESTADO, {})
            pdbs = _opcional(lambda: diagnostico_rman.estado_pdbs(consulta), "V$PDBS", avisos) or []
            archivos = diagnostico_rman.archivos_danados(consulta, pdbs, avisos)
            bloques = _opcional(
                lambda: diagnostico_rman.bloques_corruptos(consulta, pdbs, avisos),
                "V$DATABASE_BLOCK_CORRUPTION",
                avisos,
            )
            redo = _opcional(lambda: diagnostico_rman.redo_logs(consulta, existe), "V$LOG y V$LOGFILE", avisos)
    except Exception as error:
        return _diagnostico_sin_datos(base, momento, error)
    log_mode, open_mode, _ = filas[0] if filas else (None, None, None)
    miembros, actual, grupos = redo or ([], None, [])
    if not archivos:
        avisos.insert(0, "V$RECOVER_FILE no informa archivos que necesiten recuperación.")
    for perdido in {m.grupo: m for m in miembros if m.grupo_perdido and not m.actual}.values():
        avisos.append(
            f"El grupo de redo {perdido.grupo} ({perdido.estado_grupo}) perdió todos sus miembros. No es uno de los 8 "
            f"escenarios: se resuelve con ALTER DATABASE CLEAR LOGFILE GROUP {perdido.grupo} (CLEAR UNARCHIVED si "
            "no se archivó) y un respaldo completo inmediato."
        )
    resultado = Diagnostico(
        bd=base.nombre,
        generado_en=momento,
        log_mode=LogMode(str(log_mode)) if log_mode else None,
        open_mode=None if open_mode is None else str(open_mode),
        archivos=archivos,
        bloques=bloques or [],
        miembros_redo=miembros,
        redo_actual=actual,
        grupos_redo=grupos,
        pdbs=pdbs,
        avisos=avisos,
    )
    return resultado.model_copy(update={"sugeridos": diagnostico_rman.sugerir(resultado)})


def _carpeta(ajustes: Ajustes, bd: str) -> Path:
    return ajustes.rutas.recuperacion / nombres.segmento(bd)


def _anotar_en_calendario(ajustes: Ajustes, bd: str, entrada: FallaDetectada | FallaResuelta, accion: str) -> list[str]:
    ruta = _carpeta(ajustes, bd) / ARCHIVO_FALLAS
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with ruta.open("a", encoding="utf-8") as archivo:
            archivo.write(entrada.model_dump_json() + "\n")
    except OSError as error:
        return [f"No se pudo {accion} en el calendario ({ruta}): {error}"]
    return []


def _registrar_falla(ajustes: Ajustes, resultado: Diagnostico) -> list[str]:
    falla = FallaDetectada(
        bd=resultado.bd,
        detectada_en=resultado.generado_en,
        resumen=diagnostico_rman.resumen(resultado),
        sugeridos=resultado.sugeridos,
    )
    return _anotar_en_calendario(ajustes, resultado.bd, falla, "anotar la falla")


def _cerrar_fallas(ajustes: Ajustes, resultado: Diagnostico) -> list[str]:
    if not fallas_detectadas(ajustes, resultado.bd):
        return []
    cierre = FallaResuelta(bd=resultado.bd, resuelta_en=resultado.generado_en)
    return _anotar_en_calendario(ajustes, resultado.bd, cierre, "cerrar las fallas anotadas")


def fallas_detectadas(ajustes: Ajustes, bd: str) -> list[FallaDetectada]:
    ruta = _carpeta(ajustes, bd) / ARCHIVO_FALLAS
    try:
        lineas = ruta.read_text(encoding="utf-8").splitlines()[-MAXIMO_FALLAS_LEIDAS:]
    except OSError:
        return []
    vigentes: list[FallaDetectada] = []
    for linea in lineas:
        try:
            entrada = ENTRADA_DE_FALLAS.validate_json(linea)
        except ValidationError:
            continue
        if isinstance(entrada, FallaResuelta):
            vigentes.clear()
        else:
            vigentes.append(entrada)
    return vigentes


def _notificar_por_alerta(condiciones: Sequence[Condicion], ajustes: Ajustes) -> object:
    from cloudcr_backup.services import alertas

    return alertas.registrar_evento(condiciones, ajustes)


def _sujeto_caida(base: BaseDatosRegistrada) -> str:
    return f"bd:{base.id}"


def _condicion_caida(base: BaseDatosRegistrada, resultado: Diagnostico) -> Condicion:
    sugeridos = ", ".join(e.value for e in resultado.sugeridos) or "ninguno"
    return Condicion(
        codigo_regla=CodigoAlerta.CAIDA_DETECTADA.value,
        sujeto=_sujeto_caida(base),
        severidad=SeveridadAlerta.ALERTA,
        mensaje=(
            f"Diagnóstico de {base.nombre} ({resultado.generado_en:%Y-%m-%d %H:%M} UTC): "
            f"{diagnostico_rman.resumen(resultado)} Escenarios sugeridos: {sugeridos}."
        ),
        accion_sugerida="Abra Recuperación, revise el diagnóstico y genere el procedimiento del escenario sugerido.",
        bd_id=base.id,
    )


def _notificar(
    ajustes: Ajustes, base: BaseDatosRegistrada, resultado: Diagnostico, notificar: Notificador
) -> list[str]:
    try:
        notificar([_condicion_caida(base, resultado)], ajustes)
    except Exception as error:
        REGISTRO.exception("No se pudo registrar la alerta de caída de %s", base.nombre)
        return [f"No se pudo registrar la alerta de la falla: {type(error).__name__}: {error}"]
    return []


def _resolver_alerta_de_caida(ajustes: Ajustes, base: BaseDatosRegistrada) -> None:
    clave = f"{CodigoAlerta.CAIDA_DETECTADA.value}:{_sujeto_caida(base)}"
    try:
        with conexion_repositorio(ajustes) as conexion:
            for alerta in repositorio_alertas.vigentes(conexion):
                if alerta.clave_dedup == clave:
                    repositorio_alertas.resolver_vigente(conexion, alerta.id)
    except Exception:
        REGISTRO.exception("No se pudo resolver la alerta de caída de %s", base.nombre)


def diagnostico(
    ajustes: Ajustes,
    bd: str,
    abrir: AbrirConsulta = consulta_destino,
    notificar: Notificador | None = None,
    existe: ExisteArchivo = diagnostico_rman.archivo_existe,
) -> Diagnostico:
    preparar_cliente_oracle()
    with conexion_repositorio(ajustes) as conexion:
        base = resolucion.base_por_nombre(conexion, bd)
    resultado = _diagnosticar(base, abrir, existe)
    if resultado.fallo_consulta:
        return resultado
    if resultado.sin_danos:
        _resolver_alerta_de_caida(ajustes, base)
        avisos_de_cierre = _cerrar_fallas(ajustes, resultado)
        return resultado.model_copy(update={"avisos": [*resultado.avisos, *avisos_de_cierre]})
    avisos = _registrar_falla(ajustes, resultado)
    avisos += _notificar(ajustes, base, resultado, notificar or _notificar_por_alerta)
    return resultado.model_copy(update={"avisos": [*resultado.avisos, *avisos]})


def puntos(ajustes: Ajustes, bd: str) -> PuntosRecuperacion:
    preparar_cliente_oracle()
    with conexion_repositorio(ajustes) as conexion:
        base = resolucion.base_por_nombre(conexion, bd)
        ejecuciones = repositorio_ejecuciones.historial_detallado(
            conexion, FiltrosHistorial(bd_id=base.id), LIMITE_EJECUCIONES
        )
        piezas = repositorio_piezas.de_base(conexion, base.id)
        estrategias = {e.codigo: e for e in repositorio_estrategias.listar(conexion, base.id)}
        perfil = repositorio_bases_datos.ultimo_perfil(conexion, base.id)
    return puntos_recuperacion.construir(
        base.nombre, perfil.log_mode if perfil else None, ejecuciones, piezas, estrategias
    )


def calendario(
    ajustes: Ajustes, bd: str, semana: date | None = None, resumen: PuntosRecuperacion | None = None
) -> CalendarioSemanal:
    actual = resumen if resumen is not None else puntos(ajustes, bd)
    zona = ajustes.zona_horaria
    dia = semana or RelojSistema().ahora().astimezone(ZoneInfo(zona)).date()
    return calendario_semanal.construir(actual.bd, actual.puntos, fallas_detectadas(ajustes, actual.bd), dia, zona)


def _contenedores(perfil: PerfilBD | None) -> dict[int, str]:
    if perfil is None:
        return {}
    nombres_contenedor = {c.con_id: c.nombre for c in perfil.contenedores}
    return {d.file_id: nombres_contenedor.get(d.con_id, "") for d in perfil.datafiles}


def _tablespaces_criticos(perfil: PerfilBD | None) -> frozenset[str]:
    if perfil is None:
        return frozenset()
    raiz = {c.con_id for c in perfil.contenedores if c.nombre == RAIZ} | {0, 1}
    return frozenset(
        t.nombre.upper()
        for t in perfil.tablespaces
        if t.con_id in raiz and (t.contenido is ContenidoTablespace.UNDO or tablespace_critico(t.nombre))
    )


def _datafiles_criticos(perfil: PerfilBD | None) -> frozenset[int]:
    if perfil is None:
        return frozenset()
    criticos = _tablespaces_criticos(perfil)
    contenedores = _contenedores(perfil)
    return frozenset(
        d.file_id
        for d in perfil.datafiles
        if contenedores.get(d.file_id, "") in ("", RAIZ) and d.tablespace.upper() in criticos
    )


def _destino_autobackup(ajustes: Ajustes, estrategias_destinos: list[str]) -> str | None:
    if estrategias_destinos:
        return estrategias_destinos[0]
    return str(ajustes.destino_defecto) if ajustes.destino_defecto else None


def _ruta_nueva(carpeta: Path, escenario: Escenario, momento: datetime) -> Path:
    base = f"{escenario.value}_{momento:%Y%m%d_%H%M%S}"
    ruta = carpeta / f"{base}.rman"
    numero = 2
    while ruta.exists():
        ruta = carpeta / f"{base}_{numero}.rman"
        numero += 1
    return ruta


def _borrador_reutilizable(
    ajustes: Ajustes, base: BaseDatosRegistrada, escenario: Escenario, huella: str
) -> RegistroRecuperacion | None:
    try:
        with conexion_repositorio(ajustes) as conexion:
            repositorio_recuperaciones.asegurar_tabla(conexion)
            registro = repositorio_recuperaciones.borrador_sin_usar(conexion, base.id, escenario, huella)
    except (ErrorServicio, ErrorRepositorio):
        REGISTRO.exception("No se pudo buscar un borrador reutilizable de %s", base.nombre)
        return None
    if registro is None or _archivo_intacto(registro) is not True:
        return None
    return registro


def plan(
    ajustes: Ajustes,
    bd: str,
    escenario: str,
    objetivo: str | None = None,
    hasta: datetime | None = None,
    guardar: bool = True,
    abrir: AbrirConsulta = consulta_destino,
    reutilizar: bool = False,
    existe: ExisteArchivo = diagnostico_rman.archivo_existe,
) -> Procedimiento:
    elegido = escenario_de(escenario)
    preparar_cliente_oracle()
    with conexion_repositorio(ajustes) as conexion:
        base = resolucion.base_por_nombre(conexion, bd)
        perfil = repositorio_bases_datos.ultimo_perfil(conexion, base.id)
        destinos = [t.destino.ruta for e in repositorio_estrategias.listar(conexion, base.id) for t in e.tareas]
    diagnosticado = _diagnosticar(base, abrir, existe)
    resumen = puntos(ajustes, bd)
    log_mode = diagnosticado.log_mode or (perfil.log_mode if perfil else LogMode.NOARCHIVELOG)
    procedimiento = generar(
        SolicitudProcedimiento(
            bd=base.nombre,
            escenario=elegido,
            log_mode=log_mode,
            dbid=perfil.dbid if perfil else None,
            destino_autobackup=_destino_autobackup(ajustes, destinos),
            objetivo=objetivo,
            hasta=hasta,
            pieza_controlfile=next((p.controlfile for p in resumen.puntos if p.controlfile), None),
            danados=diagnosticado.archivos,
            contenedor_de_datafile=_contenedores(perfil),
            hay_respaldo=bool(resumen.puntos),
            criticos=_datafiles_criticos(perfil),
            tablespaces_criticos=_tablespaces_criticos(perfil),
            bloques=diagnosticado.bloques,
            miembros_redo=diagnosticado.miembros_redo,
            redo_actual=diagnosticado.redo_actual,
            grupos_redo=diagnosticado.grupos_redo,
            estado_pdbs={p.nombre.upper(): p.modo for p in diagnosticado.pdbs},
            sin_conexion=diagnosticado.sin_conexion,
        )
    )
    avisos = [*procedimiento.avisos, *diagnosticado.avisos]
    if not guardar or procedimiento.script is None:
        return procedimiento.model_copy(update={"avisos": avisos})
    datos = bytes_ascii(procedimiento.script)
    huella = hash_de_bytes(datos)
    existente = _borrador_reutilizable(ajustes, base, elegido, huella) if reutilizar else None
    if existente is not None:
        reutilizado: dict[str, object] = {
            "archivo": existente.ruta_script,
            "hash_sha256": existente.hash_sha256,
            "id": existente.id,
            "estado": existente.estado,
            "avisos": avisos,
        }
        return procedimiento.model_copy(update=reutilizado)
    ruta = _ruta_nueva(_carpeta(ajustes, base.nombre), elegido, diagnosticado.generado_en)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(datos)
    cambios: dict[str, object] = {"archivo": str(ruta), "hash_sha256": huella}
    try:
        with conexion_repositorio(ajustes) as conexion:
            repositorio_recuperaciones.asegurar_tabla(conexion)
            registro = repositorio_recuperaciones.registrar(
                conexion,
                base.id,
                elegido,
                procedimiento.objetivo,
                str(ruta),
                procedimiento.script,
                huella,
                utc_ingenuo(diagnosticado.generado_en),
            )
        cambios.update({"id": registro.id, "estado": registro.estado})
    except (ErrorServicio, ErrorRepositorio) as error:
        REGISTRO.exception("No se pudo registrar el procedimiento de %s", base.nombre)
        avisos.append(f"El procedimiento no quedó registrado para aprobarlo desde la herramienta: {error}")
    return procedimiento.model_copy(update={**cambios, "avisos": avisos})


def procedimientos_sugeridos(
    ajustes: Ajustes,
    resultado: Diagnostico,
    abrir: AbrirConsulta = consulta_destino,
    existe: ExisteArchivo = diagnostico_rman.archivo_existe,
) -> list[Procedimiento]:
    return [
        plan(ajustes, resultado.bd, escenario.value, abrir=abrir, reutilizar=True, existe=existe)
        for escenario in resultado.sugeridos
    ]


def _archivo_intacto(registro: RegistroRecuperacion) -> bool | None:
    try:
        datos = Path(registro.ruta_script).read_bytes()
    except OSError:
        return None
    return script_intacto(datos, registro.hash_sha256)


def _bloqueo(registro: RegistroRecuperacion, intacto: bool | None) -> str | None:
    if registro.estado is not EstadoScript.APROBADO:
        return f"El procedimiento {registro.id} está {registro.estado.value}: apruébelo antes de ejecutarlo."
    if registro.resultado is ResultadoRecuperacion.EN_CURSO:
        return f"El procedimiento {registro.id} ya se está ejecutando."
    if registro.resultado is not None:
        return (
            f"El procedimiento {registro.id} ya se ejecutó ({registro.resultado.value}); cada procedimiento aprobado "
            "se ejecuta una sola vez. " + SUGERENCIA_NUEVO
        )
    if intacto is None:
        return f"No se encuentra el script {registro.ruta_script} en disco. " + SUGERENCIA_NUEVO
    if not intacto:
        return (
            "El script fue modificado después de generarse: su huella SHA-256 no coincide con la registrada. "
            + SUGERENCIA_NUEVO
        )
    return None


def _final_del_log(registro: RegistroRecuperacion) -> str | None:
    if registro.ruta_log is None:
        return None
    lineas = leer_log(Path(registro.ruta_log)).splitlines()
    return "\n".join(lineas[-LINEAS_LOG_VISIBLES:]) or None


def _vista(base: BaseDatosRegistrada, registro: RegistroRecuperacion, aviso: str | None = None) -> VistaRecuperacion:
    intacto = _archivo_intacto(registro)
    return VistaRecuperacion(
        registro=registro,
        bd=base.nombre,
        ambiente=base.ambiente.value,
        archivo_intacto=intacto,
        bloqueo=_bloqueo(registro, intacto),
        aviso=aviso,
        log_rman=_final_del_log(registro),
    )


def _registro(conexion: Conexion, base: BaseDatosRegistrada, procedimiento_id: int) -> RegistroRecuperacion:
    repositorio_recuperaciones.asegurar_tabla(conexion)
    registro = repositorio_recuperaciones.obtener(conexion, procedimiento_id)
    if registro is None or registro.bd_id != base.id:
        raise RecursoNoEncontrado(
            f"No existe el procedimiento de recuperación {procedimiento_id} para {base.nombre}.", SUGERENCIA_NUEVO
        )
    return registro


def _resultado_en_disco(registro: RegistroRecuperacion) -> Path:
    return Path(registro.ruta_script).with_suffix(".resultado.json")


def _reconciliar(conexion: Conexion, registro: RegistroRecuperacion) -> RegistroRecuperacion:
    if registro.resultado is not ResultadoRecuperacion.EN_CURSO:
        return registro
    try:
        guardado = json.loads(_resultado_en_disco(registro).read_text(encoding="utf-8"))
        resultado = ResultadoRecuperacion(guardado["resultado"])
        mensaje = str(guardado["mensaje"])
    except (OSError, ValueError, KeyError, TypeError):
        return registro
    repositorio_recuperaciones.registrar_resultado(conexion, registro.id, resultado, mensaje)
    return repositorio_recuperaciones.obtener(conexion, registro.id) or registro


def estado_procedimiento(ajustes: Ajustes, bd: str, procedimiento_id: int) -> VistaRecuperacion:
    preparar_cliente_oracle()
    with conexion_repositorio(ajustes) as conexion:
        base = resolucion.base_por_nombre(conexion, bd)
        registro = _reconciliar(conexion, _registro(conexion, base, procedimiento_id))
    return _vista(base, registro)


def aprobar(ajustes: Ajustes, bd: str, procedimiento_id: int, aprobado_por: str, confirmo: bool) -> VistaRecuperacion:
    quien = aprobado_por.strip()
    if not confirmo:
        raise OperacionNoPermitida(
            "Falta confirmar que revisó los pasos y el script.",
            "Marque la casilla de confirmación (en la terminal, use --confirmo).",
        )
    if not quien or len(quien) > LARGO_MAXIMO_APROBADOR:
        raise OperacionNoPermitida(
            f"Indique quién aprueba el procedimiento (hasta {LARGO_MAXIMO_APROBADOR} caracteres)."
        )
    preparar_cliente_oracle()
    with conexion_repositorio(ajustes) as conexion:
        base = resolucion.base_por_nombre(conexion, bd)
        registro = _registro(conexion, base, procedimiento_id)
        try:
            validar_transicion(registro.estado, EstadoScript.APROBADO)
        except AprobacionRechazada as error:
            raise OperacionNoPermitida(error.mensaje, SUGERENCIA_NUEVO) from error
        intacto = _archivo_intacto(registro)
        if intacto is not True:
            motivo = "no está en disco" if intacto is None else "fue modificado después de generarse (hash distinto)"
            raise OperacionNoPermitida(f"No se puede aprobar: el script {motivo}.", SUGERENCIA_NUEVO)
        if not repositorio_recuperaciones.aprobar(conexion, procedimiento_id, quien):
            raise OperacionNoPermitida(f"El procedimiento {procedimiento_id} cambió de estado mientras se aprobaba.")
        registro = repositorio_recuperaciones.obtener(conexion, procedimiento_id) or registro
    return _vista(base, registro, f"Procedimiento {procedimiento_id} aprobado por {quien}.")


def preparar_ejecucion(ajustes: Ajustes, bd: str, procedimiento_id: int, confirmo: bool) -> VistaRecuperacion:
    if not confirmo:
        raise OperacionNoPermitida(
            "Falta confirmar que entiende que la ejecución modifica la base de datos de verdad.",
            "Marque la casilla de confirmación (en la terminal, use --confirmo).",
        )
    preparar_cliente_oracle()
    with conexion_repositorio(ajustes) as conexion:
        base = resolucion.base_por_nombre(conexion, bd)
        registro = _registro(conexion, base, procedimiento_id)
        bloqueo = _vista(base, registro).bloqueo
        if bloqueo is not None:
            raise OperacionNoPermitida(bloqueo)
        log = Path(registro.ruta_script).with_suffix(".log")
        if not repositorio_recuperaciones.marcar_en_curso(conexion, procedimiento_id, str(log)):
            raise OperacionNoPermitida(f"El procedimiento {procedimiento_id} ya se está ejecutando o ya se ejecutó.")
        registro = repositorio_recuperaciones.obtener(conexion, procedimiento_id) or registro
    return _vista(base, registro, f"Ejecución del procedimiento {procedimiento_id} lanzada.")


def _guardar_resultado(registro: RegistroRecuperacion, resultado: ResultadoRecuperacion, mensaje: str) -> None:
    datos = {"resultado": resultado.value, "mensaje": mensaje, "fin": RelojSistema().ahora().isoformat()}
    try:
        _resultado_en_disco(registro).write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        REGISTRO.exception("No se pudo guardar el resultado del procedimiento %s en disco", registro.id)


def _correr(
    base: BaseDatosRegistrada,
    registro: RegistroRecuperacion,
    es_cdb: bool,
    nls: str,
    lanzador: Lanzador,
    comprobar: Comprobador,
    ponedor: PonedorEnLinea,
) -> tuple[ResultadoRecuperacion, str]:
    if _archivo_intacto(registro) is not True:
        return (
            ResultadoRecuperacion.NO_LANZADO,
            "El script cambió o desapareció entre la aprobación y la ejecución: no se lanzó RMAN.",
        )
    script = Path(registro.ruta_script)
    log = Path(registro.ruta_log) if registro.ruta_log else script.with_suffix(".log")
    corrida = lanzador(
        InvocacionRman(oracle_home=Path(base.oracle_home), sid=base.nombre, script=script, log=log, nls_lang=nls)
    )
    reapertura = None
    if corrida.lanzado and registro.escenario in ESCENARIOS_CON_REINICIO:
        carpeta = script.parent / f"{script.stem}_apertura"
        reapertura = apertura.asegurar(_base(base), carpeta, es_cdb, lanzador, comprobar, nls)
    analizado = analizar(leer_log(log) or corrida.salida)
    en_linea = None
    if corrida.lanzado and not motivos_de_fallo(corrida, analizado):
        en_linea = _poner_en_linea(base, registro, ponedor)
    return clasificar(corrida, analizado, reapertura, en_linea, registro.escenario)


def _poner_en_linea(
    base: BaseDatosRegistrada, registro: RegistroRecuperacion, ponedor: PonedorEnLinea
) -> ResultadoEnLinea | None:
    objetos = objetos_a_poner_en_linea(registro.escenario, registro.contenido)
    if not objetos:
        return None
    resultados = [ponedor(_base(base), objeto) for objeto in objetos]
    return ResultadoEnLinea(
        detalle=" ".join(r.detalle for r in resultados if r.detalle),
        errores=[error for r in resultados for error in r.errores],
    )


def completar_ejecucion(
    ajustes: Ajustes,
    bd: str,
    procedimiento_id: int,
    lanzador: Lanzador = lanzar,
    comprobar: Comprobador = estado_apertura_destino,
    ponedor: PonedorEnLinea = poner_en_linea,
) -> VistaRecuperacion:
    preparar_cliente_oracle()
    with conexion_repositorio(ajustes) as conexion:
        base = resolucion.base_por_nombre(conexion, bd)
        registro = _registro(conexion, base, procedimiento_id)
        perfil = repositorio_bases_datos.ultimo_perfil(conexion, base.id)
        nls = repositorio_parametros.obtener(conexion, PARAMETRO_NLS) or NLS_POR_DEFECTO
    if registro.resultado is not ResultadoRecuperacion.EN_CURSO:
        raise OperacionNoPermitida(f"El procedimiento {procedimiento_id} no está marcado para ejecutarse.")
    es_cdb = perfil.es_cdb if perfil is not None else True
    try:
        resultado, mensaje = _correr(base, registro, es_cdb, nls, lanzador, comprobar, ponedor)
    except Exception as error:
        REGISTRO.exception("La ejecución del procedimiento %s se interrumpió", procedimiento_id)
        resultado = ResultadoRecuperacion.EJECUTADO_CON_ERRORES
        mensaje = f"La ejecución se interrumpió: {type(error).__name__}: {error}. Revise el log de RMAN."
    _guardar_resultado(registro, resultado, mensaje)
    try:
        with conexion_repositorio(ajustes) as conexion:
            repositorio_recuperaciones.registrar_resultado(conexion, procedimiento_id, resultado, mensaje)
            registro = repositorio_recuperaciones.obtener(conexion, procedimiento_id) or registro
    except (ErrorServicio, ErrorRepositorio):
        REGISTRO.exception("No se pudo registrar el resultado del procedimiento %s", procedimiento_id)
        registro = registro.model_copy(update={"resultado": resultado, "mensaje": mensaje})
    return _vista(base, registro)


def ejecutar(
    ajustes: Ajustes,
    bd: str,
    procedimiento_id: int,
    confirmo: bool,
    lanzador: Lanzador = lanzar,
    comprobar: Comprobador = estado_apertura_destino,
    ponedor: PonedorEnLinea = poner_en_linea,
) -> VistaRecuperacion:
    preparar_ejecucion(ajustes, bd, procedimiento_id, confirmo)
    return completar_ejecucion(ajustes, bd, procedimiento_id, lanzador, comprobar, ponedor)
