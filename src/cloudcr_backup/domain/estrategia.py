from datetime import date, datetime, time

from pydantic import BaseModel, Field

from cloudcr_backup.domain.enums import (
    Compresion,
    DiaSemana,
    EstadoEstrategia,
    ModoRespaldo,
    PoliticaOmision,
    Prioridad,
    TipoFrecuencia,
    TipoObjeto,
    TipoRespaldo,
)


class ObjetoAlcance(BaseModel):
    tipo: TipoObjeto
    identificador: str
    prioridad: Prioridad


class OpcionesRespaldo(BaseModel):
    compresion: Compresion = Compresion.NINGUNA
    canales: int = 1
    omitir_solo_lectura: bool = False


class Como(BaseModel):
    tipo_respaldo: TipoRespaldo
    modo_respaldo: ModoRespaldo = ModoRespaldo.AUTO
    opciones: OpcionesRespaldo = Field(default_factory=OpcionesRespaldo)


class Ventana(BaseModel):
    inicio: time
    fin: time

    @property
    def cruza_medianoche(self) -> bool:
        return self.fin <= self.inicio

    def contiene(self, hora: time) -> bool:
        if self.cruza_medianoche:
            return hora >= self.inicio or hora <= self.fin
        return self.inicio <= hora <= self.fin


class Programacion(BaseModel):
    tipo_frecuencia: TipoFrecuencia
    horas: list[time] = Field(default_factory=list)
    dias_semana: list[DiaSemana] = Field(default_factory=list)
    intervalo_minutos: int | None = None
    fecha_inicio: date | None = None
    ventana: Ventana | None = None
    zona_horaria: str = "America/Costa_Rica"
    politica_omision: PoliticaOmision = PoliticaOmision.EJECUTAR_EN_VENTANA


class Destino(BaseModel):
    ruta: str
    etiqueta: str | None = None


class Tarea(BaseModel):
    codigo: str
    como: Como
    programacion: Programacion
    destino: Destino


class Retencion(BaseModel):
    ventana_dias: int | None = None
    redundancia: int | None = None
    archived_logs_dias: int | None = None
    purga_automatica: bool = False


class Estrategia(BaseModel):
    id: int | None = None
    bd_id: int
    codigo: str
    nombre: str
    descripcion: str | None = None
    prioridad: Prioridad
    estado: EstadoEstrategia = EstadoEstrategia.INACTIVA
    version: int = 1
    creada_por: str
    creada_en: datetime | None = None
    alcance: list[ObjetoAlcance] = Field(default_factory=list)
    tareas: list[Tarea] = Field(default_factory=list)
    retencion: Retencion = Field(default_factory=Retencion)

    def tarea(self, codigo: str) -> Tarea | None:
        return next((t for t in self.tareas if t.codigo == codigo), None)
