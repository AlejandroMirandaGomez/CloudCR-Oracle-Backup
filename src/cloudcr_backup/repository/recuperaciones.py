from datetime import datetime

from cloudcr_backup.domain.enums import EstadoScript
from cloudcr_backup.domain.recuperacion import Escenario, RegistroRecuperacion, ResultadoRecuperacion
from cloudcr_backup.repository.conexion import Conexion
from cloudcr_backup.repository.esquema import DDL_RECUPERACION, TABLA_RECUPERACION

LARGO_MAXIMO_MENSAJE = 4000
LARGO_MAXIMO_OBJETIVO = 400

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


def asegurar_tabla(conexion: Conexion) -> None:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = DATABASE() AND LOWER(table_name) = :tabla",
            tabla=TABLA_RECUPERACION.lower(),
        )
        fila = cursor.fetchone()
        if fila is not None and int(fila[0]) > 0:
            return
        cursor.execute(DDL_RECUPERACION)
    finally:
        cursor.close()


def registrar(
    conexion: Conexion,
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
        cursor.execute(
            """
            INSERT INTO recuperacion_procedimiento
              (bd_id, escenario, objetivo, ruta_script, contenido, hash_sha256, estado, generado_en)
            VALUES (:bd_id, :escenario, :objetivo, :ruta_script, :contenido, :hash_sha256, 'BORRADOR', :generado_en)
            """,
            bd_id=bd_id,
            escenario=escenario.value,
            objetivo=objetivo_guardado,
            ruta_script=ruta_script,
            contenido=contenido,
            hash_sha256=hash_sha256,
            generado_en=generado_en,
        )
        conexion.commit()
        return RegistroRecuperacion(
            id=cursor.lastrowid,
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


def obtener(conexion: Conexion, procedimiento_id: int) -> RegistroRecuperacion | None:
    cursor = conexion.cursor()
    try:
        cursor.execute(f"SELECT {_COLUMNAS} FROM recuperacion_procedimiento WHERE id = :id", id=procedimiento_id)
        fila = cursor.fetchone()
        return _desde_fila(fila) if fila is not None else None
    finally:
        cursor.close()


def borrador_sin_usar(
    conexion: Conexion, bd_id: int, escenario: Escenario, hash_sha256: str
) -> RegistroRecuperacion | None:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            f"""
            SELECT {_COLUMNAS} FROM recuperacion_procedimiento
            WHERE bd_id = :bd_id AND escenario = :escenario AND hash_sha256 = :hash_sha256
              AND estado = 'BORRADOR' AND resultado IS NULL
            ORDER BY id DESC LIMIT 1
            """,
            bd_id=bd_id,
            escenario=escenario.value,
            hash_sha256=hash_sha256,
        )
        fila = cursor.fetchone()
        return _desde_fila(fila) if fila is not None else None
    finally:
        cursor.close()


def aprobar(conexion: Conexion, procedimiento_id: int, aprobado_por: str) -> bool:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            """
            UPDATE recuperacion_procedimiento
            SET estado = 'APROBADO', aprobado_por = :aprobado_por, aprobado_en = UTC_TIMESTAMP(6)
            WHERE id = :id AND estado = 'BORRADOR'
            """,
            aprobado_por=aprobado_por,
            id=procedimiento_id,
        )
        conexion.commit()
        return bool(cursor.rowcount == 1)
    finally:
        cursor.close()


def marcar_en_curso(conexion: Conexion, procedimiento_id: int, ruta_log: str) -> bool:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            """
            UPDATE recuperacion_procedimiento
            SET resultado = 'EN_CURSO', ejecutado_en = UTC_TIMESTAMP(6), ruta_log = :ruta_log
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
    conexion: Conexion, procedimiento_id: int, resultado: ResultadoRecuperacion, mensaje: str
) -> None:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            """
            UPDATE recuperacion_procedimiento
            SET resultado = :resultado, mensaje = :mensaje, finalizado_en = UTC_TIMESTAMP(6)
            WHERE id = :id
            """,
            resultado=resultado.value,
            mensaje=recortar(mensaje, LARGO_MAXIMO_MENSAJE),
            id=procedimiento_id,
        )
        conexion.commit()
    finally:
        cursor.close()
