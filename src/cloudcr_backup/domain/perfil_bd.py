from datetime import datetime
from pathlib import PurePath, PureWindowsPath

from pydantic import BaseModel

from cloudcr_backup.domain.enums import ContenidoTablespace, LogMode, TipoArchivoParametros

RAIZ_CDB = "CDB$ROOT"
SEMILLA_PDB = "PDB$SEED"


def ruta_pura(ruta: str) -> PurePath:
    return PureWindowsPath(ruta) if "\\" in ruta or ":" in ruta[:3] else PurePath(ruta)


class ArchivoFisico(BaseModel):
    ruta: str

    @property
    def nombre_archivo(self) -> str:
        return ruta_pura(self.ruta).name

    @property
    def directorio(self) -> str:
        return str(ruta_pura(self.ruta).parent)


class ContenedorInfo(BaseModel):
    con_id: int
    nombre: str
    open_mode: str

    @property
    def es_raiz(self) -> bool:
        return self.nombre == RAIZ_CDB

    @property
    def es_semilla(self) -> bool:
        return self.nombre == SEMILLA_PDB

    @property
    def abierto(self) -> bool:
        return self.open_mode.startswith("READ")


class TablespaceInfo(BaseModel):
    con_id: int
    nombre: str
    contenido: ContenidoTablespace
    estado: str | None
    bigfile: bool


class DatafileInfo(ArchivoFisico):
    file_id: int
    con_id: int
    tablespace: str
    bytes: int
    estado: str
    autoextensible: bool | None
    max_bytes: int | None
    bytes_libres: int | None

    @property
    def bytes_usados(self) -> int | None:
        if self.bytes_libres is None:
            return None
        return self.bytes - self.bytes_libres

    @property
    def limite_bytes(self) -> int:
        if self.autoextensible and self.max_bytes and self.max_bytes > self.bytes:
            return self.max_bytes
        return self.bytes

    @property
    def porcentaje_uso(self) -> float | None:
        usados = self.bytes_usados
        if usados is None or self.limite_bytes == 0:
            return None
        return usados / self.limite_bytes * 100


class TempfileInfo(ArchivoFisico):
    file_id: int
    con_id: int
    tablespace: str
    bytes: int
    estado: str


class ControlfileInfo(ArchivoFisico):
    bytes: int | None
    estado: str | None


class RedoMiembro(ArchivoFisico):
    estado: str | None
    tipo: str | None


class RedoGrupo(BaseModel):
    grupo: int
    hilo: int
    secuencia: int
    bytes: int
    estado: str
    archivado: bool
    miembros: list[RedoMiembro]


class ArchivoParametros(ArchivoFisico):
    tipo: TipoArchivoParametros

    @property
    def en_uso(self) -> bool:
        return self.tipo is TipoArchivoParametros.SPFILE


class DestinoArchivado(BaseModel):
    nombre: str
    destino: str
    estado: str


class AreaRecuperacion(BaseModel):
    ruta: str
    limite_bytes: int
    usados_bytes: int


class PerfilBD(BaseModel):
    nombre: str
    nombre_instancia: str
    dbid: int
    host: str
    version: str
    edicion: str
    es_cdb: bool
    log_mode: LogMode
    open_mode: str
    estado_instancia: str
    oracle_home: str | None
    diagnostic_dest: str | None
    capturado_en: datetime
    contenedores: list[ContenedorInfo]
    tablespaces: list[TablespaceInfo]
    datafiles: list[DatafileInfo]
    tempfiles: list[TempfileInfo]
    controlfiles: list[ControlfileInfo]
    redo_grupos: list[RedoGrupo]
    archivos_parametros: list[ArchivoParametros]
    destinos_archivado: list[DestinoArchivado]
    destino_archivado_configurado: bool
    area_recuperacion: AreaRecuperacion | None
    archivelogs_sin_respaldo: int

    def contenedor(self, con_id: int) -> ContenedorInfo | None:
        return next((c for c in self.contenedores if c.con_id == con_id), None)

    def tablespaces_de(self, con_id: int) -> list[TablespaceInfo]:
        return [t for t in self.tablespaces if t.con_id == con_id]

    def datafiles_de(self, con_id: int, tablespace: str) -> list[DatafileInfo]:
        return [d for d in self.datafiles if d.con_id == con_id and d.tablespace == tablespace]

    def tempfiles_de(self, con_id: int, tablespace: str) -> list[TempfileInfo]:
        return [t for t in self.tempfiles if t.con_id == con_id and t.tablespace == tablespace]
