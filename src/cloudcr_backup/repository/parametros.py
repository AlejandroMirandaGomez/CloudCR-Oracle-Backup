import oracledb


def obtener(conexion: oracledb.Connection, clave: str) -> str | None:
    cursor = conexion.cursor()
    try:
        cursor.execute("SELECT valor FROM parametro WHERE clave = :clave", clave=clave)
        fila = cursor.fetchone()
        return str(fila[0]) if fila is not None else None
    finally:
        cursor.close()


def listar(conexion: oracledb.Connection) -> dict[str, str]:
    cursor = conexion.cursor()
    try:
        cursor.execute("SELECT clave, valor FROM parametro ORDER BY clave")
        return {clave: valor for clave, valor in cursor.fetchall()}
    finally:
        cursor.close()


def asignar(conexion: oracledb.Connection, clave: str, valor: str) -> None:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            """
            MERGE INTO parametro p USING (SELECT :clave AS clave FROM dual) d
              ON (p.clave = d.clave)
            WHEN MATCHED THEN UPDATE SET p.valor = :valor
            WHEN NOT MATCHED THEN INSERT (clave, valor) VALUES (:clave, :valor)
            """,
            clave=clave,
            valor=valor,
        )
        conexion.commit()
    finally:
        cursor.close()
