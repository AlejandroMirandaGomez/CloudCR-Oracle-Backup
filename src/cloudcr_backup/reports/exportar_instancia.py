import io
import json
from enum import StrEnum

from rich.console import Console
from rich.terminal_theme import MONOKAI

from cloudcr_backup import __version__
from cloudcr_backup.oracle.explorador import Exploracion
from cloudcr_backup.presentacion.arbol import OpcionesArbol
from cloudcr_backup.presentacion.formato import ETIQUETA_SEVERIDAD
from cloudcr_backup.presentacion.terminal import construir_arbol, tabla_hallazgos

ANCHO_EXPORTACION = 180


class FormatoExportacion(StrEnum):
    JSON = "json"
    MD = "md"
    HTML = "html"


TIPO_CONTENIDO = {
    FormatoExportacion.JSON: "application/json; charset=utf-8",
    FormatoExportacion.MD: "text/markdown; charset=utf-8",
    FormatoExportacion.HTML: "text/html; charset=utf-8",
}


def a_json(exploracion: Exploracion) -> str:
    contenido = {
        "generado_por": f"cloudcr-oracle-backup {__version__}",
        "perfil": exploracion.perfil.model_dump(mode="json"),
        "hallazgos": [h.model_dump(mode="json") for h in exploracion.hallazgos],
    }
    return json.dumps(contenido, ensure_ascii=False, indent=2)


def texto_plano(exploracion: Exploracion, opciones: OpcionesArbol, ancho: int = ANCHO_EXPORTACION) -> str:
    buffer = io.StringIO()
    consola = Console(file=buffer, width=ancho, color_system=None, force_terminal=False, legacy_windows=False)
    consola.print(construir_arbol(exploracion, opciones))
    return buffer.getvalue().rstrip()


def _celda_md(texto: str) -> str:
    return texto.replace("|", "\\|").replace("\n", " ")


def a_markdown(exploracion: Exploracion, opciones: OpcionesArbol) -> str:
    perfil = exploracion.perfil
    lineas = [
        f"# Instancia {perfil.nombre_instancia.upper()} — estructura física",
        "",
        f"Capturado el {perfil.capturado_en:%Y-%m-%d %H:%M:%S} en {perfil.host} "
        f"con cloudcr-oracle-backup {__version__}.",
        "",
        "```text",
        texto_plano(exploracion, opciones),
        "```",
        "",
        "## Observaciones",
        "",
    ]
    if not exploracion.hallazgos:
        lineas.append("Sin observaciones.")
    else:
        lineas += ["| Nivel | Código | Observación | Acción sugerida |", "|---|---|---|---|"]
        for hallazgo in exploracion.hallazgos:
            lineas.append(
                f"| {ETIQUETA_SEVERIDAD[hallazgo.severidad]} | {hallazgo.codigo} | {_celda_md(hallazgo.mensaje)} "
                f"| {_celda_md(hallazgo.accion_sugerida or '')} |"
            )
    return "\n".join(lineas) + "\n"


def a_html(exploracion: Exploracion, opciones: OpcionesArbol) -> str:
    consola = Console(
        record=True, width=ANCHO_EXPORTACION, file=io.StringIO(), force_terminal=True, legacy_windows=False
    )
    consola.print(construir_arbol(exploracion, opciones))
    if exploracion.hallazgos:
        consola.print()
        consola.print(tabla_hallazgos(exploracion.hallazgos))
    return consola.export_html(theme=MONOKAI, inline_styles=True)


def exportar(exploracion: Exploracion, opciones: OpcionesArbol, formato: FormatoExportacion) -> str:
    if formato is FormatoExportacion.JSON:
        return a_json(exploracion)
    if formato is FormatoExportacion.MD:
        return a_markdown(exploracion, opciones)
    return a_html(exploracion, opciones)


def nombre_archivo(exploracion: Exploracion, formato: FormatoExportacion) -> str:
    perfil = exploracion.perfil
    return f"instancia-{perfil.nombre_instancia.upper()}-{perfil.capturado_en:%Y%m%d-%H%M%S}.{formato.value}"
