import oracledb

from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.domain.administracion import PerfilGuardado, VistaBaseDatos
from cloudcr_backup.domain.errores import FiltroInvalido, OperacionNoPermitida, RecursoNoEncontrado
from cloudcr_backup.oracle.connection import ErrorConexionOracle
from cloudcr_backup.oracle.discovery import InstanciaDescubierta, descubrir_instancias
from cloudcr_backup.oracle.explorador import InstanciaNoEncontrada, explorar_local, resolver_instancia
from cloudcr_backup.repository import bases_datos as repositorio_bases_datos
from cloudcr_backup.repository.bases_datos import Ambiente, BaseDatosRegistrada
from cloudcr_backup.services.cliente_oracle import preparar_cliente_oracle
from cloudcr_backup.services.sesion import conexion_repositorio

SUGERENCIA_DESCUBRIR = "Revise que el servicio de la instancia exista en este equipo ('cloudcr descubrir')."


def ambiente_de(texto: str) -> Ambiente:
    try:
        return Ambiente(texto.strip().upper())
    except ValueError as error:
        opciones = ", ".join(a.value for a in Ambiente)
        raise FiltroInvalido(f"El ambiente {texto!r} no existe.", f"Use uno de: {opciones}.") from error


def _home(registrada: BaseDatosRegistrada | None, instancia: InstanciaDescubierta | None) -> str | None:
    if registrada is not None:
        return registrada.oracle_home
    if instancia is not None and instancia.oracle_home is not None:
        return str(instancia.oracle_home)
    return None


def _vista(
    nombre: str,
    registrada: BaseDatosRegistrada | None,
    instancia: InstanciaDescubierta | None,
    perfil: PerfilGuardado | None,
) -> VistaBaseDatos:
    return VistaBaseDatos(
        nombre=nombre,
        registrada=registrada is not None,
        id=registrada.id if registrada else None,
        ambiente=registrada.ambiente.value if registrada else None,
        oracle_home=_home(registrada, instancia),
        activa=registrada.activa if registrada else False,
        en_ejecucion=instancia.en_ejecucion if instancia else None,
        perfil_capturado_en=perfil.capturado_en if perfil else None,
        log_mode=perfil.log_mode if perfil else None,
    )


def _resumen_perfil(conexion: oracledb.Connection, base: BaseDatosRegistrada) -> PerfilGuardado | None:
    perfil = repositorio_bases_datos.ultimo_perfil(conexion, base.id)
    if perfil is None:
        return None
    return PerfilGuardado(
        bd=base.nombre,
        capturado_en=perfil.capturado_en,
        log_mode=perfil.log_mode,
        tablespaces=len(perfil.tablespaces),
        datafiles=len(perfil.datafiles),
    )


def listar(ajustes: Ajustes) -> list[VistaBaseDatos]:
    instancias = {i.clave: i for i in descubrir_instancias()}
    with conexion_repositorio(ajustes) as conexion:
        registradas = {b.nombre.upper(): b for b in repositorio_bases_datos.listar(conexion)}
        perfiles = {nombre: _resumen_perfil(conexion, base) for nombre, base in registradas.items()}
    nombres = sorted({*instancias, *registradas})
    return [_vista(n, registradas.get(n), instancias.get(n), perfiles.get(n)) for n in nombres]


def registradas(ajustes: Ajustes) -> list[str]:
    with conexion_repositorio(ajustes) as conexion:
        return [b.nombre for b in repositorio_bases_datos.listar(conexion) if b.activa]


def _instancia(sid: str) -> InstanciaDescubierta:
    try:
        return resolver_instancia(descubrir_instancias(), sid.strip().upper(), None)
    except InstanciaNoEncontrada as error:
        raise RecursoNoEncontrado(str(error), SUGERENCIA_DESCUBRIR) from error


def registrar(ajustes: Ajustes, sid: str, ambiente: str) -> VistaBaseDatos:
    elegido = ambiente_de(ambiente)
    instancia = _instancia(sid)
    if instancia.oracle_home is None:
        raise OperacionNoPermitida(
            f"No se detectó el ORACLE_HOME de {instancia.sid}.",
            "Regístrela desde la terminal con 'cloudcr db agregar <SID> --oracle-home <ruta>'.",
        )
    with conexion_repositorio(ajustes) as conexion:
        try:
            base = repositorio_bases_datos.registrar(conexion, instancia.sid, str(instancia.oracle_home), elegido)
        except repositorio_bases_datos.BaseDatosYaRegistrada as error:
            raise OperacionNoPermitida(str(error)) from error
    return _vista(base.nombre.upper(), base, instancia, None)


def inspeccionar(ajustes: Ajustes, nombre: str) -> PerfilGuardado:
    preparar_cliente_oracle()
    instancia = _instancia(nombre)
    try:
        exploracion = explorar_local(instancia)
    except ErrorConexionOracle as error:
        raise OperacionNoPermitida(str(error), error.sugerencia) from error
    perfil = exploracion.perfil
    with conexion_repositorio(ajustes) as conexion:
        base = repositorio_bases_datos.obtener(conexion, instancia.sid.upper())
        if base is None:
            raise RecursoNoEncontrado(
                f"La base {instancia.sid.upper()} no está registrada en el repositorio.", "Regístrela primero."
            )
        repositorio_bases_datos.guardar_perfil(conexion, base.id, perfil)
    return PerfilGuardado(
        bd=base.nombre,
        capturado_en=perfil.capturado_en,
        log_mode=perfil.log_mode,
        tablespaces=len(perfil.tablespaces),
        datafiles=len(perfil.datafiles),
    )


def cambiar_activa(ajustes: Ajustes, nombre: str, activa: bool) -> None:
    with conexion_repositorio(ajustes) as conexion:
        base = repositorio_bases_datos.obtener(conexion, nombre.strip().upper())
        if base is None:
            raise RecursoNoEncontrado(f"No hay ninguna base de datos registrada con el nombre {nombre.upper()}.")
        if activa:
            repositorio_bases_datos.activar(conexion, base.nombre)
        else:
            repositorio_bases_datos.desactivar(conexion, base.nombre)
