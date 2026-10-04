import re
from collections.abc import Iterable
from dataclasses import dataclass, field

CODIGOS_ADVERTENCIA_POR_DEFECTO = frozenset({"RMAN-08137", "RMAN-08138", "RMAN-06207", "RMAN-06208", "RMAN-06214"})
CODIGOS_SEPARADOR = frozenset({"RMAN-00571", "RMAN-00569"})
CODIGOS_ENVOLTORIO = frozenset({"RMAN-03002", "RMAN-03009"})
TEXTO_FIN = "Recovery Manager complete."
TEXTO_PILA = "ERROR MESSAGE STACK FOLLOWS"

PATRON_MENSAJE = re.compile(r"^\s*((?:RMAN|ORA)-\d{5}):\s?(.*)$")
PATRON_ECO = re.compile(r"^(?:RMAN>|\d+>)")
PATRON_PIEZA = re.compile(r"piece handle=(?P<handle>.+?)\s+tag=(?P<tag>\S*)", re.IGNORECASE)
PATRON_PIEZA_SIN_TAG = re.compile(r"piece handle=(?P<handle>\S+)", re.IGNORECASE)
PATRON_ADVERTENCIA = re.compile(r"\bWARNING\b", re.IGNORECASE)


@dataclass(frozen=True)
class MensajeRman:
    codigo: str
    texto: str
    linea: int

    def __str__(self) -> str:
        return f"{self.codigo}: {self.texto}"


@dataclass(frozen=True)
class PiezaLog:
    handle: str
    tag: str | None


@dataclass(frozen=True)
class LogAnalizado:
    errores: list[MensajeRman] = field(default_factory=list)
    advertencias: list[MensajeRman] = field(default_factory=list)
    piezas: list[PiezaLog] = field(default_factory=list)
    completo: bool = False
    tiene_pila_error: bool = False
    conectado: bool = False

    @property
    def vacio(self) -> bool:
        return not (self.errores or self.advertencias or self.piezas or self.completo or self.conectado)

    @property
    def primer_error(self) -> MensajeRman | None:
        significativos = [e for e in self.errores if e.codigo not in CODIGOS_ENVOLTORIO]
        candidatos = significativos or self.errores
        return candidatos[0] if candidatos else None

    def resumen_errores(self) -> str:
        return "\n".join(str(error) for error in self.errores)

    def resumen_advertencias(self) -> str:
        return "\n".join(str(advertencia) for advertencia in self.advertencias)


def _pieza(linea: str) -> PiezaLog | None:
    coincidencia = PATRON_PIEZA.search(linea)
    if coincidencia is not None:
        return PiezaLog(handle=coincidencia.group("handle").strip(), tag=coincidencia.group("tag") or None)
    simple = PATRON_PIEZA_SIN_TAG.search(linea)
    if simple is not None:
        return PiezaLog(handle=simple.group("handle").strip(), tag=None)
    return None


def analizar(texto: str, codigos_advertencia: Iterable[str] = CODIGOS_ADVERTENCIA_POR_DEFECTO) -> LogAnalizado:
    advertir = frozenset(codigos_advertencia)
    errores: list[MensajeRman] = []
    advertencias: list[MensajeRman] = []
    piezas: list[PiezaLog] = []
    completo = False
    pila = False
    conectado = False
    for numero, cruda in enumerate(texto.splitlines(), start=1):
        linea = cruda.rstrip("\r")
        if PATRON_ECO.match(linea):
            continue
        if TEXTO_FIN in linea:
            completo = True
        if TEXTO_PILA in linea:
            pila = True
        if linea.startswith("connected to target database"):
            conectado = True
        mensaje = PATRON_MENSAJE.match(linea)
        if mensaje is not None:
            codigo, cuerpo = mensaje.group(1), mensaje.group(2).strip()
            if codigo in CODIGOS_SEPARADOR:
                continue
            es_advertencia = codigo in advertir or cuerpo.lower().startswith("warning")
            destino = advertencias if es_advertencia else errores
            destino.append(MensajeRman(codigo=codigo, texto=cuerpo, linea=numero))
            continue
        pieza = _pieza(linea)
        if pieza is not None and pieza.handle not in {p.handle for p in piezas}:
            piezas.append(pieza)
            continue
        if PATRON_ADVERTENCIA.search(linea):
            advertencias.append(MensajeRman(codigo="WARNING", texto=linea.strip(), linea=numero))
    return LogAnalizado(
        errores=errores,
        advertencias=advertencias,
        piezas=piezas,
        completo=completo,
        tiene_pila_error=pila,
        conectado=conectado,
    )
