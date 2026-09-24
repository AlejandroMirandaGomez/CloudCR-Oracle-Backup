from cloudcr_backup.domain.enums import LogMode, Severidad
from cloudcr_backup.domain.perfil_bd import ControlfileInfo, PerfilBD, RedoMiembro
from cloudcr_backup.oracle.observaciones import MENSAJE_NOARCHIVELOG, observar


def _codigos(perfil: PerfilBD) -> set[str]:
    return {h.codigo for h in observar(perfil)}


def test_instancia_de_pruebas_real(perfil_xe: PerfilBD) -> None:
    hallazgos = observar(perfil_xe)
    assert {h.codigo for h in hallazgos} == {"ARCH_001", "ARCH_010", "RED_001", "CTL_002", "DIS_001"}
    assert hallazgos[0].severidad is Severidad.ADVERTENCIA
    assert hallazgos[0].mensaje == MENSAJE_NOARCHIVELOG


def test_archivelog_no_emite_advertencia(perfil_xe: PerfilBD) -> None:
    perfil = perfil_xe.model_copy(update={"log_mode": LogMode.ARCHIVELOG, "destino_archivado_configurado": True})
    assert "ARCH_001" not in _codigos(perfil)
    assert "ARCH_010" not in _codigos(perfil)


def test_redo_multiplexado_no_recomienda(perfil_xe: PerfilBD) -> None:
    grupos = [
        g.model_copy(
            update={"miembros": [*g.miembros, RedoMiembro(ruta="D:\\redo\\copia.log", estado=None, tipo="ONLINE")]}
        )
        for g in perfil_xe.redo_grupos
    ]
    assert "RED_001" not in _codigos(perfil_xe.model_copy(update={"redo_grupos": grupos}))


def test_un_solo_control_file_es_advertencia(perfil_xe: PerfilBD) -> None:
    perfil = perfil_xe.model_copy(update={"controlfiles": perfil_xe.controlfiles[:1]})
    assert "CTL_001" in _codigos(perfil)
    assert "CTL_002" not in _codigos(perfil)


def test_control_files_en_discos_distintos(perfil_xe: PerfilBD) -> None:
    otro = ControlfileInfo(ruta="D:\\ORADATA\\XE\\CONTROL02.CTL", bytes=1, estado=None)
    perfil = perfil_xe.model_copy(update={"controlfiles": [perfil_xe.controlfiles[0], otro]})
    assert "CTL_002" not in _codigos(perfil)
    assert "DIS_001" not in _codigos(perfil)


def test_datafile_cerca_del_limite(perfil_xe: PerfilBD) -> None:
    lleno = perfil_xe.datafiles[0].model_copy(update={"autoextensible": False, "bytes_libres": 0})
    perfil = perfil_xe.model_copy(update={"datafiles": [lleno, *perfil_xe.datafiles[1:]]})
    hallazgos = [h for h in observar(perfil) if h.codigo == "DF_001"]
    assert len(hallazgos) == 1
    assert hallazgos[0].sujeto == f"datafile:{lleno.file_id}"


def test_pdb_cerrada(perfil_xe: PerfilBD) -> None:
    contenedores = [
        c.model_copy(update={"open_mode": "MOUNTED"}) if c.nombre == "XEPDB1" else c for c in perfil_xe.contenedores
    ]
    assert "CON_001" in _codigos(perfil_xe.model_copy(update={"contenedores": contenedores}))


def test_sin_spfile(perfil_xe: PerfilBD) -> None:
    sin_spfile = [a for a in perfil_xe.archivos_parametros if not a.en_uso]
    assert "PAR_001" in _codigos(perfil_xe.model_copy(update={"archivos_parametros": sin_spfile}))
