# Guion de la presentación — CloudCR Oracle Backup

Curso EIF402, II ciclo 2026.

Estructura que marca el enunciado: **qué se configuró → cómo → cuándo → qué script se genera → cómo se ejecuta → qué evidencia queda.** Cada momento muestra la **web** y dice el comando equivalente de la **CLI**: son la misma funcionalidad.

> Duración y formato por confirmar con el profesor. Los momentos marcados ★ son el núcleo (≈ 20 min); el resto se recorta si hace falta.

## Preparación (antes de empezar)

- XE en ARCHIVELOG, repositorio instalado y la XE registrada y con perfil guardado.
- `cloudcr web` abierto en `/estado`; una terminal de PowerShell con `$env:PYTHONUTF8 = "1"`.
- Tener `EST001` importada con script aprobado. No dejar activa una estrategia de prueba que dispare respaldos durante la exposición.
- Carpeta `C:\backups\XE` limpia o con un tamaño conocido.
- Abrir de antemano, sin conexión, `docs/evidencias/E1_explorador_noarchivelog.html` y `E8_historial.html`.
- Ensayo completo y cronometrado, dos veces.

## Momentos

| # | Momento | Qué se muestra (web · CLI) | Qué decir | Evidencia | Responde |
|---|---|---|---|---|---|
| 1 ★ | **El problema** | Explorador de la instancia (`/instancias/XE` · `cloudcr explorar`): control files, redo logs, SPFILE, tablespaces y datafiles de cada contenedor | «Esto es lo que hay que proteger.» Los redo logs online no los copia RMAN: se protegen multiplexándolos y archivándolos | E1 | Enunciado §1 |
| 2 | **Condición de riesgo** | Observación `ARCH_001` con su texto exacto sobre E1 (NOARCHIVELOG) | «La herramienta detecta antes de respaldar que la base limita la recuperación» | E1 | §1, §2 |
| 3 ★ | **QUÉ** | Asistente web, paso 2: árbol con casillas y prioridad por objeto (`/instancias/XE/estrategias/nueva` · `cloudcr estrategia crear`). Pantalla **Criterios** (`/criterios`) | Criterios de prioridad alta, media y baja del grupo: RPO, RTO y recencia. «Parcial es un alcance, no un tipo» | — | §1.1 |
| 4 ★ | **CÓMO** | Paso 3 del asistente: tipos con las dos etiquetas, «Incremental nivel 0 (total+)» | Completo, incremental N0, N1 diferencial y N1 acumulativo, y por qué se elige cada uno | — | §2 |
| 5 ★ | **CUÁNDO** | Paso 3: `EST001` a las 13, 15, 18 y 21 h con ventana 12:30–22:00 (`cloudcr tarea proximas EST001 T1 --bd XE`) | El ejemplo literal del profesor; frecuencia, días, intervalos, ventana y política de omisión | — | §3 |
| 6 ★ | **Validación** | Paso 5 / `/estrategias/XE/EST001/validar` · `cloudcr estrategia validar` | Los cuatro niveles: Error bloquea, Advertencia se acepta, Recomendación se aplica, Informativa informa. Mostrar `ARCH_002` | — | §6 |
| 7 ★ | **El script RMAN** | Pantalla del script (`/estrategias/XE/EST001/scripts/T1` · `cloudcr script ver`) con la tabla campo → cláusula | «La estrategia es la decisión; RMAN solo ejecuta» | E2 | §7 |
| 8 ★ | **Aprobación y hash** | «Aprobar» en la misma pantalla (`cloudcr script aprobar`). Modificar el archivo a mano y ejecutar: queda `BLOQUEADA` por `SCRIPT_ALTERADO` | SHA-256 del script; el script aprobado es el único que se ejecuta | E2 | §4, §7 |
| 9 ★ | **Ejecución** | «Ejecutar ahora» (`cloudcr ejecutar EST001 T1 --ahora`): piezas en `C:\backups\XE` y `evidencia.json` | Respaldo en línea con la base abierta | E3 | §4, §5 |
| 10 ★ | **El éxito se demuestra** | Log con `Recovery Manager complete.` clasificado **Fallida**; después `CROSSCHECK` + `VALIDATE` poniendo Pruebas en `OK` | «Que RMAN termine no significa que el respaldo sirva» | E4, E3 | Conclusión |
| 11 ★ | **Automatización** | `/sistema` → Agente · `cloudcr agente ejecutar`; tarea de 5 min disparándose sola; `/estado` | Latido, reclamo único por ocurrencia, dos agentes no duplican | E6 | §4 |
| 12 | **Ocurrencia perdida y alerta** | Detener el agente, dejar pasar una ocurrencia, reiniciar: `NO_EJECUTADA` y alerta `RESPALDO_NO_EJECUTADO` en `/alertas` | «No lo oculta: lo registra y avisa.» Correo al DBA, con botón de prueba en `/sistema` | E7 | §5, §6 |
| 13 ★ | **Recomendación aplicada** | Detalle de la estrategia → aplicar `ARCH_002` (`cloudcr estrategia aplicar-recomendacion`): versión 2 con `PLUS ARCHIVELOG`, script v1 obsoleto | Se aplica sin apagar la base | E5 | §2, §6 |
| 14 ★ | **Evidencia e historial** | `/historial` (`cloudcr historial`): Hora, símbolo, tipo, inicio, fin, duración, resultado y **Pruebas**; detalle y exportación a HTML | Misma tabla en terminal y navegador | E8 | §5 |
| 15 | **Retención** | `/retencion` · `cloudcr retencion informe XE` | «El sistema informa; borrar lo decide el administrador» | E9 | §3 |
| 16 | **Recuperación** | `/recuperacion` · `cloudcr recuperacion puntos XE` y `plan XE tablespace` | Procedimientos generados, nunca ejecutados; solo en ambiente `PRUEBAS` | E9 | §6 |
| 17 | **Afinamiento** | `docs/afinamiento_redo_archivelog.md` y `/estado` (observaciones de redo) | Los cuatro pasos: actual, estrategia, aplicación, final. `RED_003` mide el log switch | E1, E10 | Clase del 10/09 |
| 18 | **Cierre** | `/evidencias` (`cloudcr evidencias`): 10 evidencias y su estado. Matriz de controles antes, durante y después (`docs/analisis.md`, sec. 17) | «Planificada, ejecutada, monitoreada y documentada» | Todas | Conclusión |

## Qué decir con honestidad

- **E5:** la XE ya estaba en ARCHIVELOG cuando se capturó; el cambio de modo en sí no quedó registrado en la herramienta. El antes está en E1 y el después en E10.
- **E7 (correo):** si no hay cuenta SMTP real, la alerta y `NO_EJECUTADA` se muestran igual; el correo se verifica con el botón de prueba o se dice que está pendiente.
- **Dos agentes vivos:** el servidor web inicia su propio agente. Si se usa también `cloudcr agente ejecutar`, no se duplican ejecuciones, pero conviene usar solo uno durante la demo.
- **Pruebas de integración:** las 69 pruebas de Oracle desinstalan el repositorio al terminar. No correrlas sobre la BD de la demo.

## Preguntas probables

| Pregunta | Respuesta corta |
|---|---|
| ¿Por qué RMAN y no Data Pump? | El export es frágil si falla a mitad y solo se descubre al importar; RMAN permite verificar sin restaurar (`docs/analisis.md`, sec. 12) |
| ¿Por qué `SHUTDOWN IMMEDIATE` y no `ABORT`? | Cierra ordenado, sin *instance recovery* al abrir, y sin esperar a los usuarios (sec. 14) |
| ¿Dónde está el redo log en el respaldo? | RMAN no copia los redo logs online; se protegen multiplexados y archivados (sec. 11) |
| ¿Qué pasa si se apaga el repositorio durante un respaldo consistente? | La evidencia se escribe primero a disco y queda en el buzón; `ARCH_009` lo avisa de antemano |
| ¿La herramienta borra respaldos? | Solo con `purga_automatica` activa y confirmación; si no, solo informa |
| ¿Qué diferencia hay entre diferencial y acumulativo? | Diferencial: cambios desde el último respaldo de cualquier nivel; acumulativo: desde el último nivel 0 |
| ¿Por qué CLI y web? | Ambas llaman a la misma capa de servicios, así que muestran lo mismo |
