from dataclasses import dataclass

from cloudcr_backup.domain.enums import TipoRespaldo


@dataclass(frozen=True)
class EquivalenciaVocabulario:
    tipo: TipoRespaldo
    nombre_sistema: str
    termino_clase: str
    clausula_rman: str
    significado: str


_EQUIVALENCIAS: dict[TipoRespaldo, EquivalenciaVocabulario] = {
    TipoRespaldo.COMPLETO: EquivalenciaVocabulario(
        tipo=TipoRespaldo.COMPLETO,
        nombre_sistema="Completo",
        termino_clase="Full / total",
        clausula_rman="BACKUP DATABASE",
        significado="Todos los bloques usados del alcance; no sirve de base para incrementales.",
    ),
    TipoRespaldo.INCREMENTAL_N0: EquivalenciaVocabulario(
        tipo=TipoRespaldo.INCREMENTAL_N0,
        nombre_sistema="Incremental nivel 0",
        termino_clase="total+",
        clausula_rman="BACKUP INCREMENTAL LEVEL 0 DATABASE",
        significado="Igual de completo que un total, pero además queda como punto de partida del ciclo incremental.",
    ),
    TipoRespaldo.INCREMENTAL_N1_DIFERENCIAL: EquivalenciaVocabulario(
        tipo=TipoRespaldo.INCREMENTAL_N1_DIFERENCIAL,
        nombre_sistema="Incremental nivel 1 diferencial",
        termino_clase="Incremental",
        clausula_rman="BACKUP INCREMENTAL LEVEL 1",
        significado="Bloques cambiados desde el último respaldo de cualquier nivel.",
    ),
    TipoRespaldo.INCREMENTAL_N1_ACUMULATIVO: EquivalenciaVocabulario(
        tipo=TipoRespaldo.INCREMENTAL_N1_ACUMULATIVO,
        nombre_sistema="Incremental nivel 1 acumulativo",
        termino_clase="Incremental acumulativo",
        clausula_rman="BACKUP INCREMENTAL LEVEL 1 CUMULATIVE",
        significado="Bloques cambiados desde el último respaldo de nivel 0.",
    ),
    TipoRespaldo.ARCHIVELOG: EquivalenciaVocabulario(
        tipo=TipoRespaldo.ARCHIVELOG,
        nombre_sistema="Archived logs",
        termino_clase="Archived logs",
        clausula_rman="BACKUP ARCHIVELOG ALL",
        significado="Respaldo de los redo logs ya archivados; necesario para recuperar hasta un punto en el tiempo.",
    ),
}

NOTA_PARCIAL = (
    '"Parcial" no es un tipo de respaldo distinto: es un alcance reducido (tablespace, datafile o PDB). '
    "Se modela en el QUÉ de la estrategia, no en el CÓMO."
)

NOTA_INCOMPLETO = (
    '"Incompleto" no es un tipo de respaldo que el sistema ofrezca: describe un respaldo que no alcanza '
    "para una recuperación total. El validador lo previene con las reglas ALC_004 y ALC_005."
)


def equivalencia_de(tipo: TipoRespaldo) -> EquivalenciaVocabulario:
    return _EQUIVALENCIAS[tipo]


def todas_las_equivalencias() -> list[EquivalenciaVocabulario]:
    return list(_EQUIVALENCIAS.values())


def etiqueta_doble(tipo: TipoRespaldo) -> str:
    equivalencia = equivalencia_de(tipo)
    if equivalencia.termino_clase.lower() == equivalencia.nombre_sistema.lower():
        return equivalencia.nombre_sistema
    return f"{equivalencia.nombre_sistema} ({equivalencia.termino_clase})"
