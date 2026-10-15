from cloudcr_backup.repository.conexion import Conexion


def obtener(conexion: Conexion, clave: str) -> str | None:
    cursor = conexion.cursor()
    try:
        cursor.execute("SELECT valor FROM parametro WHERE clave = :clave", clave=clave)
        fila = cursor.fetchone()
        return str(fila[0]) if fila is not None else None
    finally:
        cursor.close()


def listar(conexion: Conexion) -> dict[str, str]:
    cursor = conexion.cursor()
    try:
        cursor.execute("SELECT clave, valor FROM parametro ORDER BY clave")
        return {clave: valor for clave, valor in cursor.fetchall()}
    finally:
        cursor.close()


def asignar(conexion: Conexion, clave: str, valor: str) -> None:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO parametro (clave, valor) VALUES (:clave, :valor) AS nuevo
            ON DUPLICATE KEY UPDATE valor = nuevo.valor
            """,
            clave=clave,
            valor=valor,
        )
        conexion.commit()
    finally:
        cursor.close()
