import html
from datetime import datetime

from cloudcr_backup import __version__
from cloudcr_backup.domain.historial import DetalleEjecucion
from cloudcr_backup.presentacion.detalle import secciones
from cloudcr_backup.reports.historial import ESTILOS_HTML, FormatoHistorial


def a_markdown(detalle: DetalleEjecucion, generado_en: datetime) -> str:
    lineas = [
        f"# Evidencia de la ejecución {detalle.fila.ejecucion_id}",
        "",
        f"Generado el {generado_en:%Y-%m-%d %H:%M:%S %Z} con cloudcr-oracle-backup {__version__}.",
    ]
    for titulo, contenido in secciones(detalle):
        lineas += ["", f"## {titulo}", ""]
        if titulo.startswith(("Log", "Evidencia")):
            lineas += ["```text", *contenido, "```"]
        else:
            lineas += [f"- {linea}" for linea in contenido]
    return "\n".join(lineas) + "\n"


def a_html(detalle: DetalleEjecucion, generado_en: datetime) -> str:
    partes = []
    for titulo, contenido in secciones(detalle):
        partes.append(f"<h2>{html.escape(titulo)}</h2>")
        if titulo.startswith(("Log", "Evidencia")):
            partes.append(f"<pre>{html.escape(chr(10).join(contenido))}</pre>")
        else:
            partes.append("<ul>" + "".join(f"<li>{html.escape(linea)}</li>" for linea in contenido) + "</ul>")
    titulo = f"Evidencia de la ejecución {detalle.fila.ejecucion_id}"
    return (
        "<!DOCTYPE html>\n<html lang=\"es\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{html.escape(titulo)}</title>\n<style>{ESTILOS_HTML}"
        "h2 { font-size: 16px; margin: 20px 0 6px; } pre { white-space: pre-wrap; font-size: 12px; }"
        "</style>\n</head>\n<body>\n"
        f"<h1>{html.escape(titulo)}</h1>\n"
        f"<p class=\"meta\">Generado el {generado_en:%Y-%m-%d %H:%M:%S %Z} con cloudcr-oracle-backup "
        f"{html.escape(__version__)}</p>\n" + "\n".join(partes) + "\n</body>\n</html>\n"
    )


def exportar(detalle: DetalleEjecucion, formato: FormatoHistorial, generado_en: datetime) -> str:
    if formato is FormatoHistorial.HTML:
        return a_html(detalle, generado_en)
    return a_markdown(detalle, generado_en)
