from cloudcr_backup.domain.enums import LogMode, TipoObjeto
from cloudcr_backup.domain.perfil_bd import PerfilBD
from cloudcr_backup.presentacion.seleccion import OpcionAlcance, opciones_de_alcance


def _por_identificador(opciones: dict[str, OpcionAlcance], tipo: TipoObjeto, identificador: str) -> OpcionAlcance:
    return next(o for o in opciones.values() if o.tipo is tipo and o.identificador == identificador)


def test_la_instancia_es_la_base_completa(perfil_xe: PerfilBD) -> None:
    opciones = opciones_de_alcance(perfil_xe)
    raiz = _por_identificador(opciones, TipoObjeto.BASE_DATOS, "")
    assert raiz.nodo_id == "instancia"
    assert raiz.cubierta_por == ()
    assert raiz.habilitada


def test_tablespaces_de_la_raiz_no_llevan_prefijo_y_los_de_una_pdb_si(perfil_xe: PerfilBD) -> None:
    opciones = opciones_de_alcance(perfil_xe)
    en_raiz = _por_identificador(opciones, TipoObjeto.TABLESPACE, "USERS")
    en_pdb = _por_identificador(opciones, TipoObjeto.TABLESPACE, "XEPDB1:USERS")
    assert en_raiz.nodo_id != en_pdb.nodo_id
    assert en_raiz.cubierta_por == ("instancia",)
    assert en_pdb.cubierta_por[-1] == "instancia"
    assert len(en_pdb.cubierta_por) == 2


def test_la_pdb_es_seleccionable_y_cubre_sus_tablespaces_y_datafiles(perfil_xe: PerfilBD) -> None:
    opciones = opciones_de_alcance(perfil_xe)
    pdb = _por_identificador(opciones, TipoObjeto.PDB, "XEPDB1")
    assert pdb.cubierta_por == ("instancia",)
    tablespace = _por_identificador(opciones, TipoObjeto.TABLESPACE, "XEPDB1:USERS")
    assert pdb.nodo_id in tablespace.cubierta_por
    datafiles_de_la_pdb = [
        o for o in opciones.values() if o.tipo is TipoObjeto.DATAFILE and tablespace.nodo_id in o.cubierta_por
    ]
    assert datafiles_de_la_pdb
    for datafile in datafiles_de_la_pdb:
        assert datafile.cubierta_por == (tablespace.nodo_id, pdb.nodo_id, "instancia")


def test_la_raiz_cdb_y_la_semilla_no_son_pdbs_seleccionables(perfil_xe: PerfilBD) -> None:
    opciones = opciones_de_alcance(perfil_xe)
    pdbs = [o.identificador for o in opciones.values() if o.tipo is TipoObjeto.PDB]
    assert pdbs == ["XEPDB1"]


def test_la_semilla_y_los_temporales_no_se_ofrecen(perfil_xe: PerfilBD) -> None:
    opciones = opciones_de_alcance(perfil_xe)
    identificadores = {o.identificador for o in opciones.values() if o.tipo is TipoObjeto.TABLESPACE}
    assert "TEMP" not in identificadores
    assert "XEPDB1:TEMP" not in identificadores
    assert not any(i.startswith("PDB$SEED") for i in identificadores)


def test_los_datafiles_se_identifican_por_su_numero(perfil_xe: PerfilBD) -> None:
    opciones = opciones_de_alcance(perfil_xe)
    numeros = {o.identificador for o in opciones.values() if o.tipo is TipoObjeto.DATAFILE}
    numeros_esperados = {str(d.file_id) for d in perfil_xe.datafiles if d.con_id != 2}
    assert numeros == numeros_esperados


def test_archived_logs_se_deshabilitan_en_noarchivelog(perfil_xe: PerfilBD) -> None:
    opciones = opciones_de_alcance(perfil_xe)
    archivelog = _por_identificador(opciones, TipoObjeto.ARCHIVELOG, "")
    assert not archivelog.habilitada
    assert archivelog.motivo is not None
    assert "NOARCHIVELOG" in archivelog.motivo


def test_archived_logs_se_habilitan_en_archivelog(perfil_xe: PerfilBD) -> None:
    opciones = opciones_de_alcance(perfil_xe.model_copy(update={"log_mode": LogMode.ARCHIVELOG}))
    assert _por_identificador(opciones, TipoObjeto.ARCHIVELOG, "").habilitada


def test_spfile_y_control_files_estan_habilitados_cuando_existen(perfil_xe: PerfilBD) -> None:
    opciones = opciones_de_alcance(perfil_xe)
    assert _por_identificador(opciones, TipoObjeto.SPFILE, "").habilitada
    assert _por_identificador(opciones, TipoObjeto.CONTROLFILE, "").habilitada


def test_la_base_completa_cubre_control_files_y_spfile_pero_no_archived_logs(perfil_xe: PerfilBD) -> None:
    opciones = opciones_de_alcance(perfil_xe.model_copy(update={"log_mode": LogMode.ARCHIVELOG}))
    assert _por_identificador(opciones, TipoObjeto.CONTROLFILE, "").cubierta_por == ("instancia",)
    assert _por_identificador(opciones, TipoObjeto.SPFILE, "").cubierta_por == ("instancia",)
    assert _por_identificador(opciones, TipoObjeto.ARCHIVELOG, "").cubierta_por == ()


def test_sin_spfile_ni_control_files_se_deshabilitan(perfil_xe: PerfilBD) -> None:
    perfil = perfil_xe.model_copy(update={"archivos_parametros": [], "controlfiles": []})
    opciones = opciones_de_alcance(perfil)
    assert not _por_identificador(opciones, TipoObjeto.SPFILE, "").habilitada
    assert not _por_identificador(opciones, TipoObjeto.CONTROLFILE, "").habilitada
