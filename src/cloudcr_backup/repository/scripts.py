import hashlib
from dataclasses import dataclass

import oracledb

from cloudcr_backup.domain.enums import EstadoScript


@dataclass(frozen=True)
class ScriptRman:
    id: int
    tarea_id: int
    version: int
    contenido: str
    hash_sha256: str
    estado: EstadoScript


def _desde_fila(tarea_id: int, fila: tuple[object, ...]) -> ScriptRman:
    id_, version, contenido, hash_sha256, estado = fila
    assert isinstance(id_, int)
    assert isinstance(version, int)
    return ScriptRman(
        id=id_,
        tarea_id=tarea_id,
        version=version,
        contenido=str(contenido),
        hash_sha256=str(hash_sha256),
        estado=EstadoScript(str(estado)),
    )


def _siguiente_version(cursor: oracledb.Cursor, tarea_id: int) -> int:
    cursor.execute("SELECT MAX(version) FROM script_rman WHERE tarea_id = :tarea_id", tarea_id=tarea_id)
    fila = cursor.fetchone()
    maximo = fila[0] if fila is not None else None
    return int(maximo) + 1 if maximo is not None else 1


def guardar_borrador(conexion: oracledb.Connection, tarea_id: int, contenido: str) -> ScriptRman:
    cursor = conexion.cursor()
    try:
        version = _siguiente_version(cursor, tarea_id)
        hash_sha256 = hashlib.sha256(contenido.encode("utf-8")).hexdigest()
        id_var = cursor.var(int)
        cursor.execute(
            """
            INSERT INTO script_rman (tarea_id, version, contenido, hash_sha256, estado)
            VALUES (:tarea_id, :version, :contenido, :hash_sha256, 'BORRADOR')
            RETURNING id INTO :id
            """,
            tarea_id=tarea_id,
            version=version,
            contenido=contenido,
            hash_sha256=hash_sha256,
            id=id_var,
        )
        conexion.commit()
        return ScriptRman(
            id=int(id_var.getvalue()[0]),
            tarea_id=tarea_id,
            version=version,
            contenido=contenido,
            hash_sha256=hash_sha256,
            estado=EstadoScript.BORRADOR,
        )
    finally:
        cursor.close()


def obtener_vigente(conexion: oracledb.Connection, tarea_id: int) -> ScriptRman | None:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            """
            SELECT id, version, contenido, hash_sha256, estado FROM script_rman
            WHERE tarea_id = :tarea_id AND estado = 'APROBADO'
            """,
            tarea_id=tarea_id,
        )
        fila = cursor.fetchone()
        return _desde_fila(tarea_id, fila) if fila is not None else None
    finally:
        cursor.close()


def _obtener_por_id(cursor: oracledb.Cursor, script_id: int) -> tuple[int, tuple[object, ...]]:
    cursor.execute(
        "SELECT tarea_id, id, version, contenido, hash_sha256, estado FROM script_rman WHERE id = :id",
        id=script_id,
    )
    fila = cursor.fetchone()
    if fila is None:
        raise ValueError(f"No existe el script {script_id}.")
    tarea_id, *resto = fila
    assert isinstance(tarea_id, int)
    return tarea_id, tuple(resto)


def aprobar(conexion: oracledb.Connection, script_id: int, aprobado_por: str) -> ScriptRman:
    cursor = conexion.cursor()
    try:
        tarea_id, _ = _obtener_por_id(cursor, script_id)
        cursor.execute(
            """
            UPDATE script_rman SET estado = 'APROBADO', aprobado_por = :aprobado_por, aprobado_en = SYSTIMESTAMP
            WHERE id = :id
            """,
            aprobado_por=aprobado_por,
            id=script_id,
        )
        conexion.commit()
        _, fila = _obtener_por_id(cursor, script_id)
        return _desde_fila(tarea_id, fila)
    finally:
        cursor.close()


def rechazar(conexion: oracledb.Connection, script_id: int, motivo: str) -> ScriptRman:
    cursor = conexion.cursor()
    try:
        tarea_id, _ = _obtener_por_id(cursor, script_id)
        cursor.execute(
            "UPDATE script_rman SET estado = 'RECHAZADO', motivo_rechazo = :motivo WHERE id = :id",
            motivo=motivo,
            id=script_id,
        )
        conexion.commit()
        _, fila = _obtener_por_id(cursor, script_id)
        return _desde_fila(tarea_id, fila)
    finally:
        cursor.close()


def marcar_obsoleto(conexion: oracledb.Connection, script_id: int) -> None:
    cursor = conexion.cursor()
    try:
        cursor.execute("UPDATE script_rman SET estado = 'OBSOLETO' WHERE id = :id", id=script_id)
        conexion.commit()
    finally:
        cursor.close()
