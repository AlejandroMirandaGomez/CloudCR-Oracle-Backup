# E3 (en línea) y E5 (recomendación ARCH_002 aplicada)

Producidas el 4 de octubre de 2026 sobre la XE local, que ya estaba en ARCHIVELOG (`SELECT log_mode FROM v$database` → `ARCHIVELOG`). La evidencia del estado anterior (NOARCHIVELOG) es E1.

## Circuito ejecutado

```
cloudcr db agregar XE
cloudcr db inspeccionar XE
cloudcr estrategia importar config/estrategias/est001.yaml --bd XE
cloudcr script generar EST001 --bd XE
cloudcr script aprobar EST001 T1 --bd XE
cloudcr ejecutar EST001 T1 --bd XE --ahora
cloudcr estrategia aplicar-recomendacion EST001 ARCH_002 --bd XE
cloudcr script generar EST001 --bd XE
cloudcr script aprobar EST001 T1 --bd XE
cloudcr ejecutar EST001 T1 --bd XE --ahora
```

Cada paso existe también en la web: *Sistema → Bases de datos*, *Estrategias → Importar*, el detalle de la estrategia (aplicar recomendación), *Script RMAN* (generar y aprobar) y el botón de ejecutar.

## E3 en línea — `E3_ejecucion_en_linea_v1/`

| Campo | Valor |
|---|---|
| Estrategia / tarea | EST001 / T1, script versión 1 |
| Modo | `EN_LINEA`, sin apagar la base |
| Resultado | EXITOSA, Pruebas OK |
| Piezas | 4 (3 MB, 17,9 MB, 112 KB y el autobackup del control file de 18 MB) |

## E5 — ARCH_002 aplicada — `E5_aplicar_arch_002_v2/`

La validación de EST001 en ARCHIVELOG emite `ARCH_002` (recomendación). Con `aplicar-recomendacion` se agrega ARCHIVELOG al alcance: la estrategia pasa a la versión 2, el script v1 queda `OBSOLETO` y se genera el script v2, que agrega `PLUS ARCHIVELOG` a la sentencia de respaldo.

| | v1 | v2 |
|---|---|---|
| Sentencia | `BACKUP INCREMENTAL LEVEL 1 CUMULATIVE TABLESPACE XEPDB1:VENTAS, XEPDB1:FINANZAS TAG '&1';` | la misma, más `PLUS ARCHIVELOG` |
| Resultado | EXITOSA, Pruebas OK | EXITOSA, Pruebas OK |
| Piezas | 4 | 6 (incluye 506 MB de archived logs) |

## Qué no cubre esta evidencia

El paso de NOARCHIVELOG a ARCHIVELOG ya estaba hecho en esta máquina cuando se produjo la evidencia, así que **no se capturó** que la alerta `BD_NOARCHIVELOG` se resuelve sola tras el cambio. Eso solo se puede demostrar con una XE en NOARCHIVELOG.
