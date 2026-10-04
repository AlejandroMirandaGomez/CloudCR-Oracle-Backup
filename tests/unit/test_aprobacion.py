from pathlib import Path

import pytest

from cloudcr_backup.domain.enums import EstadoScript, ModoRespaldo
from cloudcr_backup.rman import aprobacion
from cloudcr_backup.rman.aprobacion import AprobacionRechazada

ORO = Path(__file__).resolve().parents[1] / "fixtures" / "scripts_oro"
CONSISTENTE = (ORO / "est002_t1.rman").read_text(encoding="ascii")
EN_LINEA = (ORO / "est001_t1.rman").read_text(encoding="ascii")


def test_hash_sha256_es_estable_y_coincide_con_los_bytes() -> None:
    hash_texto = aprobacion.calcular_hash(EN_LINEA)
    assert len(hash_texto) == 64
    assert hash_texto == aprobacion.hash_de_bytes(EN_LINEA.encode("ascii"))
    assert aprobacion.script_intacto(EN_LINEA.encode("ascii"), hash_texto.upper())


def test_script_modificado_a_mano_no_esta_intacto() -> None:
    hash_texto = aprobacion.calcular_hash(EN_LINEA)
    alterado = EN_LINEA.replace("TABLESPACE", "DATABASE").encode("ascii")
    assert not aprobacion.script_intacto(alterado, hash_texto)


def test_modo_se_deduce_del_contenido() -> None:
    assert aprobacion.modo_de_script(CONSISTENTE) is ModoRespaldo.CONSISTENTE
    assert aprobacion.modo_de_script(EN_LINEA) is ModoRespaldo.EN_LINEA


def test_consistente_sin_aceptar_la_caida_se_rechaza_con_mensaje_claro() -> None:
    with pytest.raises(AprobacionRechazada) as error:
        aprobacion.validar_aprobacion(
            EstadoScript.BORRADOR, CONSISTENTE, aprobacion.calcular_hash(CONSISTENTE), acepto_caida=False
        )
    assert "SHUTDOWN IMMEDIATE" in error.value.mensaje
    assert error.value.sugerencia is not None
    assert "--acepto-caida" in error.value.sugerencia


def test_consistente_con_caida_aceptada_se_aprueba() -> None:
    aprobacion.validar_aprobacion(
        EstadoScript.BORRADOR, CONSISTENTE, aprobacion.calcular_hash(CONSISTENTE), acepto_caida=True
    )


def test_en_linea_no_exige_aceptar_caida() -> None:
    aprobacion.validar_aprobacion(EstadoScript.BORRADOR, EN_LINEA, aprobacion.calcular_hash(EN_LINEA), False)


def test_contenido_que_no_coincide_con_el_hash_no_se_aprueba() -> None:
    with pytest.raises(AprobacionRechazada, match="alterado"):
        aprobacion.validar_aprobacion(EstadoScript.BORRADOR, EN_LINEA + "X", aprobacion.calcular_hash(EN_LINEA), False)


@pytest.mark.parametrize(
    ("actual", "nuevo", "permitido"),
    [
        (EstadoScript.BORRADOR, EstadoScript.APROBADO, True),
        (EstadoScript.BORRADOR, EstadoScript.RECHAZADO, True),
        (EstadoScript.APROBADO, EstadoScript.OBSOLETO, True),
        (EstadoScript.RECHAZADO, EstadoScript.OBSOLETO, True),
        (EstadoScript.APROBADO, EstadoScript.RECHAZADO, False),
        (EstadoScript.RECHAZADO, EstadoScript.APROBADO, False),
        (EstadoScript.OBSOLETO, EstadoScript.APROBADO, False),
    ],
)
def test_transiciones(actual: EstadoScript, nuevo: EstadoScript, permitido: bool) -> None:
    if permitido:
        aprobacion.validar_transicion(actual, nuevo)
    else:
        with pytest.raises(AprobacionRechazada):
            aprobacion.validar_transicion(actual, nuevo)
