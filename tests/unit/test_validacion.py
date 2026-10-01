from datetime import datetime, time

import pytest

from cloudcr_backup.domain.enums import (
    Compresion,
    ContenidoTablespace,
    DiaSemana,
    EstadoEstrategia,
    LogMode,
    ModoRespaldo,
    Prioridad,
    Severidad,
    TipoFrecuencia,
    TipoObjeto,
    TipoRespaldo,
)
from cloudcr_backup.domain.estrategia import (
    Como,
    Destino,
    Estrategia,
    ObjetoAlcance,
    OpcionesRespaldo,
    Programacion,
    Retencion,
    Tarea,
    Ventana,
)
from cloudcr_backup.domain.hallazgos import Hallazgo
from cloudcr_backup.domain.perfil_bd import (
    ArchivoParametros,
    ContenedorInfo,
    ControlfileInfo,
    DatafileInfo,
    PerfilBD,
    TablespaceInfo,
)
from cloudcr_backup.validation import motor, reglas  # noqa: F401  importar reglas registra las 11 reglas
from cloudcr_backup.validation.contexto import ContextoValidacion


def _perfil(log_mode: LogMode) -> PerfilBD:
    return PerfilBD(
        nombre="XE",
        nombre_instancia="XE",
        dbid=1,
        host="localhost",
        version="21.3.0.0.0",
        edicion="Express Edition",
        es_cdb=True,
        log_mode=log_mode,
        open_mode="READ WRITE",
        estado_instancia="OPEN",
        oracle_home=None,
        diagnostic_dest=None,
        capturado_en=datetime.now(),
        contenedores=[],
        tablespaces=[],
        datafiles=[],
        tempfiles=[],
        controlfiles=[],
        redo_grupos=[],
        archivos_parametros=[],
        destinos_archivado=[],
        destino_archivado_configurado=False,
        area_recuperacion=None,
        archivelogs_sin_respaldo=0,
    )


def _estrategia(modo: ModoRespaldo, incluir_archivelog: bool = False) -> Estrategia:
    alcance = [ObjetoAlcance(tipo=TipoObjeto.TABLESPACE, identificador="XEPDB1:VENTAS", prioridad=Prioridad.ALTA)]
    if incluir_archivelog:
        alcance.append(ObjetoAlcance(tipo=TipoObjeto.ARCHIVELOG, identificador="", prioridad=Prioridad.ALTA))
    return Estrategia(
        bd_id=1,
        codigo="EST001",
        nombre="Demo",
        prioridad=Prioridad.ALTA,
        creada_por="luis",
        alcance=alcance,
        tareas=[
            Tarea(
                codigo="T1",
                como=Como(tipo_respaldo=TipoRespaldo.COMPLETO, modo_respaldo=modo),
                programacion=Programacion(tipo_frecuencia=TipoFrecuencia.DIARIA, horas=[time(13, 0)]),
                destino=Destino(ruta=r"C:\backups\XE"),
            )
        ],
    )


def test_una_regla_duplicada_no_se_puede_registrar(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(motor, "_reglas", {})

    @motor.regla("X_001")
    def primera(contexto: ContextoValidacion) -> list[Hallazgo]:
        return []

    with pytest.raises(ValueError, match="ya está registrada"):

        @motor.regla("X_001")
        def segunda(contexto: ContextoValidacion) -> list[Hallazgo]:
            return []


def test_validar_ordena_los_hallazgos_por_severidad(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(motor, "_reglas", {})

    @motor.regla("X_INFO")
    def informativa(contexto: ContextoValidacion) -> list[Hallazgo]:
        return [Hallazgo(codigo="X_INFO", severidad=Severidad.INFORMATIVA, mensaje="info", sujeto="x")]

    @motor.regla("X_ERROR")
    def con_error(contexto: ContextoValidacion) -> list[Hallazgo]:
        return [Hallazgo(codigo="X_ERROR", severidad=Severidad.ERROR, mensaje="error", sujeto="x")]

    contexto = ContextoValidacion(estrategia=_estrategia(ModoRespaldo.AUTO), perfil=_perfil(LogMode.ARCHIVELOG))
    hallazgos = motor.validar(contexto)
    assert [h.codigo for h in hallazgos] == ["X_ERROR", "X_INFO"]
    assert motor.hay_bloqueantes(hallazgos)


def test_sin_hallazgos_de_error_no_hay_bloqueo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(motor, "_reglas", {})

    @motor.regla("X_ADVERTENCIA")
    def advertencia(contexto: ContextoValidacion) -> list[Hallazgo]:
        return [Hallazgo(codigo="X_ADVERTENCIA", severidad=Severidad.ADVERTENCIA, mensaje="aviso", sujeto="x")]

    contexto = ContextoValidacion(estrategia=_estrategia(ModoRespaldo.AUTO), perfil=_perfil(LogMode.ARCHIVELOG))
    assert not motor.hay_bloqueantes(motor.validar(contexto))


def test_arch_001_se_dispara_en_noarchivelog() -> None:
    contexto = ContextoValidacion(
        estrategia=_estrategia(ModoRespaldo.CONSISTENTE), perfil=_perfil(LogMode.NOARCHIVELOG)
    )
    codigos = [h.codigo for h in motor.validar(contexto)]
    assert "ARCH_001" in codigos


def test_arch_001_no_se_dispara_en_archivelog() -> None:
    contexto = ContextoValidacion(estrategia=_estrategia(ModoRespaldo.EN_LINEA), perfil=_perfil(LogMode.ARCHIVELOG))
    codigos = [h.codigo for h in motor.validar(contexto)]
    assert "ARCH_001" not in codigos


def test_arch_002_recomienda_archivar_los_redo_logs_si_faltan() -> None:
    contexto = ContextoValidacion(
        estrategia=_estrategia(ModoRespaldo.EN_LINEA, incluir_archivelog=False), perfil=_perfil(LogMode.ARCHIVELOG)
    )
    codigos = [h.codigo for h in motor.validar(contexto)]
    assert "ARCH_002" in codigos


def test_arch_002_no_se_dispara_si_ya_incluye_archivelogs() -> None:
    contexto = ContextoValidacion(
        estrategia=_estrategia(ModoRespaldo.EN_LINEA, incluir_archivelog=True), perfil=_perfil(LogMode.ARCHIVELOG)
    )
    codigos = [h.codigo for h in motor.validar(contexto)]
    assert "ARCH_002" not in codigos


def test_arch_005_bloquea_un_respaldo_en_linea_sin_archivelog() -> None:
    contexto = ContextoValidacion(estrategia=_estrategia(ModoRespaldo.EN_LINEA), perfil=_perfil(LogMode.NOARCHIVELOG))
    hallazgos = motor.validar(contexto)
    assert any(h.codigo == "ARCH_005" and h.severidad is Severidad.ERROR for h in hallazgos)
    assert motor.hay_bloqueantes(hallazgos)


def test_arch_005_no_se_dispara_en_modo_consistente_sobre_noarchivelog() -> None:
    contexto = ContextoValidacion(
        estrategia=_estrategia(ModoRespaldo.CONSISTENTE), perfil=_perfil(LogMode.NOARCHIVELOG)
    )
    hallazgos = motor.validar(contexto)
    assert not any(h.codigo == "ARCH_005" for h in hallazgos)


def test_arch_005_resuelve_el_modo_auto_segun_el_log_mode_actual() -> None:
    contexto = ContextoValidacion(estrategia=_estrategia(ModoRespaldo.AUTO), perfil=_perfil(LogMode.NOARCHIVELOG))
    hallazgos = motor.validar(contexto)
    assert not any(h.codigo == "ARCH_005" for h in hallazgos)


def _estrategia_con_alcance(alcance: list[ObjetoAlcance], prioridad: Prioridad = Prioridad.ALTA) -> Estrategia:
    return Estrategia(
        bd_id=1,
        codigo="EST001",
        nombre="Demo",
        prioridad=prioridad,
        creada_por="luis",
        alcance=alcance,
        tareas=[
            Tarea(
                codigo="T1",
                como=Como(tipo_respaldo=TipoRespaldo.COMPLETO, modo_respaldo=ModoRespaldo.AUTO),
                programacion=Programacion(tipo_frecuencia=TipoFrecuencia.DIARIA, horas=[time(13, 0)]),
                destino=Destino(ruta=r"C:\backups\XE"),
            )
        ],
    )


def _perfil_estructura(
    *,
    log_mode: LogMode = LogMode.ARCHIVELOG,
    contenedores: list[ContenedorInfo] | None = None,
    tablespaces: list[TablespaceInfo] | None = None,
    controlfiles: list[ControlfileInfo] | None = None,
    archivos_parametros: list[ArchivoParametros] | None = None,
) -> PerfilBD:
    return _perfil(log_mode).model_copy(
        update={
            "contenedores": contenedores or [],
            "tablespaces": tablespaces or [],
            "controlfiles": controlfiles or [],
            "archivos_parametros": archivos_parametros or [],
        }
    )


def _tablespace(
    nombre: str, contenido: ContenidoTablespace = ContenidoTablespace.PERMANENTE, estado: str | None = "ONLINE"
) -> TablespaceInfo:
    return TablespaceInfo(con_id=3, nombre=nombre, contenido=contenido, estado=estado, bigfile=False)


def test_gen_001_detecta_codigo_duplicado() -> None:
    contexto = ContextoValidacion(
        estrategia=_estrategia(ModoRespaldo.AUTO),
        perfil=_perfil(LogMode.ARCHIVELOG),
        codigos_estrategia_existentes=["EST001"],
    )
    assert "GEN_001" in [h.codigo for h in motor.validar(contexto)]


def test_gen_001_no_se_dispara_con_un_codigo_nuevo() -> None:
    contexto = ContextoValidacion(
        estrategia=_estrategia(ModoRespaldo.AUTO),
        perfil=_perfil(LogMode.ARCHIVELOG),
        codigos_estrategia_existentes=["EST999"],
    )
    assert "GEN_001" not in [h.codigo for h in motor.validar(contexto)]


def test_gen_002_detecta_estrategia_sin_tareas() -> None:
    estrategia = _estrategia_con_alcance(
        [ObjetoAlcance(tipo=TipoObjeto.BASE_DATOS, identificador="", prioridad=Prioridad.ALTA)]
    ).model_copy(update={"tareas": []})
    contexto = ContextoValidacion(estrategia=estrategia, perfil=_perfil(LogMode.ARCHIVELOG))
    assert "GEN_002" in [h.codigo for h in motor.validar(contexto)]


def test_gen_002_no_se_dispara_con_al_menos_una_tarea() -> None:
    contexto = ContextoValidacion(estrategia=_estrategia(ModoRespaldo.AUTO), perfil=_perfil(LogMode.ARCHIVELOG))
    assert "GEN_002" not in [h.codigo for h in motor.validar(contexto)]


def test_alc_001_detecta_alcance_vacio() -> None:
    estrategia = _estrategia_con_alcance([])
    contexto = ContextoValidacion(estrategia=estrategia, perfil=_perfil(LogMode.ARCHIVELOG))
    assert "ALC_001" in [h.codigo for h in motor.validar(contexto)]


def test_alc_001_no_se_dispara_con_alcance_definido() -> None:
    contexto = ContextoValidacion(estrategia=_estrategia(ModoRespaldo.AUTO), perfil=_perfil(LogMode.ARCHIVELOG))
    assert "ALC_001" not in [h.codigo for h in motor.validar(contexto)]


def test_alc_002_detecta_un_objeto_que_ya_no_existe() -> None:
    estrategia = _estrategia_con_alcance(
        [ObjetoAlcance(tipo=TipoObjeto.TABLESPACE, identificador="XEPDB1:VENTAS", prioridad=Prioridad.ALTA)]
    )
    perfil = _perfil_estructura(
        contenedores=[ContenedorInfo(con_id=3, nombre="XEPDB1", open_mode="READ WRITE")],
        tablespaces=[
            _tablespace("OTRA")
        ],
    )
    contexto = ContextoValidacion(estrategia=estrategia, perfil=perfil)
    assert "ALC_002" in [h.codigo for h in motor.validar(contexto)]


def test_alc_002_no_se_dispara_si_el_objeto_existe() -> None:
    estrategia = _estrategia_con_alcance(
        [ObjetoAlcance(tipo=TipoObjeto.TABLESPACE, identificador="XEPDB1:VENTAS", prioridad=Prioridad.ALTA)]
    )
    perfil = _perfil_estructura(
        contenedores=[ContenedorInfo(con_id=3, nombre="XEPDB1", open_mode="READ WRITE")],
        tablespaces=[
            _tablespace("VENTAS")
        ],
    )
    contexto = ContextoValidacion(estrategia=estrategia, perfil=perfil)
    assert "ALC_002" not in [h.codigo for h in motor.validar(contexto)]


def test_alc_003_detecta_tablespace_temporal_en_el_alcance() -> None:
    estrategia = _estrategia_con_alcance(
        [ObjetoAlcance(tipo=TipoObjeto.TABLESPACE, identificador="XEPDB1:TEMP", prioridad=Prioridad.BAJA)]
    )
    perfil = _perfil_estructura(
        contenedores=[ContenedorInfo(con_id=3, nombre="XEPDB1", open_mode="READ WRITE")],
        tablespaces=[
            _tablespace("TEMP", ContenidoTablespace.TEMPORAL, None)
        ],
    )
    contexto = ContextoValidacion(estrategia=estrategia, perfil=perfil)
    assert "ALC_003" in [h.codigo for h in motor.validar(contexto)]


def test_alc_004_detecta_alcance_parcial_sin_controlfile_ni_spfile() -> None:
    estrategia = _estrategia_con_alcance(
        [ObjetoAlcance(tipo=TipoObjeto.TABLESPACE, identificador="XEPDB1:VENTAS", prioridad=Prioridad.ALTA)]
    )
    perfil = _perfil_estructura(
        contenedores=[ContenedorInfo(con_id=3, nombre="XEPDB1", open_mode="READ WRITE")],
        tablespaces=[
            _tablespace("VENTAS")
        ],
    )
    contexto = ContextoValidacion(estrategia=estrategia, perfil=perfil)
    assert "ALC_004" in [h.codigo for h in motor.validar(contexto)]


def test_alc_004_no_se_dispara_si_incluye_controlfile() -> None:
    estrategia = _estrategia_con_alcance(
        [
            ObjetoAlcance(tipo=TipoObjeto.TABLESPACE, identificador="XEPDB1:VENTAS", prioridad=Prioridad.ALTA),
            ObjetoAlcance(tipo=TipoObjeto.CONTROLFILE, identificador="", prioridad=Prioridad.ALTA),
        ]
    )
    perfil = _perfil_estructura(
        contenedores=[ContenedorInfo(con_id=3, nombre="XEPDB1", open_mode="READ WRITE")],
        tablespaces=[
            _tablespace("VENTAS")
        ],
        controlfiles=[ControlfileInfo(ruta=r"C:\oradata\XE\CONTROL01.CTL", bytes=100, estado="OK")],
    )
    contexto = ContextoValidacion(estrategia=estrategia, perfil=perfil)
    assert "ALC_004" not in [h.codigo for h in motor.validar(contexto)]


def test_alc_005_detecta_alcance_parcial_sin_system_ni_undo() -> None:
    estrategia = _estrategia_con_alcance(
        [ObjetoAlcance(tipo=TipoObjeto.TABLESPACE, identificador="XEPDB1:VENTAS", prioridad=Prioridad.ALTA)]
    )
    perfil = _perfil_estructura(
        contenedores=[ContenedorInfo(con_id=3, nombre="XEPDB1", open_mode="READ WRITE")],
        tablespaces=[
            _tablespace("VENTAS")
        ],
    )
    contexto = ContextoValidacion(estrategia=estrategia, perfil=perfil)
    assert "ALC_005" in [h.codigo for h in motor.validar(contexto)]


def test_alc_005_no_se_dispara_si_incluye_undo() -> None:
    estrategia = _estrategia_con_alcance(
        [
            ObjetoAlcance(tipo=TipoObjeto.TABLESPACE, identificador="XEPDB1:VENTAS", prioridad=Prioridad.ALTA),
            ObjetoAlcance(tipo=TipoObjeto.TABLESPACE, identificador="XEPDB1:UNDOTBS1", prioridad=Prioridad.ALTA),
        ]
    )
    perfil = _perfil_estructura(
        contenedores=[ContenedorInfo(con_id=3, nombre="XEPDB1", open_mode="READ WRITE")],
        tablespaces=[
            _tablespace("VENTAS"),
            _tablespace("UNDOTBS1", ContenidoTablespace.UNDO),
        ],
    )
    contexto = ContextoValidacion(estrategia=estrategia, perfil=perfil)
    assert "ALC_005" not in [h.codigo for h in motor.validar(contexto)]


def test_alc_006_avisa_que_la_estrategia_protege_una_pdb() -> None:
    contexto = ContextoValidacion(estrategia=_estrategia(ModoRespaldo.AUTO), perfil=_perfil(LogMode.ARCHIVELOG))
    assert "ALC_006" in [h.codigo for h in motor.validar(contexto)]


def test_alc_007_detecta_objeto_alta_en_estrategia_baja() -> None:
    estrategia = _estrategia_con_alcance(
        [ObjetoAlcance(tipo=TipoObjeto.TABLESPACE, identificador="XEPDB1:VENTAS", prioridad=Prioridad.ALTA)],
        prioridad=Prioridad.BAJA,
    )
    contexto = ContextoValidacion(estrategia=estrategia, perfil=_perfil(LogMode.ARCHIVELOG))
    assert "ALC_007" in [h.codigo for h in motor.validar(contexto)]


def test_alc_007_no_se_dispara_si_las_prioridades_son_consistentes() -> None:
    estrategia = _estrategia_con_alcance(
        [ObjetoAlcance(tipo=TipoObjeto.TABLESPACE, identificador="XEPDB1:VENTAS", prioridad=Prioridad.BAJA)],
        prioridad=Prioridad.BAJA,
    )
    contexto = ContextoValidacion(estrategia=estrategia, perfil=_perfil(LogMode.ARCHIVELOG))
    assert "ALC_007" not in [h.codigo for h in motor.validar(contexto)]


def test_alc_008_detecta_tablespace_de_solo_lectura() -> None:
    estrategia = _estrategia_con_alcance(
        [ObjetoAlcance(tipo=TipoObjeto.TABLESPACE, identificador="XEPDB1:HISTORICO", prioridad=Prioridad.BAJA)]
    )
    perfil = _perfil_estructura(
        contenedores=[ContenedorInfo(con_id=3, nombre="XEPDB1", open_mode="READ WRITE")],
        tablespaces=[_tablespace("HISTORICO", estado="READ ONLY")],
    )
    contexto = ContextoValidacion(estrategia=estrategia, perfil=perfil)
    assert "ALC_008" in [h.codigo for h in motor.validar(contexto)]


def _estrategia_con_retencion(retencion: Retencion, tareas: list[Tarea] | None = None) -> Estrategia:
    return Estrategia(
        bd_id=1,
        codigo="EST001",
        nombre="Demo",
        prioridad=Prioridad.ALTA,
        creada_por="luis",
        alcance=[ObjetoAlcance(tipo=TipoObjeto.BASE_DATOS, identificador="", prioridad=Prioridad.ALTA)],
        tareas=tareas
        if tareas is not None
        else [
            Tarea(
                codigo="T1",
                como=Como(tipo_respaldo=TipoRespaldo.INCREMENTAL_N0, modo_respaldo=ModoRespaldo.AUTO),
                programacion=Programacion(tipo_frecuencia=TipoFrecuencia.SEMANAL, horas=[time(2, 0)]),
                destino=Destino(ruta=r"C:\backups\XE"),
            )
        ],
        retencion=retencion,
    )


def test_ret_001_detecta_estrategia_sin_politica_de_retencion() -> None:
    estrategia = _estrategia_con_retencion(Retencion())
    contexto = ContextoValidacion(estrategia=estrategia, perfil=_perfil(LogMode.ARCHIVELOG))
    assert "RET_001" in [h.codigo for h in motor.validar(contexto)]


def test_ret_001_no_se_dispara_con_ventana_definida() -> None:
    estrategia = _estrategia_con_retencion(Retencion(ventana_dias=30))
    contexto = ContextoValidacion(estrategia=estrategia, perfil=_perfil(LogMode.ARCHIVELOG))
    assert "RET_001" not in [h.codigo for h in motor.validar(contexto)]


def test_ret_002_detecta_ventana_y_redundancia_a_la_vez() -> None:
    estrategia = _estrategia_con_retencion(Retencion(ventana_dias=30, redundancia=2))
    contexto = ContextoValidacion(estrategia=estrategia, perfil=_perfil(LogMode.ARCHIVELOG))
    hallazgos = motor.validar(contexto)
    assert any(h.codigo == "RET_002" and h.severidad is Severidad.ERROR for h in hallazgos)
    assert motor.hay_bloqueantes(hallazgos)


def test_ret_002_no_se_dispara_con_un_solo_criterio() -> None:
    estrategia = _estrategia_con_retencion(Retencion(redundancia=2))
    contexto = ContextoValidacion(estrategia=estrategia, perfil=_perfil(LogMode.ARCHIVELOG))
    assert "RET_002" not in [h.codigo for h in motor.validar(contexto)]


def test_ret_003_detecta_ventana_menor_que_el_intervalo_n0() -> None:
    estrategia = _estrategia_con_retencion(Retencion(ventana_dias=3))
    contexto = ContextoValidacion(estrategia=estrategia, perfil=_perfil(LogMode.ARCHIVELOG))
    assert "RET_003" in [h.codigo for h in motor.validar(contexto)]


def test_ret_003_no_se_dispara_si_la_ventana_alcanza() -> None:
    estrategia = _estrategia_con_retencion(Retencion(ventana_dias=30))
    contexto = ContextoValidacion(estrategia=estrategia, perfil=_perfil(LogMode.ARCHIVELOG))
    assert "RET_003" not in [h.codigo for h in motor.validar(contexto)]


def test_ret_003_no_se_dispara_si_la_tarea_no_es_de_nivel_0() -> None:
    tarea = Tarea(
        codigo="T1",
        como=Como(tipo_respaldo=TipoRespaldo.INCREMENTAL_N1_DIFERENCIAL, modo_respaldo=ModoRespaldo.AUTO),
        programacion=Programacion(tipo_frecuencia=TipoFrecuencia.SEMANAL, horas=[time(2, 0)]),
        destino=Destino(ruta=r"C:\backups\XE"),
    )
    estrategia = _estrategia_con_retencion(Retencion(ventana_dias=3), tareas=[tarea])
    contexto = ContextoValidacion(estrategia=estrategia, perfil=_perfil(LogMode.ARCHIVELOG))
    assert "RET_003" not in [h.codigo for h in motor.validar(contexto)]


def test_ret_004_detecta_purga_automatica_activa() -> None:
    estrategia = _estrategia_con_retencion(Retencion(ventana_dias=30, purga_automatica=True))
    contexto = ContextoValidacion(estrategia=estrategia, perfil=_perfil(LogMode.ARCHIVELOG))
    assert "RET_004" in [h.codigo for h in motor.validar(contexto)]


def test_ret_004_no_se_dispara_por_defecto() -> None:
    estrategia = _estrategia_con_retencion(Retencion(ventana_dias=30))
    contexto = ContextoValidacion(estrategia=estrategia, perfil=_perfil(LogMode.ARCHIVELOG))
    assert "RET_004" not in [h.codigo for h in motor.validar(contexto)]


def _estrategia_con_tareas(
    tareas: list[Tarea], estado: EstadoEstrategia = EstadoEstrategia.ACTIVA, prioridad: Prioridad = Prioridad.ALTA
) -> Estrategia:
    return Estrategia(
        bd_id=1,
        codigo="EST001",
        nombre="Demo",
        prioridad=prioridad,
        estado=estado,
        creada_por="luis",
        alcance=[ObjetoAlcance(tipo=TipoObjeto.BASE_DATOS, identificador="", prioridad=prioridad)],
        tareas=tareas,
    )


def test_prg_001_detecta_tarea_activa_sin_programacion() -> None:
    tarea = Tarea(
        codigo="T1",
        como=Como(tipo_respaldo=TipoRespaldo.COMPLETO, modo_respaldo=ModoRespaldo.AUTO),
        programacion=Programacion(tipo_frecuencia=TipoFrecuencia.DIARIA),
        destino=Destino(ruta=r"C:\backups\XE"),
    )
    estrategia = _estrategia_con_tareas([tarea], estado=EstadoEstrategia.ACTIVA)
    contexto = ContextoValidacion(estrategia=estrategia, perfil=_perfil(LogMode.ARCHIVELOG))
    assert "PRG_001" in [h.codigo for h in motor.validar(contexto)]


def test_prg_001_no_se_dispara_si_la_estrategia_esta_inactiva() -> None:
    tarea = Tarea(
        codigo="T1",
        como=Como(tipo_respaldo=TipoRespaldo.COMPLETO, modo_respaldo=ModoRespaldo.AUTO),
        programacion=Programacion(tipo_frecuencia=TipoFrecuencia.DIARIA),
        destino=Destino(ruta=r"C:\backups\XE"),
    )
    estrategia = _estrategia_con_tareas([tarea], estado=EstadoEstrategia.INACTIVA)
    contexto = ContextoValidacion(estrategia=estrategia, perfil=_perfil(LogMode.ARCHIVELOG))
    assert "PRG_001" not in [h.codigo for h in motor.validar(contexto)]


def test_prg_001_no_se_dispara_con_programacion_completa_en_estrategia_activa() -> None:
    tarea = Tarea(
        codigo="T1",
        como=Como(tipo_respaldo=TipoRespaldo.COMPLETO, modo_respaldo=ModoRespaldo.AUTO),
        programacion=Programacion(tipo_frecuencia=TipoFrecuencia.DIARIA, horas=[time(13, 0)]),
        destino=Destino(ruta=r"C:\backups\XE"),
    )
    estrategia = _estrategia_con_tareas([tarea], estado=EstadoEstrategia.ACTIVA)
    contexto = ContextoValidacion(estrategia=estrategia, perfil=_perfil(LogMode.ARCHIVELOG))
    assert "PRG_001" not in [h.codigo for h in motor.validar(contexto)]


def test_prg_002_detecta_frecuencia_semanal_sin_dias() -> None:
    tarea = Tarea(
        codigo="T1",
        como=Como(tipo_respaldo=TipoRespaldo.COMPLETO, modo_respaldo=ModoRespaldo.AUTO),
        programacion=Programacion(tipo_frecuencia=TipoFrecuencia.SEMANAL, horas=[time(2, 0)]),
        destino=Destino(ruta=r"C:\backups\XE"),
    )
    estrategia = _estrategia_con_tareas([tarea])
    contexto = ContextoValidacion(estrategia=estrategia, perfil=_perfil(LogMode.ARCHIVELOG))
    assert "PRG_002" in [h.codigo for h in motor.validar(contexto)]


def test_prg_002_detecta_intervalo_sin_minutos() -> None:
    tarea = Tarea(
        codigo="T1",
        como=Como(tipo_respaldo=TipoRespaldo.COMPLETO, modo_respaldo=ModoRespaldo.AUTO),
        programacion=Programacion(tipo_frecuencia=TipoFrecuencia.INTERVALO),
        destino=Destino(ruta=r"C:\backups\XE"),
    )
    estrategia = _estrategia_con_tareas([tarea])
    contexto = ContextoValidacion(estrategia=estrategia, perfil=_perfil(LogMode.ARCHIVELOG))
    assert "PRG_002" in [h.codigo for h in motor.validar(contexto)]


def test_prg_002_no_se_dispara_con_programacion_completa() -> None:
    contexto = ContextoValidacion(estrategia=_estrategia(ModoRespaldo.AUTO), perfil=_perfil(LogMode.ARCHIVELOG))
    assert "PRG_002" not in [h.codigo for h in motor.validar(contexto)]


def test_prg_003_detecta_hora_fuera_de_la_ventana() -> None:
    tarea = Tarea(
        codigo="T1",
        como=Como(tipo_respaldo=TipoRespaldo.COMPLETO, modo_respaldo=ModoRespaldo.AUTO),
        programacion=Programacion(
            tipo_frecuencia=TipoFrecuencia.DIARIA,
            horas=[time(23, 0)],
            ventana=Ventana(inicio=time(12, 30), fin=time(22, 0)),
        ),
        destino=Destino(ruta=r"C:\backups\XE"),
    )
    estrategia = _estrategia_con_tareas([tarea])
    contexto = ContextoValidacion(estrategia=estrategia, perfil=_perfil(LogMode.ARCHIVELOG))
    assert "PRG_003" in [h.codigo for h in motor.validar(contexto)]


def test_prg_003_no_se_dispara_con_horas_dentro_de_la_ventana() -> None:
    tarea = Tarea(
        codigo="T1",
        como=Como(tipo_respaldo=TipoRespaldo.COMPLETO, modo_respaldo=ModoRespaldo.AUTO),
        programacion=Programacion(
            tipo_frecuencia=TipoFrecuencia.DIARIA,
            horas=[time(13, 0)],
            ventana=Ventana(inicio=time(12, 30), fin=time(22, 0)),
        ),
        destino=Destino(ruta=r"C:\backups\XE"),
    )
    estrategia = _estrategia_con_tareas([tarea])
    contexto = ContextoValidacion(estrategia=estrategia, perfil=_perfil(LogMode.ARCHIVELOG))
    assert "PRG_003" not in [h.codigo for h in motor.validar(contexto)]


def test_prg_005_detecta_frecuencia_insuficiente_para_prioridad_alta() -> None:
    tarea = Tarea(
        codigo="T1",
        como=Como(tipo_respaldo=TipoRespaldo.INCREMENTAL_N0, modo_respaldo=ModoRespaldo.AUTO),
        programacion=Programacion(tipo_frecuencia=TipoFrecuencia.SEMANAL, horas=[time(2, 0)]),
        destino=Destino(ruta=r"C:\backups\XE"),
    )
    estrategia = _estrategia_con_tareas([tarea], prioridad=Prioridad.ALTA)
    contexto = ContextoValidacion(estrategia=estrategia, perfil=_perfil(LogMode.ARCHIVELOG))
    assert "PRG_005" in [h.codigo for h in motor.validar(contexto)]


def test_prg_005_no_se_dispara_si_la_frecuencia_alcanza() -> None:
    contexto = ContextoValidacion(estrategia=_estrategia(ModoRespaldo.AUTO), perfil=_perfil(LogMode.ARCHIVELOG))
    assert "PRG_005" not in [h.codigo for h in motor.validar(contexto)]


def test_prg_005_cuenta_los_dias_semana_al_calcular_el_intervalo_semanal() -> None:
    tarea = Tarea(
        codigo="T1",
        como=Como(tipo_respaldo=TipoRespaldo.INCREMENTAL_N1_DIFERENCIAL, modo_respaldo=ModoRespaldo.AUTO),
        programacion=Programacion(
            tipo_frecuencia=TipoFrecuencia.SEMANAL,
            horas=[time(15, 0)],
            dias_semana=list(DiaSemana),
        ),
        destino=Destino(ruta=r"C:\backups\XE"),
    )
    estrategia = _estrategia_con_tareas([tarea], prioridad=Prioridad.ALTA)
    contexto = ContextoValidacion(estrategia=estrategia, perfil=_perfil(LogMode.ARCHIVELOG))
    assert "PRG_005" not in [h.codigo for h in motor.validar(contexto)]


def test_prg_005_no_se_dispara_para_prioridad_baja_con_frecuencia_semanal() -> None:
    tarea = Tarea(
        codigo="T1",
        como=Como(tipo_respaldo=TipoRespaldo.INCREMENTAL_N0, modo_respaldo=ModoRespaldo.AUTO),
        programacion=Programacion(tipo_frecuencia=TipoFrecuencia.SEMANAL, horas=[time(2, 0)]),
        destino=Destino(ruta=r"C:\backups\XE"),
    )
    estrategia = _estrategia_con_tareas([tarea], prioridad=Prioridad.BAJA)
    contexto = ContextoValidacion(estrategia=estrategia, perfil=_perfil(LogMode.ARCHIVELOG))
    assert "PRG_005" not in [h.codigo for h in motor.validar(contexto)]


def test_dst_001_detecta_destino_no_escribible() -> None:
    contexto = ContextoValidacion(
        estrategia=_estrategia_con_tareas(
            [
                Tarea(
                    codigo="T1",
                    como=Como(tipo_respaldo=TipoRespaldo.COMPLETO, modo_respaldo=ModoRespaldo.AUTO),
                    programacion=Programacion(tipo_frecuencia=TipoFrecuencia.DIARIA, horas=[time(13, 0)]),
                    destino=Destino(ruta=r"C:\backups\XE"),
                )
            ]
        ),
        perfil=_perfil(LogMode.ARCHIVELOG),
        destinos_escribibles={r"C:\backups\XE": False},
    )
    assert "DST_001" in [h.codigo for h in motor.validar(contexto)]


def test_dst_001_no_se_dispara_si_el_destino_es_escribible() -> None:
    contexto = ContextoValidacion(estrategia=_estrategia(ModoRespaldo.AUTO), perfil=_perfil(LogMode.ARCHIVELOG))
    assert "DST_001" not in [h.codigo for h in motor.validar(contexto)]


def test_dst_002_detecta_espacio_insuficiente() -> None:
    contexto = ContextoValidacion(
        estrategia=_estrategia(ModoRespaldo.AUTO),
        perfil=_perfil(LogMode.ARCHIVELOG),
        espacio_estimado_bytes={"T1": 2_000_000_000},
        espacio_libre_destino_bytes={r"C:\backups\XE": 1_000_000_000},
    )
    assert "DST_002" in [h.codigo for h in motor.validar(contexto)]


def test_dst_002_no_se_dispara_si_alcanza_el_espacio() -> None:
    contexto = ContextoValidacion(
        estrategia=_estrategia(ModoRespaldo.AUTO),
        perfil=_perfil(LogMode.ARCHIVELOG),
        espacio_estimado_bytes={"T1": 1_000_000_000},
        espacio_libre_destino_bytes={r"C:\backups\XE": 2_000_000_000},
    )
    assert "DST_002" not in [h.codigo for h in motor.validar(contexto)]


def test_dst_003_detecta_uso_de_disco_sobre_el_85_por_ciento() -> None:
    contexto = ContextoValidacion(
        estrategia=_estrategia(ModoRespaldo.AUTO),
        perfil=_perfil(LogMode.ARCHIVELOG),
        espacio_total_destino_bytes={r"C:\backups\XE": 100},
        espacio_libre_destino_bytes={r"C:\backups\XE": 5},
    )
    assert "DST_003" in [h.codigo for h in motor.validar(contexto)]


def test_dst_003_no_se_dispara_con_espacio_de_sobra() -> None:
    contexto = ContextoValidacion(
        estrategia=_estrategia(ModoRespaldo.AUTO),
        perfil=_perfil(LogMode.ARCHIVELOG),
        espacio_total_destino_bytes={r"C:\backups\XE": 100},
        espacio_libre_destino_bytes={r"C:\backups\XE": 50},
    )
    assert "DST_003" not in [h.codigo for h in motor.validar(contexto)]


def _datafile(ruta: str) -> DatafileInfo:
    return DatafileInfo(
        ruta=ruta,
        file_id=1,
        con_id=3,
        tablespace="VENTAS",
        bytes=1_000_000,
        estado="ONLINE",
        autoextensible=False,
        max_bytes=None,
        bytes_libres=None,
    )


def test_dst_004_detecta_destino_en_el_mismo_disco_que_los_datafiles() -> None:
    perfil = _perfil(LogMode.ARCHIVELOG).model_copy(
        update={"datafiles": [_datafile(r"C:\oradata\XE\SYSTEM01.DBF")]}
    )
    contexto = ContextoValidacion(estrategia=_estrategia(ModoRespaldo.AUTO), perfil=perfil)
    assert "DST_004" in [h.codigo for h in motor.validar(contexto)]


def test_dst_004_no_se_dispara_si_el_destino_esta_en_otro_disco() -> None:
    perfil = _perfil(LogMode.ARCHIVELOG).model_copy(
        update={"datafiles": [_datafile(r"D:\oradata\XE\SYSTEM01.DBF")]}
    )
    contexto = ContextoValidacion(estrategia=_estrategia(ModoRespaldo.AUTO), perfil=perfil)
    assert "DST_004" not in [h.codigo for h in motor.validar(contexto)]


def test_dst_006_detecta_ruta_con_caracteres_no_ascii() -> None:
    tarea = Tarea(
        codigo="T1",
        como=Como(tipo_respaldo=TipoRespaldo.COMPLETO, modo_respaldo=ModoRespaldo.AUTO),
        programacion=Programacion(tipo_frecuencia=TipoFrecuencia.DIARIA, horas=[time(13, 0)]),
        destino=Destino(ruta=r"C:\respaldosñ\XE"),
    )
    estrategia = _estrategia_con_tareas([tarea])
    contexto = ContextoValidacion(estrategia=estrategia, perfil=_perfil(LogMode.ARCHIVELOG))
    assert "DST_006" in [h.codigo for h in motor.validar(contexto)]


def test_dst_006_no_se_dispara_con_una_ruta_ascii() -> None:
    contexto = ContextoValidacion(estrategia=_estrategia(ModoRespaldo.AUTO), perfil=_perfil(LogMode.ARCHIVELOG))
    assert "DST_006" not in [h.codigo for h in motor.validar(contexto)]


def _tarea(
    tipo: TipoRespaldo, codigo: str = "T1", canales: int = 1, compresion: Compresion = Compresion.NINGUNA
) -> Tarea:
    return Tarea(
        codigo=codigo,
        como=Como(
            tipo_respaldo=tipo,
            modo_respaldo=ModoRespaldo.AUTO,
            opciones=OpcionesRespaldo(canales=canales, compresion=compresion),
        ),
        programacion=Programacion(tipo_frecuencia=TipoFrecuencia.DIARIA, horas=[time(13, 0)]),
        destino=Destino(ruta=r"C:\backups\XE"),
    )


def test_met_001_detecta_n1_sin_n0_en_la_estrategia() -> None:
    estrategia = _estrategia_con_tareas([_tarea(TipoRespaldo.INCREMENTAL_N1_DIFERENCIAL)])
    contexto = ContextoValidacion(estrategia=estrategia, perfil=_perfil(LogMode.ARCHIVELOG))
    assert "MET_001" in [h.codigo for h in motor.validar(contexto)]


def test_met_001_no_se_dispara_si_hay_una_tarea_n0() -> None:
    estrategia = _estrategia_con_tareas(
        [_tarea(TipoRespaldo.INCREMENTAL_N0, "T1"), _tarea(TipoRespaldo.INCREMENTAL_N1_DIFERENCIAL, "T2")]
    )
    contexto = ContextoValidacion(estrategia=estrategia, perfil=_perfil(LogMode.ARCHIVELOG))
    assert "MET_001" not in [h.codigo for h in motor.validar(contexto)]


def test_met_002_detecta_n1_con_base_completo() -> None:
    estrategia = _estrategia_con_tareas(
        [_tarea(TipoRespaldo.COMPLETO, "T1"), _tarea(TipoRespaldo.INCREMENTAL_N1_ACUMULATIVO, "T2")]
    )
    contexto = ContextoValidacion(estrategia=estrategia, perfil=_perfil(LogMode.ARCHIVELOG))
    assert "MET_002" in [h.codigo for h in motor.validar(contexto)]


def test_met_002_no_se_dispara_con_base_n0() -> None:
    estrategia = _estrategia_con_tareas(
        [_tarea(TipoRespaldo.INCREMENTAL_N0, "T1"), _tarea(TipoRespaldo.INCREMENTAL_N1_ACUMULATIVO, "T2")]
    )
    contexto = ContextoValidacion(estrategia=estrategia, perfil=_perfil(LogMode.ARCHIVELOG))
    assert "MET_002" not in [h.codigo for h in motor.validar(contexto)]


def test_met_003_detecta_compresion_no_soportada_en_xe() -> None:
    estrategia = _estrategia_con_tareas([_tarea(TipoRespaldo.COMPLETO, compresion=Compresion.HIGH)])
    perfil = _perfil(LogMode.ARCHIVELOG).model_copy(update={"edicion": "XE"})
    contexto = ContextoValidacion(estrategia=estrategia, perfil=perfil)
    assert "MET_003" in [h.codigo for h in motor.validar(contexto)]


def test_met_003_no_se_dispara_con_compresion_basic_en_xe() -> None:
    estrategia = _estrategia_con_tareas([_tarea(TipoRespaldo.COMPLETO, compresion=Compresion.BASIC)])
    perfil = _perfil(LogMode.ARCHIVELOG).model_copy(update={"edicion": "XE"})
    contexto = ContextoValidacion(estrategia=estrategia, perfil=perfil)
    assert "MET_003" not in [h.codigo for h in motor.validar(contexto)]


def test_met_003_la_misma_compresion_se_acepta_en_enterprise() -> None:
    estrategia = _estrategia_con_tareas([_tarea(TipoRespaldo.COMPLETO, compresion=Compresion.HIGH)])
    perfil = _perfil(LogMode.ARCHIVELOG).model_copy(update={"edicion": "EE"})
    contexto = ContextoValidacion(estrategia=estrategia, perfil=perfil)
    assert "MET_003" not in [h.codigo for h in motor.validar(contexto)]


def test_met_004_detecta_mas_canales_de_los_soportados_en_xe() -> None:
    estrategia = _estrategia_con_tareas([_tarea(TipoRespaldo.COMPLETO, canales=2)])
    perfil = _perfil(LogMode.ARCHIVELOG).model_copy(update={"edicion": "XE"})
    contexto = ContextoValidacion(estrategia=estrategia, perfil=perfil)
    assert "MET_004" in [h.codigo for h in motor.validar(contexto)]


def test_met_004_no_se_dispara_con_un_canal_en_xe() -> None:
    estrategia = _estrategia_con_tareas([_tarea(TipoRespaldo.COMPLETO, canales=1)])
    perfil = _perfil(LogMode.ARCHIVELOG).model_copy(update={"edicion": "XE"})
    contexto = ContextoValidacion(estrategia=estrategia, perfil=perfil)
    assert "MET_004" not in [h.codigo for h in motor.validar(contexto)]
