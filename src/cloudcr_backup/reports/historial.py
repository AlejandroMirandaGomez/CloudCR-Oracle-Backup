import csv
import html
import io
from datetime import datetime
from enum import StrEnum

from cloudcr_backup import __version__
from cloudcr_backup.presentacion.historial import LEYENDA_SIMBOLOS, TablaHistorial


class FormatoHistorial(StrEnum):
    CSV = "csv"
    MD = "md"
    HTML = "html"


TIPO_CONTENIDO = {
    FormatoHistorial.CSV: "text/csv; charset=utf-8",
    FormatoHistorial.MD: "text/markdown; charset=utf-8",
    FormatoHistorial.HTML: "text/html; charset=utf-8",
}

SEPARADOR_CSV = ";"
BOM_UTF8 = "\ufeff"
COLUMNAS_EXTRA = ("Ejecución", "Tamaño", "Mensaje")
TITULO_POR_DEFECTO = "Historial de ejecuciones de respaldo"

ESTILOS_HTML = """
:root { --fondo: #ffffff; --texto: #1b2230; --suave: #5b6576; --borde: #d9dee6; --cabecera: #eef1f5;
  --exito: #1d7a46; --advertencia: #9a6400; --peligro: #b3261e; --dato: #0b6a88; color-scheme: light dark; }
@media (prefers-color-scheme: dark) {
  :root { --fondo: #0f141b; --texto: #e6ebf2; --suave: #9aa6b8; --borde: #2b3644; --cabecera: #1e2733;
    --exito: #4cc788; --advertencia: #f0b43c; --peligro: #ff7b72; --dato: #4fc3e8; }
}
* { box-sizing: border-box; }
body { margin: 0; padding: 24px; background: var(--fondo); color: var(--texto);
  font: 14px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif; }
h1 { font-size: 20px; margin: 0 0 4px; }
p.meta { color: var(--suave); margin: 0 0 16px; }
.tabla { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--borde); white-space: nowrap; }
th { background: var(--cabecera); color: var(--suave); font-size: 12px; text-transform: uppercase; }
td.simbolo { text-align: center; }
.exito { color: var(--exito); } .advertencia { color: var(--advertencia); }
.peligro { color: var(--peligro); font-weight: 600; } .atenuado { color: var(--suave); } .dato { color: var(--dato); }
.tardia { font-style: italic; }
ul { color: var(--suave); }
@media print { body { padding: 0; background: #fff; color: #000; } th { background: #eee; color: #000; }
  .tabla { overflow: visible; } th, td { white-space: normal; font-size: 11px; } }
"""


def nombre_archivo(formato: FormatoHistorial, momento: datetime) -> str:
    return f"historial-{momento:%Y%m%d-%H%M%S}.{formato.value}"


def a_csv(tabla: TablaHistorial, separador: str = SEPARADOR_CSV) -> str:
    salida = io.StringIO()
    escritor = csv.writer(salida, delimiter=separador, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    escritor.writerow([*tabla.columnas, *COLUMNAS_EXTRA])
    for fila in tabla.filas:
        escritor.writerow([*fila.celdas(), str(fila.ejecucion_id), fila.tamano, fila.mensaje or ""])
    return BOM_UTF8 + salida.getvalue()


def _celda_md(texto: str) -> str:
    return texto.replace("|", "\\|").replace("\n", " ")


def a_markdown(tabla: TablaHistorial, titulo: str, filtros: str, generado_en: datetime) -> str:
    lineas = [
        f"# {titulo}",
        "",
        f"Generado el {generado_en:%Y-%m-%d %H:%M:%S %Z} con cloudcr-oracle-backup {__version__}. Filtros: {filtros}.",
        "",
        "| " + " | ".join(tabla.columnas) + " |",
        "|" + "---|" * len(tabla.columnas),
    ]
    for fila in tabla.filas:
        lineas.append("| " + " | ".join(_celda_md(c) for c in fila.celdas()) + " |")
    if not tabla.filas:
        lineas += ["", "Sin ejecuciones para estos filtros."]
    lineas += ["", "Símbolos: " + ", ".join(f"{s} {t}" for s, t in LEYENDA_SIMBOLOS) + "."]
    lineas += [f"- {nota}" for nota in tabla.notas]
    return "\n".join(lineas) + "\n"


def a_html(tabla: TablaHistorial, titulo: str, filtros: str, generado_en: datetime) -> str:
    cabecera = "".join(f"<th scope=\"col\">{html.escape(c)}</th>" for c in tabla.columnas)
    filas = []
    for fila in tabla.filas:
        celdas = fila.celdas()
        clases = ["" for _ in celdas]
        clases[5] = f"simbolo {fila.tono_resultado.value}"
        clases[10] = fila.tono_resultado.value
        clases[11] = fila.tono_pruebas.value
        if fila.tardia:
            clases[7] = "tardia"
        partes = [
            f"<td class=\"{clase}\">{html.escape(valor)}</td>" if clase else f"<td>{html.escape(valor)}</td>"
            for clase, valor in zip(clases, celdas, strict=True)
        ]
        titulo_fila = html.escape(fila.mensaje or "", quote=True)
        filas.append(f"<tr title=\"{titulo_fila}\">{''.join(partes)}</tr>")
    vacio = f"<tr><td colspan=\"{len(tabla.columnas)}\">Sin ejecuciones para estos filtros.</td></tr>"
    cuerpo = "".join(filas) or vacio
    leyenda = ", ".join(f"{html.escape(s)} {html.escape(t)}" for s, t in LEYENDA_SIMBOLOS)
    notas = "".join(f"<li>{html.escape(n)}</li>" for n in tabla.notas)
    return (
        "<!DOCTYPE html>\n<html lang=\"es\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{html.escape(titulo)}</title>\n<style>{ESTILOS_HTML}</style>\n</head>\n<body>\n"
        f"<h1>{html.escape(titulo)}</h1>\n"
        f"<p class=\"meta\">Generado el {generado_en:%Y-%m-%d %H:%M:%S %Z} con cloudcr-oracle-backup "
        f"{html.escape(__version__)} · {len(tabla.filas)} ejecuciones · Filtros: {html.escape(filtros)}</p>\n"
        f"<div class=\"tabla\"><table>\n<thead><tr>{cabecera}</tr></thead>\n<tbody>{cuerpo}</tbody>\n</table></div>\n"
        f"<p class=\"meta\">Símbolos: {leyenda}.</p>\n"
        + (f"<ul>{notas}</ul>\n" if notas else "")
        + "</body>\n</html>\n"
    )


def exportar(
    tabla: TablaHistorial,
    formato: FormatoHistorial,
    filtros: str,
    generado_en: datetime,
    titulo: str = TITULO_POR_DEFECTO,
) -> str:
    if formato is FormatoHistorial.CSV:
        return a_csv(tabla)
    if formato is FormatoHistorial.MD:
        return a_markdown(tabla, titulo, filtros, generado_en)
    return a_html(tabla, titulo, filtros, generado_en)
