from dataclasses import dataclass

import oracledb

from cloudcr_backup.domain.enums import EstadoAlerta


@dataclass(frozen=True)
class Alerta:
    id: int
    codigo: str
    clave_dedup: str
    estado: EstadoAlerta
    mensaje: str


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
            "UPDATE alerta SET estado = 'RESUELTA', resuelta_en = SYSTIMESTAMP WHERE id = :id", id=alerta_id
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
