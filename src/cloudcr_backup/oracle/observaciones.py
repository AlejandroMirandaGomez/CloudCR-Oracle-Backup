from collections.abc import Callable, Iterator

from cloudcr_backup.domain.enums import LogMode, Severidad
from cloudcr_backup.domain.hallazgos import Hallazgo, ordenar_por_severidad
from cloudcr_backup.domain.perfil_bd import PerfilBD, ruta_pura

UMBRAL_USO_PCT = 85.0
ESTADOS_DATAFILE_NORMALES = {"ONLINE", "SYSTEM"}
ESTADOS_REDO_PROBLEMATICOS = {"INVALID", "STALE", "DELETED"}

SUJETO_INSTANCIA = "instancia"
SUJETO_ARCHIVADO = "archivado"
SUJETO_REDO = "redo"
SUJETO_CONTROLFILES = "controlfiles"
SUJETO_PARAMETROS = "parametros"

MENSAJE_NOARCHIVELOG = (
    "La base de datos se encuentra en modo NOARCHIVELOG. Las posibilidades de recuperación son más limitadas. "
    "Revise la estrategia de respaldo y los requerimientos de recuperación antes de continuar."
)

Regla = Callable[[PerfilBD], Iterator[Hallazgo]]


def sujeto_contenedor(con_id: int) -> str:
    return f"contenedor:{con_id}"


def sujeto_tablespace(con_id: int, nombre: str) -> str:
    return f"tablespace:{con_id}:{nombre}"


def sujeto_datafile(file_id: int) -> str:
    return f"datafile:{file_id}"


def sujeto_redo_grupo(grupo: int) -> str:
    return f"redo:{grupo}"


def modo_archivado(perfil: PerfilBD) -> Iterator[Hallazgo]:
    if perfil.log_mode is LogMode.NOARCHIVELOG:
        yield Hallazgo(
            codigo="ARCH_001",
            severidad=Severidad.ADVERTENCIA,
            mensaje=MENSAJE_NOARCHIVELOG,
            sujeto=SUJETO_ARCHIVADO,
            accion_sugerida="Evaluar activar ARCHIVELOG (decisión del administrador; la herramienta no lo cambia).",
        )
    elif perfil.archivelogs_sin_respaldo:
        yield Hallazgo(
            codigo="ARCH_011",
            severidad=Severidad.INFORMATIVA,
            mensaje=f"Hay {perfil.archivelogs_sin_respaldo} archived logs que todavía no tienen respaldo.",
            sujeto=SUJETO_ARCHIVADO,
        )


def destino_archivado(perfil: PerfilBD) -> Iterator[Hallazgo]:
    if perfil.destino_archivado_configurado:
        return
    actual = ", ".join(d.destino for d in perfil.destinos_archivado) or "el destino por defecto de Oracle"
    yield Hallazgo(
        codigo="ARCH_010",
        severidad=Severidad.RECOMENDACION,
        mensaje=(
            "No hay un destino de archivado definido explícitamente (LOG_ARCHIVE_DEST_n ni área de recuperación). "
            f"Los archived logs irían a {actual}."
        ),
        sujeto=SUJETO_ARCHIVADO,
        accion_sugerida="Definir LOG_ARCHIVE_DEST_1 o DB_RECOVERY_FILE_DEST en un disco distinto al de los datafiles.",
    )


def area_recuperacion(perfil: PerfilBD) -> Iterator[Hallazgo]:
    area = perfil.area_recuperacion
    if area is None or area.limite_bytes == 0:
        return
    uso = area.usados_bytes / area.limite_bytes * 100
    if uso >= UMBRAL_USO_PCT:
        yield Hallazgo(
            codigo="FRA_001",
            severidad=Severidad.ADVERTENCIA,
            mensaje=f"El área de recuperación está al {uso:.0f} % de su límite.",
            sujeto=SUJETO_ARCHIVADO,
        )


def redo_logs(perfil: PerfilBD) -> Iterator[Hallazgo]:
    sin_multiplexar = [g.grupo for g in perfil.redo_grupos if len(g.miembros) < 2]
    if sin_multiplexar:
        grupos = ", ".join(str(g) for g in sin_multiplexar)
        yield Hallazgo(
            codigo="RED_001",
            severidad=Severidad.RECOMENDACION,
            mensaje=f"Los grupos de redo {grupos} tienen un solo miembro (no están multiplexados).",
            sujeto=SUJETO_REDO,
            accion_sugerida="Agregar un segundo miembro por grupo en otro disco (ALTER DATABASE ADD LOGFILE MEMBER).",
        )
    for grupo in perfil.redo_grupos:
        for miembro in grupo.miembros:
            if (miembro.estado or "").upper() in ESTADOS_REDO_PROBLEMATICOS:
                yield Hallazgo(
                    codigo="RED_002",
                    severidad=Severidad.ADVERTENCIA,
                    mensaje=(
                        f"El miembro {miembro.nombre_archivo} del grupo {grupo.grupo} está en estado {miembro.estado}."
                    ),
                    sujeto=sujeto_redo_grupo(grupo.grupo),
                )


def control_files(perfil: PerfilBD) -> Iterator[Hallazgo]:
    if len(perfil.controlfiles) == 1:
        yield Hallazgo(
            codigo="CTL_001",
            severidad=Severidad.ADVERTENCIA,
            mensaje="La instancia tiene un único control file; su pérdida detiene la base.",
            sujeto=SUJETO_CONTROLFILES,
            accion_sugerida="Multiplexar el control file en al menos dos discos distintos.",
        )
    directorios = {c.directorio.lower() for c in perfil.controlfiles}
    if len(perfil.controlfiles) > 1 and len(directorios) == 1:
        yield Hallazgo(
            codigo="CTL_002",
            severidad=Severidad.RECOMENDACION,
            mensaje="Todas las copias del control file están en el mismo directorio.",
            sujeto=SUJETO_CONTROLFILES,
            accion_sugerida="Ubicar cada copia del control file en un disco distinto.",
        )


def archivo_parametros(perfil: PerfilBD) -> Iterator[Hallazgo]:
    if not any(a.en_uso for a in perfil.archivos_parametros):
        yield Hallazgo(
            codigo="PAR_001",
            severidad=Severidad.ADVERTENCIA,
            mensaje="La instancia se inició con un PFILE; RMAN no podrá respaldar el SPFILE.",
            sujeto=SUJETO_PARAMETROS,
            accion_sugerida="Crear un SPFILE (CREATE SPFILE FROM PFILE) y reiniciar la instancia con él.",
        )


def mismo_disco(perfil: PerfilBD) -> Iterator[Hallazgo]:
    rutas = [
        *(d.ruta for d in perfil.datafiles),
        *(c.ruta for c in perfil.controlfiles),
        *(m.ruta for g in perfil.redo_grupos for m in g.miembros),
    ]
    unidades = {(ruta_pura(r).anchor or "/").upper() for r in rutas}
    if rutas and len(unidades) == 1:
        yield Hallazgo(
            codigo="DIS_001",
            severidad=Severidad.RECOMENDACION,
            mensaje=f"Datafiles, control files y redo logs están todos en la misma unidad ({unidades.pop()}).",
            sujeto=SUJETO_INSTANCIA,
            accion_sugerida="Separar control files, redo logs y respaldos en discos distintos a los datafiles.",
        )


def contenedores(perfil: PerfilBD) -> Iterator[Hallazgo]:
    for contenedor in perfil.contenedores:
        if contenedor.es_semilla or contenedor.abierto:
            continue
        yield Hallazgo(
            codigo="CON_001",
            severidad=Severidad.ADVERTENCIA,
            mensaje=(
                f"La PDB {contenedor.nombre} no está abierta ({contenedor.open_mode}); "
                "no se puede medir el uso de sus datafiles."
            ),
            sujeto=sujeto_contenedor(contenedor.con_id),
        )


def tablespaces(perfil: PerfilBD) -> Iterator[Hallazgo]:
    for tablespace in perfil.tablespaces:
        if (tablespace.estado or "").upper() == "READ ONLY":
            yield Hallazgo(
                codigo="TS_001",
                severidad=Severidad.INFORMATIVA,
                mensaje=f"El tablespace {tablespace.nombre} es de solo lectura.",
                sujeto=sujeto_tablespace(tablespace.con_id, tablespace.nombre),
            )


def datafiles(perfil: PerfilBD) -> Iterator[Hallazgo]:
    for datafile in perfil.datafiles:
        uso = datafile.porcentaje_uso
        if uso is not None and uso >= UMBRAL_USO_PCT:
            yield Hallazgo(
                codigo="DF_001",
                severidad=Severidad.ADVERTENCIA,
                mensaje=f"{datafile.nombre_archivo} está al {uso:.0f} % de su capacidad máxima.",
                sujeto=sujeto_datafile(datafile.file_id),
                accion_sugerida="Ampliar el datafile (RESIZE) o agregar otro datafile al tablespace.",
            )
        if datafile.estado.upper() not in ESTADOS_DATAFILE_NORMALES:
            yield Hallazgo(
                codigo="DF_002",
                severidad=Severidad.ADVERTENCIA,
                mensaje=f"{datafile.nombre_archivo} está en estado {datafile.estado}.",
                sujeto=sujeto_datafile(datafile.file_id),
            )


REGLAS: tuple[Regla, ...] = (
    modo_archivado,
    destino_archivado,
    area_recuperacion,
    redo_logs,
    control_files,
    archivo_parametros,
    mismo_disco,
    contenedores,
    tablespaces,
    datafiles,
)


def observar(perfil: PerfilBD) -> list[Hallazgo]:
    return ordenar_por_severidad([hallazgo for regla in REGLAS for hallazgo in regla(perfil)])
