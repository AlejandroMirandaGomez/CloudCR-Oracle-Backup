from enum import StrEnum

from cloudcr_backup.domain.enums import ContenidoTablespace, Severidad, TipoArchivoParametros

UNIDADES = ("B", "KB", "MB", "GB", "TB", "PB")
UMBRAL_USO_ADVERTENCIA = 85.0
UMBRAL_USO_PELIGRO = 95.0


class Tono(StrEnum):
    NORMAL = "normal"
    ATENUADO = "atenuado"
    RESALTADO = "resaltado"
    DATO = "dato"
    EXITO = "exito"
    ADVERTENCIA = "advertencia"
    PELIGRO = "peligro"


ETIQUETA_SEVERIDAD = {
    Severidad.ERROR: "ERROR",
    Severidad.ADVERTENCIA: "ADVERTENCIA",
    Severidad.RECOMENDACION: "RECOMENDACIÓN",
    Severidad.INFORMATIVA: "INFORMATIVA",
}

ETIQUETA_SEVERIDAD_PLURAL = {
    Severidad.ERROR: "ERRORES",
    Severidad.ADVERTENCIA: "ADVERTENCIAS",
    Severidad.RECOMENDACION: "RECOMENDACIONES",
    Severidad.INFORMATIVA: "INFORMATIVAS",
}

EDICIONES = {
    "XE": "Express Edition",
    "EE": "Enterprise Edition",
    "SE2": "Standard Edition 2",
    "SE": "Standard Edition",
    "PE": "Personal Edition",
}

DESCRIPCION_PARAMETROS = {
    TipoArchivoParametros.SPFILE: "SPFILE (en uso)",
    TipoArchivoParametros.PFILE_INSTANCIA: "PFILE de la instancia",
    TipoArchivoParametros.PFILE_CREACION: "PFILE de creación",
    TipoArchivoParametros.PFILE_EJEMPLO: "PFILE de ejemplo de Oracle",
    TipoArchivoParametros.PFILE_OTRO: "PFILE encontrado en disco",
}

DESCRIPCION_CONTENIDO = {
    ContenidoTablespace.PERMANENTE: "permanente",
    ContenidoTablespace.UNDO: "undo",
    ContenidoTablespace.TEMPORAL: "temporal",
    ContenidoTablespace.DESCONOCIDO: "",
}


def formato_bytes(cantidad: int | None) -> str:
    if cantidad is None:
        return "?"
    valor = float(cantidad)
    indice = 0
    while valor >= 1024 and indice < len(UNIDADES) - 1:
        valor /= 1024
        indice += 1
    if indice < 2 or valor >= 100:
        return f"{valor:.0f} {UNIDADES[indice]}"
    numero = f"{valor:.1f}".removesuffix(".0")
    return f"{numero} {UNIDADES[indice]}"


def tono_uso(porcentaje: float) -> Tono:
    if porcentaje >= UMBRAL_USO_PELIGRO:
        return Tono.PELIGRO
    if porcentaje >= UMBRAL_USO_ADVERTENCIA:
        return Tono.ADVERTENCIA
    return Tono.EXITO


def conteo_severidad(severidad: Severidad, cantidad: int) -> str:
    etiqueta = ETIQUETA_SEVERIDAD[severidad] if cantidad == 1 else ETIQUETA_SEVERIDAD_PLURAL[severidad]
    return f"{cantidad} {etiqueta}"


def nombre_edicion(codigo: str) -> str:
    return EDICIONES.get(codigo.upper(), codigo)
