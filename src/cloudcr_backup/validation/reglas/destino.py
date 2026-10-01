from cloudcr_backup.domain.enums import Severidad
from cloudcr_backup.domain.hallazgos import Hallazgo
from cloudcr_backup.domain.perfil_bd import ruta_pura
from cloudcr_backup.validation.contexto import ContextoValidacion
from cloudcr_backup.validation.motor import regla

UMBRAL_USO_DISCO_PORCENTAJE = 85.0


def _unidad(ruta: str) -> str:
    drive = ruta_pura(ruta).drive
    return drive.upper() if drive else ""


@regla("DST_001")
def dst_001_destino_no_escribible(contexto: ContextoValidacion) -> list[Hallazgo]:
    hallazgos = []
    for tarea in contexto.estrategia.tareas:
        ruta = tarea.destino.ruta
        if contexto.destinos_escribibles.get(ruta) is False:
            hallazgos.append(
                Hallazgo(
                    codigo="DST_001",
                    severidad=Severidad.ERROR,
                    mensaje=f"El destino {ruta} de la tarea {tarea.codigo} no existe o no se puede escribir en él.",
                    sujeto=tarea.codigo,
                    accion_sugerida="Cree la carpeta de destino y verifique los permisos de escritura.",
                )
            )
    return hallazgos


@regla("DST_002")
def dst_002_espacio_insuficiente(contexto: ContextoValidacion) -> list[Hallazgo]:
    hallazgos = []
    for tarea in contexto.estrategia.tareas:
        estimado = contexto.espacio_estimado_bytes.get(tarea.codigo)
        libre = contexto.espacio_libre_destino_bytes.get(tarea.destino.ruta)
        if estimado is None or libre is None or estimado <= libre:
            continue
        hallazgos.append(
            Hallazgo(
                codigo="DST_002",
                severidad=Severidad.ERROR,
                mensaje=(
                    f"La tarea {tarea.codigo} necesita aproximadamente {estimado} bytes y el destino "
                    f"{tarea.destino.ruta} solo tiene {libre} bytes libres."
                ),
                sujeto=tarea.codigo,
                accion_sugerida="Libere espacio en el destino o reduzca el alcance o la retención de la tarea.",
            )
        )
    return hallazgos


@regla("DST_003")
def dst_003_uso_de_disco_supera_el_umbral(contexto: ContextoValidacion) -> list[Hallazgo]:
    hallazgos = []
    for tarea in contexto.estrategia.tareas:
        ruta = tarea.destino.ruta
        total = contexto.espacio_total_destino_bytes.get(ruta)
        libre = contexto.espacio_libre_destino_bytes.get(ruta)
        if total is None or libre is None or total == 0:
            continue
        estimado = contexto.espacio_estimado_bytes.get(tarea.codigo, 0)
        uso_pct = (total - (libre - estimado)) / total * 100
        if uso_pct > UMBRAL_USO_DISCO_PORCENTAJE:
            hallazgos.append(
                Hallazgo(
                    codigo="DST_003",
                    severidad=Severidad.ADVERTENCIA,
                    mensaje=f"Tras la tarea {tarea.codigo}, el uso del disco en {ruta} llegaría a {uso_pct:.1f} %.",
                    sujeto=tarea.codigo,
                    accion_sugerida="Revise la política de retención o amplíe el espacio del destino.",
                )
            )
    return hallazgos


@regla("DST_004")
def dst_004_mismo_disco_que_los_datafiles(contexto: ContextoValidacion) -> list[Hallazgo]:
    unidades_datafiles = {_unidad(d.ruta) for d in contexto.perfil.datafiles if _unidad(d.ruta)}
    hallazgos = []
    for tarea in contexto.estrategia.tareas:
        unidad_destino = _unidad(tarea.destino.ruta)
        if not unidad_destino or unidad_destino not in unidades_datafiles:
            continue
        hallazgos.append(
            Hallazgo(
                codigo="DST_004",
                severidad=Severidad.RECOMENDACION,
                mensaje=(
                    f"El destino de la tarea {tarea.codigo} está en la misma unidad ({unidad_destino}) que "
                    "los datafiles: si se pierde ese disco, se pierden los datos y la copia."
                ),
                sujeto=tarea.codigo,
                accion_sugerida="Use un disco distinto al de los datafiles para los respaldos.",
            )
        )
    return hallazgos


@regla("DST_006")
def dst_006_ruta_con_caracteres_no_ascii(contexto: ContextoValidacion) -> list[Hallazgo]:
    return [
        Hallazgo(
            codigo="DST_006",
            severidad=Severidad.ERROR,
            mensaje=f"La ruta de destino de la tarea {tarea.codigo} tiene caracteres fuera de ASCII: "
            f"{tarea.destino.ruta}",
            sujeto=tarea.codigo,
            accion_sugerida="Use solo letras, números y símbolos ASCII en la ruta de destino.",
        )
        for tarea in contexto.estrategia.tareas
        if not tarea.destino.ruta.isascii()
    ]
