from typing import Any

import pymysql
import pytest

from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.repository import preparacion
from cloudcr_backup.repository.conexion import ErrorConexionRepositorio, ParametrosMySql


class CursorAdministrador:
    def __init__(self, servidor: "ServidorFalso") -> None:
        self._servidor = servidor

    def execute(self, sql: str, **parametros: Any) -> None:
        self._servidor.sentencias.append((" ".join(sql.split()), parametros))
        if self._servidor.falla_al_crear is not None:
            raise self._servidor.falla_al_crear
        if sql.startswith("GRANT"):
            self._servidor.repositorio_creado = True

    def close(self) -> None:
        pass


class ConexionFalsaMySql:
    def __init__(self, servidor: "ServidorFalso", administrador: bool) -> None:
        self._servidor = servidor
        self._administrador = administrador

    def cursor(self) -> CursorAdministrador:
        return CursorAdministrador(self._servidor)

    def commit(self) -> None:
        self._servidor.commits += 1

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        self._servidor.cierres += 1


class ServidorFalso:
    def __init__(self, repositorio_creado: bool = False) -> None:
        self.repositorio_creado = repositorio_creado
        self.sentencias: list[tuple[str, dict[str, Any]]] = []
        self.conexiones: list[ParametrosMySql] = []
        self.commits = 0
        self.cierres = 0
        self.falla_al_crear: Exception | None = None

    def conectar(self, parametros: ParametrosMySql) -> ConexionFalsaMySql:
        self.conexiones.append(parametros)
        if parametros.base is None:
            return ConexionFalsaMySql(self, administrador=True)
        if not self.repositorio_creado:
            raise ErrorConexionRepositorio("La base no existe.")
        return ConexionFalsaMySql(self, administrador=False)


@pytest.fixture
def servidor(monkeypatch: pytest.MonkeyPatch) -> ServidorFalso:
    falso = ServidorFalso()
    monkeypatch.setattr(preparacion, "conectar", falso.conectar)
    monkeypatch.setenv("CLOUDCR_REPO_CLAVE", "clave-del-repositorio")
    return falso


def test_si_el_repositorio_ya_es_accesible_no_se_toca_nada(servidor: ServidorFalso) -> None:
    servidor.repositorio_creado = True
    resultado = preparacion.preparar(Ajustes())
    assert resultado.ya_preparado
    assert servidor.sentencias == []
    assert [p.base for p in servidor.conexiones] == ["cloudcr"]


def test_crea_la_base_el_usuario_y_los_privilegios_con_el_administrador(
    servidor: ServidorFalso, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLOUDCR_MYSQL_ADMIN_USUARIO", "admin_mysql")
    monkeypatch.setenv("CLOUDCR_MYSQL_ADMIN_CLAVE", "clave-del-admin")
    resultado = preparacion.preparar(Ajustes(repositorio_base="mi_catalogo", repositorio_usuario="usuario_app"))
    assert not resultado.ya_preparado
    assert (resultado.base, resultado.usuario) == ("mi_catalogo", "usuario_app")
    administrador = next(p for p in servidor.conexiones if p.base is None)
    assert (administrador.usuario, administrador.clave) == ("admin_mysql", "clave-del-admin")
    sql = [s for s, _ in servidor.sentencias]
    assert sql[0] == "CREATE DATABASE IF NOT EXISTS `mi_catalogo` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin"
    assert sql[1].startswith("CREATE USER IF NOT EXISTS :usuario@:host IDENTIFIED BY :clave")
    assert sql[2].startswith("ALTER USER :usuario@:host IDENTIFIED BY :clave")
    assert sql[3] == (
        f"GRANT {preparacion.PRIVILEGIOS} ON `mi\\_catalogo`.* TO :usuario@:host"
    )
    identidad = {"usuario": "usuario_app", "host": "localhost", "clave": "clave-del-repositorio"}
    assert servidor.sentencias[1][1] == identidad
    assert "ALL" not in sql[3]
    assert servidor.commits == 1
    assert servidor.cierres >= 1


def test_para_un_servidor_remoto_el_usuario_se_crea_para_cualquier_origen(
    servidor: ServidorFalso, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLOUDCR_MYSQL_ADMIN_CLAVE", "clave-del-admin")
    preparacion.preparar(Ajustes(repositorio_host="mysql.interno"))
    assert servidor.sentencias[1][1]["host"] == "%"


def test_sin_clave_de_administrador_explica_como_seguir(servidor: ServidorFalso) -> None:
    with pytest.raises(ErrorConexionRepositorio) as error:
        preparacion.preparar(Ajustes())
    assert "CLOUDCR_MYSQL_ADMIN_CLAVE" in (error.value.sugerencia or "")
    assert servidor.sentencias == []


def test_sin_clave_del_repositorio_pide_configurarla(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLOUDCR_REPO_CLAVE", raising=False)
    with pytest.raises(ErrorConexionRepositorio) as error:
        preparacion.preparar(Ajustes())
    assert "CLOUDCR_REPO_CLAVE" in (error.value.sugerencia or "")


@pytest.mark.parametrize(
    "ajustes",
    [
        Ajustes(repositorio_base="base; DROP DATABASE mysql"),
        Ajustes(repositorio_base="con-guion"),
        Ajustes(repositorio_usuario="usuario'--"),
        Ajustes(repositorio_usuario="u" * 33),
    ],
)
def test_los_nombres_con_caracteres_peligrosos_se_rechazan(servidor: ServidorFalso, ajustes: Ajustes) -> None:
    with pytest.raises(ErrorConexionRepositorio, match="no es válido"):
        preparacion.preparar(ajustes)
    assert servidor.conexiones == []


def test_un_rechazo_de_mysql_al_crear_se_traduce(servidor: ServidorFalso, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLOUDCR_MYSQL_ADMIN_CLAVE", "clave-del-admin")
    servidor.falla_al_crear = pymysql.OperationalError(1227, "Access denied; you need the CREATE USER privilege")
    with pytest.raises(ErrorConexionRepositorio, match="no permitió crear"):
        preparacion.preparar(Ajustes())
    assert servidor.cierres == 1


def test_si_tras_crear_el_usuario_no_puede_conectar_lo_informa(
    servidor: ServidorFalso, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLOUDCR_MYSQL_ADMIN_CLAVE", "clave-del-admin")

    def crear_sin_efecto(sql: str, **parametros: Any) -> None:
        servidor.sentencias.append((sql, parametros))

    monkeypatch.setattr(CursorAdministrador, "execute", lambda self, sql, **p: crear_sin_efecto(sql, **p))
    with pytest.raises(ErrorConexionRepositorio, match="no pudo conectarse"):
        preparacion.preparar(Ajustes())
