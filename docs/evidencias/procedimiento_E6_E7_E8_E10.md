# Procedimiento para producir las evidencias E6, E7, E8 y E10

Ninguna de estas evidencias existe todavía: todas exigen una ejecución real contra la XE, y algunas además el pipeline de RMAN (carril de Juan) o una cuenta SMTP. Este documento deja los pasos exactos para producirlas. Los archivos resultantes se guardan aquí con el estilo de E1: `E6_…`, `E7_…`, `E8_…`, `E10_…`.

> Una corrida con `--simulado` sirve para ensayar el procedimiento, pero **no es evidencia**: queda rotulada SIMULACION y así debe presentarse.

## E6 — Ejecuciones automáticas del agente

**Requiere:** el pipeline real de RMAN integrado (`cloudcr_backup.execution.pipeline`), una estrategia activa con una tarea `INTERVALO` de 5 minutos y su script aprobado.

1. `cloudcr agente ejecutar` y dejarlo correr unos 15 minutos.
2. `cloudcr historial --bd XE --estrategia <EST> --salida md --archivo docs\evidencias\E6_ejecuciones_agente.md`
3. Captura de `/estado` y `/historial` → `E6_estado.png`, `E6_historial.png`.
4. Copia de `logs\cloudcr.log` del período → `E6_agente.log`.

`[PENDIENTE: pipeline real (Juan)]`

## E7 — Ocurrencia no ejecutada, alerta y correo

**Requiere:** cuenta SMTP del usuario (§8 del manual) con `CLOUDCR_SMTP_CLAVE` en `.env` y `notificacion.canales = ["consola","email"]`.

1. Agente corriendo; detenerlo con Ctrl+C un minuto antes de una ocurrencia.
2. Esperar a que pasen la ocurrencia y la gracia (`agente.gracia_omision_min`).
3. Volver a arrancar el agente. En consola debe verse `NUEVA ALERTA [ALERTA] RESPALDO_NO_EJECUTADO …`.
4. `cloudcr historial --estado NO_EJECUTADA --salida md --archivo docs\evidencias\E7_no_ejecutada.md`
5. `cloudcr alertas --json > docs\evidencias\E7_alertas.json`
6. Captura del correo recibido (asunto y cuerpo) → `E7_correo.png`.
7. Dejar correr la siguiente ocurrencia correcta y mostrar que la alerta pasó a RESUELTA (`cloudcr alertas --estado RESUELTA`).

`[PENDIENTE: cuenta SMTP del usuario; para la parte NO_EJECUTADA + alerta basta el agente, con --simulado rotulado]`

## E8 — Historial con la columna Pruebas exportado a HTML

1. `cloudcr reporte historial --formato html --archivo docs\evidencias\E8_historial.html`
2. Abrirlo sin conexión a internet; probar tema claro, oscuro e impresión (Ctrl+P).
3. Si la columna Pruebas sale «Pendiente» es porque la verificación todavía no la llena el pipeline: se dice en el informe.

`[PENDIENTE: ejecuciones reales en el historial]`

## E10 — Afinamiento: explorador después y `ARCHIVE LOG LIST`

**Requiere:** que el DBA ejecute el §3 de `docs/afinamiento_redo_archivelog.md` (paso a ARCHIVELOG con respaldo antes y después).

1. `cloudcr db inspeccionar XE`
2. `cloudcr explorar XE --salida html --archivo docs\evidencias\E10_explorador_archivelog.html`
3. `cloudcr explorar XE --salida json --archivo docs\evidencias\E10_explorador_archivelog.json`
4. Salida de `ARCHIVE LOG LIST` en SQL*Plus → `E10_archive_log_list.txt`.
5. Completar el §4 del documento de afinamiento con la tabla antes/después.

`[PENDIENTE: paso de la XE a ARCHIVELOG (decisión del DBA)]`
