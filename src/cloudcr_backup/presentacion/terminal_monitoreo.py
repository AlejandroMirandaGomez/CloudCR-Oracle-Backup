from rich.table import Table
from rich.text import Text

from cloudcr_backup.domain.alertas import VistaAlerta
from cloudcr_backup.domain.monitoreo import EstadoAgente, EstadoGeneral
from cloudcr_backup.presentacion.estado import (
    TONO_SEVERIDAD_ALERTA,
    fila_agente,
    fila_alerta,
    fila_semaforo,
)
from cloudcr_backup.presentacion.historial import LEYENDA_SIMBOLOS, TablaHistorial
from cloudcr_backup.presentacion.terminal import ESTILO_TONO

COLUMNAS_SIN_CORTE = {"Fecha", "Hora", "◆", "Inicio", "Fin", "Duración"}


def tabla_historial(tabla: TablaHistorial, titulo: str = "Historial de ejecuciones") -> Table:
    resultado = Table(title=titulo, expand=False)
    resultado.add_column("Id", justify="right", style="dim")
    for columna in tabla.columnas:
        resultado.add_column(columna, no_wrap=columna in COLUMNAS_SIN_CORTE)
    for fila in tabla.filas:
        celdas: list[Text | str] = [str(fila.ejecucion_id)]
        for indice, valor in enumerate(fila.celdas()):
            if indice in (5, 10):
                celdas.append(Text(valor, style=ESTILO_TONO[fila.tono_resultado]))
            elif indice == 11:
                celdas.append(Text(valor, style=ESTILO_TONO[fila.tono_pruebas]))
            elif indice == 7 and fila.tardia:
                celdas.append(Text(f"{valor} (+{fila.retraso_minutos} min)", style="yellow"))
            else:
                celdas.append(valor)
        resultado.add_row(*celdas)
    return resultado


def leyenda_simbolos() -> str:
    return "Símbolos: " + ", ".join(f"{simbolo} {texto}" for simbolo, texto in LEYENDA_SIMBOLOS)


def tabla_semaforos(estado: EstadoGeneral, zona_horaria: str) -> Table:
    tabla = Table(title="Estrategias", show_lines=True)
    tabla.add_column("Estado", no_wrap=True)
    tabla.add_column("BD")
    tabla.add_column("Estrategia")
    tabla.add_column("Prioridad")
    tabla.add_column("Última ejecución", no_wrap=True)
    tabla.add_column("Próxima", no_wrap=True)
    tabla.add_column("Alertas", justify="right")
    tabla.add_column("Motivos")
    for semaforo in estado.semaforos:
        fila = fila_semaforo(semaforo, zona_horaria)
        tabla.add_row(
            Text(f"{fila.simbolo} {fila.etiqueta}", style=ESTILO_TONO[fila.tono]),
            fila.bd,
            f"{fila.estrategia} — {fila.nombre}",
            fila.prioridad,
            fila.ultima,
            fila.proxima,
            str(fila.alertas),
            "\n".join(fila.motivos),
        )
    return tabla


def tabla_alertas(alertas: list[VistaAlerta], zona_horaria: str, titulo: str = "Alertas") -> Table:
    tabla = Table(title=titulo, show_lines=True)
    tabla.add_column("Id", justify="right")
    tabla.add_column("Severidad", no_wrap=True)
    tabla.add_column("Código", no_wrap=True)
    tabla.add_column("Estado", no_wrap=True)
    tabla.add_column("Dónde")
    tabla.add_column("Mensaje")
    tabla.add_column("Abierta", no_wrap=True)
    for alerta in alertas:
        fila = fila_alerta(alerta, zona_horaria)
        tabla.add_row(
            fila["id"],
            Text(fila["severidad"], style=ESTILO_TONO[TONO_SEVERIDAD_ALERTA[alerta.severidad]]),
            fila["codigo"],
            fila["estado"],
            fila["donde"],
            fila["mensaje"],
            fila["abierta"],
        )
    return tabla


def tabla_agentes(agentes: list[EstadoAgente], zona_horaria: str) -> Table:
    tabla = Table(title="Agentes")
    tabla.add_column("Equipo")
    tabla.add_column("PID", justify="right")
    tabla.add_column("Estado")
    tabla.add_column("Último tick", no_wrap=True)
    tabla.add_column("Hace", justify="right")
    tabla.add_column("Modo")
    for agente in agentes:
        fila = fila_agente(agente, zona_horaria)
        tabla.add_row(
            fila.hostname,
            str(fila.pid),
            Text(fila.estado, style="green" if fila.vivo else "bold red"),
            fila.ultimo_tick,
            f"{fila.segundos_desde_tick} s",
            "SIMULACIÓN" if fila.simulado else "real",
        )
    return tabla
