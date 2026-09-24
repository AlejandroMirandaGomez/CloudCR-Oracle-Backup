from dataclasses import dataclass
from datetime import datetime

from cloudcr_backup.domain.enums import LogMode, Severidad
from cloudcr_backup.domain.hallazgos import ORDEN_SEVERIDAD
from cloudcr_backup.oracle.explorador import Exploracion
from cloudcr_backup.presentacion.formato import Tono, nombre_edicion


@dataclass(frozen=True)
class ConteoSeveridad:
    severidad: Severidad
    cantidad: int


@dataclass(frozen=True)
class ResumenInstancia:
    instancia: str
    base: str
    version: str
    edicion: str
    tipo: str
    contenedores: int
    pdbs: int
    log_mode: str
    tono_log_mode: Tono
    bytes_datafiles: int
    bytes_tempfiles: int
    cantidad_datafiles: int
    cantidad_tempfiles: int
    observaciones: list[ConteoSeveridad]
    total_observaciones: int
    host: str
    capturado_en: datetime


def resumir(exploracion: Exploracion) -> ResumenInstancia:
    perfil = exploracion.perfil
    conteos = [
        ConteoSeveridad(severidad, sum(1 for h in exploracion.hallazgos if h.severidad is severidad))
        for severidad in ORDEN_SEVERIDAD
    ]
    return ResumenInstancia(
        instancia=perfil.nombre_instancia.upper(),
        base=perfil.nombre,
        version=perfil.version,
        edicion=nombre_edicion(perfil.edicion),
        tipo="CDB (multitenant)" if perfil.es_cdb else "no-CDB",
        contenedores=len(perfil.contenedores),
        pdbs=sum(1 for c in perfil.contenedores if not c.es_raiz and not c.es_semilla),
        log_mode=perfil.log_mode.value,
        tono_log_mode=Tono.EXITO if perfil.log_mode is LogMode.ARCHIVELOG else Tono.ADVERTENCIA,
        bytes_datafiles=sum(d.bytes for d in perfil.datafiles),
        bytes_tempfiles=sum(t.bytes for t in perfil.tempfiles),
        cantidad_datafiles=len(perfil.datafiles),
        cantidad_tempfiles=len(perfil.tempfiles),
        observaciones=[c for c in conteos if c.cantidad],
        total_observaciones=len(exploracion.hallazgos),
        host=perfil.host,
        capturado_en=perfil.capturado_en,
    )
