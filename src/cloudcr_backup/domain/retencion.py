from datetime import datetime

from pydantic import BaseModel, Field


class PiezaRetencion(BaseModel):
    pieza_id: int
    ruta: str
    tamano_bytes: int | None = None
    ejecucion_id: int
    tarea: str
    fin: datetime | None = None
    vence_en: datetime | None = None
    vencida: bool = False
    obsoleta_rman: bool = False
    marcada_obsoleta: bool = False


class RetencionEstrategia(BaseModel):
    estrategia: str
    nombre: str
    politica: str | None = None
    descripcion: str
    archived_logs_dias: int | None = None
    purga_automatica: bool = False
    piezas_total: int = 0
    vencidas: list[PiezaRetencion] = Field(default_factory=list)
    script: str | None = None
    avisos: list[str] = Field(default_factory=list)

    @property
    def bytes_vencidos(self) -> int:
        return sum(p.tamano_bytes or 0 for p in self.vencidas)


class InformeRetencion(BaseModel):
    bd: str
    generado_en: datetime
    estrategias: list[RetencionEstrategia] = Field(default_factory=list)
    archivelogs_sin_respaldo: int | None = None
    consulto_rman: bool = False
    obsoletas_rman: list[str] = Field(default_factory=list)
    avisos: list[str] = Field(default_factory=list)

    @property
    def total_vencidas(self) -> int:
        return sum(len(e.vencidas) for e in self.estrategias)


class ResultadoPurga(BaseModel):
    bd: str
    estrategia: str
    script: str
    log: str | None = None
    candidatas: list[str] = Field(default_factory=list)
    piezas_marcadas: int = 0
    borradas: list[str] = Field(default_factory=list)
    errores: list[str] = Field(default_factory=list)
    avisos: list[str] = Field(default_factory=list)

    @property
    def correcta(self) -> bool:
        return not self.errores
