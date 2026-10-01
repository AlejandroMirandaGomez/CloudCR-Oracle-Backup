from dataclasses import dataclass

from cloudcr_backup.domain.enums import ContenidoTablespace, LogMode, TipoArchivoParametros, TipoObjeto
from cloudcr_backup.domain.perfil_bd import ContenedorInfo, PerfilBD
from cloudcr_backup.oracle.observaciones import (
    SUJETO_ARCHIVADO,
    SUJETO_CONTROLFILES,
    SUJETO_INSTANCIA,
    SUJETO_PARAMETROS,
    sujeto_contenedor,
    sujeto_datafile,
    sujeto_tablespace,
)
from cloudcr_backup.presentacion.arbol import id_nodo
from cloudcr_backup.strategy.alcance import identificador_tablespace


@dataclass(frozen=True)
class OpcionAlcance:
    nodo_id: str
    tipo: TipoObjeto
    identificador: str
    etiqueta: str
    habilitada: bool = True
    motivo: str | None = None
    cubierta_por: tuple[str, ...] = ()


def _contenedor_seleccionable(perfil: PerfilBD, contenedor: ContenedorInfo) -> bool:
    return perfil.es_cdb and not contenedor.es_raiz and not contenedor.es_semilla


def _opciones_de_instancia(perfil: PerfilBD, raiz: str) -> list[OpcionAlcance]:
    tiene_spfile = any(a.tipo is TipoArchivoParametros.SPFILE for a in perfil.archivos_parametros)
    en_archivelog = perfil.log_mode is LogMode.ARCHIVELOG
    return [
        OpcionAlcance(nodo_id=raiz, tipo=TipoObjeto.BASE_DATOS, identificador="", etiqueta="Toda la base de datos"),
        OpcionAlcance(
            nodo_id=id_nodo(SUJETO_CONTROLFILES),
            tipo=TipoObjeto.CONTROLFILE,
            identificador="",
            etiqueta="Control files",
            habilitada=bool(perfil.controlfiles),
            motivo=None if perfil.controlfiles else "No se encontraron control files.",
        ),
        OpcionAlcance(
            nodo_id=id_nodo(SUJETO_PARAMETROS),
            tipo=TipoObjeto.SPFILE,
            identificador="",
            etiqueta="SPFILE",
            habilitada=tiene_spfile,
            motivo=None if tiene_spfile else "La instancia no usa un SPFILE.",
        ),
        OpcionAlcance(
            nodo_id=id_nodo(SUJETO_ARCHIVADO),
            tipo=TipoObjeto.ARCHIVELOG,
            identificador="",
            etiqueta="Archived logs",
            habilitada=en_archivelog,
            motivo=None if en_archivelog else "La base está en NOARCHIVELOG: no se generan archived logs.",
        ),
    ]


def _opciones_de_contenedor(perfil: PerfilBD, contenedor: ContenedorInfo, raiz: str) -> list[OpcionAlcance]:
    opciones: list[OpcionAlcance] = []
    cubierta: tuple[str, ...] = (raiz,)
    if _contenedor_seleccionable(perfil, contenedor):
        id_contenedor = id_nodo(sujeto_contenedor(contenedor.con_id))
        opciones.append(
            OpcionAlcance(
                nodo_id=id_contenedor,
                tipo=TipoObjeto.PDB,
                identificador=contenedor.nombre,
                etiqueta=f"PDB {contenedor.nombre}",
                cubierta_por=cubierta,
            )
        )
        cubierta = (id_contenedor, raiz)
    for tablespace in perfil.tablespaces_de(contenedor.con_id):
        if tablespace.contenido is ContenidoTablespace.TEMPORAL:
            continue
        identificador = identificador_tablespace(contenedor, tablespace.nombre)
        id_tablespace = id_nodo(sujeto_tablespace(contenedor.con_id, tablespace.nombre))
        opciones.append(
            OpcionAlcance(
                nodo_id=id_tablespace,
                tipo=TipoObjeto.TABLESPACE,
                identificador=identificador,
                etiqueta=f"Tablespace {identificador}",
                cubierta_por=cubierta,
            )
        )
        for datafile in perfil.datafiles_de(contenedor.con_id, tablespace.nombre):
            opciones.append(
                OpcionAlcance(
                    nodo_id=id_nodo(sujeto_datafile(datafile.file_id)),
                    tipo=TipoObjeto.DATAFILE,
                    identificador=str(datafile.file_id),
                    etiqueta=f"Datafile #{datafile.file_id} ({datafile.nombre_archivo})",
                    cubierta_por=(id_tablespace, *cubierta),
                )
            )
    return opciones


def opciones_de_alcance(perfil: PerfilBD) -> dict[str, OpcionAlcance]:
    raiz = id_nodo(SUJETO_INSTANCIA)
    opciones = _opciones_de_instancia(perfil, raiz)
    for contenedor in perfil.contenedores:
        if not contenedor.es_semilla:
            opciones.extend(_opciones_de_contenedor(perfil, contenedor, raiz))
    return {opcion.nodo_id: opcion for opcion in opciones}
