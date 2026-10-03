import json

from cloudcr_backup.domain.historial import DetalleEjecucion
from cloudcr_backup.presentacion.formato import formato_bytes
from cloudcr_backup.presentacion.historial import TEXTO_PRUEBAS, construir_fila, local


def secciones(detalle: DetalleEjecucion) -> list[tuple[str, list[str]]]:
    fila = detalle.fila
    tabla = construir_fila(fila)
    zona = fila.zona_horaria
    datos = [
        f"Ejecución: {fila.ejecucion_id}",
        f"Base de datos: {fila.bd}",
        f"Estrategia: {fila.estrategia} — {fila.estrategia_nombre}",
        f"Tarea: {fila.tarea} · {tabla.tipo}" + (f" · modo {fila.modo_respaldo.value}" if fila.modo_respaldo else ""),
        f"Hora programada: {tabla.fecha} {tabla.hora} ({zona})",
        f"Inicio: {tabla.inicio} · Fin: {tabla.fin} · Duración: {tabla.duracion}",
        f"Resultado: {tabla.simbolo} {tabla.resultado} · Pruebas: {tabla.pruebas}",
        f"Agente: {fila.agente or '—'}",
        f"Ubicación: {fila.ubicacion or '—'}",
        f"Archivos generados: {fila.archivos_generados if fila.archivos_generados is not None else '—'}"
        f" · Tamaño: {tabla.tamano}",
    ]
    if tabla.tardia:
        datos.append(f"Inició {tabla.retraso_minutos} min después de la hora programada (recuperada tarde).")
    script = [
        f"Script: {detalle.script_id if detalle.script_id is not None else '—'}"
        f" · versión {detalle.script_version if detalle.script_version is not None else '—'}",
        f"SHA-256: {detalle.script_hash or '—'}",
        f"Aprobado por: {detalle.script_aprobado_por or '—'}"
        + (
            f" el {local(detalle.script_aprobado_en, zona):%Y-%m-%d %H:%M}"
            if detalle.script_aprobado_en is not None
            else ""
        ),
    ]
    resultado = [f"Mensaje: {fila.mensaje or '—'}"]
    if detalle.errores:
        resultado.append(f"Errores: {detalle.errores}")
    if detalle.advertencias:
        resultado.append(f"Advertencias: {detalle.advertencias}")
    piezas = [
        f"{p.nombre_archivo} · {formato_bytes(p.tamano_bytes)} · tag {p.tag or '—'}"
        + (f" · vence {p.vence_en:%Y-%m-%d}" if p.vence_en else "")
        + (" · obsoleta" if p.obsoleta else "")
        for p in detalle.piezas
    ] or ["Sin piezas registradas."]
    verificaciones = [
        f"{v.tipo_prueba}: {TEXTO_PRUEBAS[v.resultado]}" + (f" — {v.detalle}" if v.detalle else "")
        for v in detalle.verificaciones
    ] or ["Sin verificaciones registradas."]
    log: list[str]
    if detalle.log_rman is None:
        log = ["Sin log de RMAN asociado."]
    elif not detalle.log_rman.existe:
        log = [f"{detalle.log_rman.ruta} (no existe en este equipo)"]
    else:
        log = [detalle.log_rman.ruta, "Primeras líneas:", *detalle.log_rman.primeras_lineas]
        if detalle.log_rman.ultimas_lineas:
            log += ["…", "Últimas líneas:", *detalle.log_rman.ultimas_lineas]
    resultado_secciones = [
        ("Ejecución", datos),
        ("Script RMAN", script),
        ("Resultado", resultado),
        ("Piezas de respaldo", piezas),
        ("Verificaciones", verificaciones),
        ("Log de RMAN", log),
    ]
    if detalle.evidencia is not None:
        resultado_secciones.append(
            (
                f"Evidencia ({detalle.ruta_evidencia})",
                json.dumps(detalle.evidencia, ensure_ascii=False, indent=2).splitlines(),
            )
        )
    if detalle.avisos:
        resultado_secciones.append(("Avisos", detalle.avisos))
    return resultado_secciones
