from datetime import date, datetime
from typing import Any

import oracledb
import pytest

from cloudcr_backup.repository import esquema
from cloudcr_backup.repository.migracion_oracle import (
    DestinoConDatos,
    DestinoSinEsquema,
    MigracionIncompleta,
    migrar,
)
from tests.unit.oracle_falso import ConexionFalsa

COLUMNA_NUMERO = oracledb.DB_TYPE_NUMBER
COLUMNA_TEXTO = oracledb.DB_TYPE_VARCHAR
COLUMNA_FECHA = oracledb.DB_TYPE_DATE


class CursorOrigen:
    def __init__(self, origen: "OrigenFalso") -> None:
        self._origen = origen
        self.description: list[tuple[str, Any]] | None = None
        self._filas: list[tuple[Any, ...]] = []
        self._contar = False

    def execute(self, sql: str, **parametros: Any) -> None:
        sql = " ".join(sql.split())
        self._contar = False
        if sql.startswith("SELECT COUNT(*) FROM user_tables"):
            self._filas = [(1 if parametros["tabla"] in self._origen.tablas else 0,)]
        elif sql.startswith("SELECT COUNT(*) FROM "):
            tabla = sql.removeprefix("SELECT COUNT(*) FROM ")
            self._filas = [(self._origen.conteo_reportado.get(tabla, len(self._origen.tablas[tabla][1])),)]
        else:
            tabla = sql.removeprefix("SELECT * FROM ").removesuffix(" ORDER BY 1")
            columnas, filas = self._origen.tablas[tabla]
            self.description = [(nombre, tipo) for nombre, tipo in columnas]
            self._filas = list(filas)

    def fetchone(self) -> tuple[Any, ...]:
        return self._filas[0]

    def __iter__(self) -> Any:
        return iter(self._filas)

    def close(self) -> None:
        pass


class OrigenFalso:
    def __init__(self, tablas: dict[str, tuple[list[tuple[str, Any]], list[tuple[Any, ...]]]]) -> None:
        self.tablas = tablas
        self.conteo_reportado: dict[str, int] = {}
        self.outputtypehandler: Any = None

    def cursor(self) -> CursorOrigen:
        return CursorOrigen(self)


def destino_instalado(filas_por_tabla: dict[str, int] | None = None) -> ConexionFalsa:
    filas_por_tabla = filas_por_tabla or {}
    respuestas: list[Any] = [[(tabla,) for tabla in esquema.TABLAS]]
    respuestas.extend((filas_por_tabla.get(tabla, 0),) for tabla in esquema.TABLAS)
    return ConexionFalsa(respuestas)


ORIGEN_BASICO = {
    "PARAMETRO": (
        [("CLAVE", COLUMNA_TEXTO), ("VALOR", COLUMNA_TEXTO)],
        [("agente.tick_segundos", "30"), ("rman.nls_lang", "AMERICAN_AMERICA.AL32UTF8")],
    ),
    "BD_REGISTRADA": (
        [("ID", COLUMNA_NUMERO), ("NOMBRE", COLUMNA_TEXTO)],
        [(1, "XE")],
    ),
    "PROGRAMACION": (
        [("ID", COLUMNA_NUMERO), ("FECHA_INICIO", COLUMNA_FECHA)],
        [(7, datetime(2026, 10, 1, 0, 0))],
    ),
}


def inserciones(destino: ConexionFalsa) -> list[tuple[str, dict[str, Any]]]:
    return [(sql, parametros) for sql, parametros in destino.ejecutados if sql.startswith("INSERT")]


def test_copia_las_tablas_en_orden_conservando_ids_y_convierte_fechas() -> None:
    origen = OrigenFalso(ORIGEN_BASICO)
    destino = destino_instalado()
    resultado = migrar(origen, destino)  # type: ignore[arg-type]
    assert resultado.filas == {"PARAMETRO": 2, "BD_REGISTRADA": 1, "PROGRAMACION": 1}
    assert resultado.total == 4
    assert "ESTRATEGIA" in resultado.omitidas and "RECUPERACION_PROCEDIMIENTO" in resultado.omitidas
    sentencias = inserciones(destino)
    assert sentencias[0] == (
        "INSERT INTO parametro (clave, valor) VALUES (:clave, :valor) AS nuevo "
        "ON DUPLICATE KEY UPDATE valor = nuevo.valor",
        {"clave": "agente.tick_segundos", "valor": "30"},
    )
    assert sentencias[2][1] == {"id": 1, "nombre": "XE"}
    assert sentencias[3][1]["fecha_inicio"] == date(2026, 10, 1)
    assert not isinstance(sentencias[3][1]["fecha_inicio"], datetime)
    assert destino.commits == 1 and destino.rollbacks == 0
    assert isinstance(origen.outputtypehandler, type(lambda: None))


def test_si_el_destino_ya_tiene_datos_no_copia_nada() -> None:
    destino = destino_instalado({"ESTRATEGIA": 2, "TAREA": 3})
    with pytest.raises(DestinoConDatos, match=r"ESTRATEGIA \(2\), TAREA \(3\)"):
        migrar(OrigenFalso(ORIGEN_BASICO), destino)  # type: ignore[arg-type]
    assert inserciones(destino) == []


def test_con_reemplazar_reinstala_el_esquema_antes_de_copiar() -> None:
    destino = destino_instalado({"PARAMETRO": 14, "ESTRATEGIA": 2})
    resultado = migrar(OrigenFalso(ORIGEN_BASICO), destino, reemplazar=True)  # type: ignore[arg-type]
    assert resultado.total == 4
    sentencias = [sql for sql, _ in destino.ejecutados]
    indice_drop = next(i for i, sql in enumerate(sentencias) if sql.startswith("DROP TABLE IF EXISTS"))
    indice_primera_insercion = next(i for i, sql in enumerate(sentencias) if sql.startswith("INSERT"))
    assert indice_drop < indice_primera_insercion


def test_sin_esquema_en_el_destino_pide_instalarlo() -> None:
    destino = ConexionFalsa([[]])
    with pytest.raises(DestinoSinEsquema, match="repo instalar"):
        migrar(OrigenFalso(ORIGEN_BASICO), destino)  # type: ignore[arg-type]


def test_si_no_coinciden_las_filas_copiadas_con_las_del_origen_se_revierte() -> None:
    origen = OrigenFalso(ORIGEN_BASICO)
    origen.conteo_reportado["BD_REGISTRADA"] = 5
    destino = destino_instalado()
    with pytest.raises(MigracionIncompleta, match="BD_REGISTRADA: se copiaron 1 de 5"):
        migrar(origen, destino)  # type: ignore[arg-type]
    assert destino.rollbacks == 1 and destino.commits == 0


def test_todas_las_tablas_del_esquema_estan_en_la_migracion() -> None:
    from cloudcr_backup.repository.migracion_oracle import TABLAS_A_MIGRAR

    assert set(esquema.TABLAS) <= set(TABLAS_A_MIGRAR)
    assert esquema.TABLA_RECUPERACION in TABLAS_A_MIGRAR
    assert TABLAS_A_MIGRAR.index("BD_REGISTRADA") < TABLAS_A_MIGRAR.index("ESTRATEGIA")
    assert TABLAS_A_MIGRAR.index("ESTRATEGIA") < TABLAS_A_MIGRAR.index("TAREA")
    assert TABLAS_A_MIGRAR.index("SCRIPT_RMAN") < TABLAS_A_MIGRAR.index("EJECUCION")


def test_los_parametros_iniciales_del_destino_no_cuentan_como_datos() -> None:
    destino = destino_instalado({"PARAMETRO": 14})
    resultado = migrar(OrigenFalso(ORIGEN_BASICO), destino)  # type: ignore[arg-type]
    assert resultado.filas["PARAMETRO"] == 2
    assert not any(sql.startswith("DROP") for sql, _ in destino.ejecutados)
