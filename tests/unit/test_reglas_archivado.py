from cloudcr_backup.domain.enums import LogMode, ModoRespaldo, Severidad, TipoObjeto
from cloudcr_backup.domain.perfil_bd import ContenedorInfo
from cloudcr_backup.validation import motor, reglas  # noqa: F401
from cloudcr_backup.validation.contexto import ContextoValidacion, servicio_de_dsn
from tests.unit.test_validacion import _estrategia, _perfil


def _codigos(contexto: ContextoValidacion) -> set[str]:
    return {h.codigo for h in motor.validar(contexto)}


def test_arch_004_bloquea_archivelogs_sin_archivelog() -> None:
    contexto = ContextoValidacion(
        estrategia=_estrategia(ModoRespaldo.CONSISTENTE, incluir_archivelog=True), perfil=_perfil(LogMode.NOARCHIVELOG)
    )
    hallazgos = motor.validar(contexto)
    assert any(h.codigo == "ARCH_004" and h.severidad is Severidad.ERROR for h in hallazgos)
    assert motor.hay_bloqueantes(hallazgos)


def test_arch_004_no_se_dispara_sin_archivelogs_o_con_archivelog() -> None:
    sin_logs = ContextoValidacion(
        estrategia=_estrategia(ModoRespaldo.CONSISTENTE), perfil=_perfil(LogMode.NOARCHIVELOG)
    )
    con_archivelog = ContextoValidacion(
        estrategia=_estrategia(ModoRespaldo.EN_LINEA, incluir_archivelog=True), perfil=_perfil(LogMode.ARCHIVELOG)
    )
    assert "ARCH_004" not in _codigos(sin_logs)
    assert "ARCH_004" not in _codigos(con_archivelog)


def test_arch_006_avisa_de_alcance_parcial_en_noarchivelog() -> None:
    contexto = ContextoValidacion(
        estrategia=_estrategia(ModoRespaldo.CONSISTENTE), perfil=_perfil(LogMode.NOARCHIVELOG)
    )
    hallazgos = motor.validar(contexto)
    assert any(h.codigo == "ARCH_006" and h.severidad is Severidad.ADVERTENCIA for h in hallazgos)


def test_arch_006_no_se_dispara_en_archivelog_ni_con_la_base_completa() -> None:
    en_archivelog = ContextoValidacion(
        estrategia=_estrategia(ModoRespaldo.EN_LINEA), perfil=_perfil(LogMode.ARCHIVELOG)
    )
    completa = _estrategia(ModoRespaldo.CONSISTENTE)
    completa.alcance[0].tipo = TipoObjeto.BASE_DATOS
    sobre_la_base = ContextoValidacion(estrategia=completa, perfil=_perfil(LogMode.NOARCHIVELOG))
    assert "ARCH_006" not in _codigos(en_archivelog)
    assert "ARCH_006" not in _codigos(sobre_la_base)


def test_arch_007_avisa_de_la_caida_en_modo_consistente() -> None:
    contexto = ContextoValidacion(
        estrategia=_estrategia(ModoRespaldo.CONSISTENTE), perfil=_perfil(LogMode.NOARCHIVELOG)
    )
    hallazgos = motor.validar(contexto)
    assert any(h.codigo == "ARCH_007" and h.severidad is Severidad.ADVERTENCIA for h in hallazgos)


def test_arch_007_resuelve_el_modo_auto_y_no_se_dispara_en_linea() -> None:
    auto_sin_archivelog = ContextoValidacion(
        estrategia=_estrategia(ModoRespaldo.AUTO), perfil=_perfil(LogMode.NOARCHIVELOG)
    )
    en_linea = ContextoValidacion(estrategia=_estrategia(ModoRespaldo.EN_LINEA), perfil=_perfil(LogMode.ARCHIVELOG))
    assert "ARCH_007" in _codigos(auto_sin_archivelog)
    assert "ARCH_007" not in _codigos(en_linea)


def _perfil_con_bkpcat(log_mode: LogMode):
    perfil = _perfil(log_mode)
    perfil.contenedores = [ContenedorInfo(con_id=4, nombre="BKPCAT", open_mode="READ WRITE")]
    return perfil


def test_arch_009_avisa_si_el_repositorio_vive_en_la_cdb_respaldada() -> None:
    contexto = ContextoValidacion(
        estrategia=_estrategia(ModoRespaldo.CONSISTENTE),
        perfil=_perfil_con_bkpcat(LogMode.NOARCHIVELOG),
        repositorio_servicio="bkpcat",
    )
    hallazgos = motor.validar(contexto)
    assert any(h.codigo == "ARCH_009" and h.severidad is Severidad.ADVERTENCIA for h in hallazgos)


def test_arch_009_no_se_dispara_en_linea_ni_con_repositorio_externo_o_sin_dato() -> None:
    en_linea = ContextoValidacion(
        estrategia=_estrategia(ModoRespaldo.EN_LINEA),
        perfil=_perfil_con_bkpcat(LogMode.ARCHIVELOG),
        repositorio_servicio="BKPCAT",
    )
    externo = ContextoValidacion(
        estrategia=_estrategia(ModoRespaldo.CONSISTENTE),
        perfil=_perfil_con_bkpcat(LogMode.NOARCHIVELOG),
        repositorio_servicio="OTRO",
    )
    sin_dato = ContextoValidacion(
        estrategia=_estrategia(ModoRespaldo.CONSISTENTE), perfil=_perfil_con_bkpcat(LogMode.NOARCHIVELOG)
    )
    assert "ARCH_009" not in _codigos(en_linea)
    assert "ARCH_009" not in _codigos(externo)
    assert "ARCH_009" not in _codigos(sin_dato)


def test_servicio_de_dsn() -> None:
    assert servicio_de_dsn("localhost:1521/BKPCAT") == "BKPCAT"
    assert servicio_de_dsn("localhost:1521") is None
    assert servicio_de_dsn(None) is None
