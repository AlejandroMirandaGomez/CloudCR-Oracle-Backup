from dataclasses import dataclass
from typing import TYPE_CHECKING

import oracledb

if TYPE_CHECKING:
    from cloudcr_backup.domain.enums import EstadoScript


@dataclass(frozen=True)
class ScriptRman:
    id: int
    tarea_id: int
    version: int
    contenido: str
    hash_sha256: str
    estado: "EstadoScript"


def guardar_borrador(conexion: oracledb.Connection, tarea_id: int, contenido: str) -> ScriptRman:
    raise NotImplementedError


def obtener_vigente(conexion: oracledb.Connection, tarea_id: int) -> ScriptRman | None:
    raise NotImplementedError


def aprobar(conexion: oracledb.Connection, script_id: int, aprobado_por: str) -> ScriptRman:
    raise NotImplementedError


def rechazar(conexion: oracledb.Connection, script_id: int, motivo: str) -> ScriptRman:
    raise NotImplementedError


def marcar_obsoleto(conexion: oracledb.Connection, script_id: int) -> None:
    raise NotImplementedError
