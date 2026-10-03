import csv
import io
import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from cloudcr_backup.domain.enums import EstadoEjecucion, EstadoPrueba, TipoRespaldo
from cloudcr_backup.domain.historial import FilaHistorial
from cloudcr_backup.presentacion.formato import Tono
from cloudcr_backup.presentacion.historial import (
    COLUMNAS,
    SIMBOLO_ESTADO,
    TEXTO_RESULTADO,
    construir_tabla,
    formato_duracion,
)
from cloudcr_backup.reports.historial import BOM_UTF8, FormatoHistorial, a_csv, a_html, a_markdown, nombre_archivo
from tests.unit.alertas_falsas import fila

GENERADO = datetime(2026, 10, 3, 12, 0, tzinfo=ZoneInfo("America/Costa_Rica"))


def test_columnas_en_el_orden_pedido() -> None:
    assert COLUMNAS == (
        "Fecha", "BD", "Estrategia", "Tarea", "Hora", "◆", "Tipo", "Inicio", "Fin", "Duración", "Resultado", "Pruebas",
    )


@pytest.mark.parametrize(
    ("estado", "simbolo", "texto"),
    [
        (EstadoEjecucion.EXITOSA, "●", "Exitoso"),
        (EstadoEjecucion.CON_ADVERTENCIAS, "▲", "Con advertencias"),
        (EstadoEjecucion.FALLIDA, "✕", "Error"),
        (EstadoEjecucion.BLOQUEADA, "✕", "Bloqueada"),
        (EstadoEjecucion.NO_EJECUTADA, "○", "No ejecutada"),
        (EstadoEjecucion.CANCELADA, "○", "Cancelada"),
        (EstadoEjecucion.EN_CURSO, "◐", "En curso"),
        (EstadoEjecucion.PROGRAMADA, "◌", "Programada"),
    ],
)
def test_cada_estado_tiene_simbolo_y_texto(estado: EstadoEjecucion, simbolo: str, texto: str) -> None:
    [resultado] = construir_tabla([fila(estado=estado)]).filas
    assert resultado.simbolo == simbolo
    assert resultado.resultado == texto
    assert set(SIMBOLO_ESTADO) == set(TEXTO_RESULTADO) == set(EstadoEjecucion)


def test_horas_en_la_zona_de_la_tarea_y_tipo_con_las_dos_etiquetas() -> None:
    programada = datetime(2026, 10, 3, 19, 0, tzinfo=UTC)
    original = fila(programada=programada)
    datos = original.model_copy(
        update={
            "inicio": programada + timedelta(seconds=5),
            "fin": programada + timedelta(minutes=3, seconds=12),
            "duracion_segundos": None,
        }
    )
    [resultado] = construir_tabla([datos]).filas
    assert resultado.celdas() == [
        "2026-10-03", "XE", "EST001", "T1", "13:00", "●", "Incremental nivel 1 acumulativo (Incremental acumulativo)",
        "13:00:05", "13:03:12", "3 min 07 s", "Exitoso", "OK",
    ]


def test_tipo_del_nivel_0_usa_el_termino_de_clase() -> None:
    datos = fila().model_copy(update={"tipo_respaldo": TipoRespaldo.INCREMENTAL_N0})
    assert construir_tabla([datos]).filas[0].tipo == "Incremental nivel 0 (total+)"


def test_inicio_tardio_se_marca() -> None:
    programada = datetime(2026, 10, 3, 19, 0, tzinfo=UTC)
    tardia = fila(programada=programada).model_copy(update={"inicio": programada + timedelta(minutes=45)})
    tabla = construir_tabla([tardia])
    assert tabla.filas[0].tardia
    assert tabla.filas[0].retraso_minutos == 45
    assert any("tardías" in nota for nota in tabla.notas)
    assert not construir_tabla([fila()]).filas[0].tardia


def test_inicio_en_otro_dia_muestra_la_fecha() -> None:
    programada = datetime(2026, 10, 4, 5, 0, tzinfo=UTC)
    datos = fila(programada=programada).model_copy(update={"inicio": programada + timedelta(hours=8)})
    assert construir_tabla([datos]).filas[0].inicio == "04/10 07:00:00"


def test_sin_inicio_ni_fin_muestra_guiones() -> None:
    datos = fila(estado=EstadoEjecucion.NO_EJECUTADA, prueba=EstadoPrueba.NO_APLICA).model_copy(
        update={"inicio": None, "fin": None, "duracion_segundos": None}
    )
    resultado = construir_tabla([datos]).filas[0]
    assert (resultado.inicio, resultado.fin, resultado.duracion) == ("—", "—", "—")
    assert resultado.pruebas == "No aplica"
    assert resultado.tono_resultado is Tono.ATENUADO


def test_notas_de_pruebas_pendientes_y_simulacion() -> None:
    tabla = construir_tabla(
        [fila(prueba=EstadoPrueba.PENDIENTE), fila(41, mensaje="SIMULACION: ejecución de prueba")]
    )
    assert any("Pendiente" in nota for nota in tabla.notas)
    assert any("SIMULACION" in nota for nota in tabla.notas)


def test_formato_duracion() -> None:
    assert formato_duracion(None) == "—"
    assert formato_duracion(42) == "42 s"
    assert formato_duracion(175) == "2 min 55 s"
    assert formato_duracion(3725) == "1 h 02 min"


def _peligrosa() -> FilaHistorial:
    return fila(mensaje='Error "grave"; <script>alert(1)</script>').model_copy(
        update={"estrategia": "EST<script>", "bd": "X;E"}
    )


def test_csv_con_bom_separador_explicito_y_comillas() -> None:
    contenido = a_csv(construir_tabla([_peligrosa()]))
    assert contenido.startswith(BOM_UTF8)
    filas = list(csv.reader(io.StringIO(contenido.removeprefix(BOM_UTF8)), delimiter=";"))
    assert filas[0][:12] == list(COLUMNAS)
    assert filas[0][12:] == ["Ejecución", "Tamaño", "Mensaje"]
    assert filas[1][1] == "X;E"
    assert filas[1][14] == 'Error "grave"; <script>alert(1)</script>'
    assert '"X;E"' in contenido


def test_markdown_tiene_tabla_y_leyenda() -> None:
    texto = a_markdown(construir_tabla([fila()]), "Historial", "BD XE", GENERADO)
    assert "| Fecha | BD | Estrategia |" in texto
    assert "Símbolos: ● exitosa" in texto
    assert "Filtros: BD XE" in texto


def test_html_autocontenido_escapado_con_temas_e_impresion() -> None:
    html = a_html(construir_tabla([_peligrosa()]), "Historial", "ninguno", GENERADO)
    assert "<script>" not in html
    assert "EST&lt;script&gt;" in html
    assert "prefers-color-scheme: dark" in html
    assert "@media print" in html
    assert not re.search(r"(src|href)=\"https?://", html)
    assert "<link" not in html


def test_html_sin_filas() -> None:
    assert "Sin ejecuciones para estos filtros." in a_html(construir_tabla([]), "H", "ninguno", GENERADO)


def test_nombre_de_archivo() -> None:
    assert nombre_archivo(FormatoHistorial.CSV, GENERADO) == "historial-20261003-120000.csv"
