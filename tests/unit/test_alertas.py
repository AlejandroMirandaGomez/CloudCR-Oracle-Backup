from datetime import UTC, datetime, timedelta

import pytest

from cloudcr_backup.alerts import reglas
from cloudcr_backup.alerts.instantanea import ScriptVigente, UsoDisco
from cloudcr_backup.alerts.motor import MotorAlertas
from cloudcr_backup.domain.alertas import CodigoAlerta, Condicion, SeveridadAlerta, alcanza
from cloudcr_backup.domain.enums import (
    EstadoAlerta,
    EstadoEjecucion,
    EstadoPrueba,
    LogMode,
    ModoRespaldo,
    TipoFrecuencia,
    TipoRespaldo,
)
from cloudcr_backup.domain.estrategia import Programacion
from cloudcr_backup.domain.perfil_bd import PerfilBD
from tests.unit.alertas_falsas import (
    AHORA,
    APROBADO,
    DESTINO,
    FuenteAlertasMemoria,
    NotificadorMemoria,
    estrategia,
    fila,
    instantanea,
    tarea,
)

GIGA = 1024**3


@pytest.fixture
def archivelog(perfil_xe: PerfilBD) -> PerfilBD:
    return perfil_xe.model_copy(update={"log_mode": LogMode.ARCHIVELOG})


def _ejecutar(regla: reglas.ReglaAlerta, *args: object, **kwargs: object) -> list[Condicion]:
    return list(regla(instantanea(*args, **kwargs)))  # type: ignore[arg-type]


def test_bd_noarchivelog_dispara(perfil_xe: PerfilBD) -> None:
    condiciones = _ejecutar(reglas.bd_noarchivelog, perfil_xe)
    assert [c.clave_dedup for c in condiciones] == ["BD_NOARCHIVELOG:XE"]
    assert condiciones[0].severidad is SeveridadAlerta.ADVERTENCIA


def test_bd_noarchivelog_no_dispara_en_archivelog_o_sin_perfil(archivelog: PerfilBD) -> None:
    assert _ejecutar(reglas.bd_noarchivelog, archivelog) == []
    assert _ejecutar(reglas.bd_noarchivelog, None) == []


def test_estrategia_sin_tareas_dispara(archivelog: PerfilBD) -> None:
    condiciones = list(reglas.estrategia_sin_programacion(instantanea(archivelog, estrategia(tareas=[]))))
    assert [c.codigo_regla for c in condiciones] == ["ESTRATEGIA_SIN_PROGRAMACION"]
    assert "no tiene tareas" in condiciones[0].mensaje


def test_estrategia_con_programacion_incompleta_dispara(archivelog: PerfilBD) -> None:
    incompleta = tarea(programacion=Programacion(tipo_frecuencia=TipoFrecuencia.DIARIA))
    condiciones = list(reglas.estrategia_sin_programacion(instantanea(archivelog, estrategia(incompleta))))
    assert len(condiciones) == 1
    assert "T1" in condiciones[0].mensaje


def test_estrategia_con_programacion_valida_no_dispara(archivelog: PerfilBD) -> None:
    assert _ejecutar(reglas.estrategia_sin_programacion, archivelog) == []


def test_respaldo_no_ejecutado_por_ultima_no_ejecutada(archivelog: PerfilBD) -> None:
    perdida = fila(estado=EstadoEjecucion.NO_EJECUTADA, prueba=EstadoPrueba.NO_APLICA, mensaje="agente detenido")
    condiciones = list(reglas.respaldo_no_ejecutado(instantanea(archivelog, estrategia(tarea(ultimas=[perdida])))))
    assert [c.clave_dedup for c in condiciones] == ["RESPALDO_NO_EJECUTADO:XE/EST001/T1"]
    assert condiciones[0].severidad is SeveridadAlerta.ALERTA
    assert "agente detenido" in condiciones[0].mensaje
    assert condiciones[0].ejecucion_id == 40


def test_respaldo_no_ejecutado_por_ocurrencias_sin_reclamar(archivelog: PerfilBD) -> None:
    sin_reclamar = tarea(ocurrencias_perdidas=[AHORA - timedelta(hours=2)])
    condiciones = list(reglas.respaldo_no_ejecutado(instantanea(archivelog, estrategia(sin_reclamar))))
    assert len(condiciones) == 1
    assert "agente parece detenido" in condiciones[0].mensaje


def test_respaldo_no_ejecutado_se_resuelve_cuando_la_siguiente_termina_bien(archivelog: PerfilBD) -> None:
    perdida = fila(39, EstadoEjecucion.NO_EJECUTADA, EstadoPrueba.NO_APLICA, AHORA - timedelta(hours=2))
    ultimas = [fila(40), perdida]
    assert list(reglas.respaldo_no_ejecutado(instantanea(archivelog, estrategia(tarea(ultimas=ultimas))))) == []


def test_ejecucion_fallida_dispara_con_extracto_de_rman(archivelog: PerfilBD) -> None:
    fallida = fila(estado=EstadoEjecucion.FALLIDA, prueba=EstadoPrueba.PENDIENTE, mensaje="RMAN-03009: failure")
    condiciones = list(reglas.ejecucion_fallida(instantanea(archivelog, estrategia(tarea(ultimas=[fallida])))))
    assert [c.codigo_regla for c in condiciones] == ["EJECUCION_FALLIDA"]
    assert "RMAN-03009" in condiciones[0].mensaje
    assert condiciones[0].alcance == ["XEPDB1:VENTAS", "XEPDB1:FINANZAS"]


def test_ejecucion_fallida_no_dispara_si_la_siguiente_salio_bien(archivelog: PerfilBD) -> None:
    ultimas = [fila(41), fila(40, EstadoEjecucion.FALLIDA, EstadoPrueba.PENDIENTE)]
    assert list(reglas.ejecucion_fallida(instantanea(archivelog, estrategia(tarea(ultimas=ultimas))))) == []


def test_un_exito_con_pruebas_pendientes_no_resuelve_la_falla(archivelog: PerfilBD) -> None:
    ultimas = [fila(41, prueba=EstadoPrueba.PENDIENTE), fila(40, EstadoEjecucion.FALLIDA, EstadoPrueba.PENDIENTE)]
    condiciones = list(reglas.ejecucion_fallida(instantanea(archivelog, estrategia(tarea(ultimas=ultimas)))))
    assert [c.ejecucion_id for c in condiciones] == [40]


def test_ejecucion_bloqueada_dispara_y_no_dispara(archivelog: PerfilBD) -> None:
    bloqueada = fila(estado=EstadoEjecucion.BLOQUEADA, prueba=EstadoPrueba.NO_APLICA)
    disparo = list(reglas.ejecucion_bloqueada(instantanea(archivelog, estrategia(tarea(ultimas=[bloqueada])))))
    assert [c.codigo_regla for c in disparo] == ["EJECUCION_BLOQUEADA"]
    assert _ejecutar(reglas.ejecucion_bloqueada, archivelog) == []


def test_verificacion_fallida_dispara_y_no_dispara(archivelog: PerfilBD) -> None:
    mala = fila(prueba=EstadoPrueba.FALLIDA)
    disparo = list(reglas.verificacion_fallida(instantanea(archivelog, estrategia(tarea(ultimas=[mala])))))
    assert [c.codigo_regla for c in disparo] == ["VERIFICACION_FALLIDA"]
    assert _ejecutar(reglas.verificacion_fallida, archivelog) == []


def test_espacio_insuficiente_por_porcentaje(archivelog: PerfilBD) -> None:
    uso = {DESTINO: UsoDisco(total_bytes=100 * GIGA, usados_bytes=90 * GIGA, libres_bytes=10 * GIGA)}
    condiciones = _ejecutar(reglas.espacio_insuficiente, archivelog, uso=uso)
    assert [c.severidad for c in condiciones] == [SeveridadAlerta.ADVERTENCIA]
    assert "90 %" in condiciones[0].mensaje


def test_espacio_insuficiente_por_tamano_estimado(archivelog: PerfilBD) -> None:
    uso = {DESTINO: UsoDisco(total_bytes=100 * GIGA, usados_bytes=50 * GIGA, libres_bytes=2 * GIGA)}
    grande = estrategia(tarea(tamano_ultimo_exito=5 * GIGA))
    condiciones = list(reglas.espacio_insuficiente(instantanea(archivelog, grande, uso=uso)))
    assert [c.severidad for c in condiciones] == [SeveridadAlerta.ALERTA]
    assert "no cabe" in condiciones[0].mensaje


def test_espacio_suficiente_no_dispara(archivelog: PerfilBD) -> None:
    uso = {DESTINO: UsoDisco(total_bytes=100 * GIGA, usados_bytes=50 * GIGA, libres_bytes=50 * GIGA)}
    assert _ejecutar(reglas.espacio_insuficiente, archivelog, uso=uso) == []
    assert _ejecutar(reglas.espacio_insuficiente, archivelog, uso={DESTINO: None}) == []


def test_umbral_de_disco_viene_de_los_parametros(archivelog: PerfilBD) -> None:
    uso = {DESTINO: UsoDisco(total_bytes=100 * GIGA, usados_bytes=90 * GIGA, libres_bytes=10 * GIGA)}
    parametros = {"alertas.disco_uso_pct": "95"}
    assert _ejecutar(reglas.espacio_insuficiente, archivelog, uso=uso, parametros=parametros) == []


def test_sin_respaldo_reciente_dispara(archivelog: PerfilBD) -> None:
    vieja = estrategia(ultimo_exito=AHORA - timedelta(hours=30))
    condiciones = list(reglas.sin_respaldo_reciente(instantanea(archivelog, vieja)))
    assert [c.clave_dedup for c in condiciones] == ["SIN_RESPALDO_RECIENTE:XE/EST001"]
    assert "30 h" in condiciones[0].mensaje


def test_sin_respaldo_reciente_respeta_el_parametro(archivelog: PerfilBD) -> None:
    vieja = estrategia(ultimo_exito=AHORA - timedelta(hours=30))
    parametros = {"alertas.recencia_horas.ALTA": "48"}
    assert list(reglas.sin_respaldo_reciente(instantanea(archivelog, vieja, parametros=parametros))) == []


def test_sin_respaldo_reciente_no_alerta_el_primer_dia_tras_aprobar(archivelog: PerfilBD) -> None:
    recien = tarea(script=ScriptVigente(9, AHORA - timedelta(hours=3), LogMode.ARCHIVELOG), ultimas=[])
    nueva = estrategia(recien, ultimo_exito=None)
    assert list(reglas.sin_respaldo_reciente(instantanea(archivelog, nueva))) == []
    sin_nada = estrategia(tarea(ultimas=[]), ultimo_exito=None)
    condiciones = list(reglas.sin_respaldo_reciente(instantanea(archivelog, sin_nada)))
    assert "todavía no hay ningún respaldo correcto" in condiciones[0].mensaje


def test_sin_respaldo_reciente_ignora_estrategias_sin_script(archivelog: PerfilBD) -> None:
    sin_script = estrategia(tarea(script=None), ultimo_exito=None)
    assert list(reglas.sin_respaldo_reciente(instantanea(archivelog, sin_script))) == []


def test_modo_archivado_de_noarchivelog_a_archivelog_es_advertencia(archivelog: PerfilBD) -> None:
    script = ScriptVigente(9, APROBADO, LogMode.NOARCHIVELOG)
    consistente = estrategia(tarea(script=script, modo_respaldo=ModoRespaldo.CONSISTENTE))
    condiciones = list(reglas.modo_archivado_cambio(instantanea(archivelog, consistente)))
    assert [c.severidad for c in condiciones] == [SeveridadAlerta.ADVERTENCIA]
    assert "regenérelo" in condiciones[0].mensaje


def test_modo_archivado_de_archivelog_a_noarchivelog_en_linea_es_alerta(perfil_xe: PerfilBD) -> None:
    condiciones = _ejecutar(reglas.modo_archivado_cambio, perfil_xe)
    assert [c.severidad for c in condiciones] == [SeveridadAlerta.ALERTA]
    assert "va a fallar" in condiciones[0].mensaje


def test_modo_archivado_a_noarchivelog_con_script_de_archived_logs(perfil_xe: PerfilBD) -> None:
    archivados = estrategia(tarea(tipo_respaldo=TipoRespaldo.ARCHIVELOG, modo_respaldo=ModoRespaldo.CONSISTENTE))
    assert len(list(reglas.modo_archivado_cambio(instantanea(perfil_xe, archivados)))) == 1


def test_modo_archivado_sin_cambio_o_consistente_no_dispara(archivelog: PerfilBD, perfil_xe: PerfilBD) -> None:
    assert _ejecutar(reglas.modo_archivado_cambio, archivelog) == []
    consistente = estrategia(tarea(modo_respaldo=ModoRespaldo.CONSISTENTE))
    assert list(reglas.modo_archivado_cambio(instantanea(perfil_xe, consistente))) == []
    sin_dato = estrategia(tarea(script=ScriptVigente(9, APROBADO, None)))
    assert list(reglas.modo_archivado_cambio(instantanea(perfil_xe, sin_dato))) == []


def test_retencion_vencida_dispara_y_no_dispara(archivelog: PerfilBD) -> None:
    vencida = estrategia(piezas_vencidas=4)
    condiciones = list(reglas.retencion_vencida(instantanea(archivelog, vencida)))
    assert [c.severidad for c in condiciones] == [SeveridadAlerta.RECOMENDACION]
    assert _ejecutar(reglas.retencion_vencida, archivelog) == []
    con_purga = estrategia(piezas_vencidas=4, purga_automatica=True)
    assert list(reglas.retencion_vencida(instantanea(archivelog, con_purga))) == []


def test_archivelog_acumulado_dispara_y_no_dispara(archivelog: PerfilBD, perfil_xe: PerfilBD) -> None:
    muchos = archivelog.model_copy(update={"archivelogs_sin_respaldo": 150})
    assert [c.codigo_regla for c in _ejecutar(reglas.archivelog_acumulado, muchos)] == ["ARCHIVELOG_ACUMULADO"]
    assert _ejecutar(reglas.archivelog_acumulado, archivelog) == []
    assert _ejecutar(reglas.archivelog_acumulado, muchos, parametros={"alertas.archivelogs_max": "200"}) == []
    noarch = perfil_xe.model_copy(update={"archivelogs_sin_respaldo": 150})
    assert _ejecutar(reglas.archivelog_acumulado, noarch) == []


def test_hay_once_reglas_periodicas_con_su_descripcion() -> None:
    assert len(reglas.REGLAS) == 11
    assert all(reglas.descripcion(codigo) is not None for codigo in CodigoAlerta)


def test_alcanza_severidad() -> None:
    assert alcanza(SeveridadAlerta.ALERTA, SeveridadAlerta.ADVERTENCIA)
    assert not alcanza(SeveridadAlerta.RECOMENDACION, SeveridadAlerta.ADVERTENCIA)


def _motor_con_falla(archivelog: PerfilBD) -> tuple[MotorAlertas, FuenteAlertasMemoria, NotificadorMemoria]:
    fallida = fila(estado=EstadoEjecucion.FALLIDA, prueba=EstadoPrueba.PENDIENTE)
    fuente = FuenteAlertasMemoria(instantanea(archivelog, estrategia(tarea(ultimas=[fallida]))))
    notificador = NotificadorMemoria()
    return MotorAlertas(fuente, [notificador]), fuente, notificador


def test_motor_abre_una_alerta_nueva_y_notifica(archivelog: PerfilBD) -> None:
    motor, _, notificador = _motor_con_falla(archivelog)
    resumen = motor.evaluar(AHORA)
    assert resumen.abiertas == ["EJECUCION_FALLIDA:XE/EST001/T1"]
    assert len(notificador.recibidas) == 1
    assert notificador.recibidas[0][1].alcance == ["XEPDB1:VENTAS", "XEPDB1:FINANZAS"]


def test_motor_deduplica_y_no_vuelve_a_notificar(archivelog: PerfilBD) -> None:
    motor, fuente, notificador = _motor_con_falla(archivelog)
    motor.evaluar(AHORA)
    resumen = motor.evaluar(AHORA + timedelta(minutes=5))
    assert resumen.abiertas == []
    assert resumen.actualizadas == ["EJECUCION_FALLIDA:XE/EST001/T1"]
    assert len(fuente.alertas) == 1
    assert len(notificador.recibidas) == 1


def test_una_alerta_reconocida_no_se_duplica(archivelog: PerfilBD) -> None:
    motor, fuente, notificador = _motor_con_falla(archivelog)
    motor.evaluar(AHORA)
    fuente.reconocer(1)
    motor.evaluar(AHORA + timedelta(minutes=5))
    assert len(fuente.alertas) == 1
    assert fuente.alertas[0].estado is EstadoAlerta.RECONOCIDA
    assert len(notificador.recibidas) == 1


def test_motor_resuelve_automaticamente_incluso_reconocidas(archivelog: PerfilBD) -> None:
    motor, fuente, _ = _motor_con_falla(archivelog)
    motor.evaluar(AHORA)
    fuente.reconocer(1)
    fuente.actual = instantanea(archivelog, estrategia(tarea(ultimas=[fila(41), fila(40, EstadoEjecucion.FALLIDA)])))
    resumen = motor.evaluar(AHORA + timedelta(hours=1))
    assert resumen.resueltas == ["EJECUCION_FALLIDA:XE/EST001/T1"]
    assert fuente.alertas[0].estado is EstadoAlerta.RESUELTA


def test_las_alertas_de_evento_no_se_resuelven_solas(archivelog: PerfilBD) -> None:
    fuente = FuenteAlertasMemoria(instantanea(archivelog))
    motor = MotorAlertas(fuente)
    evento = Condicion(
        codigo_regla="SCRIPT_ALTERADO", sujeto="XE/EST001/T1", severidad=SeveridadAlerta.ALERTA, mensaje="hash"
    )
    motor.registrar_evento([evento], AHORA)
    motor.evaluar(AHORA)
    assert fuente.alertas[0].estado is EstadoAlerta.ABIERTA


def test_una_regla_que_falla_no_resuelve_sus_alertas_ni_detiene_las_demas(archivelog: PerfilBD) -> None:
    motor, fuente, _ = _motor_con_falla(archivelog)
    motor.evaluar(AHORA)

    def rota(_: object) -> list[Condicion]:
        raise RuntimeError("dato inesperado")

    reglas_rotas = dict(reglas.REGLAS)
    reglas_rotas[CodigoAlerta.EJECUCION_FALLIDA] = rota  # type: ignore[assignment]
    resumen = MotorAlertas(fuente, reglas=reglas_rotas).evaluar(AHORA)
    assert resumen.resueltas == []
    assert any("EJECUCION_FALLIDA" in e for e in resumen.errores)
    assert fuente.alertas[0].estado is EstadoAlerta.ABIERTA


def test_el_fallo_del_notificador_no_interrumpe_la_evaluacion(archivelog: PerfilBD) -> None:
    fallida = fila(estado=EstadoEjecucion.FALLIDA, prueba=EstadoPrueba.PENDIENTE)
    fuente = FuenteAlertasMemoria(instantanea(archivelog, estrategia(tarea(ultimas=[fallida]), piezas_vencidas=2)))
    roto = NotificadorMemoria(nombre="email", fallar=True)
    sano = NotificadorMemoria()
    resumen = MotorAlertas(fuente, [roto, sano]).evaluar(AHORA)
    assert len(resumen.abiertas) == 2
    assert len(sano.recibidas) == 2
    assert sum("email" in e for e in resumen.errores) == 2


def test_la_clave_de_deduplicacion_se_recorta() -> None:
    condicion = Condicion(codigo_regla="X", sujeto="y" * 500, severidad=SeveridadAlerta.ALERTA, mensaje="m")
    assert len(condicion.clave_dedup) == 200


def test_hora_local_en_mensajes() -> None:
    assert reglas.hora_local(datetime(2026, 10, 3, 19, 0, tzinfo=UTC), "America/Costa_Rica") == "2026-10-03 13:00"
    assert reglas.hora_local(datetime(2026, 10, 3, 19, 0, tzinfo=UTC), "Zona/Inexistente") == "2026-10-03 13:00"
