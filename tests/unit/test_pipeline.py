import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from cloudcr_backup.domain.alertas import Condicion
from cloudcr_backup.domain.ejecucion import Evidencia
from cloudcr_backup.domain.enums import (
    Compresion,
    EstadoEjecucion,
    EstadoPrueba,
    EstadoScript,
    LogMode,
    Severidad,
)
from cloudcr_backup.domain.errores import OperacionNoPermitida, RepositorioNoDisponible
from cloudcr_backup.domain.estrategia import Estrategia
from cloudcr_backup.domain.hallazgos import Hallazgo
from cloudcr_backup.domain.perfil_bd import PerfilBD
from cloudcr_backup.execution import buzon
from cloudcr_backup.execution.correlator import Consulta
from cloudcr_backup.execution.destino import BaseDestino, EstadoApertura
from cloudcr_backup.execution.pipeline import (
    ContextoEjecucion,
    Dependencias,
    EjecucionEnCurso,
    EntornoValidacion,
    EstadoCarpeta,
    Pipeline,
    bloqueo_bd,
    codigos_advertencia,
    ruta_script_aprobado,
    verificacion_automatica,
)
from cloudcr_backup.execution.runner import InvocacionRman, ResultadoRman
from cloudcr_backup.rman.aprobacion import calcular_hash
from cloudcr_backup.rman.constructor import SolicitudScript, construir
from cloudcr_backup.strategy.yaml_io import cargar_estrategia_yaml

RAIZ = Path(__file__).resolve().parents[2]
LOGS = RAIZ / "tests" / "fixtures" / "rman_logs"
PERFIL = RAIZ / "tests" / "fixtures" / "perfiles_bd" / "xe_noarchivelog.json"
PROGRAMADA = datetime(2026, 10, 4, 19, 0)
AHORA = datetime(2026, 10, 4, 19, 0, 5, tzinfo=UTC)
PIEZA = "C:\\BACKUPS\\XE\\XE_EST001_T1_20261004_01_1_1.BKP"
AUTOBACKUP = "C:\\BACKUPS\\XE\\C-3114375768-20261004-00"


def log_exitoso(tag: str) -> str:
    return (
        "connected to target database: XE (DBID=3114375768)\n"
        "RMAN> RUN {\n"
        f"piece handle={PIEZA} tag={tag} comment=NONE\n"
        f"piece handle={AUTOBACKUP} comment=NONE\n"
        "Recovery Manager complete.\n"
    )


def perfil(log_mode: LogMode) -> PerfilBD:
    return PerfilBD.model_validate_json(PERFIL.read_text(encoding="utf-8")).model_copy(update={"log_mode": log_mode})


def estrategia(codigo: str) -> Estrategia:
    return cargar_estrategia_yaml(RAIZ / "config" / "estrategias" / f"{codigo.lower()}.yaml").model_copy(
        update={"id": 5}
    )


def contexto(codigo: str = "EST001", log_mode: LogMode = LogMode.ARCHIVELOG, **cambios: Any) -> ContextoEjecucion:
    est = estrategia(codigo)
    tarea = est.tareas[0]
    contenido = construir(SolicitudScript(estrategia=est, tarea=tarea, log_mode=log_mode)).contenido
    base: dict[str, Any] = {
        "ejecucion_id": 41,
        "estado": EstadoEjecucion.PROGRAMADA,
        "programada_para": PROGRAMADA,
        "bd_id": 1,
        "bd_nombre": "XE",
        "oracle_home": "C:\\oracle",
        "estrategia": est,
        "tarea": tarea,
        "tarea_id": 3,
        "script_id": 9,
        "script_version": 2,
        "script_estado": EstadoScript.APROBADO,
        "script_contenido": contenido,
        "script_hash": calcular_hash(contenido),
        "acepto_caida": False,
        "log_mode_al_generar": log_mode,
        "parametros": {},
    }
    base.update(cambios)
    return ContextoEjecucion(**base)


class RepositorioFalso:
    def __init__(self, ctx: ContextoEjecucion, caido: bool = False) -> None:
        self.ctx = ctx
        self.caido = caido
        self.persistidas: list[Evidencia] = []
        self.en_curso: list[int] = []
        self.perfiles: list[PerfilBD] = []

    def cargar(self, ejecucion_id: int) -> ContextoEjecucion:
        return self.ctx

    def marcar_en_curso(self, ejecucion_id: int, agente: str) -> None:
        self.en_curso.append(ejecucion_id)

    def guardar_perfil(self, bd_id: int, perfil: PerfilBD) -> None:
        self.perfiles.append(perfil)

    def persistir(self, evidencia: Evidencia) -> None:
        if self.caido:
            raise RepositorioNoDisponible("BKPCAT está cerrada")
        self.persistidas.append(evidencia)


class Escenario:
    def __init__(
        self,
        tmp_path: Path,
        ctx: ContextoEjecucion,
        log_mode: LogMode = LogMode.ARCHIVELOG,
        log_respaldo: str | None = None,
        estado_job: str = "COMPLETED",
        estado_pieza: str = "A",
        abierta: bool = True,
        caido: bool = False,
        hallazgos: list[Hallazgo] | None = None,
    ) -> None:
        self.tmp_path = tmp_path
        self.repositorio = RepositorioFalso(ctx, caido)
        self.invocaciones: list[InvocacionRman] = []
        self.eventos: list[Condicion] = []
        self.evaluadas: list[int] = []
        self.log_respaldo = log_respaldo
        self.estado_job = estado_job
        self.estado_pieza = estado_pieza
        self.abierta = abierta
        self.log_mode = log_mode
        self.hallazgos = hallazgos or []
        self.tag: str | None = None

    def lanzar(self, invocacion: InvocacionRman) -> ResultadoRman:
        self.invocaciones.append(invocacion)
        nombre = invocacion.script.name
        if nombre.startswith("asegurar_apertura"):
            texto = "connected to target database: XE\nRecovery Manager complete.\n"
        elif nombre == "verificacion.rman":
            texto = "connected to target database: XE\ncrosschecked backup piece: found to be 'AVAILABLE'\n"
            texto += "Recovery Manager complete.\n"
        else:
            self.tag = invocacion.argumentos[0]
            texto = self.log_respaldo if self.log_respaldo is not None else log_exitoso(self.tag)
        modo = "a" if invocacion.agregar_al_log else "w"
        with invocacion.log.open(modo, encoding="utf-8") as archivo:
            archivo.write(texto)
        return ResultadoRman(codigo_salida=0, agotado=False, duracion_segundos=1.0)

    @contextmanager
    def catalogo(self, base: BaseDestino) -> Iterator[Consulta]:
        def consulta(sql: str, parametros: dict[str, Any]) -> list[tuple[Any, ...]]:
            if "v$rman_backup_job_details" in sql:
                return [(self.estado_job, 10, 5, None, None, "DB INCR")]
            if self.log_respaldo is not None:
                return []
            return [(PIEZA, 2048, parametros["tag"], self.estado_pieza, 7, None)]

        yield consulta

    def validar(self, est: Estrategia, perfil_bd: PerfilBD, entorno: EntornoValidacion) -> list[Hallazgo]:
        return self.hallazgos

    def dependencias(self) -> Dependencias:
        return Dependencias(
            repositorio=self.repositorio,
            carpeta_ejecuciones=self.tmp_path / "ejecuciones",
            carpeta_scripts=self.tmp_path / "scripts",
            carpeta_buzon=self.tmp_path / "buzon",
            perfil=lambda base: perfil(self.log_mode),
            lanzar=self.lanzar,
            catalogo=self.catalogo,
            comprobar_apertura=lambda base: EstadoApertura(self.abierta, "estado simulado"),
            medir_destino=lambda ruta: EstadoCarpeta(True, 10**12),
            medir_archivo=lambda ruta: 2048,
            validar=self.validar,
            registrar_evento=lambda condiciones: self.eventos.extend(condiciones),
            evaluar_alertas=self.evaluadas.append,
            ahora=lambda: AHORA,
            agente="host-prueba",
        )

    def ejecutar(self) -> Any:
        return Pipeline(self.dependencias()).ejecutar(41)


def test_ejecucion_exitosa_deja_evidencia_piezas_y_pruebas_ok(tmp_path: Path) -> None:
    escenario = Escenario(tmp_path, contexto())
    resultado = escenario.ejecutar()
    assert resultado.estado is EstadoEjecucion.EXITOSA
    assert resultado.estado_prueba is EstadoPrueba.OK
    assert escenario.repositorio.en_curso == [41]
    respaldo = escenario.invocaciones[0]
    assert respaldo.script.name == "EST001.XE.RMAN"
    assert respaldo.log.name == "EST001.XE.LOG"
    assert respaldo.argumentos == ("EST001_T1_2610041300", "CLOUDCR_41")
    assert respaldo.script.read_bytes() == escenario.repositorio.ctx.script_contenido.encode("ascii")
    assert [i.script.name for i in escenario.invocaciones] == ["EST001.XE.RMAN", "verificacion.rman"]
    evidencia = json.loads((tmp_path / "ejecuciones" / "41" / "evidencia.json").read_text(encoding="utf-8"))
    assert evidencia["estado"] == "EXITOSA"
    assert evidencia["estado_prueba"] == "OK"
    assert evidencia["tag"] == "EST001_T1_2610041300"
    assert {p["ruta"] for p in evidencia["piezas"]} == {PIEZA, AUTOBACKUP}
    assert evidencia["log_rman"].endswith("EST001.XE.LOG")
    assert [p["tipo"] for p in evidencia["pruebas"]] == ["EXISTENCIA", "CROSSCHECK", "VALIDATE"]
    ultima = escenario.repositorio.persistidas[-1]
    assert ultima.estado_prueba is EstadoPrueba.OK
    assert ultima.archivos_generados == 2
    assert escenario.evaluadas == [41]
    assert len(escenario.repositorio.perfiles) == 1
    aprobado = ruta_script_aprobado(tmp_path / "scripts", escenario.repositorio.ctx)
    assert aprobado.read_bytes() == escenario.repositorio.ctx.script_contenido.encode("ascii")


def test_vencimiento_de_piezas_sale_de_la_ventana_de_retencion(tmp_path: Path) -> None:
    ctx = contexto("EST004")
    escenario = Escenario(tmp_path, ctx)
    escenario.ejecutar()
    piezas = escenario.repositorio.persistidas[-1].piezas
    assert all(p.vence_en == AHORA + timedelta(days=30) for p in piezas)


def test_script_modificado_a_mano_bloquea_y_alerta_script_alterado(tmp_path: Path) -> None:
    ctx = contexto()
    aprobado = ruta_script_aprobado(tmp_path / "scripts", ctx)
    aprobado.parent.mkdir(parents=True)
    aprobado.write_bytes(ctx.script_contenido.replace("CUMULATIVE", "").encode("ascii"))
    escenario = Escenario(tmp_path, ctx)
    resultado = escenario.ejecutar()
    assert resultado.estado is EstadoEjecucion.BLOQUEADA
    assert resultado.estado_prueba is EstadoPrueba.NO_APLICA
    assert any("SCRIPT_ALTERADO" in m for m in resultado.motivos)
    assert escenario.invocaciones == []
    assert escenario.repositorio.en_curso == []
    assert [e.codigo_regla for e in escenario.eventos] == ["SCRIPT_ALTERADO"]
    assert escenario.eventos[0].ejecucion_id == 41
    assert escenario.repositorio.persistidas[-1].estado is EstadoEjecucion.BLOQUEADA


def test_log_real_de_noarchivelog_queda_fallida_sin_verificar(tmp_path: Path) -> None:
    log = (LOGS / "fallo_rman06817_noarchivelog.log").read_text(encoding="utf-8")
    escenario = Escenario(tmp_path, contexto(), log_respaldo=log, estado_job="FAILED")
    resultado = escenario.ejecutar()
    assert resultado.estado is EstadoEjecucion.FALLIDA
    assert resultado.estado_prueba is EstadoPrueba.NO_APLICA
    assert [i.script.name for i in escenario.invocaciones] == ["EST001.XE.RMAN"]
    registro = escenario.repositorio.persistidas[-1]
    assert registro.mensaje_rman is not None
    assert registro.mensaje_rman.startswith("RMAN-06817")
    assert "RMAN-03002" in "\n".join(registro.errores)


def test_consistente_sin_aceptar_caida_se_bloquea(tmp_path: Path) -> None:
    ctx = contexto("EST002", LogMode.NOARCHIVELOG)
    escenario = Escenario(tmp_path, ctx, log_mode=LogMode.NOARCHIVELOG)
    resultado = escenario.ejecutar()
    assert resultado.estado is EstadoEjecucion.BLOQUEADA
    assert any("CAIDA_NO_ACEPTADA" in m for m in resultado.motivos)


def test_consistente_siempre_asegura_la_apertura_y_alerta_si_no_reabre(tmp_path: Path) -> None:
    ctx = contexto("EST002", LogMode.NOARCHIVELOG, acepto_caida=True)
    escenario = Escenario(tmp_path, ctx, log_mode=LogMode.NOARCHIVELOG, abierta=False)
    resultado = escenario.ejecutar()
    nombres_scripts = [i.script.name for i in escenario.invocaciones]
    assert nombres_scripts[:4] == [
        "EST002.XE.RMAN",
        "asegurar_apertura_1.rman",
        "asegurar_apertura_2.rman",
        "asegurar_apertura_3.rman",
    ]
    assert resultado.estado is EstadoEjecucion.CON_ADVERTENCIAS
    assert [e.codigo_regla for e in escenario.eventos] == ["BASE_NO_REABIERTA"]
    assert escenario.repositorio.persistidas[-1].reapertura_correcta is False


def test_consistente_que_reabre_queda_exitoso(tmp_path: Path) -> None:
    ctx = contexto("EST002", LogMode.NOARCHIVELOG, acepto_caida=True)
    escenario = Escenario(tmp_path, ctx, log_mode=LogMode.NOARCHIVELOG)
    assert escenario.ejecutar().estado is EstadoEjecucion.EXITOSA
    assert escenario.eventos == []


def test_cambio_de_modo_de_archivado_bloquea(tmp_path: Path) -> None:
    escenario = Escenario(tmp_path, contexto(), log_mode=LogMode.NOARCHIVELOG)
    resultado = escenario.ejecutar()
    assert resultado.estado is EstadoEjecucion.BLOQUEADA
    assert any("MODO_ARCHIVADO_CAMBIO" in m for m in resultado.motivos)


def test_errores_de_validacion_de_la_propia_tarea_bloquean_y_los_de_otras_no(tmp_path: Path) -> None:
    propio = Hallazgo(codigo="ARCH_005", severidad=Severidad.ERROR, mensaje="EN_LINEA en NOARCHIVELOG", sujeto="T1")
    ajeno = Hallazgo(codigo="ARCH_004", severidad=Severidad.ERROR, mensaje="otra tarea", sujeto="T3")
    bloqueada = Escenario(tmp_path / "a", contexto(), hallazgos=[propio]).ejecutar()
    assert bloqueada.estado is EstadoEjecucion.BLOQUEADA
    assert Escenario(tmp_path / "b", contexto("EST004"), hallazgos=[ajeno]).ejecutar().estado is EstadoEjecucion.EXITOSA


def test_pieza_expirada_en_la_verificacion_deja_pruebas_fallidas(tmp_path: Path) -> None:
    escenario = Escenario(tmp_path, contexto(), estado_pieza="X")
    resultado = escenario.ejecutar()
    assert resultado.estado_prueba is EstadoPrueba.FALLIDA


def test_verificacion_desactivada_deja_pruebas_pendientes(tmp_path: Path) -> None:
    escenario = Escenario(tmp_path, contexto(parametros={"verificacion.automatica": "false"}))
    resultado = escenario.ejecutar()
    assert resultado.estado_prueba is EstadoPrueba.PENDIENTE
    assert len(escenario.invocaciones) == 1


def test_si_el_repositorio_cae_la_evidencia_va_al_buzon(tmp_path: Path) -> None:
    escenario = Escenario(tmp_path, contexto(), caido=True)
    resultado = escenario.ejecutar()
    assert resultado.en_buzon
    pendientes = buzon.pendientes(tmp_path / "buzon")
    assert len(pendientes) == 1
    assert json.loads(pendientes[0].read_text(encoding="utf-8"))["estado_prueba"] == "OK"
    assert (tmp_path / "ejecuciones" / "41" / "evidencia.json").exists()


def test_solo_se_ejecuta_una_ejecucion_programada(tmp_path: Path) -> None:
    escenario = Escenario(tmp_path, contexto(estado=EstadoEjecucion.EXITOSA))
    with pytest.raises(OperacionNoPermitida):
        escenario.ejecutar()


def test_un_solo_rman_a_la_vez_por_base(tmp_path: Path) -> None:
    with bloqueo_bd(tmp_path, "XE", 3600), pytest.raises(EjecucionEnCurso), bloqueo_bd(tmp_path, "XE", 3600):
        pass
    assert not list(tmp_path.glob(".rman_*"))


def test_bloqueo_vencido_se_reemplaza(tmp_path: Path) -> None:
    (tmp_path / ".rman_XE.lock").write_text("123", encoding="ascii")
    with bloqueo_bd(tmp_path, "XE", 0):
        pass
    assert not (tmp_path / ".rman_XE.lock").exists()


def test_parametros_del_pipeline() -> None:
    assert codigos_advertencia({"rman.codigos_advertencia": '["RMAN-1"]'}) == frozenset({"RMAN-1"})
    assert "RMAN-08137" in codigos_advertencia({"rman.codigos_advertencia": "no json"})
    assert not verificacion_automatica({"verificacion.automatica": "False"})
    assert verificacion_automatica({})


def test_compresion_se_respeta_en_el_script_copiado(tmp_path: Path) -> None:
    est = estrategia("EST001")
    opciones = est.tareas[0].como.opciones.model_copy(update={"compresion": Compresion.BASIC})
    tarea = est.tareas[0].model_copy(update={"como": est.tareas[0].como.model_copy(update={"opciones": opciones})})
    contenido = construir(SolicitudScript(estrategia=est, tarea=tarea, log_mode=LogMode.ARCHIVELOG)).contenido
    ctx = contexto(tarea=tarea, script_contenido=contenido, script_hash=calcular_hash(contenido))
    escenario = Escenario(tmp_path, ctx)
    escenario.ejecutar()
    assert b"AS COMPRESSED BACKUPSET" in escenario.invocaciones[0].script.read_bytes()


def test_error_interno_cierra_la_ejecucion_como_fallida_y_reabre_la_base(tmp_path: Path) -> None:
    ctx = contexto("EST002", LogMode.NOARCHIVELOG, acepto_caida=True)
    escenario = Escenario(tmp_path, ctx, log_mode=LogMode.NOARCHIVELOG)
    original = escenario.lanzar

    def lanzar(invocacion: InvocacionRman) -> ResultadoRman:
        if invocacion.script.name == "EST002.XE.RMAN":
            raise RuntimeError("disco lleno")
        return original(invocacion)

    escenario.lanzar = lanzar  # type: ignore[method-assign]
    resultado = escenario.ejecutar()
    assert resultado.estado is EstadoEjecucion.FALLIDA
    assert "disco lleno" in resultado.motivos[0]
    assert escenario.repositorio.persistidas[-1].estado is EstadoEjecucion.FALLIDA
    assert any(i.script.name.startswith("asegurar_apertura") for i in escenario.invocaciones)
