from dataclasses import dataclass
from datetime import datetime

import oracledb

from cloudcr_backup.domain.alertas import Condicion
from cloudcr_backup.domain.enums import EstadoAlerta

LARGO_MAXIMO_MENSAJE = 2000
ESTADOS_VIGENTES_SQL = "('ABIERTA', 'RECONOCIDA')"
LIMITE_LISTADO_POR_DEFECTO = 200


@dataclass(frozen=True)
class Alerta:
    id: int
    codigo: str
    clave_dedup: str
    estado: EstadoAlerta
    mensaje: str


@dataclass(frozen=True)
class AlertaDetallada:
    id: int
    codigo: str
    clave_dedup: str
    severidad: str
    estado: EstadoAlerta
    mensaje: str
    bd_id: int | None
    estrategia_id: int | None
    tarea_id: int | None
    ejecucion_id: int | None
    abierta_en: datetime | None
    resuelta_en: datetime | None
    bd_nombre: str | None = None
    estrategia_codigo: str | None = None
    tarea_codigo: str | None = None


_SELECT_DETALLADA = """
    SELECT a.id, a.codigo, a.clave_dedup, a.severidad, a.estado, a.mensaje, a.bd_id, a.estrategia_id, a.tarea_id,
           a.ejecucion_id, a.abierta_en, a.resuelta_en, b.nombre, e.codigo, t.codigo
    FROM alerta a
    LEFT JOIN bd_registrada b ON b.id = a.bd_id
    LEFT JOIN estrategia e ON e.id = a.estrategia_id
    LEFT JOIN tarea t ON t.id = a.tarea_id
"""


def _entero(valor: object) -> int | None:
    return None if valor is None else int(str(valor))


def _momento(valor: object) -> datetime | None:
    return valor if isinstance(valor, datetime) else None


def _texto(valor: object) -> str | None:
    return None if valor is None else str(valor)


def _detallada_desde_fila(fila: tuple[object, ...]) -> AlertaDetallada:
    (
        id_, codigo, clave_dedup, severidad, estado, mensaje, bd_id, estrategia_id, tarea_id, ejecucion_id,
        abierta_en, resuelta_en, bd_nombre, estrategia_codigo, tarea_codigo,
    ) = fila
    return AlertaDetallada(
        id=int(str(id_)),
        codigo=str(codigo),
        clave_dedup=str(clave_dedup),
        severidad=str(severidad),
        estado=EstadoAlerta(str(estado)),
        mensaje=str(mensaje),
        bd_id=_entero(bd_id),
        estrategia_id=_entero(estrategia_id),
        tarea_id=_entero(tarea_id),
        ejecucion_id=_entero(ejecucion_id),
        abierta_en=_momento(abierta_en),
        resuelta_en=_momento(resuelta_en),
        bd_nombre=_texto(bd_nombre),
        estrategia_codigo=_texto(estrategia_codigo),
        tarea_codigo=_texto(tarea_codigo),
    )


def obtener(conexion: oracledb.Connection, alerta_id: int) -> AlertaDetallada | None:
    cursor = conexion.cursor()
    try:
        cursor.execute(f"{_SELECT_DETALLADA} WHERE a.id = :id", id=alerta_id)
        fila = cursor.fetchone()
        return _detallada_desde_fila(fila) if fila is not None else None
    finally:
        cursor.close()


def abrir(conexion: oracledb.Connection, condicion: Condicion) -> tuple[AlertaDetallada, bool]:
    mensaje = condicion.mensaje[:LARGO_MAXIMO_MENSAJE]
    cursor = conexion.cursor()
    try:
        cursor.execute(
            f"""
            SELECT id FROM alerta WHERE clave_dedup = :clave_dedup AND estado IN {ESTADOS_VIGENTES_SQL}
            ORDER BY abierta_en DESC FETCH FIRST 1 ROWS ONLY
            """,
            clave_dedup=condicion.clave_dedup,
        )
        fila = cursor.fetchone()
        es_nueva = fila is None
        if fila is not None:
            alerta_id = int(fila[0])
            valores: dict[str, object] = {"mensaje": mensaje, "severidad": condicion.severidad.value, "id": alerta_id}
            asignaciones = "mensaje = :mensaje, severidad = :severidad"
            if condicion.ejecucion_id is not None:
                asignaciones += ", ejecucion_id = :ejecucion_id"
                valores["ejecucion_id"] = condicion.ejecucion_id
            cursor.execute(f"UPDATE alerta SET {asignaciones} WHERE id = :id", **valores)
        else:
            id_var = cursor.var(int)
            cursor.execute(
                """
                INSERT INTO alerta (codigo, clave_dedup, severidad, estado, mensaje, bd_id, estrategia_id, tarea_id,
                                    ejecucion_id, abierta_en)
                VALUES (:codigo, :clave_dedup, :severidad, 'ABIERTA', :mensaje, :bd_id, :estrategia_id, :tarea_id,
                        :ejecucion_id, SYS_EXTRACT_UTC(SYSTIMESTAMP))
                RETURNING id INTO :id
                """,
                codigo=condicion.codigo_regla,
                clave_dedup=condicion.clave_dedup,
                severidad=condicion.severidad.value,
                mensaje=mensaje,
                bd_id=condicion.bd_id,
                estrategia_id=condicion.estrategia_id,
                tarea_id=condicion.tarea_id,
                ejecucion_id=condicion.ejecucion_id,
                id=id_var,
            )
            alerta_id = int(id_var.getvalue()[0])
        conexion.commit()
    finally:
        cursor.close()
    alerta = obtener(conexion, alerta_id)
    assert alerta is not None
    return alerta, es_nueva


def vigentes(conexion: oracledb.Connection) -> list[AlertaDetallada]:
    cursor = conexion.cursor()
    try:
        cursor.execute(f"{_SELECT_DETALLADA} WHERE a.estado IN {ESTADOS_VIGENTES_SQL} ORDER BY a.abierta_en DESC")
        return [_detallada_desde_fila(fila) for fila in cursor.fetchall()]
    finally:
        cursor.close()


def listar(
    conexion: oracledb.Connection,
    estados: list[EstadoAlerta] | None = None,
    severidad: str | None = None,
    limite: int = LIMITE_LISTADO_POR_DEFECTO,
) -> list[AlertaDetallada]:
    condiciones: list[str] = []
    parametros: dict[str, object] = {"limite": limite}
    if estados:
        marcadores = ", ".join(f":estado{i}" for i in range(len(estados)))
        condiciones.append(f"a.estado IN ({marcadores})")
        parametros.update({f"estado{i}": estado.value for i, estado in enumerate(estados)})
    if severidad:
        condiciones.append("a.severidad = :severidad")
        parametros["severidad"] = severidad
    where = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""
    cursor = conexion.cursor()
    try:
        cursor.execute(
            f"{_SELECT_DETALLADA} {where} ORDER BY a.abierta_en DESC FETCH FIRST :limite ROWS ONLY", **parametros
        )
        return [_detallada_desde_fila(fila) for fila in cursor.fetchall()]
    finally:
        cursor.close()


def reconocer_abierta(conexion: oracledb.Connection, alerta_id: int) -> bool:
    cursor = conexion.cursor()
    try:
        cursor.execute("UPDATE alerta SET estado = 'RECONOCIDA' WHERE id = :id AND estado = 'ABIERTA'", id=alerta_id)
        conexion.commit()
        return cursor.rowcount == 1
    finally:
        cursor.close()


def resolver_vigente(conexion: oracledb.Connection, alerta_id: int) -> bool:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            f"""
            UPDATE alerta SET estado = 'RESUELTA', resuelta_en = SYS_EXTRACT_UTC(SYSTIMESTAMP)
            WHERE id = :id AND estado IN {ESTADOS_VIGENTES_SQL}
            """,
            id=alerta_id,
        )
        conexion.commit()
        return cursor.rowcount == 1
    finally:
        cursor.close()


def _desde_fila(fila: tuple[object, ...]) -> Alerta:
    id_, codigo, clave_dedup, estado, mensaje = fila
    assert isinstance(id_, int)
    return Alerta(
        id=id_,
        codigo=str(codigo),
        clave_dedup=str(clave_dedup),
        estado=EstadoAlerta(str(estado)),
        mensaje=str(mensaje),
    )


def upsert_abierta(conexion: oracledb.Connection, codigo: str, clave_dedup: str, mensaje: str) -> Alerta:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            "SELECT id FROM alerta WHERE clave_dedup = :clave_dedup AND estado = 'ABIERTA'",
            clave_dedup=clave_dedup,
        )
        fila = cursor.fetchone()
        if fila is not None:
            alerta_id = fila[0]
            cursor.execute("UPDATE alerta SET mensaje = :mensaje WHERE id = :id", mensaje=mensaje, id=alerta_id)
        else:
            id_var = cursor.var(int)
            cursor.execute(
                """
                INSERT INTO alerta (codigo, clave_dedup, severidad, mensaje)
                VALUES (:codigo, :clave_dedup, 'ADVERTENCIA', :mensaje)
                RETURNING id INTO :id
                """,
                codigo=codigo,
                clave_dedup=clave_dedup,
                mensaje=mensaje,
                id=id_var,
            )
            alerta_id = int(id_var.getvalue()[0])
        conexion.commit()
        cursor.execute(
            "SELECT id, codigo, clave_dedup, estado, mensaje FROM alerta WHERE id = :id", id=alerta_id
        )
        return _desde_fila(cursor.fetchone())
    finally:
        cursor.close()


def abiertas(conexion: oracledb.Connection, codigos: list[str] | None = None) -> list[Alerta]:
    cursor = conexion.cursor()
    try:
        if codigos:
            marcadores = ",".join(f":c{i}" for i in range(len(codigos)))
            parametros = {f"c{i}": codigo for i, codigo in enumerate(codigos)}
            cursor.execute(
                f"""
                SELECT id, codigo, clave_dedup, estado, mensaje FROM alerta
                WHERE estado = 'ABIERTA' AND codigo IN ({marcadores})
                ORDER BY abierta_en DESC
                """,
                **parametros,
            )
        else:
            cursor.execute(
                "SELECT id, codigo, clave_dedup, estado, mensaje FROM alerta WHERE estado = 'ABIERTA' "
                "ORDER BY abierta_en DESC"
            )
        return [_desde_fila(fila) for fila in cursor.fetchall()]
    finally:
        cursor.close()


def resolver(conexion: oracledb.Connection, alerta_id: int) -> None:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            "UPDATE alerta SET estado = 'RESUELTA', resuelta_en = SYS_EXTRACT_UTC(SYSTIMESTAMP) WHERE id = :id",
            id=alerta_id,
        )
        conexion.commit()
    finally:
        cursor.close()


def reconocer(conexion: oracledb.Connection, alerta_id: int) -> None:
    cursor = conexion.cursor()
    try:
        cursor.execute("UPDATE alerta SET estado = 'RECONOCIDA' WHERE id = :id", id=alerta_id)
        conexion.commit()
    finally:
        cursor.close()
