# E6 (agente automático) y E10 (afinamiento después)

Producidas el 4 de octubre de 2026 sobre la XE local, en ARCHIVELOG.

## E6 — Ejecuciones automáticas del agente

Estrategia de demostración `EST005` (`config/estrategias/est005.yaml`): archived logs cada 5 minutos, modo `EN_LINEA`. Se importó, se generó y aprobó el script, se activó y se arrancó el agente con `cloudcr agente ejecutar`, **sin ninguna orden de ejecución manual**.

Resultado (`E6_ejecuciones_agente.md`): la tarea se ejecutó sola a las **16:15, 16:20, 16:25 y 16:30**, cada vez en ≈ 5 s, `Exitoso`, Pruebas `OK`. Después se desactivó `EST005`.

Nota de atribución: en esa máquina había dos agentes vivos a la vez, el de `cloudcr agente ejecutar` y el que el servidor web (`cloudcr web`) inicia automáticamente. Las ocurrencias se reclaman por una restricción única, así que no se duplicaron, pero la evidencia no distingue cuál de los dos ejecutó cada una; en todos los casos fue un agente, sin intervención humana.

| Archivo | Contenido |
|---|---|
| `E6_ejecuciones_agente.md` | Historial filtrado por EST005 |
| `E6_agente_consola.log` | Salida de consola del agente al arrancar |

Limitación: el archivo `logs\cloudcr.log` quedó vacío en esta corrida, por lo que no se incluye. La evidencia es el historial del repositorio.

## E10 — Afinamiento, situación final

Ver `docs/afinamiento_redo_archivelog.md`, sección 4, y `E10_explorador_archivelog.html` / `.json` (`cloudcr explorar XE`).

Medido: ARCHIVELOG, archivado automático, 2 miembros por grupo de redo, 3 grupos de 200 MB iguales, log switch cada ≈ 22 min, 0 archived logs sin respaldo.

No quedó registrado el cambio de modo en sí (ni los tags `ANTES_ARCHIVELOG` y `DESPUES_ARCHIVELOG`): se aplicó antes de esta captura.
