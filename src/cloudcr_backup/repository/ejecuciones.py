from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

import oracledb

from cloudcr_backup.domain.enums import EstadoEjecucion

_COLUMNAS_RESULTADO = {
    "estado",
    "fin",
    "ubicacion",
    "archivos_generados",
    "tamano_bytes",
    "duracion_segundos",
    "mensaje_rman",
    "errores",
    "advertencias",
    "estado_prueba",
}


@dataclass(frozen=True)
class FiltrosHistorial:
    bd_id: int | None = None
    estrategia_codigo: str | None = None
    estado: EstadoEjecucion | None = None
    desde: datetime | None = None
    hasta: datetime | None = None


@dataclass(frozen=True)
class Ejecucion:
    id: int
    tarea_id: int
    script_id: int
    estado: EstadoEjecucion
    programada_para: datetime
    inicio: datetime | None
    fin: datetime | None


def _desde_fila(fila: tuple[object, ...]) -> Ejecucion:
    id_, tarea_id, script_id, estado, programada_para, inicio, fin = fila
    assert isinstance(id_, int)
    assert isinstance(tarea_id, int)
    assert isinstance(script_id, int)
    assert isinstance(programada_para, datetime)
    assert inicio is None or isinstance(inicio, datetime)
    assert fin is None or isinstance(fin, datetime)
    return Ejecucion(
        id=id_,
        tarea_id=tarea_id,
        script_id=script_id,
        estado=EstadoEjecucion(str(estado)),
        programada_para=programada_para,
        inicio=inicio,
        fin=fin,
    )


def _normalizar(valor: object) -> object:
    return valor.value if isinstance(valor, StrEnum) else valor


def reclamar(conexion: oracledb.Connection, tarea_id: int, programada_para: datetime) -> Ejecucion | None:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            """
            SELECT e.bd_id, t.tipo_respaldo,
                   (SELECT id FROM script_rman WHERE tarea_id = t.id AND estado = 'APROBADO')
            FROM tarea t JOIN estrategia e ON e.id = t.estrategia_id
            WHERE t.id = :tarea_id
            """,
            tarea_id=tarea_id,
        )
        fila = cursor.fetchone()
        if fila is None:
            raise ValueError(f"No existe la tarea {tarea_id}.")
        bd_id, tipo_respaldo, script_id = fila
        if script_id is None:
            raise ValueError(f"La tarea {tarea_id} no tiene un script aprobado.")
        id_var = cursor.var(int)
        try:
            cursor.execute(
                """
                INSERT INTO ejecucion (tarea_id, script_id, bd_id, programada_para, estado, tipo_respaldo)
                VALUES (:tarea_id, :script_id, :bd_id, :programada_para, 'PROGRAMADA', :tipo_respaldo)
                RETURNING id INTO :id
                """,
                tarea_id=tarea_id,
                script_id=script_id,
                bd_id=bd_id,
                programada_para=programada_para,
                tipo_respaldo=tipo_respaldo,
                id=id_var,
            )
        except oracledb.IntegrityError:
            conexion.rollback()
            return None
        conexion.commit()
        return Ejecucion(
            id=int(id_var.getvalue()[0]),
            tarea_id=tarea_id,
            script_id=int(script_id),
            estado=EstadoEjecucion.PROGRAMADA,
            programada_para=programada_para,
            inicio=None,
            fin=None,
        )
    finally:
        cursor.close()


def marcar_en_curso(conexion: oracledb.Connection, ejecucion_id: int, agente: str) -> None:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            "UPDATE ejecucion SET estado = 'EN_CURSO', inicio = SYSTIMESTAMP, agente = :agente WHERE id = :id",
            agente=agente,
            id=ejecucion_id,
        )
        conexion.commit()
    finally:
        cursor.close()


def registrar_resultado(conexion: oracledb.Connection, ejecucion_id: int, resultado: dict[str, object]) -> None:
    columnas = [c for c in resultado if c in _COLUMNAS_RESULTADO]
    if not columnas:
        return
    asignaciones = ", ".join(f"{c} = :{c}" for c in columnas)
    valores = {c: _normalizar(resultado[c]) for c in columnas}
    valores["id"] = ejecucion_id
    cursor = conexion.cursor()
    try:
        cursor.execute(f"UPDATE ejecucion SET {asignaciones} WHERE id = :id", **valores)
        conexion.commit()
    finally:
        cursor.close()


def historial(conexion: oracledb.Connection, filtros: FiltrosHistorial) -> list[Ejecucion]:
    condiciones = []
    parametros: dict[str, object] = {}
    if filtros.bd_id is not None:
        condiciones.append("ej.bd_id = :bd_id")
        parametros["bd_id"] = filtros.bd_id
    if filtros.estrategia_codigo is not None:
        condiciones.append("es.codigo = :estrategia_codigo")
        parametros["estrategia_codigo"] = filtros.estrategia_codigo
    if filtros.estado is not None:
        condiciones.append("ej.estado = :estado")
        parametros["estado"] = filtros.estado.value
    if filtros.desde is not None:
        condiciones.append("ej.programada_para >= :desde")
        parametros["desde"] = filtros.desde
    if filtros.hasta is not None:
        condiciones.append("ej.programada_para <= :hasta")
        parametros["hasta"] = filtros.hasta
    where = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""
    sql = f"""
        SELECT ej.id, ej.tarea_id, ej.script_id, ej.estado, ej.programada_para, ej.inicio, ej.fin
        FROM ejecucion ej
        JOIN tarea t ON t.id = ej.tarea_id
        JOIN estrategia es ON es.id = t.estrategia_id
        {where}
        ORDER BY ej.programada_para DESC
    """
    cursor = conexion.cursor()
    try:
        cursor.execute(sql, **parametros)
        return [_desde_fila(fila) for fila in cursor.fetchall()]
    finally:
        cursor.close()


def ultimas(conexion: oracledb.Connection, tarea_id: int, n: int) -> list[Ejecucion]:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            """
            SELECT id, tarea_id, script_id, estado, programada_para, inicio, fin FROM (
                SELECT id, tarea_id, script_id, estado, programada_para, inicio, fin
                FROM ejecucion WHERE tarea_id = :tarea_id ORDER BY programada_para DESC
            ) WHERE ROWNUM <= :n
            """,
            tarea_id=tarea_id,
            n=n,
        )
        return [_desde_fila(fila) for fila in cursor.fetchall()]
    finally:
        cursor.close()
