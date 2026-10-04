from dataclasses import dataclass

import oracledb

from cloudcr_backup.domain.errores import OperacionNoPermitida, RecursoNoEncontrado
from cloudcr_backup.domain.estrategia import Estrategia, Tarea
from cloudcr_backup.repository import bases_datos as repositorio_bases_datos
from cloudcr_backup.repository import estrategias as repositorio_estrategias
from cloudcr_backup.repository.bases_datos import BaseDatosRegistrada

SUGERENCIA_BASES = "Use 'cloudcr db listar' para ver las bases registradas."
SUGERENCIA_ESTRATEGIAS = "Use 'cloudcr estrategia listar' o la pantalla de estrategias para ver las registradas."


@dataclass(frozen=True)
class TareaResuelta:
    base: BaseDatosRegistrada
    estrategia: Estrategia
    tarea: Tarea
    tarea_id: int


def base_por_nombre(conexion: oracledb.Connection, nombre: str) -> BaseDatosRegistrada:
    base = repositorio_bases_datos.obtener(conexion, nombre.strip().upper())
    if base is None:
        raise RecursoNoEncontrado(
            f"No hay ninguna base de datos registrada con el nombre {nombre.upper()}.", SUGERENCIA_BASES
        )
    return base


def estrategia(conexion: oracledb.Connection, bd: str | None, codigo: str) -> tuple[BaseDatosRegistrada, Estrategia]:
    codigo_normal = codigo.strip().upper()
    bases = [base_por_nombre(conexion, bd)] if bd else repositorio_bases_datos.listar(conexion)
    encontradas = [
        (base, encontrada)
        for base in bases
        if (encontrada := repositorio_estrategias.obtener(conexion, base.id, codigo_normal)) is not None
    ]
    if not encontradas:
        lugar = f" en la base {bd.upper()}" if bd else ""
        raise RecursoNoEncontrado(f"No existe la estrategia {codigo_normal}{lugar}.", SUGERENCIA_ESTRATEGIAS)
    if len(encontradas) > 1:
        nombres = ", ".join(base.nombre for base, _ in encontradas)
        raise OperacionNoPermitida(
            f"La estrategia {codigo_normal} existe en varias bases ({nombres}).", "Indique --bd."
        )
    return encontradas[0]


def tareas(conexion: oracledb.Connection, bd: str | None, codigo: str, tarea: str | None) -> list[TareaResuelta]:
    base, encontrada = estrategia(conexion, bd, codigo)
    assert encontrada.id is not None
    ids = repositorio_estrategias.ids_de_tareas(conexion, encontrada.id)
    elegidas = encontrada.tareas
    if tarea is not None:
        elegida = encontrada.tarea(tarea.strip().upper())
        if elegida is None:
            raise RecursoNoEncontrado(f"No existe la tarea {tarea.upper()} en la estrategia {encontrada.codigo}.")
        elegidas = [elegida]
    if not elegidas:
        raise OperacionNoPermitida(f"La estrategia {encontrada.codigo} no tiene tareas.")
    return [TareaResuelta(base, encontrada, t, ids[t.codigo]) for t in elegidas]


def una_tarea(conexion: oracledb.Connection, bd: str | None, codigo: str, tarea: str) -> TareaResuelta:
    return tareas(conexion, bd, codigo, tarea)[0]
