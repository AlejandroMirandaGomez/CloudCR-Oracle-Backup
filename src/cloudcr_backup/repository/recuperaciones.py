from datetime import datetime

import oracledb

from cloudcr_backup.domain.enums import EstadoScript
from cloudcr_backup.domain.recuperacion import Escenario, RegistroRecuperacion, ResultadoRecuperacion
from cloudcr_backup.repository.esquema import DDL_RECUPERACION, TABLA_RECUPERACION

LARGO_MAXIMO_MENSAJE = 4000
LARGO_MAXIMO_OBJETIVO = 400
_ORA_NOMBRE_EN_USO = 955

_COLUMNAS = """
    id, bd_id, escenario, objetivo, ruta_script, contenido, hash_sha256, estado, generado_en, aprobado_por,
    aprobado_en, ejecutado_en, finalizado_en, resultado, ruta_log, mensaje
"""


def recortar(texto: str, limite_bytes: int) -> str:
    return texto.encode("utf-8")[:limite_bytes].decode("utf-8", errors="ignore")


def _texto(valor: object) -> str | None:
    return None if valor is None else str(valor)


def _momento(valor: object) -> datetime | None:
    return valor if isinstance(valor, datetime) else None


def _desde_fila(fila: tuple[object, ...]) -> RegistroRecuperacion:
    (
        id_,
        bd_id,
        escenario,
        objetivo,
        ruta_script,
        contenido,
        hash_sha256,
        estado,
        generado_en,
        aprobado_por,
        aprobado_en,
        ejecutado_en,
        finalizado_en,
        resultado,
        ruta_log,
        mensaje,
    ) = fila
    return RegistroRecuperacion(
        id=int(str(id_)),
        bd_id=int(str(bd_id)),
        escenario=Escenario(str(escenario)),
        objetivo=_texto(objetivo),
        ruta_script=str(ruta_script),
        contenido=str(contenido),
        hash_sha256=str(hash_sha256),
        estado=EstadoScript(str(estado)),
        generado_en=_momento(generado_en),
        aprobado_por=_texto(aprobado_por),
        aprobado_en=_momento(aprobado_en),
        ejecutado_en=_momento(ejecutado_en),
        finalizado_en=_momento(finalizado_en),
        resultado=None if resultado is None else ResultadoRecuperacion(str(resultado)),
        ruta_log=_texto(ruta_log),
        mensaje=_texto(mensaje),
    )


def asegurar_tabla(conexion: oracledb.Connection) -> None:
    cursor = conexion.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM user_tables WHERE table_name = :tabla", tabla=TABLA_RECUPERACION)
        fila = cursor.fetchone()
        if fila is not None and int(fila[0]) > 0:
            return
        try:
            cursor.execute(DDL_RECUPERACION)
        except oracledb.Error as error:
            detalle = error.args[0] if error.args else None
            if getattr(detalle, "code", None) != _ORA_NOMBRE_EN_USO:
                raise
    finally:
        cursor.close()


def registrar(
    conexion: oracledb.Connection,
    bd_id: int,
    escenario: Escenario,
    objetivo: str | None,
    ruta_script: str,
    contenido: str,
    hash_sha256: str,
    generado_en: datetime,
) -> RegistroRecuperacion:
    objetivo_guardado = None if objetivo is None else recortar(objetivo, LARGO_MAXIMO_OBJETIVO)
    cursor = conexion.cursor()
    try:
        id_var = cursor.var(int)
        cursor.execute(
            """
            INSERT INTO recuperacion_procedimiento
              (bd_id, escenario, objetivo, ruta_script, contenido, hash_sha256, estado, generado_en)
            VALUES (:bd_id, :escenario, :objetivo, :ruta_script, :contenido, :hash_sha256, 'BORRADOR', :generado_en)
            RETURNING id INTO :id
            """,
            bd_id=bd_id,
            escenario=escenario.value,
            objetivo=objetivo_guardado,
            ruta_script=ruta_script,
            contenido=contenido,
            hash_sha256=hash_sha256,
            generado_en=generado_en,
            id=id_var,
        )
        conexion.commit()
        return RegistroRecuperacion(
            id=int(id_var.getvalue()[0]),
            bd_id=bd_id,
            escenario=escenario,
            objetivo=objetivo_guardado,
            ruta_script=ruta_script,
            contenido=contenido,
            hash_sha256=hash_sha256,
            estado=EstadoScript.BORRADOR,
            generado_en=generado_en,
        )
    finally:
        cursor.close()


def obtener(conexion: oracledb.Connection, procedimiento_id: int) -> RegistroRecuperacion | None:
    cursor = conexion.cursor()
    try:
        cursor.execute(f"SELECT {_COLUMNAS} FROM recuperacion_procedimiento WHERE id = :id", id=procedimiento_id)
        fila = cursor.fetchone()
        return _desde_fila(fila) if fila is not None else None
    finally:
        cursor.close()


def borrador_sin_usar(
    conexion: oracledb.Connection, bd_id: int, escenario: Escenario, hash_sha256: str
) -> RegistroRecuperacion | None:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            f"""
            SELECT {_COLUMNAS} FROM recuperacion_procedimiento
            WHERE bd_id = :bd_id AND escenario = :escenario AND hash_sha256 = :hash_sha256
              AND estado = 'BORRADOR' AND resultado IS NULL
            ORDER BY id DESC FETCH FIRST 1 ROWS ONLY
            """,
            bd_id=bd_id,
            escenario=escenario.value,
            hash_sha256=hash_sha256,
        )
        fila = cursor.fetchone()
        return _desde_fila(fila) if fila is not None else None
    finally:
        cursor.close()


def aprobar(conexion: oracledb.Connection, procedimiento_id: int, aprobado_por: str) -> bool:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            """
            UPDATE recuperacion_procedimiento
            SET estado = 'APROBADO', aprobado_por = :aprobado_por, aprobado_en = SYS_EXTRACT_UTC(SYSTIMESTAMP)
            WHERE id = :id AND estado = 'BORRADOR'
            """,
            aprobado_por=aprobado_por,
            id=procedimiento_id,
        )
        conexion.commit()
        return bool(cursor.rowcount == 1)
    finally:
        cursor.close()


def marcar_en_curso(conexion: oracledb.Connection, procedimiento_id: int, ruta_log: str) -> bool:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            """
            UPDATE recuperacion_procedimiento
            SET resultado = 'EN_CURSO', ejecutado_en = SYS_EXTRACT_UTC(SYSTIMESTAMP), ruta_log = :ruta_log
            WHERE id = :id AND estado = 'APROBADO' AND resultado IS NULL
            """,
            ruta_log=ruta_log,
            id=procedimiento_id,
        )
        conexion.commit()
        return bool(cursor.rowcount == 1)
    finally:
        cursor.close()


def registrar_resultado(
    conexion: oracledb.Connection, procedimiento_id: int, resultado: ResultadoRecuperacion, mensaje: str
) -> None:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            """
            UPDATE recuperacion_procedimiento
            SET resultado = :resultado, mensaje = :mensaje, finalizado_en = SYS_EXTRACT_UTC(SYSTIMESTAMP)
            WHERE id = :id
            """,
            resultado=resultado.value,
            mensaje=recortar(mensaje, LARGO_MAXIMO_MENSAJE),
            id=procedimiento_id,
        )
        conexion.commit()
    finally:
        cursor.close()
