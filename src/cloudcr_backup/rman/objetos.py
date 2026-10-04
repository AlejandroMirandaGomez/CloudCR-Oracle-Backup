from dataclasses import dataclass

from cloudcr_backup.domain.enums import TipoObjeto
from cloudcr_backup.domain.estrategia import ObjetoAlcance

SEPARADOR_CONTENEDOR = ":"


class AlcanceInvalido(ValueError):
    pass


@dataclass(frozen=True)
class EspecificacionAlcance:
    base_datos: bool = False
    pdbs: tuple[str, ...] = ()
    tablespaces: tuple[str, ...] = ()
    datafiles: tuple[int, ...] = ()
    controlfile: bool = False
    spfile: bool = False
    archivelog: bool = False

    @property
    def tiene_datos(self) -> bool:
        return self.base_datos or bool(self.pdbs or self.tablespaces or self.datafiles)

    @property
    def parcial(self) -> bool:
        return not self.base_datos and self.tiene_datos

    @property
    def vacia(self) -> bool:
        return not (self.tiene_datos or self.controlfile or self.spfile or self.archivelog)

    def clausulas(self) -> list[str]:
        if self.base_datos:
            return ["DATABASE"]
        clausulas = []
        if self.pdbs:
            clausulas.append("PLUGGABLE DATABASE " + ", ".join(self.pdbs))
        if self.tablespaces:
            clausulas.append("TABLESPACE " + ", ".join(self.tablespaces))
        if self.datafiles:
            clausulas.append("DATAFILE " + ", ".join(str(d) for d in self.datafiles))
        return clausulas


def _sin_repetidos(valores: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(valores))


def _contenedor_de(tablespace: str) -> str | None:
    if SEPARADOR_CONTENEDOR not in tablespace:
        return None
    return tablespace.split(SEPARADOR_CONTENEDOR, 1)[0]


def _numero_datafile(identificador: str) -> int:
    try:
        numero = int(identificador.strip())
    except ValueError as error:
        raise AlcanceInvalido(f"El datafile {identificador!r} no es un número de archivo (file#) válido.") from error
    if numero <= 0:
        raise AlcanceInvalido(f"El datafile {identificador!r} no es un número de archivo (file#) válido.")
    return numero


def _identificador(objeto: ObjetoAlcance) -> str:
    texto = objeto.identificador.strip().upper()
    if not texto:
        raise AlcanceInvalido(f"El objeto {objeto.tipo.value} del alcance no tiene identificador.")
    return texto


def especificacion_de(alcance: list[ObjetoAlcance]) -> EspecificacionAlcance:
    tipos = {objeto.tipo for objeto in alcance}
    controlfile = TipoObjeto.CONTROLFILE in tipos
    spfile = TipoObjeto.SPFILE in tipos
    archivelog = TipoObjeto.ARCHIVELOG in tipos
    if TipoObjeto.BASE_DATOS in tipos:
        return EspecificacionAlcance(base_datos=True, controlfile=True, spfile=True, archivelog=archivelog)
    pdbs = _sin_repetidos([_identificador(o) for o in alcance if o.tipo is TipoObjeto.PDB])
    tablespaces = _sin_repetidos(
        [
            identificador
            for identificador in (_identificador(o) for o in alcance if o.tipo is TipoObjeto.TABLESPACE)
            if _contenedor_de(identificador) not in pdbs
        ]
    )
    datafiles = tuple(
        sorted({_numero_datafile(o.identificador) for o in alcance if o.tipo is TipoObjeto.DATAFILE})
    )
    return EspecificacionAlcance(
        pdbs=pdbs,
        tablespaces=tablespaces,
        datafiles=datafiles,
        controlfile=controlfile,
        spfile=spfile,
        archivelog=archivelog,
    )
