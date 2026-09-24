from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

import oracledb

from cloudcr_backup.domain.enums import ContenidoTablespace, LogMode, TipoArchivoParametros
from cloudcr_backup.domain.perfil_bd import (
    ArchivoParametros,
    AreaRecuperacion,
    ContenedorInfo,
    ControlfileInfo,
    DatafileInfo,
    DestinoArchivado,
    PerfilBD,
    RedoGrupo,
    RedoMiembro,
    TablespaceInfo,
    TempfileInfo,
    ruta_pura,
)
from cloudcr_backup.oracle import queries

Fila = tuple[Any, ...]
PATRONES_PFILE = ("init*.ora", "init.ora.*")


def _filas(cursor: oracledb.Cursor, sql: str) -> list[Fila]:
    cursor.execute(sql)
    return [tuple(fila) for fila in cursor.fetchall()]


def _fila_como_dict(cursor: oracledb.Cursor, sql: str) -> dict[str, Any]:
    cursor.execute(sql)
    fila = cursor.fetchone()
    if fila is None:
        return {}
    columnas = [descripcion[0].upper() for descripcion in cursor.description or []]
    return dict(zip(columnas, fila, strict=True))


def _si_no(valor: Any) -> bool | None:
    if valor is None:
        return None
    return str(valor).upper() in ("YES", "Y", "TRUE")


def _contenido(valor: Any, temporal_por_tempfiles: bool) -> ContenidoTablespace:
    try:
        return ContenidoTablespace(str(valor))
    except ValueError:
        return ContenidoTablespace.TEMPORAL if temporal_por_tempfiles else ContenidoTablespace.DESCONOCIDO


def clasificar_pfile(nombre_archivo: str, nombre_instancia: str) -> TipoArchivoParametros:
    nombre = nombre_archivo.lower()
    if nombre == f"init{nombre_instancia.lower()}.ora":
        return TipoArchivoParametros.PFILE_INSTANCIA
    if nombre == "init.ora":
        return TipoArchivoParametros.PFILE_EJEMPLO
    if nombre.startswith("init.ora."):
        return TipoArchivoParametros.PFILE_CREACION
    return TipoArchivoParametros.PFILE_OTRO


def _entero_o_nulo(valor: Any) -> int | None:
    return None if valor is None else int(valor)


def _bytes_libres(libres: Any, datos_disponibles: bool) -> int | None:
    if not datos_disponibles:
        return None
    return 0 if libres is None else int(libres)


def directorios_pfile(
    oracle_home: str | None, spfile: str | None, diagnostic_dest: str | None, db_name: str
) -> list[Path]:
    candidatos: list[Path] = []
    if oracle_home:
        candidatos += [Path(oracle_home) / "database", Path(oracle_home) / "dbs"]
    if spfile:
        candidatos.append(Path(str(ruta_pura(spfile).parent)))
    if diagnostic_dest:
        for nombre in dict.fromkeys([db_name, db_name.lower(), db_name.upper()]):
            candidatos.append(Path(diagnostic_dest) / "admin" / nombre / "pfile")
    return list(dict.fromkeys(candidatos))


def buscar_pfiles(directorios: Iterable[Path], spfile: str | None) -> list[str]:
    spfile_normalizado = spfile.lower() if spfile else None
    encontrados: dict[str, str] = {}
    for directorio in directorios:
        if not directorio.is_dir():
            continue
        for patron in PATRONES_PFILE:
            for archivo in directorio.glob(patron):
                if not archivo.is_file() or archivo.name.lower().startswith("spfile"):
                    continue
                ruta = str(archivo)
                if ruta.lower() != spfile_normalizado:
                    encontrados.setdefault(ruta.lower(), ruta)
    return sorted(encontrados.values(), key=str.lower)


def _redo(cursor: oracledb.Cursor) -> list[RedoGrupo]:
    miembros: dict[int, list[RedoMiembro]] = {}
    for grupo, ruta, estado, tipo in _filas(cursor, queries.REDO_MIEMBROS):
        miembros.setdefault(int(grupo), []).append(RedoMiembro(ruta=ruta, estado=estado, tipo=tipo))
    return [
        RedoGrupo(
            grupo=int(grupo),
            hilo=int(hilo),
            secuencia=int(secuencia),
            bytes=int(tamano),
            estado=estado,
            archivado=bool(_si_no(archivado)),
            miembros=miembros.get(int(grupo), []),
        )
        for grupo, hilo, secuencia, tamano, estado, archivado in _filas(cursor, queries.REDO_GRUPOS)
    ]


def inspeccionar(
    conexion: oracledb.Connection,
    oracle_home: str | None,
    ahora: Callable[[], datetime] = datetime.now,
) -> PerfilBD:
    cursor = conexion.cursor()
    base = _fila_como_dict(cursor, queries.BASE_DATOS)
    instancia = _fila_como_dict(cursor, queries.INSTANCIA)
    parametros = {nombre: valor for nombre, valor in _filas(cursor, queries.PARAMETROS)}
    spfile = parametros.get("spfile") or None
    diagnostic_dest = parametros.get("diagnostic_dest") or None
    destino_configurado = any(
        parametros.get(nombre) for nombre in ("log_archive_dest", "log_archive_dest_1", "db_recovery_file_dest")
    )

    nombre_instancia = str(instancia.get("INSTANCE_NAME", ""))
    archivos_parametros = []
    if spfile:
        archivos_parametros.append(ArchivoParametros(ruta=spfile, tipo=TipoArchivoParametros.SPFILE))
    for ruta in buscar_pfiles(directorios_pfile(oracle_home, spfile, diagnostic_dest, str(base["NAME"])), spfile):
        archivos_parametros.append(
            ArchivoParametros(ruta=ruta, tipo=clasificar_pfile(ruta_pura(ruta).name, nombre_instancia))
        )
    tempfiles = [
        TempfileInfo(
            file_id=int(file_id), con_id=int(con_id), tablespace=tablespace, ruta=ruta, bytes=int(tamano), estado=estado
        )
        for file_id, con_id, tablespace, ruta, tamano, estado in _filas(cursor, queries.TEMPFILES)
    ]
    con_tempfiles = {(t.con_id, t.tablespace) for t in tempfiles}

    area = _filas(cursor, queries.AREA_RECUPERACION)
    archivelogs_sin_respaldo = _filas(cursor, queries.ARCHIVELOGS_SIN_RESPALDO)

    return PerfilBD(
        nombre=str(base["NAME"]),
        nombre_instancia=nombre_instancia,
        dbid=int(base["DBID"]),
        host=str(instancia.get("HOST_NAME", "")),
        version=str(instancia.get("VERSION_FULL") or instancia.get("VERSION", "")),
        edicion=str(instancia.get("EDITION") or "DESCONOCIDA"),
        es_cdb=bool(_si_no(base["CDB"])),
        log_mode=LogMode(str(base["LOG_MODE"])),
        open_mode=str(base["OPEN_MODE"]),
        estado_instancia=str(instancia.get("STATUS", "")),
        oracle_home=oracle_home,
        diagnostic_dest=diagnostic_dest,
        capturado_en=ahora(),
        contenedores=[
            ContenedorInfo(con_id=int(con_id), nombre=nombre, open_mode=open_mode)
            for con_id, nombre, open_mode in _filas(cursor, queries.CONTENEDORES)
        ],
        tablespaces=[
            TablespaceInfo(
                con_id=int(con_id),
                nombre=nombre,
                contenido=_contenido(contenido, temporal_por_tempfiles=(int(con_id), nombre) in con_tempfiles),
                estado=estado,
                bigfile=bool(_si_no(bigfile)),
            )
            for con_id, nombre, bigfile, contenido, estado in _filas(cursor, queries.TABLESPACES)
        ],
        datafiles=[
            DatafileInfo(
                file_id=int(file_id),
                con_id=int(con_id),
                tablespace=tablespace,
                ruta=ruta,
                bytes=int(tamano),
                estado=estado,
                autoextensible=_si_no(autoextensible),
                max_bytes=_entero_o_nulo(max_bytes),
                bytes_libres=_bytes_libres(libres, datos_disponibles=autoextensible is not None),
            )
            for file_id, con_id, tablespace, ruta, tamano, estado, autoextensible, max_bytes, libres in _filas(
                cursor, queries.DATAFILES
            )
        ],
        tempfiles=tempfiles,
        controlfiles=[
            ControlfileInfo(ruta=ruta, estado=estado, bytes=_entero_o_nulo(tamano))
            for ruta, estado, tamano in _filas(cursor, queries.CONTROLFILES)
        ],
        redo_grupos=_redo(cursor),
        archivos_parametros=archivos_parametros,
        destinos_archivado=[
            DestinoArchivado(nombre=nombre, destino=destino, estado=estado)
            for nombre, destino, estado in _filas(cursor, queries.DESTINOS_ARCHIVADO)
        ],
        destino_archivado_configurado=destino_configurado,
        area_recuperacion=(
            AreaRecuperacion(ruta=area[0][0], limite_bytes=int(area[0][1]), usados_bytes=int(area[0][2]))
            if area
            else None
        ),
        archivelogs_sin_respaldo=int(archivelogs_sin_respaldo[0][0]) if archivelogs_sin_respaldo else 0,
    )
