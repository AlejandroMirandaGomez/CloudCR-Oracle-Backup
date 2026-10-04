import json
import logging
import os
import shutil
import socket
import tempfile
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

from cloudcr_backup.config.ajustes import Ajustes, cargar_ajustes
from cloudcr_backup.domain.alertas import CodigoAlerta, Condicion, SeveridadAlerta
from cloudcr_backup.domain.ejecucion import Evidencia, PiezaEvidencia, ResultadoEjecucion
from cloudcr_backup.domain.enums import EstadoEjecucion, EstadoPrueba, EstadoScript, LogMode, ModoRespaldo
from cloudcr_backup.domain.errores import OperacionNoPermitida, RecursoNoEncontrado
from cloudcr_backup.domain.estrategia import Estrategia, Tarea
from cloudcr_backup.domain.hallazgos import Hallazgo
from cloudcr_backup.domain.perfil_bd import PerfilBD
from cloudcr_backup.execution import apertura, buzon, evidencia, preflight
from cloudcr_backup.execution.apertura import ComprobadorApertura, ResultadoApertura
from cloudcr_backup.execution.clasificador import EntradaClasificacion, PiezaVerificada, clasificar
from cloudcr_backup.execution.correlator import Consulta, Correlacion, correlacionar, piezas_de
from cloudcr_backup.execution.destino import (
    BaseDestino,
    consulta_destino,
    estado_apertura_destino,
    perfil_actual,
)
from cloudcr_backup.execution.parser import CODIGOS_ADVERTENCIA_POR_DEFECTO, analizar
from cloudcr_backup.execution.persistencia import persistir, repositorio
from cloudcr_backup.execution.preflight import (
    CodigoPreflight,
    EntradaPreflight,
    ProblemaPreflight,
    ResultadoPreflight,
)
from cloudcr_backup.execution.runner import InvocacionRman, Lanzador, escribir_script, lanzar, leer_log
from cloudcr_backup.rman import nombres
from cloudcr_backup.rman.aprobacion import modo_de_script
from cloudcr_backup.verification.verificador import tamano_en_disco, verificar

REGISTRO = logging.getLogger("cloudcr.pipeline")

PARAMETRO_TIMEOUT = "rman.timeout_max_min"
PARAMETRO_NLS = "rman.nls_lang"
PARAMETRO_ADVERTENCIAS = "rman.codigos_advertencia"
PARAMETRO_VERIFICACION = "verificacion.automatica"
PARAMETRO_FORMATO = "respaldo.formato_pieza"
TIMEOUT_POR_DEFECTO_MIN = 120
ARCHIVO_BLOQUEO = ".rman_{bd}.lock"
VALORES_FALSOS = frozenset({"false", "no", "n", "0", "off"})

_candados: dict[str, threading.Lock] = {}
_candado_global = threading.Lock()


class EjecucionEnCurso(OperacionNoPermitida):
    pass


@dataclass(frozen=True)
class ContextoEjecucion:
    ejecucion_id: int
    estado: EstadoEjecucion
    programada_para: datetime
    bd_id: int
    bd_nombre: str
    oracle_home: str
    estrategia: Estrategia
    tarea: Tarea
    tarea_id: int
    script_id: int
    script_version: int
    script_estado: EstadoScript
    script_contenido: str
    script_hash: str
    acepto_caida: bool
    log_mode_al_generar: LogMode | None
    parametros: dict[str, str] = field(default_factory=dict)
    estimado_bytes: int | None = None

    @property
    def base(self) -> BaseDestino:
        return BaseDestino(oracle_home=Path(self.oracle_home), sid=self.bd_nombre)

    @property
    def zona_horaria(self) -> str:
        return self.tarea.programacion.zona_horaria


@dataclass
class Corrida:
    contexto: ContextoEjecucion
    modo: ModoRespaldo
    carpeta: Path
    es_cdb: bool
    timeout: int
    nls: str
    tag: str
    command_id: str
    script: Path
    log: Path
    reapertura_intentada: bool = False


class PuertoRepositorio(Protocol):
    def cargar(self, ejecucion_id: int) -> ContextoEjecucion: ...

    def marcar_en_curso(self, ejecucion_id: int, agente: str) -> None: ...

    def guardar_perfil(self, bd_id: int, perfil: PerfilBD) -> None: ...

    def persistir(self, evidencia: Evidencia) -> None: ...


@dataclass(frozen=True)
class EstadoCarpeta:
    escribible: bool
    libre_bytes: int | None


def medir_carpeta(ruta: str) -> EstadoCarpeta:
    carpeta = Path(ruta)
    if not carpeta.is_dir():
        return EstadoCarpeta(False, None)
    try:
        with tempfile.NamedTemporaryFile(dir=carpeta, prefix=".cloudcr_", delete=True):
            pass
        libre: int | None = shutil.disk_usage(carpeta).free
    except OSError:
        return EstadoCarpeta(False, None)
    return EstadoCarpeta(True, libre)


def _ahora_utc() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class EntornoValidacion:
    parametros: dict[str, str]
    libres: dict[str, int]
    estimados: dict[str, int]
    escribibles: dict[str, bool]


Validador = Callable[[Estrategia, PerfilBD, EntornoValidacion], list[Hallazgo]]


def _sin_validacion(estrategia: Estrategia, perfil: PerfilBD, entorno: EntornoValidacion) -> list[Hallazgo]:
    return []


def _sin_evento(_: Sequence[Condicion]) -> None:
    return None


def _sin_evaluacion(_: int) -> None:
    return None


@dataclass
class Dependencias:
    repositorio: PuertoRepositorio
    carpeta_ejecuciones: Path
    carpeta_scripts: Path
    carpeta_buzon: Path
    perfil: Callable[[BaseDestino], PerfilBD] = perfil_actual
    lanzar: Lanzador = lanzar
    catalogo: Callable[[BaseDestino], AbstractContextManager[Consulta]] = consulta_destino
    comprobar_apertura: ComprobadorApertura = estado_apertura_destino
    medir_destino: Callable[[str], EstadoCarpeta] = medir_carpeta
    medir_archivo: Callable[[str], int | None] = tamano_en_disco
    validar: Validador = _sin_validacion
    registrar_evento: Callable[[Sequence[Condicion]], object] = _sin_evento
    evaluar_alertas: Callable[[int], object] = _sin_evaluacion
    ahora: Callable[[], datetime] = _ahora_utc
    agente: str = field(default_factory=socket.gethostname)


def _entero(parametros: dict[str, str], clave: str, defecto: int) -> int:
    try:
        valor = int(parametros[clave])
    except (KeyError, ValueError):
        return defecto
    return valor if valor > 0 else defecto


def codigos_advertencia(parametros: dict[str, str]) -> frozenset[str]:
    texto = parametros.get(PARAMETRO_ADVERTENCIAS)
    if not texto:
        return CODIGOS_ADVERTENCIA_POR_DEFECTO
    try:
        valores = json.loads(texto)
    except ValueError:
        return CODIGOS_ADVERTENCIA_POR_DEFECTO
    return frozenset(str(v) for v in valores) if isinstance(valores, list) else CODIGOS_ADVERTENCIA_POR_DEFECTO


def verificacion_automatica(parametros: dict[str, str]) -> bool:
    return parametros.get(PARAMETRO_VERIFICACION, "true").strip().lower() not in VALORES_FALSOS


def ruta_script_aprobado(carpeta_scripts: Path, contexto: ContextoEjecucion) -> Path:
    return (
        carpeta_scripts
        / nombres.segmento(contexto.bd_nombre)
        / nombres.segmento(contexto.estrategia.codigo)
        / nombres.archivo_script_aprobado(contexto.tarea.codigo, contexto.script_version)
    )


def _candado_de(bd: str) -> threading.Lock:
    with _candado_global:
        return _candados.setdefault(bd, threading.Lock())


@contextmanager
def bloqueo_bd(carpeta: Path, bd: str, vencimiento_segundos: int) -> Iterator[None]:
    candado = _candado_de(bd)
    if not candado.acquire(blocking=False):
        raise EjecucionEnCurso(f"Ya hay un RMAN en curso sobre la base {bd} en este proceso.")
    carpeta.mkdir(parents=True, exist_ok=True)
    archivo = carpeta / ARCHIVO_BLOQUEO.format(bd=nombres.segmento(bd))
    try:
        try:
            descriptor = os.open(archivo, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            edad = max(time.time() - archivo.stat().st_mtime, 0.0)
            if edad < vencimiento_segundos:
                raise EjecucionEnCurso(
                    f"Ya hay un RMAN en curso sobre la base {bd} (bloqueo {archivo}).",
                    "Espere a que termine; si no hay ninguno, borre el archivo de bloqueo.",
                ) from None
            archivo.unlink(missing_ok=True)
            descriptor = os.open(archivo, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(descriptor, "w", encoding="ascii") as manejador:
            manejador.write(str(os.getpid()))
        try:
            yield
        finally:
            archivo.unlink(missing_ok=True)
    finally:
        candado.release()


class Pipeline:
    def __init__(self, dependencias: Dependencias) -> None:
        self._d = dependencias

    def ejecutar(self, ejecucion_id: int) -> ResultadoEjecucion:
        contexto = self._d.repositorio.cargar(ejecucion_id)
        if contexto.estado is not EstadoEjecucion.PROGRAMADA:
            raise OperacionNoPermitida(
                f"La ejecución {ejecucion_id} está {contexto.estado.value}; solo se ejecuta una PROGRAMADA."
            )
        timeout = _entero(contexto.parametros, PARAMETRO_TIMEOUT, TIMEOUT_POR_DEFECTO_MIN) * 60
        try:
            with bloqueo_bd(self._d.carpeta_ejecuciones, contexto.bd_nombre, timeout + 600):
                return self._ejecutar(contexto, timeout)
        except EjecucionEnCurso as ocupada:
            modo = modo_de_script(contexto.script_contenido)
            carpeta = evidencia.carpeta_ejecucion(self._d.carpeta_ejecuciones, ejecucion_id)
            problema = ProblemaPreflight(CodigoPreflight.BD_OCUPADA, ocupada.mensaje, ocupada.sugerencia)
            return self._bloquear(
                contexto, self._base_evidencia(contexto, modo), carpeta, ResultadoPreflight([problema])
            )

    def _base_evidencia(self, contexto: ContextoEjecucion, modo: ModoRespaldo) -> Evidencia:
        return Evidencia(
            ejecucion_id=contexto.ejecucion_id,
            bd=contexto.bd_nombre,
            bd_id=contexto.bd_id,
            estrategia=contexto.estrategia.codigo,
            estrategia_nombre=contexto.estrategia.nombre,
            tarea=contexto.tarea.codigo,
            tarea_id=contexto.tarea_id,
            tipo_respaldo=contexto.tarea.como.tipo_respaldo,
            modo_respaldo=modo,
            programada_para=contexto.programada_para,
            estado=EstadoEjecucion.EN_CURSO,
            script_id=contexto.script_id,
            script_version=contexto.script_version,
            script_hash=contexto.script_hash,
            ubicacion=contexto.tarea.destino.ruta,
            agente=self._d.agente,
        )

    def _preflight(
        self, contexto: ContextoEjecucion, modo: ModoRespaldo, ruta_aprobado: Path
    ) -> tuple[ResultadoPreflight, PerfilBD | None]:
        bytes_en_disco = None
        if ruta_aprobado.is_file():
            bytes_en_disco = ruta_aprobado.read_bytes()
        perfil: PerfilBD | None = None
        error_conexion = None
        try:
            perfil = self._d.perfil(contexto.base)
        except Exception as error:
            error_conexion = f"{type(error).__name__}: {error}"
        destino = contexto.tarea.destino.ruta
        carpeta = self._d.medir_destino(destino)
        hallazgos: list[Hallazgo] = []
        if perfil is not None:
            self._guardar_perfil(contexto, perfil)
            entorno = EntornoValidacion(
                parametros=contexto.parametros,
                libres={destino: carpeta.libre_bytes} if carpeta.libre_bytes is not None else {},
                estimados=(
                    {contexto.tarea.codigo: contexto.estimado_bytes} if contexto.estimado_bytes is not None else {}
                ),
                escribibles={destino: carpeta.escribible},
            )
            otras = {t.codigo for t in contexto.estrategia.tareas if t.codigo != contexto.tarea.codigo}
            hallazgos = [h for h in self._d.validar(contexto.estrategia, perfil, entorno) if h.sujeto not in otras]
        resultado = preflight.evaluar(
            EntradaPreflight(
                estado_script=contexto.script_estado,
                hash_registrado=contexto.script_hash,
                contenido_registrado=contexto.script_contenido,
                bytes_en_disco=bytes_en_disco,
                acepto_caida=contexto.acepto_caida,
                modo=modo,
                log_mode_actual=perfil.log_mode if perfil is not None else None,
                log_mode_al_generar=contexto.log_mode_al_generar,
                destino=destino,
                destino_escribible=carpeta.escribible,
                libre_bytes=carpeta.libre_bytes,
                estimado_bytes=contexto.estimado_bytes,
                hallazgos=hallazgos,
                error_conexion=error_conexion,
            )
        )
        if resultado.aprobado and bytes_en_disco is None:
            escribir_script(ruta_aprobado, contexto.script_contenido)
        return resultado, perfil

    def _guardar_perfil(self, contexto: ContextoEjecucion, perfil: PerfilBD) -> None:
        try:
            self._d.repositorio.guardar_perfil(contexto.bd_id, perfil)
        except Exception:
            REGISTRO.exception("No se pudo guardar el perfil de %s antes de la ejecución", contexto.bd_nombre)

    def _registrar(self, carpeta: Path, registro: Evidencia) -> tuple[Path, bool]:
        ruta = evidencia.escribir(carpeta, registro)
        try:
            self._d.repositorio.persistir(registro)
        except Exception as error:
            REGISTRO.warning("La evidencia %s queda en el buzón: %s", registro.ejecucion_id, error)
            buzon.depositar(self._d.carpeta_buzon, registro)
            return ruta, True
        buzon.descartar(self._d.carpeta_buzon, registro.ejecucion_id)
        return ruta, False

    def _bloquear(
        self, contexto: ContextoEjecucion, base: Evidencia, carpeta: Path, resultado: ResultadoPreflight
    ) -> ResultadoEjecucion:
        momento = self._d.ahora()
        motivos = [str(p) for p in resultado.problemas]
        registro = base.model_copy(
            update={
                "estado": EstadoEjecucion.BLOQUEADA,
                "estado_prueba": EstadoPrueba.NO_APLICA,
                "inicio": momento,
                "fin": momento,
                "duracion_segundos": 0,
                "motivos": motivos,
                "errores": motivos,
                "mensaje_rman": "Bloqueada por el preflight: " + resultado.problemas[0].mensaje,
                "generado_en": momento,
            }
        )
        ruta, en_buzon = self._registrar(carpeta, registro)
        if resultado.script_alterado:
            self._evento(
                contexto,
                CodigoAlerta.SCRIPT_ALTERADO,
                f"El script aprobado de {contexto.estrategia.codigo}/{contexto.tarea.codigo} (versión "
                f"{contexto.script_version}) fue modificado: la ejecución {contexto.ejecucion_id} quedó BLOQUEADA.",
            )
        self._evaluar(contexto.ejecucion_id)
        return ResultadoEjecucion(
            ejecucion_id=contexto.ejecucion_id,
            estado=EstadoEjecucion.BLOQUEADA,
            estado_prueba=EstadoPrueba.NO_APLICA,
            motivos=motivos,
            carpeta=str(carpeta),
            evidencia=str(ruta),
            en_buzon=en_buzon,
        )

    def _evento(self, contexto: ContextoEjecucion, codigo: CodigoAlerta, mensaje: str) -> None:
        condicion = Condicion(
            codigo_regla=codigo.value,
            sujeto=f"tarea:{contexto.tarea_id}",
            severidad=SeveridadAlerta.ALERTA,
            mensaje=mensaje,
            bd_id=contexto.bd_id,
            estrategia_id=contexto.estrategia.id,
            tarea_id=contexto.tarea_id,
            ejecucion_id=contexto.ejecucion_id,
        )
        try:
            self._d.registrar_evento([condicion])
        except Exception:
            REGISTRO.exception("No se pudo registrar la alerta %s", codigo.value)

    def _evaluar(self, ejecucion_id: int) -> None:
        try:
            self._d.evaluar_alertas(ejecucion_id)
        except Exception:
            REGISTRO.exception("No se pudieron evaluar las alertas tras la ejecución %s", ejecucion_id)

    def _tag(self, contexto: ContextoEjecucion) -> str:
        programada = contexto.programada_para.replace(tzinfo=UTC)
        try:
            local = programada.astimezone(ZoneInfo(contexto.zona_horaria))
        except (KeyError, ValueError):
            local = programada
        return nombres.tag(contexto.estrategia.codigo, contexto.tarea.codigo, local)

    def _piezas(
        self, contexto: ContextoEjecucion, tag: str, desde_log: list[str], correlacion: Correlacion, fin: datetime
    ) -> list[PiezaEvidencia]:
        dias = contexto.estrategia.retencion.ventana_dias
        vence = fin + timedelta(days=dias) if dias else None
        catalogo = {p.handle.upper(): p for p in correlacion.piezas}
        rutas = list(dict.fromkeys([*desde_log, *(p.handle for p in correlacion.piezas)]))
        vistas: set[str] = set()
        piezas = []
        for ruta in rutas:
            if ruta.upper() in vistas:
                continue
            vistas.add(ruta.upper())
            registrada = catalogo.get(ruta.upper())
            tamano = self._d.medir_archivo(ruta)
            piezas.append(
                PiezaEvidencia(
                    ruta=ruta,
                    tamano_bytes=tamano if tamano is not None else (registrada.bytes if registrada else None),
                    existe=tamano is not None,
                    tag=registrada.tag if registrada else None,
                    conjunto=registrada.conjunto if registrada else None,
                    vence_en=vence,
                )
            )
        return piezas

    def _correlacionar(self, contexto: ContextoEjecucion, tag: str, command_id: str) -> Correlacion:
        try:
            with self._d.catalogo(contexto.base) as consulta:
                return correlacionar(consulta, tag, command_id)
        except Exception as error:
            return Correlacion(consultado=False, error=f"{type(error).__name__}: {error}")

    def _apertura(self, contexto: ContextoEjecucion, carpeta: Path, nls: str, es_cdb: bool) -> ResultadoApertura:
        resultado = apertura.asegurar(contexto.base, carpeta, es_cdb, self._d.lanzar, self._d.comprobar_apertura, nls)
        if not resultado.abierta:
            self._evento(
                contexto,
                CodigoAlerta.BASE_NO_REABIERTA,
                f"Tras el respaldo consistente de la ejecución {contexto.ejecucion_id}, la base "
                f"{contexto.bd_nombre} no quedó abierta: {resultado.detalle}",
            )
        return resultado

    def _ejecutar(self, contexto: ContextoEjecucion, timeout: int) -> ResultadoEjecucion:
        modo = modo_de_script(contexto.script_contenido)
        carpeta = evidencia.carpeta_ejecucion(self._d.carpeta_ejecuciones, contexto.ejecucion_id)
        base = self._base_evidencia(contexto, modo)
        resultado_preflight, perfil = self._preflight(
            contexto, modo, ruta_script_aprobado(self._d.carpeta_scripts, contexto)
        )
        if not resultado_preflight.aprobado:
            return self._bloquear(contexto, base, carpeta, resultado_preflight)
        tarea_nombre = contexto.tarea.codigo if len(contexto.estrategia.tareas) > 1 else None
        corrida = Corrida(
            contexto=contexto,
            modo=modo,
            carpeta=carpeta,
            es_cdb=perfil.es_cdb if perfil is not None else True,
            timeout=timeout,
            nls=contexto.parametros.get(PARAMETRO_NLS) or "AMERICAN_AMERICA.AL32UTF8",
            tag=self._tag(contexto),
            command_id=nombres.command_id(contexto.ejecucion_id),
            script=carpeta / nombres.nombre_script(contexto.estrategia.codigo, contexto.bd_nombre, tarea_nombre),
            log=carpeta / nombres.nombre_log(contexto.estrategia.codigo, contexto.bd_nombre, tarea_nombre),
        )
        self._d.repositorio.marcar_en_curso(contexto.ejecucion_id, self._d.agente)
        inicio = self._d.ahora()
        en_curso = base.model_copy(
            update={
                "inicio": inicio,
                "tag": corrida.tag,
                "command_id": corrida.command_id,
                "script_ruta": str(corrida.script),
                "log_rman": str(corrida.log),
                "generado_en": inicio,
            }
        )
        try:
            return self._correr(corrida, en_curso, inicio)
        except Exception as error:
            REGISTRO.exception("La ejecución %s falló por un error interno", contexto.ejecucion_id)
            return self._fallo_interno(corrida, en_curso, inicio, error)

    def _correr(self, corrida: Corrida, en_curso: Evidencia, inicio: datetime) -> ResultadoEjecucion:
        contexto = corrida.contexto
        escribir_script(corrida.script, contexto.script_contenido)
        evidencia.escribir(corrida.carpeta, en_curso)
        resultado_rman = self._d.lanzar(
            InvocacionRman(
                oracle_home=contexto.base.oracle_home,
                sid=contexto.base.sid,
                script=corrida.script,
                log=corrida.log,
                argumentos=(corrida.tag, corrida.command_id),
                timeout_segundos=corrida.timeout,
                nls_lang=corrida.nls,
            )
        )
        reapertura: ResultadoApertura | None = None
        if corrida.modo is ModoRespaldo.CONSISTENTE:
            corrida.reapertura_intentada = True
            reapertura = self._apertura(contexto, corrida.carpeta, corrida.nls, corrida.es_cdb)
        analizado = analizar(leer_log(corrida.log), codigos_advertencia(contexto.parametros))
        correlacion = self._correlacionar(contexto, corrida.tag, corrida.command_id)
        fin = self._d.ahora()
        piezas = self._piezas(contexto, corrida.tag, [p.handle for p in analizado.piezas], correlacion, fin)
        clasificacion = clasificar(
            EntradaClasificacion(
                codigo_salida=resultado_rman.codigo_salida,
                agotado=resultado_rman.agotado,
                log=analizado,
                estado_job=correlacion.estado_job,
                catalogo_consultado=correlacion.consultado,
                piezas=[PiezaVerificada(p.ruta, p.existe, p.tamano_bytes) for p in piezas],
                reapertura_correcta=reapertura.abierta if reapertura is not None else None,
                error_lanzamiento=resultado_rman.error_lanzamiento,
            )
        )
        principal = analizado.primer_error
        errores = [str(e) for e in analizado.errores]
        if reapertura is not None:
            errores += reapertura.errores
        registro = en_curso.model_copy(
            update={
                "estado": clasificacion.estado,
                "estado_prueba": EstadoPrueba.PENDIENTE if clasificacion.correcta else EstadoPrueba.NO_APLICA,
                "fin": fin,
                "duracion_segundos": max(int((fin - inicio).total_seconds()), 0),
                "motivos": clasificacion.motivos,
                "mensaje_rman": str(principal) if principal is not None else clasificacion.motivos[0],
                "errores": errores,
                "advertencias": [str(a) for a in analizado.advertencias],
                "codigo_salida": resultado_rman.codigo_salida,
                "piezas": piezas,
                "estado_job_rman": correlacion.estado_job,
                "reapertura_correcta": reapertura.abierta if reapertura is not None else None,
                "generado_en": fin,
            }
        )
        ruta, en_buzon = self._registrar(corrida.carpeta, registro)
        avisos = [correlacion.error] if correlacion.error else []
        if clasificacion.correcta and verificacion_automatica(contexto.parametros):
            registro = self._con_verificacion(contexto, registro, corrida.tag, corrida.carpeta, corrida.nls)
            ruta, en_buzon = self._registrar(corrida.carpeta, registro)
        self._evaluar(contexto.ejecucion_id)
        return ResultadoEjecucion(
            ejecucion_id=contexto.ejecucion_id,
            estado=registro.estado,
            estado_prueba=registro.estado_prueba,
            motivos=registro.motivos,
            carpeta=str(corrida.carpeta),
            evidencia=str(ruta),
            en_buzon=en_buzon,
            piezas=registro.piezas,
            avisos=avisos,
        )

    def _fallo_interno(
        self, corrida: Corrida, en_curso: Evidencia, inicio: datetime, error: Exception
    ) -> ResultadoEjecucion:
        contexto = corrida.contexto
        if corrida.modo is ModoRespaldo.CONSISTENTE and not corrida.reapertura_intentada:
            try:
                self._apertura(contexto, corrida.carpeta, corrida.nls, corrida.es_cdb)
            except Exception:
                REGISTRO.exception("No se pudo asegurar la apertura tras el error en %s", contexto.ejecucion_id)
        fin = self._d.ahora()
        motivo = f"Error interno durante la ejecución: {type(error).__name__}: {error}"
        registro = en_curso.model_copy(
            update={
                "estado": EstadoEjecucion.FALLIDA,
                "estado_prueba": EstadoPrueba.NO_APLICA,
                "fin": fin,
                "duracion_segundos": max(int((fin - inicio).total_seconds()), 0),
                "motivos": [motivo],
                "mensaje_rman": motivo,
                "errores": [motivo],
                "generado_en": fin,
            }
        )
        try:
            ruta, en_buzon = self._registrar(corrida.carpeta, registro)
        except Exception:
            REGISTRO.exception("No se pudo guardar la evidencia del error en %s", contexto.ejecucion_id)
            ruta, en_buzon = corrida.carpeta / evidencia.ARCHIVO_EVIDENCIA, False
        self._evaluar(contexto.ejecucion_id)
        return ResultadoEjecucion(
            ejecucion_id=contexto.ejecucion_id,
            estado=EstadoEjecucion.FALLIDA,
            estado_prueba=EstadoPrueba.NO_APLICA,
            motivos=[motivo],
            carpeta=str(corrida.carpeta),
            evidencia=str(ruta),
            en_buzon=en_buzon,
        )

    def _con_verificacion(
        self, contexto: ContextoEjecucion, registro: Evidencia, tag: str, carpeta: Path, nls: str
    ) -> Evidencia:
        try:
            with self._d.catalogo(contexto.base) as consulta:
                resultado = verificar(
                    contexto.base,
                    tag,
                    carpeta,
                    lambda etiqueta: piezas_de(consulta, etiqueta),
                    self._d.lanzar,
                    nls,
                    medir=self._d.medir_archivo,
                    ahora=self._d.ahora,
                )
        except Exception as error:
            REGISTRO.exception("La verificación de la ejecución %s no pudo completarse", contexto.ejecucion_id)
            return registro.model_copy(
                update={"motivos": [*registro.motivos, f"La verificación no pudo completarse: {error}"]}
            )
        return registro.model_copy(
            update={"estado_prueba": resultado.estado, "pruebas": resultado.pruebas, "log_verificacion": resultado.log}
        )

    def verificar(self, ejecucion_id: int) -> ResultadoEjecucion:
        contexto = self._d.repositorio.cargar(ejecucion_id)
        if contexto.estado not in (EstadoEjecucion.EXITOSA, EstadoEjecucion.CON_ADVERTENCIAS):
            raise OperacionNoPermitida(
                f"La ejecución {ejecucion_id} está {contexto.estado.value}; solo se verifica un respaldo correcto."
            )
        carpeta = evidencia.carpeta_ejecucion(self._d.carpeta_ejecuciones, ejecucion_id)
        ruta = carpeta / evidencia.ARCHIVO_EVIDENCIA
        if not ruta.is_file():
            raise OperacionNoPermitida(
                f"No existe la evidencia {ruta}: no se conoce el tag del respaldo que hay que verificar."
            )
        registro = evidencia.leer(ruta)
        if not registro.tag:
            raise OperacionNoPermitida(f"La evidencia de la ejecución {ejecucion_id} no tiene tag de RMAN.")
        nls = contexto.parametros.get(PARAMETRO_NLS) or "AMERICAN_AMERICA.AL32UTF8"
        verificado = self._con_verificacion(contexto, registro, registro.tag, carpeta, nls)
        verificado = verificado.model_copy(update={"generado_en": self._d.ahora()})
        guardada, en_buzon = self._registrar(carpeta, verificado)
        self._evaluar(ejecucion_id)
        return ResultadoEjecucion(
            ejecucion_id=ejecucion_id,
            estado=verificado.estado,
            estado_prueba=verificado.estado_prueba,
            motivos=[f"{p.tipo}: {p.detalle}" for p in verificado.pruebas],
            carpeta=str(carpeta),
            evidencia=str(guardada),
            en_buzon=en_buzon,
            piezas=verificado.piezas,
        )

    def asegurar_apertura(self, ejecucion_id: int) -> ResultadoApertura:
        contexto = self._d.repositorio.cargar(ejecucion_id)
        carpeta = evidencia.carpeta_ejecucion(self._d.carpeta_ejecuciones, ejecucion_id)
        nls = contexto.parametros.get(PARAMETRO_NLS) or "AMERICAN_AMERICA.AL32UTF8"
        return self._apertura(contexto, carpeta, nls, True)


def validar_estrategia(estrategia: Estrategia, perfil: PerfilBD, entorno: EntornoValidacion) -> list[Hallazgo]:
    from cloudcr_backup.validation import motor, reglas  # noqa: F401
    from cloudcr_backup.validation.contexto import ContextoValidacion

    return motor.validar(
        ContextoValidacion(
            estrategia=estrategia,
            perfil=perfil,
            parametros=entorno.parametros,
            espacio_libre_destino_bytes=entorno.libres,
            espacio_estimado_bytes=entorno.estimados,
            destinos_escribibles=entorno.escribibles,
        )
    )


class RepositorioOracle:
    def __init__(self, ajustes: Ajustes) -> None:
        self._ajustes = ajustes

    def cargar(self, ejecucion_id: int) -> ContextoEjecucion:
        from cloudcr_backup.repository import bases_datos, ejecuciones, estrategias, parametros, scripts

        with repositorio(self._ajustes) as conexion:
            registro = ejecuciones.detalle(conexion, ejecucion_id)
            if registro is None:
                raise RecursoNoEncontrado(f"No existe la ejecución {ejecucion_id}.")
            fila = registro.ejecucion
            bd = bases_datos.obtener(conexion, fila.bd_nombre)
            estrategia = estrategias.obtener(conexion, fila.bd_id, fila.estrategia_codigo)
            script = scripts.obtener(conexion, fila.script_id)
            if bd is None or estrategia is None or script is None:
                raise RecursoNoEncontrado(f"La ejecución {ejecucion_id} hace referencia a datos que ya no existen.")
            tarea = estrategia.tarea(fila.tarea_codigo)
            if tarea is None:
                raise RecursoNoEncontrado(
                    f"La tarea {fila.tarea_codigo} de la ejecución {ejecucion_id} ya no existe en la estrategia."
                )
            return ContextoEjecucion(
                ejecucion_id=ejecucion_id,
                estado=fila.estado,
                programada_para=fila.programada_para,
                bd_id=bd.id,
                bd_nombre=bd.nombre,
                oracle_home=bd.oracle_home,
                estrategia=estrategia,
                tarea=tarea,
                tarea_id=fila.tarea_id,
                script_id=script.id,
                script_version=script.version,
                script_estado=script.estado,
                script_contenido=script.contenido,
                script_hash=script.hash_sha256,
                acepto_caida=script.acepto_caida,
                log_mode_al_generar=bases_datos.log_mode_al_crear_script(conexion, bd.id, script.id),
                parametros=parametros.listar(conexion),
                estimado_bytes=ejecuciones.tamano_ultimo_exito_por_tarea(conexion).get(fila.tarea_id),
            )

    def marcar_en_curso(self, ejecucion_id: int, agente: str) -> None:
        from cloudcr_backup.repository import ejecuciones

        with repositorio(self._ajustes) as conexion:
            ejecuciones.marcar_en_curso(conexion, ejecucion_id, agente)

    def guardar_perfil(self, bd_id: int, perfil: PerfilBD) -> None:
        from cloudcr_backup.repository import bases_datos

        with repositorio(self._ajustes) as conexion:
            bases_datos.guardar_perfil(conexion, bd_id, perfil)

    def persistir(self, registro: Evidencia) -> None:
        with repositorio(self._ajustes) as conexion:
            persistir(conexion, registro)


def _registrar_evento(ajustes: Ajustes) -> Callable[[Sequence[Condicion]], object]:
    def registrar(condiciones: Sequence[Condicion]) -> object:
        from cloudcr_backup.services import alertas

        return alertas.registrar_evento(condiciones, ajustes)

    return registrar


def _evaluar_alertas(ajustes: Ajustes) -> Callable[[int], object]:
    def evaluar(ejecucion_id: int) -> object:
        from cloudcr_backup.services import alertas

        return alertas.evaluar_tras_ejecucion(ejecucion_id, ajustes)

    return evaluar


def dependencias_reales(ajustes: Ajustes) -> Dependencias:
    rutas = ajustes.rutas
    rutas.asegurar()
    return Dependencias(
        repositorio=RepositorioOracle(ajustes),
        carpeta_ejecuciones=rutas.ejecuciones,
        carpeta_scripts=rutas.scripts,
        carpeta_buzon=rutas.buzon,
        validar=validar_estrategia,
        registrar_evento=_registrar_evento(ajustes),
        evaluar_alertas=_evaluar_alertas(ajustes),
    )


def _preparar(ajustes: Ajustes | None) -> Ajustes:
    from cloudcr_backup.services.cliente_oracle import preparar_cliente_oracle

    configuracion = ajustes or cargar_ajustes()
    preparar_cliente_oracle()
    return configuracion


def ejecutar(ejecucion_id: int, ajustes: Ajustes | None = None) -> ResultadoEjecucion:
    configuracion = _preparar(ajustes)
    return Pipeline(dependencias_reales(configuracion)).ejecutar(ejecucion_id)


def asegurar_apertura(ejecucion_id: int, ajustes: Ajustes | None = None) -> ResultadoApertura:
    configuracion = _preparar(ajustes)
    return Pipeline(dependencias_reales(configuracion)).asegurar_apertura(ejecucion_id)


def verificar_ejecucion(ejecucion_id: int, ajustes: Ajustes | None = None) -> ResultadoEjecucion:
    configuracion = _preparar(ajustes)
    return Pipeline(dependencias_reales(configuracion)).verificar(ejecucion_id)
