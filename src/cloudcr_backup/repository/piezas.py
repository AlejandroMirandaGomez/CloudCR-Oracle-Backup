from dataclasses import dataclass
from datetime import datetime

import oracledb

from cloudcr_backup.domain.enums import EstadoPrueba

LARGO_MAXIMO_NOMBRE = 400
LARGO_MAXIMO_TAG = 30


@dataclass(frozen=True)
class PiezaNueva:
    nombre_archivo: str
    tamano_bytes: int | None
    tag: str | None
    vence_en: datetime | None


@dataclass(frozen=True)
class VerificacionNueva:
    tipo_prueba: str
    resultado: EstadoPrueba
    detalle: str | None


@dataclass(frozen=True)
class PiezaRegistrada:
    id: int
    ejecucion_id: int
    nombre_archivo: str
    tamano_bytes: int | None
    tag: str | None
    vence_en: datetime | None
    obsoleta: bool
    estrategia_id: int
    estrategia_codigo: str
    tarea_codigo: str
    fin: datetime | None


def reemplazar(conexion: oracledb.Connection, ejecucion_id: int, piezas: list[PiezaNueva]) -> None:
    cursor = conexion.cursor()
    try:
        cursor.execute("DELETE FROM ejecucion_pieza WHERE ejecucion_id = :ejecucion_id", ejecucion_id=ejecucion_id)
        for pieza in piezas:
            cursor.execute(
                """
                INSERT INTO ejecucion_pieza (ejecucion_id, nombre_archivo, tamano_bytes, tag, vence_en)
                VALUES (:ejecucion_id, :nombre_archivo, :tamano_bytes, :tag, :vence_en)
                """,
                ejecucion_id=ejecucion_id,
                nombre_archivo=pieza.nombre_archivo[:LARGO_MAXIMO_NOMBRE],
                tamano_bytes=pieza.tamano_bytes,
                tag=pieza.tag[:LARGO_MAXIMO_TAG] if pieza.tag else None,
                vence_en=pieza.vence_en,
            )
        conexion.commit()
    finally:
        cursor.close()


def reemplazar_verificaciones(
    conexion: oracledb.Connection, ejecucion_id: int, verificaciones: list[VerificacionNueva]
) -> None:
    cursor = conexion.cursor()
    try:
        cursor.execute("DELETE FROM verificacion WHERE ejecucion_id = :ejecucion_id", ejecucion_id=ejecucion_id)
        for verificacion in verificaciones:
            cursor.execute(
                """
                INSERT INTO verificacion (ejecucion_id, tipo_prueba, resultado, detalle, ejecutada_en)
                VALUES (:ejecucion_id, :tipo_prueba, :resultado, :detalle, SYS_EXTRACT_UTC(SYSTIMESTAMP))
                """,
                ejecucion_id=ejecucion_id,
                tipo_prueba=verificacion.tipo_prueba[:30],
                resultado=verificacion.resultado.value,
                detalle=verificacion.detalle,
            )
        conexion.commit()
    finally:
        cursor.close()


def de_base(conexion: oracledb.Connection, bd_id: int) -> list[PiezaRegistrada]:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            """
            SELECT pz.id, pz.ejecucion_id, pz.nombre_archivo, pz.tamano_bytes, pz.tag, pz.vence_en, pz.obsoleta,
                   es.id, es.codigo, t.codigo, ej.fin
            FROM ejecucion_pieza pz
            JOIN ejecucion ej ON ej.id = pz.ejecucion_id
            JOIN tarea t ON t.id = ej.tarea_id
            JOIN estrategia es ON es.id = t.estrategia_id
            WHERE ej.bd_id = :bd_id
            ORDER BY ej.fin DESC NULLS LAST, pz.id
            """,
            bd_id=bd_id,
        )
        return [
            PiezaRegistrada(
                id=int(id_),
                ejecucion_id=int(ejecucion_id),
                nombre_archivo=str(nombre),
                tamano_bytes=None if tamano is None else int(tamano),
                tag=None if tag is None else str(tag),
                vence_en=vence_en if isinstance(vence_en, datetime) else None,
                obsoleta=obsoleta == "S",
                estrategia_id=int(estrategia_id),
                estrategia_codigo=str(estrategia_codigo),
                tarea_codigo=str(tarea_codigo),
                fin=fin if isinstance(fin, datetime) else None,
            )
            for (
                id_, ejecucion_id, nombre, tamano, tag, vence_en, obsoleta, estrategia_id, estrategia_codigo,
                tarea_codigo, fin,
            ) in cursor.fetchall()
        ]
    finally:
        cursor.close()


def marcar_obsoletas(conexion: oracledb.Connection, ids: list[int]) -> int:
    if not ids:
        return 0
    cursor = conexion.cursor()
    try:
        marcadas = 0
        for pieza_id in ids:
            cursor.execute("UPDATE ejecucion_pieza SET obsoleta = 'S' WHERE id = :id", id=pieza_id)
            marcadas += cursor.rowcount
        conexion.commit()
        return marcadas
    finally:
        cursor.close()
