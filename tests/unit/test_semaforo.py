from cloudcr_backup.domain.alertas import SeveridadAlerta, VistaAlerta
from cloudcr_backup.domain.enums import EstadoAlerta, EstadoEjecucion, EstadoPrueba
from cloudcr_backup.domain.monitoreo import ColorSemaforo
from cloudcr_backup.services.monitoreo import color_semaforo
from tests.unit.alertas_falsas import fila


def _alerta(severidad: SeveridadAlerta, estado: EstadoAlerta = EstadoAlerta.ABIERTA) -> VistaAlerta:
    return VistaAlerta(
        id=1, codigo="X", clave_dedup="X:1", severidad=severidad, estado=estado, mensaje="m", estrategia_id=2
    )


def test_inactiva_es_sin_datos() -> None:
    color, motivos = color_semaforo(False, True, {"T1": fila()}, [])
    assert color is ColorSemaforo.SIN_DATOS
    assert "inactiva" in motivos[0]


def test_sin_script_aprobado_es_sin_datos() -> None:
    color, _ = color_semaforo(True, False, {"T1": None}, [])
    assert color is ColorSemaforo.SIN_DATOS


def test_alerta_vigente_es_rojo() -> None:
    color, motivos = color_semaforo(True, True, {"T1": fila()}, [_alerta(SeveridadAlerta.ALERTA)])
    assert color is ColorSemaforo.ROJO
    assert "ALERTA" in motivos[0]


def test_alerta_reconocida_sigue_en_rojo() -> None:
    color, _ = color_semaforo(True, True, {"T1": fila()}, [_alerta(SeveridadAlerta.ALERTA, EstadoAlerta.RECONOCIDA)])
    assert color is ColorSemaforo.ROJO


def test_ultima_fallida_bloqueada_o_no_ejecutada_es_rojo() -> None:
    for estado in (EstadoEjecucion.FALLIDA, EstadoEjecucion.BLOQUEADA, EstadoEjecucion.NO_EJECUTADA):
        color, motivos = color_semaforo(True, True, {"T1": fila(estado=estado, prueba=EstadoPrueba.NO_APLICA)}, [])
        assert color is ColorSemaforo.ROJO, estado
        assert "T1" in motivos[0]


def test_advertencia_vigente_es_amarillo() -> None:
    color, _ = color_semaforo(True, True, {"T1": fila()}, [_alerta(SeveridadAlerta.ADVERTENCIA)])
    assert color is ColorSemaforo.AMARILLO


def test_ultima_con_advertencias_es_amarillo() -> None:
    color, _ = color_semaforo(True, True, {"T1": fila(estado=EstadoEjecucion.CON_ADVERTENCIAS)}, [])
    assert color is ColorSemaforo.AMARILLO


def test_pruebas_pendientes_o_fallidas_es_amarillo() -> None:
    for prueba in (EstadoPrueba.PENDIENTE, EstadoPrueba.FALLIDA):
        color, motivos = color_semaforo(True, True, {"T1": fila(prueba=prueba)}, [])
        assert color is ColorSemaforo.AMARILLO
        assert "Pruebas" in motivos[0]


def test_todo_bien_es_verde() -> None:
    assert color_semaforo(True, True, {"T1": fila(), "T2": fila(prueba=EstadoPrueba.NO_APLICA)}, []) == (
        ColorSemaforo.VERDE,
        [],
    )


def test_sin_ejecuciones_todavia_es_verde_con_motivo() -> None:
    assert color_semaforo(True, True, {"T1": None}, []) == (ColorSemaforo.VERDE, ["Sin ejecuciones todavía."])


def test_recomendacion_y_alertas_resueltas_no_cambian_el_color() -> None:
    alertas = [_alerta(SeveridadAlerta.RECOMENDACION), _alerta(SeveridadAlerta.ALERTA, EstadoAlerta.RESUELTA)]
    assert color_semaforo(True, True, {"T1": fila()}, alertas)[0] is ColorSemaforo.VERDE


def test_rojo_gana_sobre_amarillo() -> None:
    color, motivos = color_semaforo(
        True,
        True,
        {"T1": fila(estado=EstadoEjecucion.FALLIDA), "T2": fila(estado=EstadoEjecucion.CON_ADVERTENCIAS)},
        [],
    )
    assert color is ColorSemaforo.ROJO
    assert len(motivos) == 2
