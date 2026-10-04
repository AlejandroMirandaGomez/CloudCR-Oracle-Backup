from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

Consulta = Callable[[str, dict[str, Any]], list[tuple[Any, ...]]]

SQL_TRABAJO = """
    SELECT status, input_bytes, output_bytes, start_time, end_time, input_type
    FROM v$rman_backup_job_details
    WHERE command_id = :command_id
    ORDER BY start_time DESC
"""

SQL_PIEZAS = """
    SELECT handle, bytes, tag, status, bs_key, completion_time
    FROM v$backup_piece_details
    WHERE tag = :tag
    ORDER BY bs_key, piece#
"""

ESTADO_PIEZA_DISPONIBLE = "A"
ESTADO_PIEZA_EXPIRADA = "X"


@dataclass(frozen=True)
class TrabajoRman:
    estado: str
    bytes_entrada: int | None
    bytes_salida: int | None
    inicio: datetime | None
    fin: datetime | None
    tipo_entrada: str | None


@dataclass(frozen=True)
class PiezaCatalogo:
    handle: str
    bytes: int | None
    tag: str | None
    estado: str
    conjunto: int | None
    completada: datetime | None

    @property
    def disponible(self) -> bool:
        return self.estado == ESTADO_PIEZA_DISPONIBLE

    @property
    def expirada(self) -> bool:
        return self.estado == ESTADO_PIEZA_EXPIRADA


@dataclass(frozen=True)
class Correlacion:
    consultado: bool
    trabajo: TrabajoRman | None = None
    piezas: list[PiezaCatalogo] = field(default_factory=list)
    error: str | None = None

    @property
    def estado_job(self) -> str | None:
        return self.trabajo.estado if self.trabajo is not None else None

    @property
    def conjuntos(self) -> list[int]:
        return sorted({p.conjunto for p in self.piezas if p.conjunto is not None})


def _entero(valor: Any) -> int | None:
    return None if valor is None else int(valor)


def _momento(valor: Any) -> datetime | None:
    return valor if isinstance(valor, datetime) else None


def trabajo_de(consulta: Consulta, command_id: str) -> TrabajoRman | None:
    filas = consulta(SQL_TRABAJO, {"command_id": command_id})
    if not filas:
        return None
    estado, entrada, salida, inicio, fin, tipo = filas[0]
    return TrabajoRman(
        estado=str(estado),
        bytes_entrada=_entero(entrada),
        bytes_salida=_entero(salida),
        inicio=_momento(inicio),
        fin=_momento(fin),
        tipo_entrada=None if tipo is None else str(tipo),
    )


def piezas_de(consulta: Consulta, tag: str) -> list[PiezaCatalogo]:
    return [
        PiezaCatalogo(
            handle=str(handle),
            bytes=_entero(tamano),
            tag=None if etiqueta is None else str(etiqueta),
            estado=str(estado),
            conjunto=_entero(conjunto),
            completada=_momento(completada),
        )
        for handle, tamano, etiqueta, estado, conjunto, completada in consulta(SQL_PIEZAS, {"tag": tag})
    ]


def correlacionar(consulta: Consulta, tag: str, command_id: str) -> Correlacion:
    try:
        return Correlacion(consultado=True, trabajo=trabajo_de(consulta, command_id), piezas=piezas_de(consulta, tag))
    except Exception as error:
        return Correlacion(consultado=False, error=f"{type(error).__name__}: {error}")
