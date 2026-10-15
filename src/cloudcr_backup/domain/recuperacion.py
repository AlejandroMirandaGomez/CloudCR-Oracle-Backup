from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, computed_field

from cloudcr_backup.domain.enums import DiaSemana, EstadoPrueba, EstadoScript, LogMode, TipoRespaldo

TABLESPACES_CRITICOS = ("SYSTEM",)
PREFIJO_UNDO = "UNDO"
MODO_PDB_CERRADA = "MOUNTED"


class Escenario(StrEnum):
    PDB = "pdb"
    TABLESPACE = "tablespace"
    DATAFILE = "datafile"
    DATAFILE_CRITICO = "datafile-critico"
    CONTROLFILE = "controlfile"
    MIEMBRO_REDOLOG = "miembro-redolog"
    GRUPO_REDOLOG_ACTUAL = "grupo-redolog-actual"
    CORRUPCION_BLOQUE = "corrupcion-bloque"
    SPFILE = "spfile"
    TOTAL_NOARCHIVELOG = "total-noarchivelog"
    PUNTO_EN_TIEMPO = "punto-en-tiempo"


def tablespace_critico(tablespace: str | None) -> bool:
    nombre = (tablespace or "").strip().upper()
    return nombre in TABLESPACES_CRITICOS or nombre.startswith(PREFIJO_UNDO)


class ArchivoDanado(BaseModel):
    file_id: int
    ruta: str
    tablespace: str | None = None
    contenedor: str | None = None
    estado: str
    error: str | None = None
    cambio: int | None = None
    origen: str

    @property
    def identificador_tablespace(self) -> str | None:
        if self.tablespace is None:
            return None
        if self.contenedor in (None, "", "CDB$ROOT"):
            return self.tablespace
        return f"{self.contenedor}:{self.tablespace}"

    @property
    def pdb(self) -> str | None:
        return None if self.contenedor in (None, "", "CDB$ROOT") else self.contenedor

    @computed_field  # type: ignore[prop-decorator]
    @property
    def critico(self) -> bool:
        return self.pdb is None and tablespace_critico(self.tablespace)


class BloqueCorrupto(BaseModel):
    file_id: int
    bloque: int
    bloques: int = 1
    tipo: str | None = None
    ruta: str | None = None
    tablespace: str | None = None
    contenedor: str | None = None


class MiembroRedoDanado(BaseModel):
    grupo: int
    miembro: str
    estado_miembro: str
    estado_grupo: str
    hilo: int = 1
    secuencia: int | None = None
    grupo_perdido: bool = False

    @property
    def actual(self) -> bool:
        return self.estado_grupo.upper() == "CURRENT"


class GrupoRedoActual(BaseModel):
    grupo: int
    hilo: int = 1
    secuencia: int


class GrupoRedo(BaseModel):
    grupo: int
    estado: str
    hilo: int = 1
    secuencia: int | None = None


class EstadoPdb(BaseModel):
    nombre: str
    modo: str
    con_id: int | None = None

    @property
    def cerrada(self) -> bool:
        return self.modo.upper() == MODO_PDB_CERRADA


class Diagnostico(BaseModel):
    bd: str
    generado_en: datetime
    log_mode: LogMode | None = None
    open_mode: str | None = None
    archivos: list[ArchivoDanado] = Field(default_factory=list)
    bloques: list[BloqueCorrupto] = Field(default_factory=list)
    miembros_redo: list[MiembroRedoDanado] = Field(default_factory=list)
    redo_actual: GrupoRedoActual | None = None
    grupos_redo: list[GrupoRedo] = Field(default_factory=list)
    pdbs: list[EstadoPdb] = Field(default_factory=list)
    sin_conexion: bool = False
    fallo_consulta: bool = False
    sugeridos: list[Escenario] = Field(default_factory=list)
    avisos: list[str] = Field(default_factory=list)

    @property
    def sin_danos(self) -> bool:
        return not (self.archivos or self.bloques or self.miembros_redo or self.sin_conexion or self.fallo_consulta)


class PuntoRecuperacion(BaseModel):
    ejecucion_id: int
    estrategia: str
    tarea: str
    tipo_respaldo: TipoRespaldo
    completado_en: datetime | None = None
    alcance: list[str] = Field(default_factory=list)
    base_completa: bool = False
    estado_prueba: EstadoPrueba = EstadoPrueba.PENDIENTE
    piezas: int = 0
    tamano_bytes: int = 0
    tag: str | None = None
    controlfile: str | None = None


class PuntosRecuperacion(BaseModel):
    bd: str
    log_mode: LogMode | None = None
    puntos: list[PuntoRecuperacion] = Field(default_factory=list)
    recuperable_desde: datetime | None = None
    avisos: list[str] = Field(default_factory=list)


class Procedimiento(BaseModel):
    bd: str
    escenario: Escenario
    posible: bool
    motivo: str
    objetivo: str | None = None
    pasos: list[str] = Field(default_factory=list)
    script: str | None = None
    archivo: str | None = None
    avisos: list[str] = Field(default_factory=list)
    id: int | None = None
    estado: EstadoScript | None = None
    hash_sha256: str | None = None


class ResultadoRecuperacion(StrEnum):
    EN_CURSO = "EN_CURSO"
    EJECUTADO_OK = "EJECUTADO_OK"
    EJECUTADO_CON_ERRORES = "EJECUTADO_CON_ERRORES"
    NO_LANZADO = "NO_LANZADO"


class RegistroRecuperacion(BaseModel):
    id: int
    bd_id: int
    escenario: Escenario
    objetivo: str | None = None
    ruta_script: str
    contenido: str
    hash_sha256: str
    estado: EstadoScript
    generado_en: datetime | None = None
    aprobado_por: str | None = None
    aprobado_en: datetime | None = None
    ejecutado_en: datetime | None = None
    finalizado_en: datetime | None = None
    resultado: ResultadoRecuperacion | None = None
    ruta_log: str | None = None
    mensaje: str | None = None


class VistaRecuperacion(BaseModel):
    registro: RegistroRecuperacion
    bd: str
    ambiente: str
    archivo_intacto: bool | None = None
    bloqueo: str | None = None
    aviso: str | None = None
    log_rman: str | None = None

    @property
    def puede_aprobar(self) -> bool:
        return self.registro.estado is EstadoScript.BORRADOR and self.archivo_intacto is True

    @property
    def puede_ejecutar(self) -> bool:
        return self.bloqueo is None

    @property
    def en_curso(self) -> bool:
        return self.registro.resultado is ResultadoRecuperacion.EN_CURSO


class FallaDetectada(BaseModel):
    bd: str
    detectada_en: datetime
    resumen: str
    sugeridos: list[Escenario] = Field(default_factory=list)


class FallaResuelta(BaseModel):
    bd: str
    resuelta_en: datetime


class MarcaCalendario(BaseModel):
    momento: datetime
    simbolo: str
    etiqueta: str
    detalle: str
    falla: bool = False
    tipo_respaldo: TipoRespaldo | None = None
    ejecucion_id: int | None = None


class DiaCalendario(BaseModel):
    dia: DiaSemana
    fecha: date


class FilaCalendario(BaseModel):
    hora: int
    celdas: list[list[MarcaCalendario]]


class CalendarioSemanal(BaseModel):
    bd: str
    zona: str
    inicio: date
    fin: date
    anterior: date
    siguiente: date
    dias: list[DiaCalendario]
    filas: list[FilaCalendario]
    respaldos: int = 0
    fallas: list[MarcaCalendario] = Field(default_factory=list)
    leyenda: list[tuple[str, str]] = Field(default_factory=list)
