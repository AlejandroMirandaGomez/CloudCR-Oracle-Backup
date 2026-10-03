# Afinamiento de redo logs y archivado — instancia XE

Tarea de la clase del 10/09 (§9), desarrollada en sus cuatro pasos: **1) situación actual, 2) estrategia de afinamiento, 3) aplicación, 4) situación final**.

Fuente de los datos: la evidencia **E1** (`docs/evidencias/E1_explorador_noarchivelog.html` y `.json`), capturada con `cloudcr explorar` sobre la XE 21c el 30/09/2026 a las 18:55, y las observaciones automáticas del explorador (`ARCH_001`, `ARCH_010`, `RED_001`, `RED_003`, `CTL_002`, `DIS_001`).

> Los pasos 3 y 4 exigen cambiar el modo de archivado de la base. **Esa decisión y su ejecución son del DBA**: la herramienta solo inspecciona. Mientras no se ejecuten, quedan marcados `[PENDIENTE]`.

---

## 1. Situación actual

| Aspecto | Valor observado (E1) | Observación del explorador |
|---|---|---|
| Versión | Oracle Database 21c Express Edition 21.3.0.0.0, CDB con `XEPDB1` | — |
| Modo de archivado | **NOARCHIVELOG** | `ARCH_001` ADVERTENCIA: solo respaldos consistentes (base detenida); no hay recuperación a un punto en el tiempo |
| Destino de archivado | No definido explícitamente; `LOG_ARCHIVE_DEST_1` apunta por defecto a `…\homes\OraDB21Home1\RDBMS` (dentro del `ORACLE_HOME`) | `ARCH_010` RECOMENDACION |
| Área de recuperación (FRA) | No configurada | — |
| Grupos de redo | 3 grupos (1, 2, 3) de **200 MB** cada uno | Cumple el mínimo de 2 grupos y el tamaño es parejo (`RED_003` no objeta) |
| Miembros por grupo | **1** (`REDO01.LOG`, `REDO02.LOG`, `REDO03.LOG`) | `RED_001` RECOMENDACION: no están multiplexados |
| Ubicación | Datafiles, control files y redo logs en la misma unidad `C:\` | `DIS_001` RECOMENDACION |
| Control files | 2 copias, ambas en `C:\APP\…\ORADATA\XE\` | `CTL_002` RECOMENDACION: mismo directorio |
| Ritmo de log switch | **No medido en E1** (la medición de `RED_003` se agregó después) | `[PENDIENTE: volver a correr cloudcr explorar o la consulta de V$LOG_HISTORY para tener el ritmo real]` |
| Archived logs sin respaldo | 0 (no hay archivado) | — |

Consulta para medir el ritmo real (solo lectura):

```sql
SELECT COUNT(*) AS cambios,
       ROUND((MAX(first_time) - MIN(first_time)) * 24, 1) AS horas
FROM v$log_history
WHERE first_time >= SYSDATE - 1;
```

Minutos promedio entre cambios = `horas × 60 / (cambios − 1)`. Lo recomendado en clase es **entre 15 y 30 minutos**: más seguido indica redo logs chicos (checkpoints frecuentes, espera de archivado); más espaciado indica que se puede perder mucha actividad si falla el disco del redo log actual.

**Diagnóstico.** La base no permite respaldos en línea ni recuperación a un punto en el tiempo, la pérdida del único miembro de un grupo de redo activo implica pérdida de datos, y todo (datos, control, redo y, al activar el archivado, archived logs) cae en el mismo disco.

---

## 2. Estrategia de afinamiento

| Decisión | Propuesta | Justificación |
|---|---|---|
| Modo de archivado | Pasar a **ARCHIVELOG** | Habilita `BACKUP … ONLINE`, respaldos incrementales sin detener la base y recuperación hasta un punto en el tiempo. Hace posible las estrategias EN_LINEA del sistema. |
| Destino de archivado | Definir `DB_RECOVERY_FILE_DEST` (FRA) con tamaño acotado, **en un disco distinto** al de los datafiles si existe; si la máquina solo tiene `C:`, una carpeta propia (`C:\oracle\fra`) y documentar el riesgo | Saca los archived logs del `ORACLE_HOME` (`ARCH_010`) y permite que RMAN administre el espacio |
| Grupos de redo | Mantener **3 grupos** (≥ 2, `RED_003`) | Suficiente para la carga de la XE; un cuarto grupo solo si aparece «checkpoint not complete» en el alert log |
| Tamaño de los grupos | Mantener **200 MB, todos iguales**; ajustar después de medir el ritmo: si el log switch ocurre cada < 15 min, subir a 400 MB; si es > 30 min con poca actividad, fijar `ARCHIVE_LAG_TARGET = 1800` | Tesis de clase: ritmo de 15–30 min (`RED_003`) |
| Miembros | **2 miembros por grupo**, el segundo en otro disco o, como mínimo, en otro directorio | Multiplexación (`RED_001`) |
| Control files | Mover una copia a otro disco o directorio | `CTL_002` |
| Purga de archived logs | Respaldo de archived logs con `DELETE INPUT` después de respaldarlos dos veces (`BACKUP ARCHIVELOG ALL NOT BACKED UP 2 TIMES … DELETE INPUT`) en la tarea de archived logs de la estrategia; **no** `DELETE OBSOLETE` automático hasta definir la retención | Evita que la FRA se llene sin perder logs aún no respaldados |
| Respaldo antes y después | Un respaldo **consistente** completo antes del cambio (la base está en NOARCHIVELOG) y un respaldo **en línea** nivel 0 justo después | Punto de partida seguro y primer respaldo válido del nuevo modo |

---

## 3. Aplicación

`[PENDIENTE: ejecutar en la XE (decisión y ejecución del DBA), con respaldo antes y después]`

> El script `sql/archivelog/activar_archivelog.sql` (parte del Día 2) **todavía no existe en el repositorio**. Hasta que exista, la secuencia exacta a ejecutar a mano es la siguiente. Requiere detener la base unos minutos.

**3.1 Respaldo consistente previo** (la base está en NOARCHIVELOG):

```text
rman target /
RMAN> SHUTDOWN IMMEDIATE;
RMAN> STARTUP MOUNT;
RMAN> BACKUP DATABASE TAG 'ANTES_ARCHIVELOG';
```

**3.2 Activar el archivado y definir el destino** (como SYSDBA, la base sigue en MOUNT):

```sql
ALTER SYSTEM SET db_recovery_file_dest_size = 20G SCOPE = BOTH;
ALTER SYSTEM SET db_recovery_file_dest = 'C:\oracle\fra' SCOPE = BOTH;
ALTER DATABASE ARCHIVELOG;
ALTER DATABASE OPEN;
ARCHIVE LOG LIST;
```

**3.3 Multiplexar los redo logs** (un segundo miembro por grupo; ajustar la ruta al segundo disco o directorio):

```sql
ALTER DATABASE ADD LOGFILE MEMBER 'D:\oracle\redo\REDO01B.LOG' TO GROUP 1;
ALTER DATABASE ADD LOGFILE MEMBER 'D:\oracle\redo\REDO02B.LOG' TO GROUP 2;
ALTER DATABASE ADD LOGFILE MEMBER 'D:\oracle\redo\REDO03B.LOG' TO GROUP 3;
ALTER SYSTEM SWITCH LOGFILE;
SELECT group#, member, status FROM v$logfile ORDER BY group#;
```

**3.4 Respaldo en línea posterior y registro del cambio en la herramienta:**

```text
rman target /
RMAN> BACKUP INCREMENTAL LEVEL 0 DATABASE PLUS ARCHIVELOG TAG 'DESPUES_ARCHIVELOG';
```

```powershell
cloudcr db inspeccionar XE
cloudcr explorar XE --salida html --archivo docs\evidencias\E10_explorador_archivelog.html
cloudcr explorar XE --salida json --archivo docs\evidencias\E10_explorador_archivelog.json
```

Al inspeccionar de nuevo, la alerta `BD_NOARCHIVELOG` se resuelve sola en la siguiente evaluación (evidencia E5) y `MODO_ARCHIVADO_CAMBIO` avisará que los scripts generados en NOARCHIVELOG conviene regenerarlos en modo en línea.

---

## 4. Situación final

`[PENDIENTE: completar con el explorador después del paso 3 (E10) y la salida de ARCHIVE LOG LIST]`

| Aspecto | Antes (E1) | Después (E10) |
|---|---|---|
| Modo de archivado | NOARCHIVELOG | `[PENDIENTE]` |
| Destino de archivado | Por defecto en `ORACLE_HOME\RDBMS` | `[PENDIENTE]` |
| Miembros por grupo de redo | 1 | `[PENDIENTE]` |
| Tamaño de los grupos | 3 × 200 MB | `[PENDIENTE]` |
| Ritmo de log switch | No medido | `[PENDIENTE]` |
| Observaciones del explorador | ARCH_001, ARCH_010, RED_001, CTL_002, DIS_001 | `[PENDIENTE]` |
| Respaldo antes / después | — | `[PENDIENTE: tags ANTES_ARCHIVELOG y DESPUES_ARCHIVELOG en cloudcr historial o LIST BACKUP SUMMARY]` |

Salida esperada de `ARCHIVE LOG LIST` (para comparar con la real, no como evidencia):

```text
Database log mode              Archive Mode
Automatic archival             Enabled
Archive destination            USE_DB_RECOVERY_FILE_DEST
```
