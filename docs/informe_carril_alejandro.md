# Informe del carril de Alejandro — agente, programación, alertas, historial y web

Rama `feat/agente-alertas-historial`, creada desde `main` en `8704c94`. Trabajo hecho en un contenedor Linux **sin Oracle**: todo lo que necesita la XE quedó escrito, probado con dobles y marcado `[PENDIENTE]` donde corresponde.

## 1. Línea base y resultado final

| Herramienta | Línea base (`8704c94`) | Final |
|---|---|---|
| `pytest -q` | 332 pasan, **13 fallan** | 647 pasan, **las mismas 13** fallan |
| `ruff check src tests` | limpio | limpio |
| `mypy src` (estricto) con `--platform win32` | limpio | limpio |
| `mypy src` sin plataforma (Linux) | 2 errores (`winreg` en `oracle/discovery.py`) | los mismos 2 |
| `pytest -m oracle` | no ejecutable (sin Oracle) | **no ejecutable**: 21 errores de conexión y 1 falla del explorador, todos por falta de instancia |

Las 13 fallas son pruebas de rutas Windows (`test_destinos`, `test_discovery`, `test_solicitud_estrategia`) que dependen de `os.name == "nt"`; no son regresiones y deberían pasar en Windows. Se comparó la lista exacta antes y después.

`[PENDIENTE: correr pytest -q, mypy src y pytest -m oracle en la máquina Windows con la XE]`

## 2. Archivos

**Creados (90):** `scheduling/` (reloj, recurrencia, ventana, planificador), `agent/` (bucle, latido, puertos), `alerts/` (instantánea, reglas, motor, notificadores de consola y correo), `domain/` (alertas, historial, monitoreo, planificación, errores), `services/` (sesión, conversiones, fuente Oracle, agente, alertas, historial, monitoreo, consulta de estrategias, cliente Oracle), `presentacion/` (historial, estado, estrategias, detalle, terminal_monitoreo), `reports/` (historial, evidencia), `cli/` (cmd_agente, cmd_estado, cmd_historial, cmd_alertas, cmd_reporte, comun_monitoreo), `web/` (monitoreo, errores_servicio, 4 routers, 13 plantillas, `monitoreo.css`), `deploy/windows/registrar_tarea_agente.ps1`, documentos y pruebas.

**Archivos ajenos tocados (todos aditivos, sin cambiar firmas):**

| Archivo | Dueño | Qué se agregó |
|---|---|---|
| `repository/alertas.py` | Josué | `AlertaDetallada`, `abrir(condicion)` → `(alerta, es_nueva)`, `obtener`, `vigentes` (ABIERTA + RECONOCIDA), `listar`, `reconocer_abierta`, `resolver_vigente`. `resolver` ahora guarda `SYS_EXTRACT_UTC(SYSTIMESTAMP)` |
| `repository/ejecuciones.py` | Josué | `EjecucionDetallada`, `historial_detallado`, `contar_historial`, `detalle`, `piezas`, `verificaciones` (solo lectura), `ultimas_por_tarea`, `en_curso`, `ultima_programada_por_tarea`, `ultimo_exito_por_estrategia`, `tamano_ultimo_exito_por_tarea`, `piezas_vencidas_por_estrategia`, `registrar_no_ejecutada`, `programadas_sin_iniciar`, `marcar_no_ejecutada`, `en_curso_de_agente`, `marcar_interrumpida`. `marcar_en_curso` ahora guarda `inicio` en UTC |
| `repository/scripts.py` | Josué | Campos con valor por defecto `aprobado_por`, `aprobado_en`, `creado_en` en `ScriptRman`; `vigentes_por_tarea`. `aprobar` guarda `aprobado_en` en UTC |
| `repository/bases_datos.py` | Josué | `ultimo_perfil`, `log_mode_al_crear_script` |
| `repository/estrategias.py` | Josué | `ids_de_tareas` |
| `config/rutas.py` | Josué | Propiedad `agente` (`<work_dir>/agente/`) y su creación en `asegurar()` (G10) |
| `domain/perfil_bd.py` | Josué / Luis | `RitmoCambioLog` y campo opcional `ritmo_cambio_log = None` en `PerfilBD` (G12) |
| `validation/reglas/programacion.py` | Luis | Regla `PRG_007` (INFORMATIVA, próximas 5 ejecuciones) |
| `cli/cmd_tarea.py` | Luis | Subcomando `proximas` (YAML o repositorio) |
| `cli/app.py` | compartido | Solo las líneas de registro de los grupos nuevos |
| `pyproject.toml` | compartido | `types-python-dateutil` en `dev` (mypy estricto lo exige por `scheduling/`) |
| `.env.example` | Josué | Línea `CLOUDCR_SMTP_CLAVE=` |
| `docs/guia_prueba_completa.md`, `COMO_EJECUTAR.md`, `README.md` | varios | Secciones del agente, alertas, historial, estado y web; estado actualizado |
| `tests/fixtures/salidas/arbol_*.txt`, `tests/unit/test_observaciones.py` | Alejandro | Una línea nueva por la observación INFORMATIVA de `RED_003` (revisada a mano) |

## 3. Brechas de la sección 5

| # | Estado | Cómo se cerró |
|---|---|---|
| G1 | Confirmada | `alertas.abrir(condicion)` con severidad y las 4 llaves, devuelve `es_nueva` |
| G2 | Confirmada | La deduplicación y la resolución automática tratan ABIERTA y RECONOCIDA como vigentes; probado. `upsert_abierta` (Josué) **se dejó igual** y sigue mirando solo ABIERTA: no la usa nada nuevo |
| G3 | Confirmada | `AlertaDetallada` con severidad, fechas, llaves y nombres; `VistaAlerta` en `domain/` |
| G4 | Confirmada | `historial_detallado` y `detalle` con BD, estrategia, tarea, tipo, modo, resultado, pruebas, inicio, fin, duración, tamaño, archivos, ubicación, mensaje, agente y script |
| G5 | Confirmada | `registrar_no_ejecutada`: devuelve `None` si choca con `UQ_EJECUCION_TAREA_HORA` |
| G6 | Confirmada | `aprobado_en` en `ScriptRman`; `ultimo_perfil`; `log_mode_al_crear_script` deriva el modo del último perfil con `capturado_en <= script.creado_en` |
| G7 | Confirmada | DDL intacto. Motivo en `mensaje_rman`; `MENSUAL` usa el día de `fecha_inicio`; documentado en el manual |
| **G8** | **No confirmada con consulta real** (sin Oracle aquí) | Se cambió a `SYS_EXTRACT_UTC(SYSTIMESTAMP)` en `marcar_en_curso`, `aprobar`, `resolver` y en todo lo nuevo: es correcto con cualquier zona del servidor (si el servidor ya está en UTC no cambia nada). Frontera del repositorio en UTC sin zona; fuera, con zona; se muestra en la zona de la tarea. La prueba `test_g8_hora_del_servidor_y_horas_guardadas_en_utc` imprime `SYSTIMESTAMP` y `SYS_EXTRACT_UTC` y verifica que `inicio` quede en UTC. `[PENDIENTE: correrla en la XE]`. Los scripts aprobados **antes** de este cambio tienen `aprobado_en` en hora local; solo afecta las 6 h siguientes a esa aprobación |
| G9 | Diseño implementado, sin probar en real | `services/cliente_oracle.preparar_cliente_oracle()` inicia el cliente thick con el `ORACLE_HOME` de una instancia descubierta **antes** de abrir el repositorio; lo llaman `cloudcr agente ejecutar` y `cloudcr web`. Si falla, se sigue en thin y se registra. `[PENDIENTE: abrir /historial y después /instancias/XE en la máquina real; coordinar con Juan]` |
| G10 | Confirmada | `rutas.agente` |
| G11 | Confirmada | `INTERVALO` aritmético; un día de ocurrencias de 5 min con ancla de 2015 en < 50 ms (prueba) |
| G12 | Confirmada | `ARCHIVELOG_ACUMULADO` usa el conteo; `RED_003` mide el ritmo con `V$LOG_HISTORY` (campo opcional); limitaciones documentadas |

## 4. Criterios de aceptación (§7.4)

| Criterio | Estado | Respaldo |
|---|---|---|
| Una tarea `INTERVALO` de 5 min se dispara sola con `cloudcr agente ejecutar` | Cumplido con el doble | `test_agente.py` (orden del tick, una vez, simulación), `test_cli_monitoreo.py::test_agente_simulado_una_vez`. `[PENDIENTE: corrida real de 15 min]` |
| Detener el agente y reiniciarlo produce `NO_EJECUTADA` + `RESPALDO_NO_EJECUTADO` | Cumplido con el doble | `test_planificador.py::test_agente_detenido_…`, `test_alertas.py::test_respaldo_no_ejecutado_…`. `[PENDIENTE: corrida real]` |
| Dos procesos del agente no duplican | Cumplido en lógica; pendiente en real | `test_planificador.py::test_dos_agentes_…` (memoria) y `tests/integration/test_agente_oracle.py::test_dos_agentes_contra_el_mismo_repositorio_no_duplican` (dos procesos reales). `[PENDIENTE: -m oracle]` |
| `cloudcr tarea proximas EST001 T1 -n 10` → 13, 15, 18, 21 h | **Cumplido** | `test_recurrencia.py::test_est001_…`, `test_cli_monitoreo.py` y el comando real con `--archivo` |
| Ventana `22:30–02:00` acepta 23:45 y 01:00 y rechaza 03:00 | **Cumplido** | `test_ventana.py` |
| `cloudcr estado` muestra semáforo y alertas | Cumplido con repositorio simulado | `test_cli_monitoreo.py::test_estado`, `test_semaforo.py` (una prueba por rama). `[PENDIENTE: ejecución real]` |
| `/historial` muestra la misma tabla que la CLI | **Cumplido** | `tests/web/test_monitoreo.py::test_historial_web_y_cli_muestran_las_mismas_filas` |
| Un correo llega a una cuenta real | Pendiente | Notificador probado con SMTP falso (`test_notificadores.py`). `[PENDIENTE: cuenta SMTP del usuario]` |

Web verificada en Chromium real con un servicio falso: claro y oscuro, 1280 px y 390 px, sin errores de CSP ni de consola, sin desborde horizontal, filtros HTMX, reconocer alerta y desactivar estrategia con confirmación, recorrido con teclado.

## 5. Evidencias

| Id | Estado | Qué falta |
|---|---|---|
| E6 | `[PENDIENTE]` | Pipeline real de Juan |
| E7 | `[PENDIENTE]` | Corrida real (NO_EJECUTADA + alerta) y cuenta SMTP para el correo |
| E8 | `[PENDIENTE]` | Ejecuciones reales en el historial; el exportador HTML está listo |
| E10 | `[PENDIENTE]` | Paso de la XE a ARCHIVELOG (DBA). Pasos 1 y 2 del afinamiento completos con E1 |

Procedimiento exacto en `docs/evidencias/procedimiento_E6_E7_E8_E10.md`. **No se generó ninguna evidencia**: las capturas tomadas en este entorno usan datos de prueba y no se guardaron en `docs/evidencias/`.

## 6. Auditoría de dependencias

Sin ciclos. `scheduling` → `domain`; `alerts` → `domain`, `scheduling`, `strategy`; `agent` → `alerts`, `domain`, `scheduling`. Ningún archivo nuevo de `cli/` o `web/` importa `repository`, `oracle` ni `execution`. Siguen existiendo 17 imports prohibidos en archivos **anteriores** (`cmd_db`, `cmd_estrategia`, `cmd_param`, `cmd_repo`, `cmd_doctor`, `asistente_estrategia`, `cmd_explorar` y las rutas web del explorador).

## 7. Avisos para el equipo

**Juan**
- El agente no importa `execution/`. Contrato en `agent/puertos.py`: `EjecutorRespaldo.ejecutar(ejecucion_id)` y `asegurar_apertura(ejecucion_id)`. El adaptador único está en `services/agente.py` (`EjecutorPipeline`): busca `cloudcr_backup.execution.pipeline` con funciones `ejecutar(ejecucion_id[, ajustes=…])` y opcionalmente `asegurar_apertura`. Si cambia el nombre o la firma, se toca solo ahí.
- `ejecutar` recibe la ejecución ya en `PROGRAMADA` y hace todo lo demás (`marcar_en_curso`, preflight, RMAN, evidencia, verificación, `registrar_resultado`).
- Gancho del paso 13: `services.alertas.evaluar_tras_ejecucion(ejecucion_id, ajustes)`. Eventos (`SCRIPT_ALTERADO`, `BASE_NO_REABIERTA`): `services.alertas.registrar_evento([Condicion(...)])`.
- Buzón: si existe `cloudcr_backup.execution.buzon.sincronizar([ajustes=…])`, el agente lo llama en cada tick.
- El detalle del historial busca `<work_dir>/ejecuciones/<id>/evidencia.json` y, si trae la clave `log_rman`, ese log; si no, `<work_dir>/ejecuciones/<id>/rman.log`.
- **G9 (thin/thick)**: el agente y la web inician el cliente thick antes que el repositorio. Si el pipeline abre `/ AS SYSDBA` en el mismo proceso, debe usar el mismo `ORACLE_HOME`.

**Josué**
- Cambios en `repository/` listados arriba; las tres funciones existentes que usaban `SYSTIMESTAMP` ahora usan `SYS_EXTRACT_UTC(SYSTIMESTAMP)` (G8).
- **Riesgo:** `tests/integration/test_repositorio_oracle.py` desinstala el esquema al terminar, es decir, **`pytest -m oracle` borra todos los datos de BKPCAT**. Las pruebas nuevas (`test_agente_oracle.py`) no lo hacen: crean una base con nombre único y borran solo lo suyo.
- `upsert_abierta` sigue sin considerar RECONOCIDA (G2): conviene alinearla o marcarla como reemplazada por `abrir`.
- Parámetros nuevos con valor por defecto en código (no están en la semilla): `agente.max_paralelo_host`, `agente.horizonte_perdidas_horas`, `alertas.archivelogs_max`, `notificacion.email.*`.

**Luis**
- `PRG_007` y `cloudcr tarea proximas` quedaron hechos (aditivos). La condición de «programación incompleta» de `scheduling/recurrencia.py` es la misma de `PRG_002` (hay una prueba que las compara).

## 8. Commits

33 commits en la rama, con el formato `tipo(ámbito): descripción`, solo título y sin trailers. Lista completa con `git log --oneline 8704c94..HEAD`.

## 9. Riesgos para el sábado y decisiones humanas

1. **Pipeline de Juan**: sin él, la demostración del agente es con `--simulado` y hay que presentarla como tal.
2. **Correr la verificación en Windows con la XE** (pytest, mypy, `-m oracle` en una copia del repositorio o aceptando que se borra) y la consulta de G8.
3. **Cuenta SMTP** para E7 (contraseña de aplicación en `.env`).
4. **Paso a ARCHIVELOG** (DBA) para E5, E10 y los pasos 3 y 4 del afinamiento; falta `sql/archivelog/activar_archivelog.sql` (Día 2).
5. **Valores de demostración** de retención y de `alertas.recencia_horas`.
6. **G9** probado en la máquina real (orden thick/thin en la web).
7. **Interfaz principal**: se construyó la web con escritura (decisión del 1/10). Si eso cambió, las rutas `POST` se pueden quitar sin tocar lo demás.
