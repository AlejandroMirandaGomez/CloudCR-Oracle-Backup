import hashlib
import re

from cloudcr_backup.domain.enums import EstadoScript, ModoRespaldo

PATRON_APAGADO = re.compile(r"^\s*SHUTDOWN\b", re.IGNORECASE | re.MULTILINE)

TRANSICIONES: dict[EstadoScript, frozenset[EstadoScript]] = {
    EstadoScript.BORRADOR: frozenset({EstadoScript.APROBADO, EstadoScript.RECHAZADO, EstadoScript.OBSOLETO}),
    EstadoScript.APROBADO: frozenset({EstadoScript.OBSOLETO}),
    EstadoScript.RECHAZADO: frozenset({EstadoScript.OBSOLETO}),
    EstadoScript.OBSOLETO: frozenset(),
}

MENSAJE_CAIDA = (
    "El script hace un respaldo CONSISTENTE: ejecuta SHUTDOWN IMMEDIATE y la base de datos (y todas sus PDB, "
    "incluido el repositorio BKPCAT si vive en la misma CDB) queda fuera de servicio mientras dura el respaldo."
)
SUGERENCIA_CAIDA = "Si acepta la caída del servicio, apruebe de nuevo con --acepto-caida."


class AprobacionRechazada(ValueError):
    def __init__(self, mensaje: str, sugerencia: str | None = None) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.sugerencia = sugerencia


def calcular_hash(contenido: str) -> str:
    return hashlib.sha256(contenido.encode("utf-8")).hexdigest()


def hash_de_bytes(contenido: bytes) -> str:
    return hashlib.sha256(contenido).hexdigest()


def script_intacto(contenido: bytes, hash_aprobado: str) -> bool:
    return hash_de_bytes(contenido) == hash_aprobado.lower()


def modo_de_script(contenido: str) -> ModoRespaldo:
    return ModoRespaldo.CONSISTENTE if PATRON_APAGADO.search(contenido) else ModoRespaldo.EN_LINEA


def validar_transicion(actual: EstadoScript, nuevo: EstadoScript) -> None:
    if nuevo not in TRANSICIONES[actual]:
        permitidos = ", ".join(sorted(e.value for e in TRANSICIONES[actual])) or "ninguno"
        raise AprobacionRechazada(
            f"Un script {actual.value} no puede pasar a {nuevo.value} (desde {actual.value} se permite: {permitidos}).",
            "Genere una versión nueva con 'cloudcr script generar'." if actual is not EstadoScript.BORRADOR else None,
        )


def exigir_aceptacion_caida(contenido: str, acepto_caida: bool) -> None:
    if modo_de_script(contenido) is ModoRespaldo.CONSISTENTE and not acepto_caida:
        raise AprobacionRechazada(MENSAJE_CAIDA, SUGERENCIA_CAIDA)


def validar_aprobacion(estado: EstadoScript, contenido: str, hash_registrado: str, acepto_caida: bool) -> None:
    validar_transicion(estado, EstadoScript.APROBADO)
    if calcular_hash(contenido) != hash_registrado.lower():
        raise AprobacionRechazada(
            "El contenido del script no coincide con su hash SHA-256 registrado: fue alterado después de generarse.",
            "Genere una versión nueva con 'cloudcr script generar'.",
        )
    exigir_aceptacion_caida(contenido, acepto_caida)
