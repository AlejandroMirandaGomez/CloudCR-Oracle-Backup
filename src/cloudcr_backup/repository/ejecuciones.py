from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

import oracledb

from cloudcr_backup.domain.enums import EstadoEjecucion, EstadoPrueba

_COLUMNAS_RESULTADO = {
    "estado",
    "fin",
    "ubicacion",
    "archivos_generados",
    "tamano_bytes",
    "duracion_segundos",
    "mensaje_rman",
    "errores",
    "advertencias",
    "estado_prueba",
}


@dataclass(frozen=True)
class FiltrosHistorial:
    bd_id: int | None = None
    estrategia_codigo: str | None = None
    estado: EstadoEjecucion | None = None
    desde: datetime | None = None
    hasta: datetime | None = None


@dataclass(frozen=True)
class Ejecucion:
    id: int
    tarea_id: int
    script_id: int
    estado: EstadoEjecucion
    programada_para: datetime
    inicio: datetime | None
    fin: datetime | None


def _desde_fila(fila: tuple[object, ...]) -> Ejecucion:
    id_, tarea_id, script_id, estado, programada_para, inicio, fin = fila
    assert isinstance(id_, int)
    assert isinstance(tarea_id, int)
    assert isinstance(script_id, int)
    assert isinstance(programada_para, datetime)
    assert inicio is None or isinstance(inicio, datetime)
    assert fin is None or isinstance(fin, datetime)
    return Ejecucion(
        id=id_,
        tarea_id=tarea_id,
        script_id=script_id,
        estado=EstadoEjecucion(str(estado)),
        programada_para=programada_para,
        inicio=inicio,
        fin=fin,
    )


def _normalizar(valor: object) -> object:
    return valor.value if isinstance(valor, StrEnum) else valor


def reclamar(conexion: oracledb.Connection, tarea_id: int, programada_para: datetime) -> Ejecucion | None:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            """
            SELECT e.bd_id, t.tipo_respaldo,
                   (SELECT id FROM script_rman WHERE tarea_id = t.id AND estado = 'APROBADO')
            FROM tarea t JOIN estrategia e ON e.id = t.estrategia_id
            WHERE t.id = :tarea_id
            """,
            tarea_id=tarea_id,
        )
        fila = cursor.fetchone()
        if fila is None:
            raise ValueError(f"No existe la tarea {tarea_id}.")
        bd_id, tipo_respaldo, script_id = fila
        if script_id is None:
            raise ValueError(f"La tarea {tarea_id} no tiene un script aprobado.")
        id_var = cursor.var(int)
        try:
            cursor.execute(
                """
                INSERT INTO ejecucion (tarea_id, script_id, bd_id, programada_para, estado, tipo_respaldo)
                VALUES (:tarea_id, :script_id, :bd_id, :programada_para, 'PROGRAMADA', :tipo_respaldo)
                RETURNING id INTO :id
                """,
                tarea_id=tarea_id,
                script_id=script_id,
                bd_id=bd_id,
                programada_para=programada_para,
                tipo_respaldo=tipo_respaldo,
                id=id_var,
            )
        except oracledb.IntegrityError:
            conexion.rollback()
            return None
        conexion.commit()
        return Ejecucion(
            id=int(id_var.getvalue()[0]),
            tarea_id=tarea_id,
            script_id=int(script_id),
            estado=EstadoEjecucion.PROGRAMADA,
            programada_para=programada_para,
            inicio=None,
            fin=None,
        )
    finally:
        cursor.close()


def marcar_en_curso(conexion: oracledb.Connection, ejecucion_id: int, agente: str) -> None:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            "UPDATE ejecucion SET estado = 'EN_CURSO', inicio = SYS_EXTRACT_UTC(SYSTIMESTAMP), agente = :agente "
            "WHERE id = :id",
            agente=agente,
            id=ejecucion_id,
        )
        conexion.commit()
    finally:
        cursor.close()


def registrar_resultado(conexion: oracledb.Connection, ejecucion_id: int, resultado: dict[str, object]) -> None:
    columnas = [c for c in resultado if c in _COLUMNAS_RESULTADO]
    if not columnas:
        return
    asignaciones = ", ".join(f"{c} = :{c}" for c in columnas)
    valores = {c: _normalizar(resultado[c]) for c in columnas}
    valores["id"] = ejecucion_id
    cursor = conexion.cursor()
    try:
        cursor.execute(f"UPDATE ejecucion SET {asignaciones} WHERE id = :id", **valores)
        conexion.commit()
    finally:
        cursor.close()


def historial(conexion: oracledb.Connection, filtros: FiltrosHistorial) -> list[Ejecucion]:
    condiciones = []
    parametros: dict[str, object] = {}
    if filtros.bd_id is not None:
        condiciones.append("ej.bd_id = :bd_id")
        parametros["bd_id"] = filtros.bd_id
    if filtros.estrategia_codigo is not None:
        condiciones.append("es.codigo = :estrategia_codigo")
        parametros["estrategia_codigo"] = filtros.estrategia_codigo
    if filtros.estado is not None:
        condiciones.append("ej.estado = :estado")
        parametros["estado"] = filtros.estado.value
    if filtros.desde is not None:
        condiciones.append("ej.programada_para >= :desde")
        parametros["desde"] = filtros.desde
    if filtros.hasta is not None:
        condiciones.append("ej.programada_para <= :hasta")
        parametros["hasta"] = filtros.hasta
    where = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""
    sql = f"""
        SELECT ej.id, ej.tarea_id, ej.script_id, ej.estado, ej.programada_para, ej.inicio, ej.fin
        FROM ejecucion ej
        JOIN tarea t ON t.id = ej.tarea_id
        JOIN estrategia es ON es.id = t.estrategia_id
        {where}
        ORDER BY ej.programada_para DESC
    """
    cursor = conexion.cursor()
    try:
        cursor.execute(sql, **parametros)
        return [_desde_fila(fila) for fila in cursor.fetchall()]
    finally:
        cursor.close()


def ultimas(conexion: oracledb.Connection, tarea_id: int, n: int) -> list[Ejecucion]:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            """
            SELECT id, tarea_id, script_id, estado, programada_para, inicio, fin FROM (
                SELECT id, tarea_id, script_id, estado, programada_para, inicio, fin
                FROM ejecucion WHERE tarea_id = :tarea_id ORDER BY programada_para DESC
            ) WHERE ROWNUM <= :n
            """,
            tarea_id=tarea_id,
            n=n,
        )
        return [_desde_fila(fila) for fila in cursor.fetchall()]
    finally:
        cursor.close()


@dataclass(frozen=True)
class EjecucionDetallada:
    id: int
    bd_id: int
    bd_nombre: str
    estrategia_id: int
    estrategia_codigo: str
    estrategia_nombre: str
    tarea_id: int
    tarea_codigo: str
    tipo_respaldo: str
    modo_respaldo: str
    estado: EstadoEjecucion
    estado_prueba: EstadoPrueba
    programada_para: datetime
    inicio: datetime | None
    fin: datetime | None
    duracion_segundos: int | None
    tamano_bytes: int | None
    archivos_generados: int | None
    ubicacion: str | None
    zona_horaria: str
    mensaje_rman: str | None
    agente: str | None
    script_id: int


@dataclass(frozen=True)
class DetalleEjecucionRepositorio:
    ejecucion: EjecucionDetallada
    errores: str | None
    advertencias: str | None
    script_version: int | None
    script_hash: str | None
    script_aprobado_por: str | None
    script_aprobado_en: datetime | None


@dataclass(frozen=True)
class PiezaEjecucion:
    nombre_archivo: str
    tamano_bytes: int | None
    tag: str | None
    vence_en: datetime | None
    obsoleta: bool


@dataclass(frozen=True)
class VerificacionRegistrada:
    tipo_prueba: str
    resultado: EstadoPrueba
    detalle: str | None
    ejecutada_en: datetime | None


@dataclass(frozen=True)
class EjecucionInterrumpida:
    id: int
    tarea_id: int
    programada_para: datetime
    modo_respaldo: str


_COLUMNAS_DETALLADAS = """
    ej.id ejecucion_id, ej.bd_id bd_id, b.nombre bd_nombre, es.id estrategia_id, es.codigo estrategia_codigo,
    es.nombre estrategia_nombre, t.id tarea_id, t.codigo tarea_codigo, ej.tipo_respaldo tipo_respaldo,
    t.modo_respaldo modo_respaldo, ej.estado estado, ej.estado_prueba estado_prueba,
    ej.programada_para programada_para, ej.inicio inicio, ej.fin fin, ej.duracion_segundos duracion_segundos,
    ej.tamano_bytes tamano_bytes, ej.archivos_generados archivos_generados, ej.ubicacion ubicacion,
    NVL(p.zona_horaria, 'America/Costa_Rica') zona_horaria, ej.mensaje_rman mensaje_rman, ej.agente agente,
    ej.script_id script_id
"""

_ORIGEN_DETALLADO = """
    FROM ejecucion ej
    JOIN tarea t ON t.id = ej.tarea_id
    JOIN estrategia es ON es.id = t.estrategia_id
    JOIN bd_registrada b ON b.id = ej.bd_id
    LEFT JOIN programacion p ON p.tarea_id = t.id
"""

ESTADOS_CORRECTOS_SQL = "('EXITOSA', 'CON_ADVERTENCIAS')"


def _entero_o_nulo(valor: object) -> int | None:
    return None if valor is None else int(str(valor))


def _momento_o_nulo(valor: object) -> datetime | None:
    return valor if isinstance(valor, datetime) else None


def _texto_o_nulo(valor: object) -> str | None:
    return None if valor is None else str(valor)


def _detallada_desde_fila(fila: tuple[object, ...]) -> EjecucionDetallada:
    (
        id_, bd_id, bd_nombre, estrategia_id, estrategia_codigo, estrategia_nombre, tarea_id, tarea_codigo,
        tipo_respaldo, modo_respaldo, estado, estado_prueba, programada_para, inicio, fin, duracion, tamano,
        archivos, ubicacion, zona_horaria, mensaje_rman, agente, script_id,
    ) = fila
    assert isinstance(programada_para, datetime)
    return EjecucionDetallada(
        id=int(str(id_)),
        bd_id=int(str(bd_id)),
        bd_nombre=str(bd_nombre),
        estrategia_id=int(str(estrategia_id)),
        estrategia_codigo=str(estrategia_codigo),
        estrategia_nombre=str(estrategia_nombre),
        tarea_id=int(str(tarea_id)),
        tarea_codigo=str(tarea_codigo),
        tipo_respaldo=str(tipo_respaldo),
        modo_respaldo=str(modo_respaldo),
        estado=EstadoEjecucion(str(estado)),
        estado_prueba=EstadoPrueba(str(estado_prueba)),
        programada_para=programada_para,
        inicio=_momento_o_nulo(inicio),
        fin=_momento_o_nulo(fin),
        duracion_segundos=_entero_o_nulo(duracion),
        tamano_bytes=_entero_o_nulo(tamano),
        archivos_generados=_entero_o_nulo(archivos),
        ubicacion=_texto_o_nulo(ubicacion),
        zona_horaria=str(zona_horaria),
        mensaje_rman=_texto_o_nulo(mensaje_rman),
        agente=_texto_o_nulo(agente),
        script_id=int(str(script_id)),
    )


def _condiciones_historial(filtros: FiltrosHistorial) -> tuple[str, dict[str, object]]:
    condiciones = []
    parametros: dict[str, object] = {}
    if filtros.bd_id is not None:
        condiciones.append("ej.bd_id = :bd_id")
        parametros["bd_id"] = filtros.bd_id
    if filtros.estrategia_codigo is not None:
        condiciones.append("es.codigo = :estrategia_codigo")
        parametros["estrategia_codigo"] = filtros.estrategia_codigo
    if filtros.estado is not None:
        condiciones.append("ej.estado = :estado")
        parametros["estado"] = filtros.estado.value
    if filtros.desde is not None:
        condiciones.append("ej.programada_para >= :desde")
        parametros["desde"] = filtros.desde
    if filtros.hasta is not None:
        condiciones.append("ej.programada_para <= :hasta")
        parametros["hasta"] = filtros.hasta
    where = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""
    return where, parametros


def historial_detallado(
    conexion: oracledb.Connection, filtros: FiltrosHistorial, limite: int = 200, desplazamiento: int = 0
) -> list[EjecucionDetallada]:
    where, parametros = _condiciones_historial(filtros)
    sql = f"""
        SELECT {_COLUMNAS_DETALLADAS} {_ORIGEN_DETALLADO} {where}
        ORDER BY ej.programada_para DESC, ej.id DESC
        OFFSET :desplazamiento ROWS FETCH NEXT :limite ROWS ONLY
    """
    cursor = conexion.cursor()
    try:
        cursor.execute(sql, desplazamiento=desplazamiento, limite=limite, **parametros)
        return [_detallada_desde_fila(fila) for fila in cursor.fetchall()]
    finally:
        cursor.close()


def contar_historial(conexion: oracledb.Connection, filtros: FiltrosHistorial) -> int:
    where, parametros = _condiciones_historial(filtros)
    cursor = conexion.cursor()
    try:
        cursor.execute(f"SELECT COUNT(*) {_ORIGEN_DETALLADO} {where}", **parametros)
        fila = cursor.fetchone()
        return int(fila[0]) if fila is not None else 0
    finally:
        cursor.close()


def detalle(conexion: oracledb.Connection, ejecucion_id: int) -> DetalleEjecucionRepositorio | None:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            f"""
            SELECT {_COLUMNAS_DETALLADAS}, ej.errores, ej.advertencias, s.version, s.hash_sha256, s.aprobado_por,
                   s.aprobado_en
            {_ORIGEN_DETALLADO}
            LEFT JOIN script_rman s ON s.id = ej.script_id
            WHERE ej.id = :id
            """,
            id=ejecucion_id,
        )
        fila = cursor.fetchone()
        if fila is None:
            return None
        *base, errores, advertencias, version, hash_sha256, aprobado_por, aprobado_en = fila
        return DetalleEjecucionRepositorio(
            ejecucion=_detallada_desde_fila(tuple(base)),
            errores=_texto_o_nulo(errores),
            advertencias=_texto_o_nulo(advertencias),
            script_version=_entero_o_nulo(version),
            script_hash=_texto_o_nulo(hash_sha256),
            script_aprobado_por=_texto_o_nulo(aprobado_por),
            script_aprobado_en=_momento_o_nulo(aprobado_en),
        )
    finally:
        cursor.close()


def piezas(conexion: oracledb.Connection, ejecucion_id: int) -> list[PiezaEjecucion]:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            """
            SELECT nombre_archivo, tamano_bytes, tag, vence_en, obsoleta FROM ejecucion_pieza
            WHERE ejecucion_id = :id ORDER BY id
            """,
            id=ejecucion_id,
        )
        return [
            PiezaEjecucion(
                nombre_archivo=str(nombre),
                tamano_bytes=_entero_o_nulo(tamano),
                tag=_texto_o_nulo(tag),
                vence_en=_momento_o_nulo(vence_en),
                obsoleta=obsoleta == "S",
            )
            for nombre, tamano, tag, vence_en, obsoleta in cursor.fetchall()
        ]
    finally:
        cursor.close()


def verificaciones(conexion: oracledb.Connection, ejecucion_id: int) -> list[VerificacionRegistrada]:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            """
            SELECT tipo_prueba, resultado, detalle, ejecutada_en FROM verificacion
            WHERE ejecucion_id = :id ORDER BY ejecutada_en
            """,
            id=ejecucion_id,
        )
        return [
            VerificacionRegistrada(
                tipo_prueba=str(tipo),
                resultado=EstadoPrueba(str(resultado)),
                detalle=_texto_o_nulo(texto),
                ejecutada_en=_momento_o_nulo(ejecutada_en),
            )
            for tipo, resultado, texto, ejecutada_en in cursor.fetchall()
        ]
    finally:
        cursor.close()


def ultimas_por_tarea(conexion: oracledb.Connection, n: int) -> dict[int, list[EjecucionDetallada]]:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            f"""
            SELECT * FROM (
                SELECT {_COLUMNAS_DETALLADAS},
                       ROW_NUMBER() OVER (PARTITION BY ej.tarea_id ORDER BY ej.programada_para DESC, ej.id DESC) orden
                {_ORIGEN_DETALLADO}
            ) WHERE orden <= :n
            ORDER BY tarea_id, orden
            """,
            n=n,
        )
        resultado: dict[int, list[EjecucionDetallada]] = {}
        for fila in cursor.fetchall():
            ejecucion = _detallada_desde_fila(tuple(fila[:-1]))
            resultado.setdefault(ejecucion.tarea_id, []).append(ejecucion)
        return resultado
    finally:
        cursor.close()


def en_curso(conexion: oracledb.Connection) -> list[EjecucionDetallada]:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            f"""
            SELECT {_COLUMNAS_DETALLADAS} {_ORIGEN_DETALLADO}
            WHERE ej.estado IN ('EN_CURSO', 'PROGRAMADA')
            ORDER BY ej.programada_para
            """
        )
        return [_detallada_desde_fila(fila) for fila in cursor.fetchall()]
    finally:
        cursor.close()


def ultima_programada_por_tarea(conexion: oracledb.Connection) -> dict[int, datetime]:
    cursor = conexion.cursor()
    try:
        cursor.execute("SELECT tarea_id, MAX(programada_para) FROM ejecucion GROUP BY tarea_id")
        return {int(tarea_id): momento for tarea_id, momento in cursor.fetchall() if isinstance(momento, datetime)}
    finally:
        cursor.close()


def ultimo_exito_por_estrategia(conexion: oracledb.Connection) -> dict[int, datetime]:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            f"""
            SELECT t.estrategia_id, MAX(NVL(ej.fin, ej.programada_para))
            FROM ejecucion ej JOIN tarea t ON t.id = ej.tarea_id
            WHERE ej.estado IN {ESTADOS_CORRECTOS_SQL}
            GROUP BY t.estrategia_id
            """
        )
        return {int(estrategia_id): momento for estrategia_id, momento in cursor.fetchall() if momento is not None}
    finally:
        cursor.close()


def tamano_ultimo_exito_por_tarea(conexion: oracledb.Connection) -> dict[int, int]:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            f"""
            SELECT tarea_id, tamano_bytes FROM (
                SELECT tarea_id, tamano_bytes,
                       ROW_NUMBER() OVER (PARTITION BY tarea_id ORDER BY programada_para DESC) orden
                FROM ejecucion
                WHERE estado IN {ESTADOS_CORRECTOS_SQL} AND tamano_bytes IS NOT NULL
            ) WHERE orden = 1
            """
        )
        return {int(tarea_id): int(tamano) for tarea_id, tamano in cursor.fetchall()}
    finally:
        cursor.close()


def piezas_vencidas_por_estrategia(conexion: oracledb.Connection, ahora: datetime) -> dict[int, int]:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            """
            SELECT t.estrategia_id, COUNT(*)
            FROM ejecucion_pieza pz
            JOIN ejecucion ej ON ej.id = pz.ejecucion_id
            JOIN tarea t ON t.id = ej.tarea_id
            WHERE pz.vence_en < :ahora AND pz.obsoleta = 'N'
            GROUP BY t.estrategia_id
            """,
            ahora=ahora,
        )
        return {int(estrategia_id): int(cantidad) for estrategia_id, cantidad in cursor.fetchall()}
    finally:
        cursor.close()


def registrar_no_ejecutada(
    conexion: oracledb.Connection, tarea_id: int, programada_para: datetime, motivo: str
) -> Ejecucion | None:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            """
            SELECT e.bd_id, t.tipo_respaldo,
                   (SELECT id FROM script_rman WHERE tarea_id = t.id AND estado = 'APROBADO')
            FROM tarea t JOIN estrategia e ON e.id = t.estrategia_id
            WHERE t.id = :tarea_id
            """,
            tarea_id=tarea_id,
        )
        fila = cursor.fetchone()
        if fila is None:
            raise ValueError(f"No existe la tarea {tarea_id}.")
        bd_id, tipo_respaldo, script_id = fila
        if script_id is None:
            raise ValueError(f"La tarea {tarea_id} no tiene un script aprobado.")
        id_var = cursor.var(int)
        try:
            cursor.execute(
                """
                INSERT INTO ejecucion (tarea_id, script_id, bd_id, programada_para, estado, tipo_respaldo,
                                       mensaje_rman, estado_prueba)
                VALUES (:tarea_id, :script_id, :bd_id, :programada_para, 'NO_EJECUTADA', :tipo_respaldo,
                        :motivo, 'NO_APLICA')
                RETURNING id INTO :id
                """,
                tarea_id=tarea_id,
                script_id=script_id,
                bd_id=bd_id,
                programada_para=programada_para,
                tipo_respaldo=tipo_respaldo,
                motivo=motivo[:4000],
                id=id_var,
            )
        except oracledb.IntegrityError:
            conexion.rollback()
            return None
        conexion.commit()
        return Ejecucion(
            id=int(id_var.getvalue()[0]),
            tarea_id=tarea_id,
            script_id=int(script_id),
            estado=EstadoEjecucion.NO_EJECUTADA,
            programada_para=programada_para,
            inicio=None,
            fin=None,
        )
    finally:
        cursor.close()


def programadas_sin_iniciar(conexion: oracledb.Connection, antes_de: datetime) -> list[Ejecucion]:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            """
            SELECT id, tarea_id, script_id, estado, programada_para, inicio, fin FROM ejecucion
            WHERE estado = 'PROGRAMADA' AND inicio IS NULL AND programada_para < :antes_de
            ORDER BY programada_para
            """,
            antes_de=antes_de,
        )
        return [_desde_fila(fila) for fila in cursor.fetchall()]
    finally:
        cursor.close()


def marcar_no_ejecutada(conexion: oracledb.Connection, ejecucion_id: int, motivo: str) -> bool:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            """
            UPDATE ejecucion SET estado = 'NO_EJECUTADA', mensaje_rman = :motivo, estado_prueba = 'NO_APLICA'
            WHERE id = :id AND estado = 'PROGRAMADA'
            """,
            motivo=motivo[:4000],
            id=ejecucion_id,
        )
        conexion.commit()
        return cursor.rowcount == 1
    finally:
        cursor.close()


def en_curso_de_agente(conexion: oracledb.Connection, agente: str) -> list[EjecucionInterrumpida]:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            """
            SELECT ej.id, ej.tarea_id, ej.programada_para, t.modo_respaldo
            FROM ejecucion ej JOIN tarea t ON t.id = ej.tarea_id
            WHERE ej.estado = 'EN_CURSO' AND ej.agente = :agente
            ORDER BY ej.programada_para
            """,
            agente=agente,
        )
        return [
            EjecucionInterrumpida(
                id=int(id_), tarea_id=int(tarea_id), programada_para=programada_para, modo_respaldo=str(modo)
            )
            for id_, tarea_id, programada_para, modo in cursor.fetchall()
        ]
    finally:
        cursor.close()


def marcar_interrumpida(conexion: oracledb.Connection, ejecucion_id: int, motivo: str) -> bool:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            """
            UPDATE ejecucion SET estado = 'FALLIDA', fin = SYS_EXTRACT_UTC(SYSTIMESTAMP), mensaje_rman = :motivo,
                   estado_prueba = 'NO_APLICA'
            WHERE id = :id AND estado = 'EN_CURSO'
            """,
            motivo=motivo[:4000],
            id=ejecucion_id,
        )
        conexion.commit()
        return cursor.rowcount == 1
    finally:
        cursor.close()
