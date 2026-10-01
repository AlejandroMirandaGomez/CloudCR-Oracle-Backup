from datetime import time
from pathlib import Path

import pytest

from cloudcr_backup.domain.enums import ModoRespaldo, Prioridad, TipoFrecuencia, TipoObjeto, TipoRespaldo
from cloudcr_backup.domain.estrategia import Como, Destino, Estrategia, ObjetoAlcance, Programacion, Tarea, Ventana
from cloudcr_backup.strategy.yaml_io import (
    EstrategiaYamlInvalida,
    cargar_estrategia_yaml,
    estrategia_a_yaml,
    estrategia_desde_yaml,
    guardar_estrategia_yaml,
)


def _estrategia_est001() -> Estrategia:
    return Estrategia(
        bd_id=1,
        codigo="EST001",
        nombre="Producción diaria",
        prioridad=Prioridad.ALTA,
        creada_por="luis",
        alcance=[
            ObjetoAlcance(tipo=TipoObjeto.TABLESPACE, identificador="XEPDB1:VENTAS", prioridad=Prioridad.ALTA),
            ObjetoAlcance(tipo=TipoObjeto.TABLESPACE, identificador="XEPDB1:FINANZAS", prioridad=Prioridad.ALTA),
        ],
        tareas=[
            Tarea(
                codigo="T1",
                como=Como(tipo_respaldo=TipoRespaldo.INCREMENTAL_N1_ACUMULATIVO, modo_respaldo=ModoRespaldo.EN_LINEA),
                programacion=Programacion(
                    tipo_frecuencia=TipoFrecuencia.DIARIA,
                    horas=[time(13, 0), time(15, 0), time(18, 0), time(21, 0)],
                    ventana=Ventana(inicio=time(12, 30), fin=time(22, 0)),
                ),
                destino=Destino(ruta=r"C:\backups\XE"),
            )
        ],
    )


def test_ida_y_vuelta_produce_la_misma_estrategia() -> None:
    original = _estrategia_est001()
    recuperada = estrategia_desde_yaml(estrategia_a_yaml(original))
    assert recuperada == original


def test_el_yaml_generado_es_legible_por_un_humano() -> None:
    contenido = estrategia_a_yaml(_estrategia_est001())
    assert "codigo: EST001" in contenido
    assert "prioridad: ALTA" in contenido
    assert "13:00:00" in contenido


def test_yaml_con_sintaxis_invalida_da_un_error_legible() -> None:
    with pytest.raises(EstrategiaYamlInvalida, match="no se pudo interpretar"):
        estrategia_desde_yaml("codigo: EST001\n  nombre: mal indentado")


def test_yaml_con_lista_en_lugar_de_mapa_da_un_error_legible() -> None:
    with pytest.raises(EstrategiaYamlInvalida, match="un mapa de campos"):
        estrategia_desde_yaml("- EST001\n- EST002\n")


def test_yaml_con_campos_invalidos_da_un_error_legible() -> None:
    with pytest.raises(EstrategiaYamlInvalida, match="prioridad"):
        estrategia_desde_yaml("bd_id: 1\ncodigo: EST001\nnombre: X\nprioridad: URGENTE\ncreada_por: luis\n")


def test_guardar_y_cargar_desde_archivo(tmp_path: Path) -> None:
    ruta = tmp_path / "estrategias" / "est001.yaml"
    guardar_estrategia_yaml(_estrategia_est001(), ruta)
    assert ruta.exists()
    assert cargar_estrategia_yaml(ruta) == _estrategia_est001()


def test_cargar_un_archivo_que_no_existe_da_un_error_legible(tmp_path: Path) -> None:
    with pytest.raises(EstrategiaYamlInvalida, match="No existe"):
        cargar_estrategia_yaml(tmp_path / "no_existe.yaml")
