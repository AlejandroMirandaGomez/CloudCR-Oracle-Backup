from cloudcr_backup.domain.enums import LogMode, ModoRespaldo, Severidad, TipoObjeto
from cloudcr_backup.domain.estrategia import Como
from cloudcr_backup.domain.hallazgos import Hallazgo
from cloudcr_backup.domain.perfil_bd import PerfilBD
from cloudcr_backup.validation.contexto import ContextoValidacion
from cloudcr_backup.validation.motor import regla

MENSAJE_ARCH_001 = (
    "La base de datos se encuentra en modo NOARCHIVELOG. Las posibilidades de recuperación son más limitadas. "
    "Revise la estrategia de respaldo y los requerimientos de recuperación antes de continuar."
)

MENSAJE_ARCH_002 = (
    "La base de datos se encuentra en modo ARCHIVELOG. Considere incorporar el respaldo periódico de los "
    "archived redo logs dentro de la estrategia para mejorar las posibilidades de recuperación."
)


def modo_efectivo(como: Como, perfil: PerfilBD) -> ModoRespaldo:
    if como.modo_respaldo is not ModoRespaldo.AUTO:
        return como.modo_respaldo
    return ModoRespaldo.EN_LINEA if perfil.log_mode is LogMode.ARCHIVELOG else ModoRespaldo.CONSISTENTE


@regla("ARCH_001")
def arch_001_noarchivelog(contexto: ContextoValidacion) -> list[Hallazgo]:
    if contexto.perfil.log_mode is LogMode.ARCHIVELOG:
        return []
    return [
        Hallazgo(
            codigo="ARCH_001",
            severidad=Severidad.ADVERTENCIA,
            mensaje=MENSAJE_ARCH_001,
            sujeto=contexto.perfil.nombre,
        )
    ]


@regla("ARCH_002")
def arch_002_archivelog_sin_logs_en_el_alcance(contexto: ContextoValidacion) -> list[Hallazgo]:
    if contexto.perfil.log_mode is not LogMode.ARCHIVELOG:
        return []
    ya_incluye_archivelogs = any(objeto.tipo is TipoObjeto.ARCHIVELOG for objeto in contexto.estrategia.alcance)
    if ya_incluye_archivelogs:
        return []
    return [
        Hallazgo(
            codigo="ARCH_002",
            severidad=Severidad.RECOMENDACION,
            mensaje=MENSAJE_ARCH_002,
            sujeto=contexto.estrategia.codigo,
            accion_sugerida="Agregar ARCHIVELOG al alcance de la estrategia.",
        )
    ]


@regla("ARCH_005")
def arch_005_en_linea_sin_archivelog(contexto: ContextoValidacion) -> list[Hallazgo]:
    if contexto.perfil.log_mode is LogMode.ARCHIVELOG:
        return []
    return [
        Hallazgo(
            codigo="ARCH_005",
            severidad=Severidad.ERROR,
            mensaje=(
                f"La tarea {tarea.codigo} pide un respaldo en línea (modo EN_LINEA), pero la base de datos está "
                "en NOARCHIVELOG (RMAN-06817 / ORA-19602). Un respaldo en caliente exige ARCHIVELOG."
            ),
            sujeto=tarea.codigo,
            accion_sugerida="Cambie el modo de la tarea a CONSISTENTE o active ARCHIVELOG antes de aprobar el script.",
        )
        for tarea in contexto.estrategia.tareas
        if modo_efectivo(tarea.como, contexto.perfil) is ModoRespaldo.EN_LINEA
    ]
