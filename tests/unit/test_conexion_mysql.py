from typing import Any

import pymysql
import pytest

from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.repository import conexion as repositorio_conexion
from cloudcr_backup.repository.conexion import (
    ConexionMySql,
    CursorMySql,
    ErrorConexionRepositorio,
    ParametrosMySql,
    RepositorioNoConfigurado,
    abrir_repositorio,
    conectar,
    parametros_repositorio,
    traducir_binds,
)


class CursorPyMySqlFalso:
    def __init__(self) -> None:
        self.llamadas: list[tuple[str, Any]] = []
        self.rowcount = 3
        self.lastrowid: int | None = 41
        self.cerrado = False

    def execute(self, sql: str, args: Any = None) -> None:
        self.llamadas.append((sql, args))

    def fetchone(self) -> tuple[int, ...]:
        return (1,)

    def fetchall(self) -> tuple[tuple[int, ...], ...]:
        return ((1,), (2,))

    def close(self) -> None:
        self.cerrado = True


class ConexionPyMySqlFalsa:
    def __init__(self) -> None:
        self.cursor_falso = CursorPyMySqlFalso()
        self.eventos: list[str] = []

    def cursor(self) -> CursorPyMySqlFalso:
        return self.cursor_falso

    def commit(self) -> None:
        self.eventos.append("commit")

    def rollback(self) -> None:
        self.eventos.append("rollback")

    def close(self) -> None:
        self.eventos.append("close")


PARAMETROS = ParametrosMySql(host="localhost", puerto=3306, base="cloudcr", usuario="cloudcr", clave="secreta")


def test_los_binds_con_nombre_pasan_al_formato_de_pymysql() -> None:
    sql = "SELECT * FROM t WHERE a = :a AND b = :b_2"
    assert traducir_binds(sql) == "SELECT * FROM t WHERE a = %(a)s AND b = %(b_2)s"


def test_los_dos_puntos_dentro_de_literales_no_son_binds() -> None:
    assert traducir_binds("SELECT ':x', 'a:b' FROM t WHERE c = :c") == "SELECT ':x', 'a:b' FROM t WHERE c = %(c)s"


def test_los_porcentajes_se_duplican_dentro_y_fuera_de_literales() -> None:
    sql = "SELECT * FROM t WHERE f LIKE '%x%' AND y = :y AND z % 2 = 0"
    assert traducir_binds(sql) == "SELECT * FROM t WHERE f LIKE '%%x%%' AND y = %(y)s AND z %% 2 = 0"


def test_las_comillas_escapadas_no_cortan_el_literal() -> None:
    assert traducir_binds("SELECT 'it''s :no' FROM t WHERE a = :a") == "SELECT 'it''s :no' FROM t WHERE a = %(a)s"


def test_el_cursor_traduce_el_sql_y_envia_los_parametros_como_diccionario() -> None:
    crudo = CursorPyMySqlFalso()
    cursor = CursorMySql(crudo)  # type: ignore[arg-type]
    cursor.execute("UPDATE t SET a = :a WHERE id = :id", a="x", id=4)
    assert crudo.llamadas == [("UPDATE t SET a = %(a)s WHERE id = %(id)s", {"a": "x", "id": 4})]
    cursor.execute("SELECT 1 WHERE 'a' LIKE '%'")
    assert crudo.llamadas[1] == ("SELECT 1 WHERE 'a' LIKE '%%'", {})


def test_el_cursor_expone_filas_afectadas_ultimo_id_y_resultados() -> None:
    crudo = CursorPyMySqlFalso()
    cursor = CursorMySql(crudo)  # type: ignore[arg-type]
    assert cursor.rowcount == 3
    assert cursor.lastrowid == 41
    crudo.lastrowid = None
    assert cursor.lastrowid == 0
    assert cursor.fetchone() == (1,)
    assert cursor.fetchall() == [(1,), (2,)]
    cursor.close()
    assert crudo.cerrado


def test_la_conexion_delega_commit_rollback_y_cierre() -> None:
    crudo = ConexionPyMySqlFalsa()
    conexion = ConexionMySql(crudo)  # type: ignore[arg-type]
    assert isinstance(conexion.cursor(), CursorMySql)
    conexion.commit()
    conexion.rollback()
    conexion.close()
    assert crudo.eventos == ["commit", "rollback", "close"]


def test_conectar_usa_utf8mb4_lecturas_confirmadas_y_filas_encontradas(monkeypatch: pytest.MonkeyPatch) -> None:
    recibido: dict[str, Any] = {}

    def conectar_falso(**argumentos: Any) -> ConexionPyMySqlFalsa:
        recibido.update(argumentos)
        return ConexionPyMySqlFalsa()

    monkeypatch.setattr(repositorio_conexion.pymysql, "connect", conectar_falso)
    assert isinstance(conectar(PARAMETROS), ConexionMySql)
    assert recibido["host"] == "localhost" and recibido["port"] == 3306
    assert recibido["user"] == "cloudcr" and recibido["password"] == "secreta"
    assert recibido["database"] == "cloudcr" and recibido["charset"] == "utf8mb4"
    assert recibido["autocommit"] is False
    assert recibido["client_flag"] & pymysql.constants.CLIENT.FOUND_ROWS
    assert "READ COMMITTED" in recibido["init_command"]


@pytest.mark.parametrize(
    ("codigo", "fragmento_mensaje", "fragmento_sugerencia"),
    [
        (1045, "rechazó el usuario cloudcr", "CLOUDCR_REPO_CLAVE"),
        (1049, "La base cloudcr no existe", "repo preparar"),
        (1044, "no tiene permiso sobre la base cloudcr", "repo preparar"),
        (2003, "No se pudo llegar a MySQL en localhost:3306", "MySQL80"),
        (2002, "No se pudo llegar a MySQL en localhost:3306", "MySQL80"),
        (9999, "No se pudo conectar a MySQL en localhost:3306", "MySQL80"),
    ],
)
def test_los_errores_de_conexion_se_traducen_con_sugerencia(
    monkeypatch: pytest.MonkeyPatch, codigo: int, fragmento_mensaje: str, fragmento_sugerencia: str
) -> None:
    def falla(**argumentos: Any) -> None:
        raise pymysql.OperationalError(codigo, "detalle del servidor")

    monkeypatch.setattr(repositorio_conexion.pymysql, "connect", falla)
    with pytest.raises(ErrorConexionRepositorio) as error:
        conectar(PARAMETROS)
    assert fragmento_mensaje in str(error.value)
    assert fragmento_sugerencia in (error.value.sugerencia or "")


def test_sin_clave_el_repositorio_no_esta_configurado(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLOUDCR_REPO_CLAVE", raising=False)
    with pytest.raises(RepositorioNoConfigurado, match="CLOUDCR_REPO_CLAVE"):
        parametros_repositorio(Ajustes())
    with pytest.raises(RepositorioNoConfigurado):
        abrir_repositorio(Ajustes())


def test_los_parametros_salen_de_los_ajustes_y_de_la_clave_del_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLOUDCR_REPO_CLAVE", "del-entorno")
    ajustes = Ajustes(repositorio_host="db.interna", repositorio_puerto=3310, repositorio_base="catalogo")
    assert parametros_repositorio(ajustes) == ParametrosMySql(
        host="db.interna", puerto=3310, base="catalogo", usuario="cloudcr", clave="del-entorno"
    )
