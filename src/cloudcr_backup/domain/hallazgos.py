from pydantic import BaseModel

from cloudcr_backup.domain.enums import Severidad

ORDEN_SEVERIDAD = [Severidad.ERROR, Severidad.ADVERTENCIA, Severidad.RECOMENDACION, Severidad.INFORMATIVA]


class Hallazgo(BaseModel):
    codigo: str
    severidad: Severidad
    mensaje: str
    sujeto: str
    accion_sugerida: str | None = None


def ordenar_por_severidad(hallazgos: list[Hallazgo]) -> list[Hallazgo]:
    return sorted(hallazgos, key=lambda h: ORDEN_SEVERIDAD.index(h.severidad))
