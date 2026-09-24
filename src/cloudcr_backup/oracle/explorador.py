from dataclasses import dataclass
from pathlib import Path

from cloudcr_backup.domain.hallazgos import Hallazgo
from cloudcr_backup.domain.perfil_bd import PerfilBD
from cloudcr_backup.oracle.connection import (
    ErrorConexionOracle,
    ParametrosConexionLocal,
    ParametrosConexionRemota,
    conectar_local,
    conectar_remota,
)
from cloudcr_backup.oracle.discovery import InstanciaDescubierta
from cloudcr_backup.oracle.inspector import inspeccionar
from cloudcr_backup.oracle.observaciones import observar


@dataclass(frozen=True)
class Exploracion:
    perfil: PerfilBD
    hallazgos: list[Hallazgo]


class InstanciaNoEncontrada(LookupError):
    pass


def resolver_instancia(
    descubiertas: list[InstanciaDescubierta], sid: str | None, oracle_home: Path | None
) -> InstanciaDescubierta:
    if sid is None:
        en_ejecucion = [i for i in descubiertas if i.en_ejecucion]
        if len(en_ejecucion) == 1:
            return _con_home(en_ejecucion[0], oracle_home)
        if not descubiertas:
            raise InstanciaNoEncontrada("No se encontró ninguna instancia Oracle en esta máquina.")
        raise InstanciaNoEncontrada("Hay varias instancias disponibles; indique cuál explorar.")
    elegida = next((i for i in descubiertas if i.clave == sid.upper()), None)
    if elegida is None:
        if oracle_home is None:
            raise InstanciaNoEncontrada(f"No se encontró la instancia {sid}; indique también --oracle-home.")
        return InstanciaDescubierta(sid=sid, oracle_home=oracle_home, en_ejecucion=False, origenes=("manual",))
    return _con_home(elegida, oracle_home)


def _con_home(instancia: InstanciaDescubierta, oracle_home: Path | None) -> InstanciaDescubierta:
    if oracle_home is None:
        return instancia
    return InstanciaDescubierta(
        sid=instancia.sid, oracle_home=oracle_home, en_ejecucion=instancia.en_ejecucion, origenes=instancia.origenes
    )


def explorar_local(instancia: InstanciaDescubierta) -> Exploracion:
    if instancia.oracle_home is None:
        raise ErrorConexionOracle(
            f"No se conoce el ORACLE_HOME de la instancia {instancia.sid}.",
            "Indíquelo con --oracle-home o defina la variable de entorno ORACLE_HOME.",
        )
    conexion = conectar_local(ParametrosConexionLocal(oracle_home=instancia.oracle_home, sid=instancia.sid))
    try:
        perfil = inspeccionar(conexion, str(instancia.oracle_home))
    finally:
        conexion.close()
    return Exploracion(perfil=perfil, hallazgos=observar(perfil))


def explorar_remota(parametros: ParametrosConexionRemota) -> Exploracion:
    conexion = conectar_remota(parametros)
    try:
        perfil = inspeccionar(conexion, None)
    finally:
        conexion.close()
    return Exploracion(perfil=perfil, hallazgos=observar(perfil))
