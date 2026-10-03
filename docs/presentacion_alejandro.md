# Guion de presentación — momentos de Alejandro

Momentos del §9 del plan que le tocan a este carril: **11 (automatización)**, **13 (evidencia e historial)** y **16 (afinamiento)**. La presentación completa es compartida con Luis; aquí solo están estos tres.

Preparación (antes de empezar):

- `cloudcr doctor` en verde, `cloudcr web` abierto en `/estado`, una terminal de PowerShell con `$env:PYTHONUTF8 = "1"`.
- Una estrategia de demostración **activa** con una tarea `INTERVALO` de 5 minutos y script aprobado (ver `docs/guia_prueba_completa.md` §8b.2).
- El agente corriendo desde unos 15 minutos antes, para que el historial ya tenga filas.
- `agente.gracia_omision_min` en 2 minutos solo durante la demo (`cloudcr param set agente.gracia_omision_min 2`), y devolverlo a 15 al terminar.

> **Honestidad.** Si el pipeline real de RMAN (Juan) no está integrado, el agente corre con `--simulado`. Se dice en voz alta: «estas ejecuciones son de prueba del agente, no ejecutan RMAN; el historial y la web las rotulan SIMULACIÓN». No se presentan como respaldos reales.

---

## Momento 11 — Automatización

**Qué mostrar:** el agente disparando solo una tarea de 5 minutos, y qué pasa cuando se cae.

| Paso | Comando o pantalla | Qué decir |
|---|---|---|
| 1 | `cloudcr tarea proximas <EST> T1 --bd XE -n 5` | «Cada tarea tiene una regla de recurrencia; estas son sus próximas horas, en hora de Costa Rica.» Para EST001: 13, 15, 18 y 21 h. |
| 2 | Terminal con `cloudcr agente ejecutar` (o `--simulado`) | «Cada 30 segundos el agente escribe su latido, reclama las ocurrencias vencidas y las despacha. El reclamo usa una restricción única en Oracle: aunque corran dos agentes, cada hora se ejecuta una sola vez.» |
| 3 | `/estado` | Semáforo, «Agente activo», ejecución en curso o recién terminada. |
| 4 | Ctrl+C en el agente; esperar a que pase una ocurrencia + la gracia; volver a arrancarlo | «El agente se detuvo justo cuando tocaba un respaldo. Al volver, no lo ejecuta a escondidas: registra NO_EJECUTADA con el motivo y abre una alerta.» |
| 5 | `/alertas` y la consola del agente (`NUEVA ALERTA [ALERTA] RESPALDO_NO_EJECUTADO …`) | «La alerta se notifica una sola vez; si llega la siguiente ejecución correcta, se resuelve sola.» |
| 6 | (Si hay SMTP) el correo recibido | Mostrar el asunto con el alcance: `[CloudCR][ALERTA] RESPALDO_NO_EJECUTADO XE EST…/T1 · VENTAS, FINANZAS`. |

**Evidencia que lo respalda:** E6 (ejecuciones automáticas) y E7 (NO_EJECUTADA + alerta + correo). `[PENDIENTE: E6 solo es evidencia con el pipeline real; E7 requiere la cuenta SMTP]`

**Si alguien pregunta:** la tarea programada de Windows (`deploy\windows\registrar_tarea_agente.ps1`) arranca el agente al iniciar el servidor y lo reinicia si falla.

---

## Momento 13 — Evidencia e historial

**Qué mostrar:** el historial con la columna Pruebas, su detalle y la exportación.

| Paso | Comando o pantalla | Qué decir |
|---|---|---|
| 1 | `/historial` | Leer una fila: Fecha, BD, Estrategia, Tarea, **Hora programada**, símbolo, **Tipo con las dos etiquetas** (sistema y clase), **Inicio real**, Fin, Duración, Resultado y **Pruebas**. «Hora contra Inicio prueba si el respaldo corrió a tiempo; una fila tardía se marca con +N min.» |
| 2 | Filtrar por Resultado = Error o No ejecutada | «Los filtros quedan en la dirección; se puede compartir el enlace.» |
| 3 | `cloudcr historial --bd XE` en la terminal | «Es la misma tabla: CLI y web salen del mismo modelo de presentación.» |
| 4 | Clic en el Id → detalle | Script y versión aprobada, quién lo aprobó, log de RMAN, piezas y verificaciones. |
| 5 | Exportar → HTML; abrir el archivo sin internet | «Es un HTML autocontenido, con tema claro y oscuro e imprimible: es la evidencia E8.» |
| 6 | `cloudcr reporte evidencia <ID>` | Evidencia de una ejecución en Markdown para el informe. |

**Evidencia que lo respalda:** E8 (`cloudcr reporte historial --formato html`). `[PENDIENTE: generar E8 con ejecuciones reales; si Pruebas sigue «Pendiente» porque la verificación es del carril de Juan, se dice]`

---

## Momento 16 — Afinamiento de redo y archivado

**Qué mostrar:** la tarea del 10/09 en sus cuatro pasos (`docs/afinamiento_redo_archivelog.md`).

| Paso | Comando o pantalla | Qué decir |
|---|---|---|
| 1. Situación actual | E1 (`docs/evidencias/E1_explorador_noarchivelog.html`) o `/instancias/XE` | NOARCHIVELOG (`ARCH_001`), 3 grupos de 200 MB con un solo miembro (`RED_001`), todo en `C:` (`DIS_001`), destino de archivado por defecto (`ARCH_010`). `RED_003` mide el ritmo de log switch contra 15–30 min. |
| 2. Estrategia | Tabla del §2 del documento | ARCHIVELOG + FRA, 3 grupos iguales, 2 miembros por grupo, purga de archived logs respaldados dos veces, respaldo antes y después. |
| 3. Aplicación | Secuencia del §3 (la ejecuta el DBA) | Respaldo consistente previo, `ALTER DATABASE ARCHIVELOG`, multiplexación, respaldo en línea posterior. |
| 4. Situación final | E10: explorador después + `ARCHIVE LOG LIST` | Comparar la tabla antes/después; mostrar que `BD_NOARCHIVELOG` se resolvió sola tras `cloudcr db inspeccionar XE`. |

**Evidencia que lo respalda:** E1 (antes, existe) y E10 (después). `[PENDIENTE: pasos 3 y 4 y E10 hasta que la XE pase a ARCHIVELOG]`
