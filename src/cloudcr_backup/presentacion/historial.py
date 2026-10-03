from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cloudcr_backup.domain.enums import EstadoEjecucion, EstadoPrueba
from cloudcr_backup.domain.historial import FilaHistorial
from cloudcr_backup.presentacion.formato import Tono, formato_bytes
from cloudcr_backup.strategy.vocabulario import etiqueta_doble

COLUMNAS = (
    "Fecha",
    "BD",
    "Estrategia",
    "Tarea",
    "Hora",
    "◆",
    "Tipo",
    "Inicio",
    "Fin",
    "Duración",
    "Resultado",
    "Pruebas",
)

SIMBOLO_ESTADO = {
    EstadoEjecucion.EXITOSA: "●",
    EstadoEjecucion.CON_ADVERTENCIAS: "▲",
    EstadoEjecucion.FALLIDA: "✕",
    EstadoEjecucion.BLOQUEADA: "✕",
    EstadoEjecucion.NO_EJECUTADA: "○",
    EstadoEjecucion.CANCELADA: "○",
    EstadoEjecucion.EN_CURSO: "◐",
    EstadoEjecucion.PROGRAMADA: "◌",
}

TEXTO_RESULTADO = {
    EstadoEjecucion.EXITOSA: "Exitoso",
    EstadoEjecucion.CON_ADVERTENCIAS: "Con advertencias",
    EstadoEjecucion.FALLIDA: "Error",
    EstadoEjecucion.BLOQUEADA: "Bloqueada",
    EstadoEjecucion.NO_EJECUTADA: "No ejecutada",
    EstadoEjecucion.CANCELADA: "Cancelada",
    EstadoEjecucion.EN_CURSO: "En curso",
    EstadoEjecucion.PROGRAMADA: "Programada",
}

TONO_RESULTADO = {
    EstadoEjecucion.EXITOSA: Tono.EXITO,
    EstadoEjecucion.CON_ADVERTENCIAS: Tono.ADVERTENCIA,
    EstadoEjecucion.FALLIDA: Tono.PELIGRO,
    EstadoEjecucion.BLOQUEADA: Tono.PELIGRO,
    EstadoEjecucion.NO_EJECUTADA: Tono.ATENUADO,
    EstadoEjecucion.CANCELADA: Tono.ATENUADO,
    EstadoEjecucion.EN_CURSO: Tono.DATO,
    EstadoEjecucion.PROGRAMADA: Tono.DATO,
}

TEXTO_PRUEBAS = {
    EstadoPrueba.OK: "OK",
    EstadoPrueba.FALLIDA: "Fallida",
    EstadoPrueba.PENDIENTE: "Pendiente",
    EstadoPrueba.NO_APLICA: "No aplica",
}

TONO_PRUEBAS = {
    EstadoPrueba.OK: Tono.EXITO,
    EstadoPrueba.FALLIDA: Tono.PELIGRO,
    EstadoPrueba.PENDIENTE: Tono.ADVERTENCIA,
    EstadoPrueba.NO_APLICA: Tono.ATENUADO,
}

SIN_DATO = "—"
GRACIA_POR_DEFECTO = timedelta(minutes=15)
ZONA_POR_DEFECTO = "America/Costa_Rica"


def zona(nombre: str) -> ZoneInfo:
    try:
        return ZoneInfo(nombre)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(ZONA_POR_DEFECTO)


def local(momento: datetime, nombre_zona: str) -> datetime:
    return momento.astimezone(zona(nombre_zona))


def formato_duracion(segundos: int | None) -> str:
    if segundos is None:
        return SIN_DATO
    if segundos < 60:
        return f"{segundos} s"
    minutos, resto = divmod(segundos, 60)
    if minutos < 60:
        return f"{minutos} min {resto:02d} s"
    horas, minutos = divmod(minutos, 60)
    return f"{horas} h {minutos:02d} min"


def _hora_relativa(momento: datetime | None, referencia: datetime, nombre_zona: str) -> str:
    if momento is None:
        return SIN_DATO
    valor = local(momento, nombre_zona)
    base = local(referencia, nombre_zona)
    if valor.date() != base.date():
        return valor.strftime("%d/%m %H:%M:%S")
    return valor.strftime("%H:%M:%S")


def _duracion(fila: FilaHistorial) -> int | None:
    if fila.duracion_segundos is not None:
        return fila.duracion_segundos
    if fila.inicio is not None and fila.fin is not None:
        return max(0, int((fila.fin - fila.inicio).total_seconds()))
    return None


@dataclass(frozen=True)
class FilaTabla:
    ejecucion_id: int
    estado: EstadoEjecucion
    fecha: str
    bd: str
    estrategia: str
    tarea: str
    hora: str
    simbolo: str
    tipo: str
    inicio: str
    fin: str
    duracion: str
    resultado: str
    pruebas: str
    tono_resultado: Tono
    tono_pruebas: Tono
    retraso_minutos: int | None = None
    mensaje: str | None = None
    tamano: str = SIN_DATO

    @property
    def tardia(self) -> bool:
        return self.retraso_minutos is not None

    def celdas(self) -> list[str]:
        return [
            self.fecha,
            self.bd,
            self.estrategia,
            self.tarea,
            self.hora,
            self.simbolo,
            self.tipo,
            self.inicio,
            self.fin,
            self.duracion,
            self.resultado,
            self.pruebas,
        ]


@dataclass(frozen=True)
class TablaHistorial:
    filas: list[FilaTabla]
    columnas: tuple[str, ...] = COLUMNAS
    notas: list[str] = field(default_factory=list)

    def matriz(self) -> list[list[str]]:
        return [fila.celdas() for fila in self.filas]


def construir_fila(fila: FilaHistorial, gracia: timedelta = GRACIA_POR_DEFECTO) -> FilaTabla:
    programada = local(fila.programada_para, fila.zona_horaria)
    retraso = None
    if fila.inicio is not None and fila.inicio - fila.programada_para > gracia:
        retraso = int((fila.inicio - fila.programada_para).total_seconds() // 60)
    return FilaTabla(
        ejecucion_id=fila.ejecucion_id,
        estado=fila.estado,
        fecha=programada.strftime("%Y-%m-%d"),
        bd=fila.bd,
        estrategia=fila.estrategia,
        tarea=fila.tarea,
        hora=programada.strftime("%H:%M"),
        simbolo=SIMBOLO_ESTADO[fila.estado],
        tipo=etiqueta_doble(fila.tipo_respaldo),
        inicio=_hora_relativa(fila.inicio, fila.programada_para, fila.zona_horaria),
        fin=_hora_relativa(fila.fin, fila.programada_para, fila.zona_horaria),
        duracion=formato_duracion(_duracion(fila)),
        resultado=TEXTO_RESULTADO[fila.estado],
        pruebas=TEXTO_PRUEBAS[fila.estado_prueba],
        tono_resultado=TONO_RESULTADO[fila.estado],
        tono_pruebas=TONO_PRUEBAS[fila.estado_prueba],
        retraso_minutos=retraso,
        mensaje=fila.mensaje,
        tamano=formato_bytes(fila.tamano_bytes) if fila.tamano_bytes is not None else SIN_DATO,
    )


def construir_tabla(filas: list[FilaHistorial], gracia: timedelta = GRACIA_POR_DEFECTO) -> TablaHistorial:
    tabla = [construir_fila(fila, gracia) for fila in filas]
    notas = []
    if any(f.tardia for f in tabla):
        notas.append(f"Las filas marcadas como tardías iniciaron más de {int(gracia.total_seconds() // 60)} min "
                     "después de su hora programada (recuperadas tarde).")
    if any(f.estado is EstadoEjecucion.EXITOSA and f.pruebas == TEXTO_PRUEBAS[EstadoPrueba.PENDIENTE] for f in tabla):
        notas.append("Pruebas «Pendiente»: la verificación del respaldo todavía no se ejecutó.")
    if any(f.mensaje and f.mensaje.startswith("SIMULACION") for f in tabla):
        notas.append("Las ejecuciones con mensaje SIMULACION son pruebas del agente: no ejecutaron RMAN.")
    return TablaHistorial(filas=tabla, notas=notas)


LEYENDA_SIMBOLOS = (
    ("●", "exitosa"),
    ("▲", "con advertencias"),
    ("✕", "fallida o bloqueada"),
    ("○", "no ejecutada o cancelada"),
    ("◐", "en curso"),
    ("◌", "programada, sin iniciar"),
)
