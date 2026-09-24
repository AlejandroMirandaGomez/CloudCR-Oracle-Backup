from rich.console import Console
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from cloudcr_backup.domain.enums import Severidad
from cloudcr_backup.domain.hallazgos import Hallazgo
from cloudcr_backup.oracle.explorador import Exploracion
from cloudcr_backup.presentacion.arbol import NodoArbol, OpcionesArbol, TipoNodo, construir_nodos
from cloudcr_backup.presentacion.formato import ETIQUETA_SEVERIDAD, Tono

ESTILO_SEVERIDAD = {
    Severidad.ERROR: "bold red",
    Severidad.ADVERTENCIA: "bold yellow",
    Severidad.RECOMENDACION: "bold cyan",
    Severidad.INFORMATIVA: "dim",
}

ESTILO_TONO = {
    Tono.NORMAL: "",
    Tono.ATENUADO: "dim",
    Tono.RESALTADO: "bold",
    Tono.DATO: "cyan",
    Tono.EXITO: "green",
    Tono.ADVERTENCIA: "yellow",
    Tono.PELIGRO: "bold red",
}


def etiqueta_hallazgo(hallazgo: Hallazgo) -> Text:
    return Text.assemble(
        (f"{ETIQUETA_SEVERIDAD[hallazgo.severidad]}: ", ESTILO_SEVERIDAD[hallazgo.severidad]),
        (hallazgo.mensaje, ESTILO_SEVERIDAD[hallazgo.severidad].replace("bold ", "")),
    )


def tabla_hallazgos(hallazgos: list[Hallazgo]) -> Table:
    tabla = Table(title="Observaciones sobre la instancia", show_lines=True, expand=False)
    tabla.add_column("Nivel", no_wrap=True)
    tabla.add_column("Código", no_wrap=True)
    tabla.add_column("Observación")
    tabla.add_column("Acción sugerida")
    for hallazgo in hallazgos:
        tabla.add_row(
            Text(ETIQUETA_SEVERIDAD[hallazgo.severidad], style=ESTILO_SEVERIDAD[hallazgo.severidad]),
            hallazgo.codigo,
            hallazgo.mensaje,
            hallazgo.accion_sugerida or "",
        )
    return tabla


def consola() -> Console:
    return Console(highlight=False)


ESTILO_TITULO = {
    TipoNodo.INSTANCIA: "bold",
    TipoNodo.GRUPO_PRINCIPAL: "bold magenta",
    TipoNodo.GRUPO: "bold",
    TipoNodo.REDO_GRUPO: "bold",
    TipoNodo.CONTENEDOR: "bold blue",
    TipoNodo.TABLESPACE: "bold",
    TipoNodo.ARCHIVO: "bold",
    TipoNodo.TEXTO: "",
}


def etiqueta(nodo: NodoArbol) -> Text:
    estilo_titulo = ESTILO_TONO[nodo.tono_titulo] if nodo.tono_titulo else ESTILO_TITULO[nodo.tipo]
    texto = Text(nodo.titulo, style=estilo_titulo)
    for detalle in nodo.detalles:
        texto.append(detalle.prefijo)
        texto.append(detalle.texto, style=ESTILO_TONO[detalle.tono])
    if nodo.ubicacion:
        texto.append(f"   {nodo.ubicacion}", style="dim")
    for linea in nodo.lineas_extra:
        texto.append("\n")
        for detalle in linea:
            texto.append(detalle.prefijo)
            texto.append(detalle.texto, style=ESTILO_TONO[detalle.tono])
    return texto


def _agregar(padre: Tree, nodo: NodoArbol) -> None:
    rama = padre.add(etiqueta(nodo))
    _completar(rama, nodo)


def _completar(rama: Tree, nodo: NodoArbol) -> None:
    for hallazgo in nodo.hallazgos:
        rama.add(etiqueta_hallazgo(hallazgo))
    for hijo in nodo.hijos:
        _agregar(rama, hijo)


def arbol_rich(raiz: NodoArbol) -> Tree:
    arbol = Tree(etiqueta(raiz), guide_style="bright_black")
    _completar(arbol, raiz)
    return arbol


def construir_arbol(exploracion: Exploracion, opciones: OpcionesArbol) -> Tree:
    return arbol_rich(construir_nodos(exploracion, opciones, modo="cli"))
