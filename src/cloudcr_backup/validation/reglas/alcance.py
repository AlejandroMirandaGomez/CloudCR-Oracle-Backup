from cloudcr_backup.domain.enums import ContenidoTablespace, Prioridad, Severidad, TipoArchivoParametros, TipoObjeto
from cloudcr_backup.domain.estrategia import Estrategia, ObjetoAlcance
from cloudcr_backup.domain.hallazgos import Hallazgo
from cloudcr_backup.domain.perfil_bd import RAIZ_CDB, PerfilBD, TablespaceInfo
from cloudcr_backup.validation.contexto import ContextoValidacion
from cloudcr_backup.validation.motor import regla


def _nombre_pdb_y_tablespace(identificador: str) -> tuple[str | None, str]:
    if ":" in identificador:
        pdb, tablespace = identificador.split(":", 1)
        return pdb, tablespace
    return None, identificador


def _con_id_de_pdb(perfil: PerfilBD, nombre_pdb: str | None) -> int | None:
    if nombre_pdb is None:
        raiz = next((c for c in perfil.contenedores if c.es_raiz), None)
        return raiz.con_id if raiz else None
    contenedor = next((c for c in perfil.contenedores if c.nombre == nombre_pdb), None)
    return contenedor.con_id if contenedor else None


def _tablespace_info(objeto: ObjetoAlcance, perfil: PerfilBD) -> TablespaceInfo | None:
    if objeto.tipo is not TipoObjeto.TABLESPACE:
        return None
    nombre_pdb, tablespace = _nombre_pdb_y_tablespace(objeto.identificador)
    con_id = _con_id_de_pdb(perfil, nombre_pdb)
    if con_id is None:
        return None
    return next((t for t in perfil.tablespaces_de(con_id) if t.nombre == tablespace), None)


def _objeto_existe(objeto: ObjetoAlcance, perfil: PerfilBD) -> bool:
    if objeto.tipo in (TipoObjeto.BASE_DATOS, TipoObjeto.ARCHIVELOG):
        return True
    if objeto.tipo is TipoObjeto.CONTROLFILE:
        return bool(perfil.controlfiles)
    if objeto.tipo is TipoObjeto.SPFILE:
        return any(a.tipo is TipoArchivoParametros.SPFILE for a in perfil.archivos_parametros)
    if objeto.tipo is TipoObjeto.PDB:
        return any(c.nombre == objeto.identificador for c in perfil.contenedores)
    if objeto.tipo is TipoObjeto.TABLESPACE:
        return _tablespace_info(objeto, perfil) is not None
    if objeto.tipo is TipoObjeto.DATAFILE:
        return any(str(d.file_id) == objeto.identificador for d in perfil.datafiles)
    return True


def _es_parcial(estrategia: Estrategia) -> bool:
    return bool(estrategia.alcance) and not any(o.tipo is TipoObjeto.BASE_DATOS for o in estrategia.alcance)


@regla("ALC_001")
def alc_001_alcance_vacio(contexto: ContextoValidacion) -> list[Hallazgo]:
    if contexto.estrategia.alcance:
        return []
    return [
        Hallazgo(
            codigo="ALC_001",
            severidad=Severidad.ERROR,
            mensaje="La estrategia no tiene definido qué respaldar.",
            sujeto=contexto.estrategia.codigo,
            accion_sugerida="Seleccione al menos un objeto del árbol de la instancia.",
        )
    ]


@regla("ALC_002")
def alc_002_objeto_inexistente(contexto: ContextoValidacion) -> list[Hallazgo]:
    return [
        Hallazgo(
            codigo="ALC_002",
            severidad=Severidad.ERROR,
            mensaje=f"El objeto {objeto.identificador} ({objeto.tipo}) ya no existe en el perfil actual.",
            sujeto=objeto.identificador,
            accion_sugerida="Quite el objeto del alcance o vuelva a inspeccionar la base de datos.",
        )
        for objeto in contexto.estrategia.alcance
        if not _objeto_existe(objeto, contexto.perfil)
    ]


@regla("ALC_003")
def alc_003_tablespace_temporal(contexto: ContextoValidacion) -> list[Hallazgo]:
    hallazgos = []
    for objeto in contexto.estrategia.alcance:
        info = _tablespace_info(objeto, contexto.perfil)
        if info is not None and info.contenido is ContenidoTablespace.TEMPORAL:
            hallazgos.append(
                Hallazgo(
                    codigo="ALC_003",
                    severidad=Severidad.INFORMATIVA,
                    mensaje=f"{objeto.identificador} es un tablespace temporal: RMAN no lo respalda, se ignora.",
                    sujeto=objeto.identificador,
                )
            )
    return hallazgos


@regla("ALC_004")
def alc_004_parcial_sin_controlfile_ni_spfile(contexto: ContextoValidacion) -> list[Hallazgo]:
    estrategia = contexto.estrategia
    if not _es_parcial(estrategia):
        return []
    tipos = {o.tipo for o in estrategia.alcance}
    if TipoObjeto.CONTROLFILE in tipos or TipoObjeto.SPFILE in tipos:
        return []
    return [
        Hallazgo(
            codigo="ALC_004",
            severidad=Severidad.RECOMENDACION,
            mensaje="El alcance es parcial y no incluye el control file ni el SPFILE.",
            sujeto=estrategia.codigo,
            accion_sugerida="Agregue el control file y el SPFILE al alcance para facilitar la recuperación.",
        )
    ]


@regla("ALC_005")
def alc_005_parcial_sin_system_ni_undo(contexto: ContextoValidacion) -> list[Hallazgo]:
    estrategia = contexto.estrategia
    if not _es_parcial(estrategia):
        return []
    objetos_tablespace = [o for o in estrategia.alcance if o.tipo is TipoObjeto.TABLESPACE]
    if not objetos_tablespace:
        return []
    for objeto in objetos_tablespace:
        _, nombre = _nombre_pdb_y_tablespace(objeto.identificador)
        if nombre == "SYSTEM":
            return []
        info = _tablespace_info(objeto, contexto.perfil)
        if info is not None and info.contenido is ContenidoTablespace.UNDO:
            return []
    return [
        Hallazgo(
            codigo="ALC_005",
            severidad=Severidad.RECOMENDACION,
            mensaje="El alcance parcial no incluye SYSTEM ni UNDO: no alcanza para una recuperación total.",
            sujeto=estrategia.codigo,
            accion_sugerida="Incluya SYSTEM y UNDO en el alcance, o documente que no cubre una recuperación total.",
        )
    ]


@regla("ALC_006")
def alc_006_estrategia_sobre_pdb(contexto: ContextoValidacion) -> list[Hallazgo]:
    estrategia = contexto.estrategia
    incluye_pdb = any(
        o.tipo is TipoObjeto.PDB
        or (o.tipo is TipoObjeto.TABLESPACE and _nombre_pdb_y_tablespace(o.identificador)[0] not in (None, RAIZ_CDB))
        for o in estrategia.alcance
    )
    if not incluye_pdb:
        return []
    return [
        Hallazgo(
            codigo="ALC_006",
            severidad=Severidad.INFORMATIVA,
            mensaje="La estrategia protege una PDB: el control file, el SPFILE y los archived logs son de la CDB.",
            sujeto=estrategia.codigo,
        )
    ]


@regla("ALC_007")
def alc_007_objeto_alta_en_estrategia_baja(contexto: ContextoValidacion) -> list[Hallazgo]:
    estrategia = contexto.estrategia
    if estrategia.prioridad is not Prioridad.BAJA:
        return []
    return [
        Hallazgo(
            codigo="ALC_007",
            severidad=Severidad.ADVERTENCIA,
            mensaje=f"{objeto.identificador} tiene prioridad ALTA dentro de una estrategia de prioridad BAJA.",
            sujeto=objeto.identificador,
            accion_sugerida="Revise si este objeto debería estar en una estrategia de mayor prioridad.",
        )
        for objeto in estrategia.alcance
        if objeto.prioridad is Prioridad.ALTA
    ]


@regla("ALC_008")
def alc_008_tablespace_solo_lectura(contexto: ContextoValidacion) -> list[Hallazgo]:
    hallazgos = []
    for objeto in contexto.estrategia.alcance:
        info = _tablespace_info(objeto, contexto.perfil)
        if info is not None and info.estado == "READ ONLY":
            hallazgos.append(
                Hallazgo(
                    codigo="ALC_008",
                    severidad=Severidad.INFORMATIVA,
                    mensaje=f"{objeto.identificador} es un tablespace de solo lectura.",
                    sujeto=objeto.identificador,
                    accion_sugerida="Active 'omitir_solo_lectura' (SKIP READONLY) para no copiarlo en cada ejecución.",
                )
            )
    return hallazgos
