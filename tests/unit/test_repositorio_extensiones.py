import re
from datetime import datetime
from pathlib import Path
from typing import Any

import oracledb
import pytest

from cloudcr_backup.domain.alertas import Condicion, SeveridadAlerta
from cloudcr_backup.domain.enums import EstadoAlerta, EstadoEjecucion, EstadoPrueba, LogMode
from cloudcr_backup.repository import alertas, bases_datos, ejecuciones, estrategias, scripts
from cloudcr_backup.repository.ejecuciones import FiltrosHistorial
from tests.unit.oracle_falso import ConexionFalsa, binds_de

PROGRAMADA = datetime(2026, 10, 2, 19, 0)
REPOSITORIO = Path(__file__).resolve().parents[2] / "src" / "cloudcr_backup" / "repository"


def _fila_alerta(estado: str = "ABIERTA") -> tuple[Any, ...]:
    return (
        7, "EJECUCION_FALLIDA", "EJECUCION_FALLIDA:XE/EST001/T1", "ALERTA", estado, "Falló", 1, 2, 3, 40,
        datetime(2026, 10, 2, 19, 5), None, "XE", "EST001", "T1",
    )


def _fila_detallada(id_: int = 40, estado: str = "EXITOSA") -> tuple[Any, ...]:
    return (
        id_, 1, "XE", 2, "EST001", "Producción diaria", 3, "T1", "INCREMENTAL_N1_ACUMULATIVO", "EN_LINEA",
        estado, "PENDIENTE", PROGRAMADA, datetime(2026, 10, 2, 19, 0, 5), datetime(2026, 10, 2, 19, 3), 175,
        1048576, 2, r"C:\backups\XE", "America/Costa_Rica", None, "SERVIDOR", 9,
    )


def _condicion(**cambios: Any) -> Condicion:
    datos: dict[str, Any] = {
        "codigo_regla": "EJECUCION_FALLIDA",
        "sujeto": "XE/EST001/T1",
        "severidad": SeveridadAlerta.ALERTA,
        "mensaje": "Falló",
        "bd_id": 1,
        "estrategia_id": 2,
        "tarea_id": 3,
        "ejecucion_id": 40,
    }
    datos.update(cambios)
    return Condicion(**datos)


def test_binds_ignoran_literales_y_dobles_dos_puntos() -> None:
    assert binds_de("SELECT 'a:b' FROM t WHERE x = :uno AND y = :dos") == {"uno", "dos"}


def test_abrir_alerta_nueva_inserta_con_severidad_y_llaves() -> None:
    conexion = ConexionFalsa([None, _fila_alerta()])
    alerta, es_nueva = alertas.abrir(conexion, _condicion())  # type: ignore[arg-type]
    assert es_nueva
    assert alerta.id == 7
    assert alerta.estrategia_codigo == "EST001"
    insercion = conexion.ejecutados[1]
    assert insercion[0].startswith("INSERT INTO alerta")
    assert insercion[1]["severidad"] == "ALERTA"
    assert insercion[1]["tarea_id"] == 3
    assert "SYS_EXTRACT_UTC(SYSTIMESTAMP)" in insercion[0]


def test_abrir_alerta_reconocida_vigente_no_duplica() -> None:
    conexion = ConexionFalsa([(7,), _fila_alerta("RECONOCIDA")])
    alerta, es_nueva = alertas.abrir(conexion, _condicion(mensaje="Sigue fallando"))  # type: ignore[arg-type]
    assert not es_nueva
    assert alerta.estado is EstadoAlerta.RECONOCIDA
    assert "estado IN ('ABIERTA', 'RECONOCIDA')" in conexion.sql(0)
    assert conexion.sql(1).startswith("UPDATE alerta SET mensaje")
    assert not any(sql.startswith("INSERT") for sql, _ in conexion.ejecutados)


def test_mensaje_de_alerta_se_recorta_al_largo_de_la_columna() -> None:
    conexion = ConexionFalsa([None, _fila_alerta()])
    alertas.abrir(conexion, _condicion(mensaje="x" * 3000))  # type: ignore[arg-type]
    assert len(conexion.ejecutados[1][1]["mensaje"]) == 2000


def test_listar_alertas_con_filtros() -> None:
    conexion = ConexionFalsa([[_fila_alerta()]])
    resultado = alertas.listar(  # type: ignore[arg-type]
        conexion, [EstadoAlerta.ABIERTA, EstadoAlerta.RECONOCIDA], "ALERTA", 50
    )
    assert [a.id for a in resultado] == [7]
    assert conexion.ejecutados[0][1] == {
        "estado0": "ABIERTA",
        "estado1": "RECONOCIDA",
        "severidad": "ALERTA",
        "limite": 50,
    }


def test_reconocer_solo_si_esta_abierta() -> None:
    conexion = ConexionFalsa()
    conexion.filas_afectadas = 0
    assert not alertas.reconocer_abierta(conexion, 7)  # type: ignore[arg-type]
    assert "estado = 'ABIERTA'" in conexion.sql(0)


def test_resolver_vigente_incluye_reconocidas() -> None:
    conexion = ConexionFalsa()
    assert alertas.resolver_vigente(conexion, 7)  # type: ignore[arg-type]
    assert "estado IN ('ABIERTA', 'RECONOCIDA')" in conexion.sql(0)
    assert "SYS_EXTRACT_UTC(SYSTIMESTAMP)" in conexion.sql(0)


def test_registrar_no_ejecutada_inserta_con_motivo() -> None:
    conexion = ConexionFalsa([(1, "COMPLETO", 9)])
    ejecucion = ejecuciones.registrar_no_ejecutada(  # type: ignore[arg-type]
        conexion, 3, PROGRAMADA, "agente detenido o sin capacidad"
    )
    assert ejecucion is not None
    assert ejecucion.estado is EstadoEjecucion.NO_EJECUTADA
    sql, parametros = conexion.ejecutados[1]
    assert "'NO_EJECUTADA'" in sql
    assert parametros["motivo"] == "agente detenido o sin capacidad"


def test_registrar_no_ejecutada_devuelve_none_si_ya_existe() -> None:
    conexion = ConexionFalsa([(1, "COMPLETO", 9)])
    conexion.errores.extend([None, oracledb.IntegrityError("ORA-00001")])
    assert ejecuciones.registrar_no_ejecutada(conexion, 3, PROGRAMADA, "x") is None  # type: ignore[arg-type]
    assert conexion.rollbacks == 1


def test_registrar_no_ejecutada_sin_script_aprobado() -> None:
    conexion = ConexionFalsa([(1, "COMPLETO", None)])
    with pytest.raises(ValueError, match="script aprobado"):
        ejecuciones.registrar_no_ejecutada(conexion, 3, PROGRAMADA, "x")  # type: ignore[arg-type]


def test_marcar_no_ejecutada_solo_si_sigue_programada() -> None:
    conexion = ConexionFalsa()
    conexion.filas_afectadas = 0
    assert not ejecuciones.marcar_no_ejecutada(conexion, 40, "huérfana")  # type: ignore[arg-type]
    assert "estado = 'PROGRAMADA'" in conexion.sql(0)


def test_marcar_interrumpida_solo_si_sigue_en_curso() -> None:
    conexion = ConexionFalsa()
    assert ejecuciones.marcar_interrumpida(conexion, 40, "interrumpida")  # type: ignore[arg-type]
    assert "'FALLIDA'" in conexion.sql(0)
    assert "estado = 'EN_CURSO'" in conexion.sql(0)


def test_historial_detallado_con_filtros_y_paginacion() -> None:
    conexion = ConexionFalsa([[_fila_detallada()]])
    filtros = FiltrosHistorial(bd_id=1, estrategia_codigo="EST001", estado=EstadoEjecucion.EXITOSA)
    filas = ejecuciones.historial_detallado(conexion, filtros, limite=25, desplazamiento=50)  # type: ignore[arg-type]
    assert filas[0].bd_nombre == "XE"
    assert filas[0].estado_prueba is EstadoPrueba.PENDIENTE
    assert filas[0].duracion_segundos == 175
    assert conexion.ejecutados[0][1]["limite"] == 25
    assert conexion.ejecutados[0][1]["desplazamiento"] == 50


def test_detalle_trae_script_y_textos() -> None:
    conexion = ConexionFalsa([(*_fila_detallada(), "RMAN-03009", None, 2, "abc", "alejandro", PROGRAMADA)])
    detalle = ejecuciones.detalle(conexion, 40)  # type: ignore[arg-type]
    assert detalle is not None
    assert detalle.errores == "RMAN-03009"
    assert detalle.script_version == 2
    assert detalle.script_aprobado_por == "alejandro"


def test_ultimas_por_tarea_agrupa() -> None:
    conexion = ConexionFalsa([[(*_fila_detallada(41), 1), (*_fila_detallada(40), 2)]])
    resultado = ejecuciones.ultimas_por_tarea(conexion, 2)  # type: ignore[arg-type]
    assert [e.id for e in resultado[3]] == [41, 40]


def test_script_vigentes_por_tarea_traen_fecha_de_aprobacion() -> None:
    aprobado = datetime(2026, 10, 1, 12, 0)
    conexion = ConexionFalsa([[(3, 9, 1, "abc", "APROBADO", "ale", aprobado, aprobado)]])
    vigentes = scripts.vigentes_por_tarea(conexion)  # type: ignore[arg-type]
    assert vigentes[3].aprobado_en == aprobado
    assert vigentes[3].id == 9


def test_log_mode_al_crear_script() -> None:
    conexion = ConexionFalsa([("NOARCHIVELOG",)])
    assert bases_datos.log_mode_al_crear_script(conexion, 1, 9) is LogMode.NOARCHIVELOG  # type: ignore[arg-type]
    assert "capturado_en <=" in conexion.sql(0)


def test_ultimo_perfil(perfil_xe: Any) -> None:
    conexion = ConexionFalsa([(perfil_xe.model_dump_json(),)])
    perfil = bases_datos.ultimo_perfil(conexion, 1)  # type: ignore[arg-type]
    assert perfil is not None
    assert perfil.log_mode is LogMode.NOARCHIVELOG
    assert bases_datos.ultimo_perfil(ConexionFalsa(), 1) is None  # type: ignore[arg-type]


def test_ids_de_tareas() -> None:
    conexion = ConexionFalsa([[("T1", 3), ("T2", 4)]])
    assert estrategias.ids_de_tareas(conexion, 2) == {"T1": 3, "T2": 4}  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "funcion",
    [
        lambda c: ejecuciones.contar_historial(c, FiltrosHistorial(desde=PROGRAMADA, hasta=PROGRAMADA)),
        lambda c: ejecuciones.piezas(c, 1),
        lambda c: ejecuciones.verificaciones(c, 1),
        lambda c: ejecuciones.en_curso(c),
        lambda c: ejecuciones.ultima_programada_por_tarea(c),
        lambda c: ejecuciones.ultimo_exito_por_estrategia(c),
        lambda c: ejecuciones.tamano_ultimo_exito_por_tarea(c),
        lambda c: ejecuciones.piezas_vencidas_por_estrategia(c, PROGRAMADA),
        lambda c: ejecuciones.programadas_sin_iniciar(c, PROGRAMADA),
        lambda c: ejecuciones.en_curso_de_agente(c, "SERVIDOR"),
        lambda c: alertas.vigentes(c),
        lambda c: alertas.obtener(c, 1),
    ],
)
def test_consultas_nuevas_usan_binds_coherentes(funcion: Any) -> None:
    conexion = ConexionFalsa()
    funcion(conexion)
    assert conexion.ejecutados


def test_el_repositorio_guarda_horas_en_utc() -> None:
    sin_convertir = re.compile(r"(?<!SYS_EXTRACT_UTC\()SYSTIMESTAMP")
    for archivo in REPOSITORIO.glob("*.py"):
        if archivo.name == "esquema.py":
            continue
        assert not sin_convertir.search(archivo.read_text(encoding="utf-8")), archivo.name
