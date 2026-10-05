from datetime import time
from typing import Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cloudcr_backup.domain.enums import (
    DiaSemana,
    EstadoEstrategia,
    PoliticaOmision,
    Prioridad,
    TipoObjeto,
)
from cloudcr_backup.domain.estrategia import (
    Como,
    Destino,
    Estrategia,
    ObjetoAlcance,
    Programacion,
    Retencion,
    Tarea,
    Ventana,
)
from cloudcr_backup.services.destinos import normalizar_ruta, ruta_es_absoluta
from cloudcr_backup.strategy.codigos import PATRON_CODIGO
from cloudcr_backup.strategy.plantillas_esquema import EsquemaPredefinido, ParametrosEsquema, tareas_de

MAXIMO_TAREAS = 20
MAXIMO_OBJETOS = 500


def _zona_horaria_valida(zona: str) -> str:
    try:
        ZoneInfo(zona)
    except (ZoneInfoNotFoundError, ValueError, OSError) as error:
        raise ValueError(f"La zona horaria {zona} no existe (por ejemplo America/Costa_Rica).") from error
    return zona


class ObjetoSolicitado(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    tipo: TipoObjeto
    identificador: str = ""
    prioridad: Prioridad


class ProgramacionSolicitada(Programacion):
    @field_validator("zona_horaria")
    @classmethod
    def _validar_zona(cls, zona: str) -> str:
        return _zona_horaria_valida(zona)

    @field_validator("intervalo_minutos")
    @classmethod
    def _validar_intervalo(cls, minutos: int | None) -> int | None:
        if minutos is not None and minutos < 1:
            raise ValueError("El intervalo debe ser de al menos 1 minuto.")
        return minutos

    @field_validator("horas")
    @classmethod
    def _horas_sin_repetidas(cls, horas: list[time]) -> list[time]:
        return sorted(set(horas))

    @field_validator("dias_semana")
    @classmethod
    def _dias_sin_repetidos(cls, dias: list[DiaSemana]) -> list[DiaSemana]:
        orden = list(DiaSemana)
        return sorted(set(dias), key=orden.index)


class TareaSolicitada(BaseModel):
    como: Como
    programacion: ProgramacionSolicitada


class EsquemaSolicitado(BaseModel):
    esquema: EsquemaPredefinido
    dia_n0: DiaSemana = DiaSemana.DOMINGO
    hora_n0: time = time(2, 0)
    hora_n1: time = time(15, 0)
    intervalo_archivelog_minutos: int = Field(default=240, ge=1)
    ventana: Ventana | None = None
    politica_omision: PoliticaOmision = PoliticaOmision.EJECUTAR_EN_VENTANA
    zona_horaria: str = "America/Costa_Rica"

    @field_validator("zona_horaria")
    @classmethod
    def _validar_zona(cls, zona: str) -> str:
        return _zona_horaria_valida(zona)


class RetencionSolicitada(Retencion):
    @field_validator("ventana_dias", "redundancia", "archived_logs_dias")
    @classmethod
    def _validar_positivo(cls, valor: int | None) -> int | None:
        if valor is not None and valor < 1:
            raise ValueError("Debe ser un número entero mayor que cero.")
        return valor


class SolicitudEstrategia(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    codigo: str = Field(max_length=20)
    nombre: str = Field(default="", max_length=200)
    descripcion: str | None = Field(default=None, max_length=1000)
    prioridad: Prioridad
    creada_por: str = Field(min_length=1, max_length=100)
    alcance: list[ObjetoSolicitado] = Field(default_factory=list, max_length=MAXIMO_OBJETOS)
    esquema: EsquemaSolicitado | None = None
    tareas: list[TareaSolicitada] = Field(default_factory=list, max_length=MAXIMO_TAREAS)
    destino_ruta: str
    retencion: RetencionSolicitada = Field(default_factory=RetencionSolicitada)
    activar: bool = False
    aceptar_caida: bool = False
    guardar_en_repositorio: bool = True

    @field_validator("codigo")
    @classmethod
    def _validar_codigo(cls, codigo: str) -> str:
        normalizado = codigo.upper()
        if PATRON_CODIGO.fullmatch(normalizado) is None:
            raise ValueError("Use solo letras, números, guion y guion bajo (máximo 20 caracteres).")
        return normalizado

    @field_validator("descripcion")
    @classmethod
    def _descripcion_vacia_es_nula(cls, descripcion: str | None) -> str | None:
        return descripcion or None

    @field_validator("destino_ruta")
    @classmethod
    def _validar_destino(cls, ruta: str) -> str:
        if not ruta:
            raise ValueError("Indique la carpeta de destino de los respaldos.")
        if not ruta_es_absoluta(ruta):
            raise ValueError("La ruta debe ser absoluta, por ejemplo C:\\backups\\XE.")
        return normalizar_ruta(ruta)

    @model_validator(mode="after")
    def _nombre_por_omision_es_el_codigo(self) -> Self:
        if not self.nombre:
            self.nombre = self.codigo
        return self

    @model_validator(mode="after")
    def _esquema_o_tareas(self) -> Self:
        if self.esquema is not None and self.tareas:
            raise ValueError("Elija un esquema predefinido o defina el tipo de respaldo manualmente, no ambos.")
        return self


def _alcance_sin_repetidos(objetos: list[ObjetoSolicitado]) -> list[ObjetoAlcance]:
    vistos: set[tuple[TipoObjeto, str]] = set()
    alcance = []
    for objeto in objetos:
        clave = (objeto.tipo, objeto.identificador)
        if clave in vistos:
            continue
        vistos.add(clave)
        alcance.append(ObjetoAlcance(tipo=objeto.tipo, identificador=objeto.identificador, prioridad=objeto.prioridad))
    return alcance


def _tareas_del_esquema(esquema: EsquemaSolicitado, destino: Destino) -> list[Tarea]:
    parametros = ParametrosEsquema(
        destino=destino,
        dia_n0=esquema.dia_n0,
        hora_n0=esquema.hora_n0,
        hora_n1=esquema.hora_n1,
        intervalo_archivelog_minutos=esquema.intervalo_archivelog_minutos,
        ventana=esquema.ventana,
        politica_omision=esquema.politica_omision,
    )
    tareas = tareas_de(esquema.esquema, parametros)
    return [
        tarea.model_copy(
            update={"programacion": tarea.programacion.model_copy(update={"zona_horaria": esquema.zona_horaria})}
        )
        for tarea in tareas
    ]


def _tareas_a_mano(tareas: list[TareaSolicitada], destino: Destino) -> list[Tarea]:
    return [
        Tarea(codigo=f"T{numero}", como=tarea.como, programacion=tarea.programacion, destino=destino)
        for numero, tarea in enumerate(tareas, start=1)
    ]


def construir_estrategia(solicitud: SolicitudEstrategia, bd_id: int = 0) -> Estrategia:
    destino = Destino(ruta=solicitud.destino_ruta)
    if solicitud.esquema is not None:
        tareas = _tareas_del_esquema(solicitud.esquema, destino)
    else:
        tareas = _tareas_a_mano(solicitud.tareas, destino)
    return Estrategia(
        bd_id=bd_id,
        codigo=solicitud.codigo,
        nombre=solicitud.nombre,
        descripcion=solicitud.descripcion,
        prioridad=solicitud.prioridad,
        estado=EstadoEstrategia.ACTIVA if solicitud.activar else EstadoEstrategia.INACTIVA,
        creada_por=solicitud.creada_por,
        alcance=_alcance_sin_repetidos(solicitud.alcance),
        tareas=tareas,
        retencion=Retencion.model_validate(solicitud.retencion.model_dump()),
    )
