import hashlib
from dataclasses import dataclass
from datetime import datetime

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
    aprobado_por: str | None = None
    aprobado_en: datetime | None = None
    creado_en: datetime | None = None
    acepto_caida: bool = False
    motivo_rechazo: str | None = None


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


def aprobar(
    conexion: oracledb.Connection, script_id: int, aprobado_por: str, acepto_caida: bool = False
) -> ScriptRman:
    cursor = conexion.cursor()
    try:
        tarea_id, _ = _obtener_por_id(cursor, script_id)
        cursor.execute(
            """
            UPDATE script_rman SET estado = 'APROBADO', aprobado_por = :aprobado_por,
                   aprobado_en = SYS_EXTRACT_UTC(SYSTIMESTAMP), acepto_caida = :acepto_caida
            WHERE id = :id
            """,
            aprobado_por=aprobado_por,
            acepto_caida="S" if acepto_caida else "N",
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


def vigentes_por_tarea(conexion: oracledb.Connection) -> dict[int, ScriptRman]:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            """
            SELECT tarea_id, id, version, hash_sha256, estado, aprobado_por, aprobado_en, creado_en
            FROM script_rman WHERE estado = 'APROBADO'
            """
        )
        return {
            int(tarea_id): ScriptRman(
                id=int(id_),
                tarea_id=int(tarea_id),
                version=int(version),
                contenido="",
                hash_sha256=str(hash_sha256),
                estado=EstadoScript(str(estado)),
                aprobado_por=None if aprobado_por is None else str(aprobado_por),
                aprobado_en=aprobado_en if isinstance(aprobado_en, datetime) else None,
                creado_en=creado_en if isinstance(creado_en, datetime) else None,
            )
            for tarea_id, id_, version, hash_sha256, estado, aprobado_por, aprobado_en, creado_en in cursor.fetchall()
        }
    finally:
        cursor.close()


_COLUMNAS_COMPLETAS = """
    id, tarea_id, version, contenido, hash_sha256, estado, aprobado_por, aprobado_en, creado_en, acepto_caida,
    motivo_rechazo
"""


def _completo_desde_fila(fila: tuple[object, ...]) -> ScriptRman:
    (
        id_, tarea_id, version, contenido, hash_sha256, estado, aprobado_por, aprobado_en, creado_en, acepto_caida,
        motivo_rechazo,
    ) = fila
    return ScriptRman(
        id=int(str(id_)),
        tarea_id=int(str(tarea_id)),
        version=int(str(version)),
        contenido=str(contenido),
        hash_sha256=str(hash_sha256),
        estado=EstadoScript(str(estado)),
        aprobado_por=None if aprobado_por is None else str(aprobado_por),
        aprobado_en=aprobado_en if isinstance(aprobado_en, datetime) else None,
        creado_en=creado_en if isinstance(creado_en, datetime) else None,
        acepto_caida=acepto_caida == "S",
        motivo_rechazo=None if motivo_rechazo is None else str(motivo_rechazo),
    )


def obtener(conexion: oracledb.Connection, script_id: int) -> ScriptRman | None:
    cursor = conexion.cursor()
    try:
        cursor.execute(f"SELECT {_COLUMNAS_COMPLETAS} FROM script_rman WHERE id = :id", id=script_id)
        fila = cursor.fetchone()
        return _completo_desde_fila(fila) if fila is not None else None
    finally:
        cursor.close()


def listar(conexion: oracledb.Connection, tarea_id: int) -> list[ScriptRman]:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            f"SELECT {_COLUMNAS_COMPLETAS} FROM script_rman WHERE tarea_id = :tarea_id ORDER BY version DESC",
            tarea_id=tarea_id,
        )
        return [_completo_desde_fila(fila) for fila in cursor.fetchall()]
    finally:
        cursor.close()
