from dataclasses import dataclass
from enum import StrEnum

import oracledb

from cloudcr_backup.domain.perfil_bd import PerfilBD


class Ambiente(StrEnum):
    PRODUCCION = "PRODUCCION"
    PRUEBAS = "PRUEBAS"
    DESARROLLO = "DESARROLLO"


class BaseDatosYaRegistrada(ValueError):
    pass


@dataclass(frozen=True)
class BaseDatosRegistrada:
    id: int
    nombre: str
    oracle_home: str
    ambiente: Ambiente
    activa: bool


def _desde_fila(fila: tuple[int, str, str, str, str]) -> BaseDatosRegistrada:
    id_, nombre, oracle_home, ambiente, activa = fila
    return BaseDatosRegistrada(
        id=id_, nombre=nombre, oracle_home=oracle_home, ambiente=Ambiente(ambiente), activa=activa == "S"
    )


def registrar(
    conexion: oracledb.Connection, nombre: str, oracle_home: str, ambiente: Ambiente
) -> BaseDatosRegistrada:
    cursor = conexion.cursor()
    try:
        id_var = cursor.var(int)
        try:
            cursor.execute(
                """
                INSERT INTO bd_registrada (nombre, oracle_home, ambiente)
                VALUES (:nombre, :oracle_home, :ambiente)
                RETURNING id INTO :id
                """,
                nombre=nombre,
                oracle_home=oracle_home,
                ambiente=ambiente.value,
                id=id_var,
            )
        except oracledb.IntegrityError as error:
            raise BaseDatosYaRegistrada(f"Ya existe una base de datos registrada con el nombre {nombre}.") from error
        conexion.commit()
        return BaseDatosRegistrada(id=int(id_var.getvalue()[0]), nombre=nombre, oracle_home=oracle_home,
                                    ambiente=ambiente, activa=True)
    finally:
        cursor.close()


def listar(conexion: oracledb.Connection) -> list[BaseDatosRegistrada]:
    cursor = conexion.cursor()
    try:
        cursor.execute("SELECT id, nombre, oracle_home, ambiente, activa FROM bd_registrada ORDER BY nombre")
        return [_desde_fila(fila) for fila in cursor.fetchall()]
    finally:
        cursor.close()


def obtener(conexion: oracledb.Connection, nombre: str) -> BaseDatosRegistrada | None:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            "SELECT id, nombre, oracle_home, ambiente, activa FROM bd_registrada WHERE nombre = :nombre",
            nombre=nombre,
        )
        fila = cursor.fetchone()
        return _desde_fila(fila) if fila is not None else None
    finally:
        cursor.close()


def desactivar(conexion: oracledb.Connection, nombre: str) -> None:
    cursor = conexion.cursor()
    try:
        cursor.execute("UPDATE bd_registrada SET activa = 'N' WHERE nombre = :nombre", nombre=nombre)
        conexion.commit()
    finally:
        cursor.close()


def guardar_perfil(conexion: oracledb.Connection, bd_id: int, perfil: PerfilBD) -> None:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO perfil_bd (bd_id, log_mode, contenido_json)
            VALUES (:bd_id, :log_mode, :contenido_json)
            """,
            bd_id=bd_id,
            log_mode=perfil.log_mode.value,
            contenido_json=perfil.model_dump_json(),
        )
        conexion.commit()
    finally:
        cursor.close()
