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


def _tareas_consistentes(contexto: ContextoValidacion) -> list[str]:
    return [
        tarea.codigo
        for tarea in contexto.estrategia.tareas
        if modo_efectivo(tarea.como, contexto.perfil) is ModoRespaldo.CONSISTENTE
    ]


@regla("ARCH_004")
def arch_004_archivelogs_sin_archivelog(contexto: ContextoValidacion) -> list[Hallazgo]:
    if contexto.perfil.log_mode is LogMode.ARCHIVELOG:
        return []
    if not any(objeto.tipo is TipoObjeto.ARCHIVELOG for objeto in contexto.estrategia.alcance):
        return []
    return [
        Hallazgo(
            codigo="ARCH_004",
            severidad=Severidad.ERROR,
            mensaje=(
                "La estrategia pide respaldar archived redo logs, pero la base de datos está en NOARCHIVELOG: "
                "no se generan archived logs que respaldar."
            ),
            sujeto=contexto.estrategia.codigo,
            accion_sugerida="Quite ARCHIVELOG del alcance o active el modo ARCHIVELOG antes de aprobar el script.",
        )
    ]


@regla("ARCH_006")
def arch_006_alcance_parcial_sin_archivelog(contexto: ContextoValidacion) -> list[Hallazgo]:
    if contexto.perfil.log_mode is LogMode.ARCHIVELOG:
        return []
    parciales = {TipoObjeto.PDB, TipoObjeto.TABLESPACE, TipoObjeto.DATAFILE}
    if not any(objeto.tipo in parciales for objeto in contexto.estrategia.alcance):
        return []
    return [
        Hallazgo(
            codigo="ARCH_006",
            severidad=Severidad.ADVERTENCIA,
            mensaje=(
                "La estrategia respalda un alcance parcial (PDB, tablespace o datafile) con la base en NOARCHIVELOG: "
                "las copias parciales no se pueden recuperar hasta un punto en el tiempo y pueden quedar "
                "inconsistentes con el resto de la base."
            ),
            sujeto=contexto.estrategia.codigo,
            accion_sugerida="Active ARCHIVELOG o respalde la base completa en modo CONSISTENTE.",
        )
    ]


@regla("ARCH_007")
def arch_007_respaldo_consistente_con_caida(contexto: ContextoValidacion) -> list[Hallazgo]:
    return [
        Hallazgo(
            codigo="ARCH_007",
            severidad=Severidad.ADVERTENCIA,
            mensaje=(
                f"La tarea {codigo} se ejecutará en modo CONSISTENTE: implica SHUTDOWN IMMEDIATE y la caída del "
                "servicio durante el respaldo. El script no se puede aprobar sin aceptar esa caída."
            ),
            sujeto=codigo,
            accion_sugerida="Programe la tarea sin usuarios conectados o active ARCHIVELOG para respaldar en línea.",
        )
        for codigo in _tareas_consistentes(contexto)
    ]


@regla("ARCH_009")
def arch_009_repositorio_en_la_misma_cdb(contexto: ContextoValidacion) -> list[Hallazgo]:
    servicio = contexto.repositorio_servicio
    if servicio is None or not contexto.perfil.es_cdb:
        return []
    vive_en_la_cdb = servicio.upper() in {c.nombre.upper() for c in contexto.perfil.contenedores}
    if not vive_en_la_cdb:
        return []
    return [
        Hallazgo(
            codigo="ARCH_009",
            severidad=Severidad.ADVERTENCIA,
            mensaje=(
                f"El repositorio ({servicio}) vive en la misma CDB que se respaldará en modo CONSISTENTE en la tarea "
                f"{codigo}: el SHUTDOWN IMMEDIATE lo apagará a mitad de la ejecución. La evidencia se escribe primero "
                "a disco y queda en el buzón hasta que el repositorio vuelva."
            ),
            sujeto=codigo,
            accion_sugerida="Respalde en línea (ARCHIVELOG) o ubique el repositorio en otra instancia.",
        )
        for codigo in _tareas_consistentes(contexto)
    ]
