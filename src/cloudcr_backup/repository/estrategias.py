from datetime import datetime, time

import oracledb

from cloudcr_backup.domain.enums import (
    Compresion,
    DiaSemana,
    EstadoEstrategia,
    ModoRespaldo,
    PoliticaOmision,
    Prioridad,
    TipoFrecuencia,
    TipoObjeto,
    TipoRespaldo,
)
from cloudcr_backup.domain.estrategia import (
    Como,
    Destino,
    Estrategia,
    ObjetoAlcance,
    OpcionesRespaldo,
    Programacion,
    Retencion,
    Tarea,
    Ventana,
)


def _cargar_alcance(cursor: oracledb.Cursor, estrategia_id: int) -> list[ObjetoAlcance]:
    cursor.execute(
        "SELECT tipo_objeto, identificador, prioridad FROM estrategia_objeto WHERE estrategia_id = :id ORDER BY id",
        id=estrategia_id,
    )
    return [
        ObjetoAlcance(tipo=TipoObjeto(tipo), identificador=identificador or "", prioridad=Prioridad(prioridad))
        for tipo, identificador, prioridad in cursor.fetchall()
    ]


def _cargar_tareas(cursor: oracledb.Cursor, estrategia_id: int) -> list[Tarea]:
    cursor.execute(
        """
        SELECT t.codigo, t.tipo_respaldo, t.modo_respaldo, t.compresion, t.canales, t.destino_ruta,
               t.destino_etiqueta, t.omitir_solo_lectura, p.tipo_frecuencia, p.horas, p.dias_semana,
               p.intervalo_minutos, p.fecha_inicio, p.ventana_inicio, p.ventana_fin, p.zona_horaria,
               p.politica_omision
        FROM tarea t
        JOIN programacion p ON p.tarea_id = t.id
        WHERE t.estrategia_id = :id
        ORDER BY t.id
        """,
        id=estrategia_id,
    )
    tareas = []
    for fila in cursor.fetchall():
        (
            codigo, tipo_respaldo, modo_respaldo, compresion, canales, destino_ruta, destino_etiqueta,
            omitir_solo_lectura, tipo_frecuencia, horas, dias_semana, intervalo_minutos, fecha_inicio,
            ventana_inicio, ventana_fin, zona_horaria, politica_omision,
        ) = fila
        ventana = None
        if ventana_inicio and ventana_fin:
            ventana = Ventana(inicio=time.fromisoformat(ventana_inicio), fin=time.fromisoformat(ventana_fin))
        tareas.append(
            Tarea(
                codigo=codigo,
                como=Como(
                    tipo_respaldo=TipoRespaldo(tipo_respaldo),
                    modo_respaldo=ModoRespaldo(modo_respaldo),
                    opciones=OpcionesRespaldo(
                        compresion=Compresion(compresion),
                        canales=canales,
                        omitir_solo_lectura=omitir_solo_lectura == "S",
                    ),
                ),
                programacion=Programacion(
                    tipo_frecuencia=TipoFrecuencia(tipo_frecuencia),
                    horas=[time.fromisoformat(h) for h in horas.split(",")] if horas else [],
                    dias_semana=[DiaSemana(d) for d in dias_semana.split(",")] if dias_semana else [],
                    intervalo_minutos=intervalo_minutos,
                    fecha_inicio=fecha_inicio.date() if isinstance(fecha_inicio, datetime) else fecha_inicio,
                    ventana=ventana,
                    zona_horaria=zona_horaria,
                    politica_omision=PoliticaOmision(politica_omision),
                ),
                destino=Destino(ruta=destino_ruta, etiqueta=destino_etiqueta),
            )
        )
    return tareas


def _guardar_alcance(cursor: oracledb.Cursor, estrategia_id: int, alcance: list[ObjetoAlcance]) -> None:
    for objeto in alcance:
        cursor.execute(
            """
            INSERT INTO estrategia_objeto (estrategia_id, tipo_objeto, identificador, prioridad)
            VALUES (:estrategia_id, :tipo, :identificador, :prioridad)
            """,
            estrategia_id=estrategia_id,
            tipo=objeto.tipo.value,
            identificador=objeto.identificador,
            prioridad=objeto.prioridad.value,
        )


def _guardar_tareas(cursor: oracledb.Cursor, estrategia_id: int, tareas: list[Tarea]) -> None:
    for tarea in tareas:
        tarea_id_var = cursor.var(int)
        cursor.execute(
            """
            INSERT INTO tarea (estrategia_id, codigo, tipo_respaldo, modo_respaldo, compresion, canales,
                                destino_ruta, destino_etiqueta, omitir_solo_lectura)
            VALUES (:estrategia_id, :codigo, :tipo_respaldo, :modo_respaldo, :compresion, :canales,
                    :destino_ruta, :destino_etiqueta, :omitir_solo_lectura)
            RETURNING id INTO :tarea_id
            """,
            estrategia_id=estrategia_id,
            codigo=tarea.codigo,
            tipo_respaldo=tarea.como.tipo_respaldo.value,
            modo_respaldo=tarea.como.modo_respaldo.value,
            compresion=tarea.como.opciones.compresion.value,
            canales=tarea.como.opciones.canales,
            destino_ruta=tarea.destino.ruta,
            destino_etiqueta=tarea.destino.etiqueta,
            omitir_solo_lectura="S" if tarea.como.opciones.omitir_solo_lectura else "N",
            tarea_id=tarea_id_var,
        )
        tarea_id = int(tarea_id_var.getvalue()[0])
        prog = tarea.programacion
        cursor.execute(
            """
            INSERT INTO programacion (tarea_id, tipo_frecuencia, horas, dias_semana, intervalo_minutos,
                                       fecha_inicio, ventana_inicio, ventana_fin, zona_horaria, politica_omision)
            VALUES (:tarea_id, :tipo_frecuencia, :horas, :dias_semana, :intervalo_minutos,
                    :fecha_inicio, :ventana_inicio, :ventana_fin, :zona_horaria, :politica_omision)
            """,
            tarea_id=tarea_id,
            tipo_frecuencia=prog.tipo_frecuencia.value,
            horas=",".join(h.strftime("%H:%M") for h in prog.horas) or None,
            dias_semana=",".join(d.value for d in prog.dias_semana) or None,
            intervalo_minutos=prog.intervalo_minutos,
            fecha_inicio=prog.fecha_inicio,
            ventana_inicio=prog.ventana.inicio.strftime("%H:%M") if prog.ventana else None,
            ventana_fin=prog.ventana.fin.strftime("%H:%M") if prog.ventana else None,
            zona_horaria=prog.zona_horaria,
            politica_omision=prog.politica_omision.value,
        )


def _ensamblar(cursor: oracledb.Cursor, bd_id: int, fila: tuple[object, ...]) -> Estrategia:
    (
        id_, codigo, nombre, descripcion, prioridad, estado, version, creada_por, creada_en,
        ventana_dias, redundancia, archivelog_dias, purga,
    ) = fila
    assert isinstance(id_, int)
    return Estrategia(
        id=id_,
        bd_id=bd_id,
        codigo=codigo,  # type: ignore[arg-type]
        nombre=nombre,  # type: ignore[arg-type]
        descripcion=descripcion,  # type: ignore[arg-type]
        prioridad=Prioridad(str(prioridad)),
        estado=EstadoEstrategia(str(estado)),
        version=version,  # type: ignore[arg-type]
        creada_por=creada_por,  # type: ignore[arg-type]
        creada_en=creada_en,  # type: ignore[arg-type]
        alcance=_cargar_alcance(cursor, id_),
        tareas=_cargar_tareas(cursor, id_),
        retencion=Retencion(
            ventana_dias=ventana_dias,  # type: ignore[arg-type]
            redundancia=redundancia,  # type: ignore[arg-type]
            archived_logs_dias=archivelog_dias,  # type: ignore[arg-type]
            purga_automatica=purga == "S",
        ),
    )


_COLUMNAS = (
    "id, codigo, nombre, descripcion, prioridad, estado, version, creada_por, creada_en, "
    "retencion_ventana_dias, retencion_redundancia, retencion_archivelog_dias, retencion_purga_automatica"
)


def crear(conexion: oracledb.Connection, estrategia: Estrategia) -> Estrategia:
    cursor = conexion.cursor()
    try:
        id_var = cursor.var(int)
        cursor.execute(
            """
            INSERT INTO estrategia (bd_id, codigo, nombre, descripcion, prioridad, estado, version, creada_por,
                                     retencion_ventana_dias, retencion_redundancia, retencion_archivelog_dias,
                                     retencion_purga_automatica)
            VALUES (:bd_id, :codigo, :nombre, :descripcion, :prioridad, :estado, :version, :creada_por,
                    :ventana_dias, :redundancia, :archivelog_dias, :purga)
            RETURNING id INTO :id
            """,
            bd_id=estrategia.bd_id,
            codigo=estrategia.codigo,
            nombre=estrategia.nombre,
            descripcion=estrategia.descripcion,
            prioridad=estrategia.prioridad.value,
            estado=estrategia.estado.value,
            version=estrategia.version,
            creada_por=estrategia.creada_por,
            ventana_dias=estrategia.retencion.ventana_dias,
            redundancia=estrategia.retencion.redundancia,
            archivelog_dias=estrategia.retencion.archived_logs_dias,
            purga="S" if estrategia.retencion.purga_automatica else "N",
            id=id_var,
        )
        estrategia_id = int(id_var.getvalue()[0])
        _guardar_alcance(cursor, estrategia_id, estrategia.alcance)
        _guardar_tareas(cursor, estrategia_id, estrategia.tareas)
        conexion.commit()
        return estrategia.model_copy(update={"id": estrategia_id})
    finally:
        cursor.close()


def actualizar(conexion: oracledb.Connection, estrategia: Estrategia) -> Estrategia:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            "SELECT id FROM estrategia WHERE bd_id = :bd_id AND codigo = :codigo",
            bd_id=estrategia.bd_id,
            codigo=estrategia.codigo,
        )
        fila = cursor.fetchone()
        if fila is None:
            raise ValueError(f"No existe la estrategia {estrategia.codigo} en la base {estrategia.bd_id}.")
        estrategia_id = fila[0]
        cursor.execute(
            """
            UPDATE estrategia
            SET nombre = :nombre, descripcion = :descripcion, prioridad = :prioridad, estado = :estado,
                version = :version, retencion_ventana_dias = :ventana_dias,
                retencion_redundancia = :redundancia, retencion_archivelog_dias = :archivelog_dias,
                retencion_purga_automatica = :purga
            WHERE id = :id
            """,
            nombre=estrategia.nombre,
            descripcion=estrategia.descripcion,
            prioridad=estrategia.prioridad.value,
            estado=estrategia.estado.value,
            version=estrategia.version,
            ventana_dias=estrategia.retencion.ventana_dias,
            redundancia=estrategia.retencion.redundancia,
            archivelog_dias=estrategia.retencion.archived_logs_dias,
            purga="S" if estrategia.retencion.purga_automatica else "N",
            id=estrategia_id,
        )
        cursor.execute(
            "DELETE FROM programacion WHERE tarea_id IN (SELECT id FROM tarea WHERE estrategia_id = :id)",
            id=estrategia_id,
        )
        cursor.execute("DELETE FROM tarea WHERE estrategia_id = :id", id=estrategia_id)
        cursor.execute("DELETE FROM estrategia_objeto WHERE estrategia_id = :id", id=estrategia_id)
        _guardar_alcance(cursor, estrategia_id, estrategia.alcance)
        _guardar_tareas(cursor, estrategia_id, estrategia.tareas)
        conexion.commit()
        return estrategia.model_copy(update={"id": estrategia_id})
    finally:
        cursor.close()


def listar(conexion: oracledb.Connection, bd_id: int) -> list[Estrategia]:
    cursor = conexion.cursor()
    try:
        cursor.execute(f"SELECT {_COLUMNAS} FROM estrategia WHERE bd_id = :bd_id ORDER BY codigo", bd_id=bd_id)
        return [_ensamblar(cursor, bd_id, fila) for fila in cursor.fetchall()]
    finally:
        cursor.close()


def obtener(conexion: oracledb.Connection, bd_id: int, codigo: str) -> Estrategia | None:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            f"SELECT {_COLUMNAS} FROM estrategia WHERE bd_id = :bd_id AND codigo = :codigo",
            bd_id=bd_id,
            codigo=codigo,
        )
        fila = cursor.fetchone()
        return _ensamblar(cursor, bd_id, fila) if fila is not None else None
    finally:
        cursor.close()


def _cambiar_estado(conexion: oracledb.Connection, bd_id: int, codigo: str, estado: EstadoEstrategia) -> None:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            "UPDATE estrategia SET estado = :estado WHERE bd_id = :bd_id AND codigo = :codigo",
            estado=estado.value,
            bd_id=bd_id,
            codigo=codigo,
        )
        conexion.commit()
    finally:
        cursor.close()


def activar(conexion: oracledb.Connection, bd_id: int, codigo: str) -> None:
    _cambiar_estado(conexion, bd_id, codigo, EstadoEstrategia.ACTIVA)


def desactivar(conexion: oracledb.Connection, bd_id: int, codigo: str) -> None:
    _cambiar_estado(conexion, bd_id, codigo, EstadoEstrategia.INACTIVA)


def obtener_tarea_id(
    conexion: oracledb.Connection, bd_id: int, estrategia_codigo: str, tarea_codigo: str
) -> int | None:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            """
            SELECT t.id FROM tarea t
            JOIN estrategia e ON e.id = t.estrategia_id
            WHERE e.bd_id = :bd_id AND e.codigo = :estrategia_codigo AND t.codigo = :tarea_codigo
            """,
            bd_id=bd_id,
            estrategia_codigo=estrategia_codigo,
            tarea_codigo=tarea_codigo,
        )
        fila = cursor.fetchone()
        return int(fila[0]) if fila is not None else None
    finally:
        cursor.close()


def ids_de_tareas(conexion: oracledb.Connection, estrategia_id: int) -> dict[str, int]:
    cursor = conexion.cursor()
    try:
        cursor.execute("SELECT codigo, id FROM tarea WHERE estrategia_id = :id", id=estrategia_id)
        return {str(codigo): int(id_) for codigo, id_ in cursor.fetchall()}
    finally:
        cursor.close()
