from dataclasses import dataclass
from datetime import datetime
from typing import Any

import oracledb

from cloudcr_backup.repository import esquema
from cloudcr_backup.repository.conexion import Conexion

TABLAS_A_MIGRAR = (*esquema.TABLAS, *esquema.TABLAS_COMPLEMENTARIAS)
TABLA_CON_VALORES_INICIALES = "PARAMETRO"
COLUMNA_A_ACTUALIZAR = "valor"


class DestinoConDatos(RuntimeError):
    pass


class DestinoSinEsquema(RuntimeError):
    pass


class MigracionIncompleta(RuntimeError):
    pass


@dataclass(frozen=True)
class ResultadoMigracion:
    filas: dict[str, int]
    omitidas: list[str]

    @property
    def total(self) -> int:
        return sum(self.filas.values())


def _manejador_tipos_salida(cursor: oracledb.Cursor, metadatos: oracledb.FetchInfo) -> oracledb.Var | None:
    if metadatos.type_code is oracledb.DB_TYPE_CLOB:
        return cursor.var(oracledb.DB_TYPE_LONG, arraysize=cursor.arraysize)
    return None


def _tabla_existe_en_origen(origen: oracledb.Connection, tabla: str) -> bool:
    cursor = origen.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM user_tables WHERE table_name = :tabla", tabla=tabla)
        fila = cursor.fetchone()
        return fila is not None and int(fila[0]) > 0
    finally:
        cursor.close()


def _convertir(valor: Any, es_fecha: bool) -> Any:
    if es_fecha and isinstance(valor, datetime):
        return valor.date()
    return valor


def _copiar_tabla(origen: oracledb.Connection, destino: Conexion, tabla: str) -> int:
    lector = origen.cursor()
    escritor = destino.cursor()
    try:
        lector.execute(f"SELECT * FROM {tabla} ORDER BY 1")
        descripciones = lector.description or []
        columnas = [descripcion[0].lower() for descripcion in descripciones]
        es_fecha = [descripcion[1] is oracledb.DB_TYPE_DATE for descripcion in descripciones]
        sentencia = (
            f"INSERT INTO {tabla.lower()} ({', '.join(columnas)}) VALUES ({', '.join(f':{c}' for c in columnas)})"
        )
        if tabla == TABLA_CON_VALORES_INICIALES:
            sentencia += f" AS nuevo ON DUPLICATE KEY UPDATE {COLUMNA_A_ACTUALIZAR} = nuevo.{COLUMNA_A_ACTUALIZAR}"
        copiadas = 0
        for fila in lector:
            valores = {c: _convertir(v, fecha) for c, v, fecha in zip(columnas, fila, es_fecha, strict=True)}
            escritor.execute(sentencia, **valores)
            copiadas += 1
        return copiadas
    finally:
        lector.close()
        escritor.close()


def _contar_origen(origen: oracledb.Connection, tabla: str) -> int:
    cursor = origen.cursor()
    try:
        cursor.execute(f"SELECT COUNT(*) FROM {tabla}")
        return int(cursor.fetchone()[0])
    finally:
        cursor.close()


def migrar(origen: oracledb.Connection, destino: Conexion, reemplazar: bool = False) -> ResultadoMigracion:
    origen.outputtypehandler = _manejador_tipos_salida
    estado_destino = esquema.estado(destino)
    if not estado_destino.instalado:
        raise DestinoSinEsquema(
            "El esquema de MySQL no está instalado: ejecute 'cloudcr repo instalar' antes de migrar."
        )
    con_datos = {
        tabla: filas
        for tabla, filas in estado_destino.tablas.items()
        if filas > 0 and tabla != TABLA_CON_VALORES_INICIALES
    }
    if con_datos and not reemplazar:
        detalle = ", ".join(f"{tabla} ({filas})" for tabla, filas in sorted(con_datos.items()))
        raise DestinoConDatos(f"El repositorio MySQL ya tiene datos: {detalle}.")
    if con_datos:
        esquema.instalar(destino)
    filas: dict[str, int] = {}
    omitidas: list[str] = []
    try:
        for tabla in TABLAS_A_MIGRAR:
            if not _tabla_existe_en_origen(origen, tabla):
                omitidas.append(tabla)
                continue
            copiadas = _copiar_tabla(origen, destino, tabla)
            esperadas = _contar_origen(origen, tabla)
            if copiadas != esperadas:
                raise MigracionIncompleta(f"{tabla}: se copiaron {copiadas} de {esperadas} filas.")
            filas[tabla] = copiadas
        destino.commit()
    except BaseException:
        destino.rollback()
        raise
    return ResultadoMigracion(filas=filas, omitidas=omitidas)
