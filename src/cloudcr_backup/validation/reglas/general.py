from cloudcr_backup.domain.enums import Severidad
from cloudcr_backup.domain.hallazgos import Hallazgo
from cloudcr_backup.validation.contexto import ContextoValidacion
from cloudcr_backup.validation.motor import regla


@regla("GEN_001")
def gen_001_codigo_duplicado(contexto: ContextoValidacion) -> list[Hallazgo]:
    estrategia = contexto.estrategia
    if estrategia.codigo not in contexto.codigos_estrategia_existentes:
        return []
    return [
        Hallazgo(
            codigo="GEN_001",
            severidad=Severidad.ERROR,
            mensaje=f"Ya existe una estrategia con el código {estrategia.codigo} para esta base de datos.",
            sujeto=estrategia.codigo,
            accion_sugerida="Elija otro código, o edite la estrategia existente en lugar de crear una nueva.",
        )
    ]


@regla("GEN_002")
def gen_002_sin_tareas(contexto: ContextoValidacion) -> list[Hallazgo]:
    if contexto.estrategia.tareas:
        return []
    return [
        Hallazgo(
            codigo="GEN_002",
            severidad=Severidad.ERROR,
            mensaje="La estrategia no tiene ninguna tarea definida.",
            sujeto=contexto.estrategia.codigo,
            accion_sugerida="Agregue al menos una tarea con su tipo de respaldo y su programación.",
        )
    ]
