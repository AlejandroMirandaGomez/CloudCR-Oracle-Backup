from datetime import datetime

from pydantic import BaseModel, Field

from cloudcr_backup.domain.enums import LogMode, Severidad
from cloudcr_backup.domain.hallazgos import Hallazgo


class ComprobacionEntorno(BaseModel):
    nombre: str
    ok: bool
    detalle: str
    sugerencia: str | None = None


class TablaRepositorio(BaseModel):
    nombre: str
    filas: int


class EstadoRepositorio(BaseModel):
    instalado: bool
    esperadas: int
    tablas: list[TablaRepositorio] = Field(default_factory=list)


class ParametroRepositorio(BaseModel):
    clave: str
    valor: str
    inicial: str | None = None

    @property
    def modificado(self) -> bool:
        return self.inicial is not None and self.valor != self.inicial


class VistaBaseDatos(BaseModel):
    nombre: str
    registrada: bool
    id: int | None = None
    ambiente: str | None = None
    oracle_home: str | None = None
    activa: bool = False
    en_ejecucion: bool | None = None
    perfil_capturado_en: datetime | None = None
    log_mode: LogMode | None = None


class PerfilGuardado(BaseModel):
    bd: str
    capturado_en: datetime
    log_mode: LogMode
    tablespaces: int
    datafiles: int


class EjemploEstrategia(BaseModel):
    archivo: str
    codigo: str
    nombre: str


class EstrategiaImportada(BaseModel):
    bd: str
    codigo: str
    nombre: str
    version: int
    reemplazada: bool = False


class ResultadoValidacion(BaseModel):
    bd: str
    estrategia: str
    version: int
    hallazgos: list[Hallazgo] = Field(default_factory=list)
    perfil_capturado_en: datetime | None = None
    perfil_en_vivo: bool = True
    avisos: list[str] = Field(default_factory=list)

    @property
    def bloqueante(self) -> bool:
        return any(h.severidad is Severidad.ERROR for h in self.hallazgos)

    def cantidad(self, severidad: Severidad) -> int:
        return sum(1 for h in self.hallazgos if h.severidad is severidad)

    def tiene(self, codigo: str) -> bool:
        return any(h.codigo == codigo for h in self.hallazgos)


class RecomendacionAplicada(BaseModel):
    bd: str
    estrategia: str
    codigo: str
    version: int
    aplicada: bool
    mensaje: str


class MensajeAgente(BaseModel):
    momento: datetime
    texto: str


class EstadoControlAgente(BaseModel):
    corriendo: bool
    simulado: bool = False
    iniciado_en: datetime | None = None
    ciclo_en_curso: bool = False
    mensajes: list[MensajeAgente] = Field(default_factory=list)


class BorradorEdicion(BaseModel):
    bd: str
    codigo: str
    nombre: str
    version: int
    contenido: str
    tarea_agregada: str | None = None


class EstrategiaEditada(BaseModel):
    bd: str
    codigo: str
    nombre: str
    version: int
    tareas_agregadas: list[str] = Field(default_factory=list)
    tareas_eliminadas: list[str] = Field(default_factory=list)
    tareas_a_regenerar: list[str] = Field(default_factory=list)

    @property
    def mensaje(self) -> str:
        partes = [f"Estrategia {self.codigo} guardada como versión {self.version}."]
        if self.tareas_agregadas:
            partes.append(f"Tareas agregadas: {', '.join(self.tareas_agregadas)}.")
        if self.tareas_eliminadas:
            partes.append(f"Tareas eliminadas: {', '.join(self.tareas_eliminadas)}.")
        if self.tareas_a_regenerar:
            partes.append(
                f"Cambió lo que se respalda o cómo se respalda en {', '.join(self.tareas_a_regenerar)}: "
                "su script anterior quedó obsoleto, genere y apruebe uno nuevo."
            )
        if self.tareas_agregadas:
            partes.append(
                f"Genere y apruebe el script de {', '.join(self.tareas_agregadas)} para que el agente las ejecute."
            )
        return " ".join(partes)
