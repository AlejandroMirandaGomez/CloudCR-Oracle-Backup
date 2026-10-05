from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from cloudcr_backup.domain.enums import (
    DiaSemana,
    EstadoEstrategia,
    ModoRespaldo,
    TipoFrecuencia,
    TipoObjeto,
    TipoRespaldo,
)
from cloudcr_backup.services.solicitud_estrategia import SolicitudEstrategia, construir_estrategia
from tests.unit.ayudas_solicitud import datos_solicitud, solicitud

DESTINO = r"C:\backups\XE"


def _tarea_a_mano(**programacion: Any) -> dict[str, Any]:
    return {
        "como": {"tipo_respaldo": "INCREMENTAL_N0", "modo_respaldo": "EN_LINEA"},
        "programacion": {"tipo_frecuencia": "DIARIA", "horas": ["13:00"], **programacion},
    }


def test_el_codigo_se_normaliza_a_mayusculas() -> None:
    assert solicitud(DESTINO, codigo="  est010 ").codigo == "EST010"


@pytest.mark.parametrize("codigo", ["", "EST 1", "EST/1", "..\\x", "E" * 21, "ÉST1"])
def test_codigo_invalido_se_rechaza(codigo: str) -> None:
    with pytest.raises(ValidationError):
        solicitud(DESTINO, codigo=codigo)


def test_descripcion_vacia_queda_en_nulo() -> None:
    assert solicitud(DESTINO, descripcion="   ").descripcion is None


def test_responsable_es_obligatorio() -> None:
    with pytest.raises(ValidationError):
        solicitud(DESTINO, creada_por="")


@pytest.mark.parametrize("nombre", ["", "   "])
def test_nombre_vacio_usa_el_codigo(nombre: str) -> None:
    pedida = solicitud(DESTINO, nombre=nombre)
    assert pedida.nombre == "EST010"
    assert construir_estrategia(pedida).nombre == "EST010"


def test_nombre_ausente_usa_el_codigo() -> None:
    datos = datos_solicitud(DESTINO)
    del datos["nombre"]
    assert SolicitudEstrategia.model_validate(datos).nombre == "EST010"


def test_nombre_escrito_se_conserva() -> None:
    assert solicitud(DESTINO, nombre="  Producción diaria ").nombre == "Producción diaria"


def test_destino_relativo_o_vacio_se_rechaza() -> None:
    for ruta in ("", "backups", r"backups\XE"):
        with pytest.raises(ValidationError):
            solicitud(ruta)


def test_destino_se_normaliza() -> None:
    assert solicitud("C:/backups/XE/").destino_ruta == r"C:\backups\XE"


def test_no_se_aceptan_esquema_y_tareas_a_la_vez() -> None:
    with pytest.raises(ValidationError):
        solicitud(DESTINO, tareas=[_tarea_a_mano()])


def test_zona_horaria_inexistente_se_rechaza() -> None:
    with pytest.raises(ValidationError):
        solicitud(DESTINO, esquema={**datos_solicitud(DESTINO)["esquema"], "zona_horaria": "Marte/Olimpo"})
    with pytest.raises(ValidationError):
        solicitud(DESTINO, esquema=None, tareas=[_tarea_a_mano(zona_horaria="Marte/Olimpo")])


@pytest.mark.parametrize("campo", ["ventana_dias", "redundancia", "archived_logs_dias"])
def test_retencion_no_acepta_valores_menores_a_uno(campo: str) -> None:
    for valor in (0, -3):
        with pytest.raises(ValidationError):
            solicitud(DESTINO, retencion={campo: valor})


def test_intervalo_menor_a_un_minuto_se_rechaza() -> None:
    with pytest.raises(ValidationError):
        solicitud(DESTINO, esquema=None, tareas=[_tarea_a_mano(tipo_frecuencia="INTERVALO", intervalo_minutos=0)])


def test_hora_invalida_se_rechaza() -> None:
    with pytest.raises(ValidationError):
        solicitud(DESTINO, esquema=None, tareas=[_tarea_a_mano(horas=["25:99"])])


def test_demasiadas_tareas_se_rechazan() -> None:
    with pytest.raises(ValidationError):
        solicitud(DESTINO, esquema=None, tareas=[_tarea_a_mano() for _ in range(21)])


def test_construye_la_estrategia_desde_un_esquema() -> None:
    estrategia = construir_estrategia(solicitud(DESTINO))
    assert estrategia.codigo == "EST010"
    assert estrategia.estado is EstadoEstrategia.INACTIVA
    assert [t.codigo for t in estrategia.tareas] == ["T1", "T2"]
    assert estrategia.tareas[0].como.tipo_respaldo is TipoRespaldo.INCREMENTAL_N0
    assert estrategia.tareas[0].programacion.dias_semana == [DiaSemana.DOMINGO]
    assert {t.destino.ruta for t in estrategia.tareas} == {DESTINO}
    assert estrategia.retencion.ventana_dias == 30
    assert {o.tipo for o in estrategia.alcance} == {TipoObjeto.TABLESPACE, TipoObjeto.CONTROLFILE, TipoObjeto.SPFILE}


def test_el_esquema_aplica_la_zona_horaria_y_la_ventana() -> None:
    esquema = {
        **datos_solicitud(DESTINO)["esquema"],
        "zona_horaria": "America/Mexico_City",
        "ventana": {"inicio": "01:00", "fin": "05:00"},
    }
    estrategia = construir_estrategia(solicitud(DESTINO, esquema=esquema))
    for tarea in estrategia.tareas:
        assert tarea.programacion.zona_horaria == "America/Mexico_City"
        assert tarea.programacion.ventana is not None


def test_construye_tareas_a_mano_con_destino_comun_y_codigos_correlativos() -> None:
    tareas = [_tarea_a_mano(), _tarea_a_mano(tipo_frecuencia="SEMANAL", dias_semana=["VIE", "LUN", "LUN"])]
    estrategia = construir_estrategia(solicitud(DESTINO, esquema=None, tareas=tareas))
    assert [t.codigo for t in estrategia.tareas] == ["T1", "T2"]
    assert estrategia.tareas[0].como.modo_respaldo is ModoRespaldo.EN_LINEA
    assert estrategia.tareas[1].programacion.tipo_frecuencia is TipoFrecuencia.SEMANAL
    assert estrategia.tareas[1].programacion.dias_semana == [DiaSemana.LUNES, DiaSemana.VIERNES]
    assert {t.destino.ruta for t in estrategia.tareas} == {DESTINO}


def test_activar_marca_la_estrategia_como_activa() -> None:
    assert construir_estrategia(solicitud(DESTINO, activar=True)).estado is EstadoEstrategia.ACTIVA


def test_el_alcance_no_repite_objetos() -> None:
    alcance = [*datos_solicitud(DESTINO)["alcance"], {"tipo": "SPFILE", "identificador": "", "prioridad": "BAJA"}]
    estrategia = construir_estrategia(solicitud(DESTINO, alcance=alcance))
    assert len(estrategia.alcance) == 3


def test_una_solicitud_sin_tareas_ni_alcance_se_construye_para_que_la_validacion_la_senale() -> None:
    estrategia = construir_estrategia(solicitud(DESTINO, esquema=None, alcance=[]))
    assert estrategia.tareas == []
    assert estrategia.alcance == []


def test_el_modelo_es_serializable_a_json() -> None:
    texto = solicitud(DESTINO).model_dump_json()
    assert SolicitudEstrategia.model_validate_json(texto).codigo == "EST010"


def test_el_destino_no_necesita_existir_para_construir(tmp_path: Path) -> None:
    assert construir_estrategia(solicitud(str(tmp_path / "no_existe"))).tareas
