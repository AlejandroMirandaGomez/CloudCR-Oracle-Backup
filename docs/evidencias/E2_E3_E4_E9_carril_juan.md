# Evidencias E2, E3, E4 y E9 — motor RMAN, ejecución, verificación, retención y recuperación

Capturadas el sábado 4 de octubre de 2026 en una Oracle XE 21c local (Windows 11, `ORACLE_SID=XE`,
DBID 3114375768), en modo **NOARCHIVELOG**, con RMAN real y autenticación del sistema operativo
(`rman target /`).

## Cómo se capturaron (y qué no se usó)

En la máquina de la captura **no existe la PDB `BKPCAT`**: el repositorio vive en la XE de otro integrante.
Por eso las ejecuciones corrieron con el pipeline real (`execution/pipeline.py`), con el preflight, el runner,
el parser, el correlador contra `V$RMAN_BACKUP_JOB_DETAILS`/`V$BACKUP_PIECE_DETAILS`, la reapertura, el
clasificador y el verificador de verdad. Solo el puerto del repositorio se reemplazó por uno en memoria.
Todo lo que el pipeline escribe a disco (`evidencia.json`, script, logs) es exactamente lo que produce
contra `BKPCAT`. En la máquina con `BKPCAT` el mismo flujo se repite con:

```
cloudcr script generar EST002 --bd XE
cloudcr script aprobar EST002 T1 --acepto-caida
cloudcr ejecutar EST002 T1 --ahora
cloudcr historial mostrar <id>
```

## E2 — Script generado, hash, aprobación y rechazo por script alterado

Carpeta `E2_script_alterado_bloqueado/`.

1. El script de `EST002/T1` se generó desde la estrategia (`E3_ejecucion_exitosa_consistente/EST002.XE.RMAN`).
   Su SHA-256 aprobado era `eacc9e386584a72b0dacebdbe833f65795e62a319f2cc3f8dbad96622355e303`.
2. Se modificó a mano el archivo aprobado (`scripts/XE/EST002/T1_v1.rman`) agregando `SKIP READONLY`.
   El SHA-256 pasó a `97f2b2c14765f8bcbfda4a2aed21df1f80e431f47e0c63a6802fd2a4882a14e4`.
3. Al ejecutar, el preflight dejó la ejecución **BLOQUEADA** con `SCRIPT_ALTERADO` y **RMAN nunca se invocó**
   (la carpeta de la ejecución solo contiene `evidencia.json`). El pipeline abre además la alerta de evento
   `SCRIPT_ALTERADO` en el repositorio.

La aprobación de un script `CONSISTENTE` sin `--acepto-caida` se rechaza con este mensaje
(prueba `tests/unit/test_aprobacion.py` y `tests/unit/test_servicios_juan.py`):

> El script hace un respaldo CONSISTENTE: ejecuta SHUTDOWN IMMEDIATE y la base de datos (y todas sus PDB,
> incluido el repositorio BKPCAT si vive en la misma CDB) queda fuera de servicio mientras dura el respaldo.
> Sugerencia: Si acepta la caída del servicio, apruebe de nuevo con --acepto-caida.

## E3 — Ejecución exitosa con piezas reales y `evidencia.json`

Carpeta `E3_ejecucion_exitosa_consistente/`. Respaldo **incremental nivel 0 CONSISTENTE** de la CDB completa
(`EST002/T1`, el escenario NOARCHIVELOG del día 1):

| Dato | Valor |
|---|---|
| Tag | `EST002_T1_2610041008` |
| COMMAND ID | `CLOUDCR_1001` |
| Inicio → fin | 10:08:45 → 10:09:25 (hora local) |
| Piezas | 5 del tag + autobackup `C-3114375768-20261004-00` (≈ 3,0 GB en `C:\backups\XE`) |
| `V$RMAN_BACKUP_JOB_DETAILS.STATUS` | `COMPLETED` |
| Resultado | **EXITOSA** |
| Pruebas | **OK** (EXISTENCIA, CROSSCHECK y VALIDATE BACKUPSET 1–5) |
| Reapertura | `asegurar_apertura.log`: `database is already started`, `ORA-01531` (ya abierta, OK) y `ALTER PLUGGABLE DATABASE ALL OPEN` |

Después del respaldo la base quedó `READ WRITE` y `XEPDB1` `READ WRITE`.

**Prueba de la columna Pruebas:** se apartó a mano la pieza 5 (`…_05541AE7_5_1_1.BKP`) y se volvió a verificar
(`evidencia_pieza_apartada.json`, `verificacion_pieza_apartada.log`). `CROSSCHECK` la marcó `EXPIRED` y las
tres pruebas fallaron (`EXISTENCIA`, `CROSSCHECK`, `VALIDATE` con `RMAN-06160`). Resultado: Pruebas
**FALLIDA**. Al devolver la pieza y verificar otra vez, Pruebas volvió a **OK** (`evidencia.json`).

## E4 — Ejecución fallida real, bien clasificada

Carpeta `E4_ejecucion_fallida_noarchivelog/`. Un respaldo en línea (N1 acumulativo de `XEPDB1:USERS`) contra
la base en NOARCHIVELOG. El log termina con **`Recovery Manager complete.`** y aun así se clasifica
**FALLIDA** (`clasificacion.json`):

- RMAN terminó con código de salida 1.
- Error principal `RMAN-06817: Pluggable Database XEPDB1 cannot be backed up in NOARCHIVELOG mode.`
- `V$RMAN_BACKUP_JOB_DETAILS` informa el trabajo `CLOUDCR_9001` como `FAILED`.
- No se generó ninguna pieza.

El mismo log es el fixture `tests/fixtures/rman_logs/fallo_rman06817_noarchivelog.log`. En el flujo normal
esta ejecución ni siquiera llega a RMAN: la regla `ARCH_005` (EN_LINEA en NOARCHIVELOG) la bloquea en la
aprobación y en el preflight. Para capturar el fallo se invocó el runner directamente.

## E9 — Informe de retención y procedimientos de recuperación

Carpeta `E9_retencion_y_recuperacion/`.

- `ventana.rman` / `ventana.log`: `CROSSCHECK BACKUP; REPORT OBSOLETE RECOVERY WINDOW OF 30 DAYS;` →
  `no obsolete backups found` (más la advertencia `RMAN-07553`, que el parser clasifica como advertencia).
- `redundancia0.rman` / `redundancia0.log`: `REPORT OBSOLETE REDUNDANCY 1;` → RMAN informa obsoletas las
  piezas 4 y 5 (control file y SPFILE, porque el autobackup es más nuevo). **No se borró nada.**
- `recuperacion_total-noarchivelog.json`: procedimiento generado (sin ejecutar) para volver al respaldo
  consistente: `RESTORE DATABASE; RECOVER DATABASE NOREDO; ALTER DATABASE OPEN RESETLOGS;`.
- `recuperacion_controlfile.json`: restauración del control file desde la pieza de autobackup real.
- `recuperacion_datafile.json`: el escenario **no es posible** en NOARCHIVELOG y el sistema lo explica en
  lugar de generar un script inválido.

`V$RECOVER_FILE` no informó archivos dañados (base sana). La identificación automática del datafile desde
`V$RECOVER_FILE` está cubierta por `tests/unit/test_recuperacion.py` y `tests/unit/test_servicios_juan.py`.

## Sintaxis de todos los scripts

`tests/integration/test_sintaxis_rman.py` pasa por `rman checksyntax` los 43 scripts que la herramienta
genera: respaldo de las cuatro estrategias en ambos modos de archivado y con tres compresiones, retención,
verificación y los seis escenarios de recuperación. RMAN los acepta todos:

```
ORACLE_HOME=C:\app\juanp\product\21c\dbhomeXE pytest -m oracle tests/integration/test_sintaxis_rman.py
43 passed
```
