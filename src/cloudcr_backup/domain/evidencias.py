from pydantic import BaseModel


class EvidenciaEsperada(BaseModel):
    id: str
    titulo: str
    archivos: list[str] = []

    @property
    def disponible(self) -> bool:
        return bool(self.archivos)


class CatalogoEvidencias(BaseModel):
    carpeta: str | None
    evidencias: list[EvidenciaEsperada]

    @property
    def disponibles(self) -> int:
        return sum(1 for e in self.evidencias if e.disponible)
