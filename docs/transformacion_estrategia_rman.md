# De la estrategia al script RMAN

Este documento explica cómo CloudCR Oracle Backup convierte una estrategia (la **decisión**: qué, cómo,
cuándo y dónde respaldar) en un script RMAN (la **ejecución**), cómo se aprueba, cómo se ejecuta y cómo se
demuestra el resultado. Es la separación que pide el enunciado §7: la estrategia es un dato versionado y RMAN
solo ejecuta el script aprobado.

Código: `rman/` (constructor, nombres, aprobación y plantillas), `execution/` (preflight, runner, parser,
correlador, clasificador, evidencia, buzón y pipeline), `verification/`, `retention/` y `recovery/`.

## 1. Tabla configuración → cláusula RMAN

| Campo de la estrategia | Valor | Cláusula generada |
|---|---|---|
| Alcance `BASE_DATOS` | toda la base | `BACKUP … DATABASE` + `BACKUP CURRENT CONTROLFILE` + `BACKUP SPFILE` (la base completa siempre lleva control file y SPFILE; `DATABASE` domina sobre cualquier otro objeto) |
| Alcance `PDB` | `XEPDB1` | `BACKUP … PLUGGABLE DATABASE XEPDB1` (domina sobre sus tablespaces) |
| Alcance `TABLESPACE` | `XEPDB1:VENTAS` | `BACKUP … TABLESPACE XEPDB1:VENTAS, XEPDB1:FINANZAS` (todos en una sentencia) |
| Alcance `DATAFILE` | `7` (file#) | `BACKUP … DATAFILE 7` |
| Alcance `CONTROLFILE` | — | `BACKUP CURRENT CONTROLFILE TAG '&1';` |
| Alcance `SPFILE` | — | `BACKUP SPFILE TAG '&1';` |
| Alcance `ARCHIVELOG` + modo efectivo `EN_LINEA` | — | `… PLUS ARCHIVELOG` en la primera sentencia de datos |
| Tipo `COMPLETO` | completo / total | `BACKUP …` (sin nivel; **no** sirve de base para incrementales) |
| Tipo `INCREMENTAL_N0` | total+ | `BACKUP INCREMENTAL LEVEL 0 …` |
| Tipo `INCREMENTAL_N1_DIFERENCIAL` | incremental | `BACKUP INCREMENTAL LEVEL 1 …` |
| Tipo `INCREMENTAL_N1_ACUMULATIVO` | incremental acumulativo | `BACKUP INCREMENTAL LEVEL 1 CUMULATIVE …` |
| Tipo `ARCHIVELOG` | solo archived logs | `BACKUP ARCHIVELOG ALL NOT BACKED UP 1 TIMES TAG '&1';` (sin control file ni SPFILE) |
| Modo `EN_LINEA` | en caliente | el `RUN { … }` corre con la base abierta (exige ARCHIVELOG) |
| Modo `CONSISTENTE` | en frío | `SHUTDOWN IMMEDIATE; STARTUP MOUNT;` antes del `RUN` y `ALTER DATABASE OPEN; ALTER PLUGGABLE DATABASE ALL OPEN;` después |
| Modo `AUTO` | — | `EN_LINEA` si la base está en ARCHIVELOG; `CONSISTENTE` si está en NOARCHIVELOG |
| Compresión `NINGUNA` | — | backupset normal |
| Compresión `BASIC` | — | `BACKUP AS COMPRESSED BACKUPSET …` (BASIC es el algoritmo por defecto: no hace falta `SET`) |
| Compresión `LOW`/`MEDIUM`/`HIGH` | — | `SET COMPRESSION ALGORITHM 'MEDIUM';` **antes** del `RUN` (dentro daría `RMAN-03032`) + `AS COMPRESSED BACKUPSET`. El validador las rechaza en XE (`MET_003`) |
| `omitir_solo_lectura` | — | `… SKIP READONLY` |
| Canales | `n` | `ALLOCATE CHANNEL c1 … cn DEVICE TYPE DISK` y su `RELEASE` (XE admite 1: `MET_004`) |
| Destino | `C:\backups\XE` | `FORMAT 'C:\backups\XE\%d_EST001_T1_%T_%U.bkp'` (parámetro `respaldo.formato_pieza`) y `SET CONTROLFILE AUTOBACKUP FORMAT … TO 'C:\backups\XE\%F'` |
| Etiqueta | — | `TAG '&1'`: el valor real (`EST001_T1_2610041300`, ≤ 30 caracteres) entra al ejecutar |
| Identificador | — | `SET COMMAND ID TO '&2'`: el valor real (`CLOUDCR_<id de ejecución>`) entra al ejecutar |

Los cuatro scripts de oro del plan (`EST004/T1`, `EST001/T1`, `EST002/T1`, `EST004/T3`) están en
`tests/fixtures/scripts_oro/` y `tests/unit/test_constructor.py` comprueba que el constructor los produce
**byte a byte**. `tests/integration/test_sintaxis_rman.py` pasa todos los scripts generados por
`rman checksyntax`.

Ejemplo, `EST001/T1` (el `EST001` de la clase: N1 acumulativo de dos tablespaces a las 13, 15, 18 y 21 h):

```
RUN {
  SET COMMAND ID TO '&2';
  ALLOCATE CHANNEL c1 DEVICE TYPE DISK FORMAT 'C:\backups\XE\%d_EST001_T1_%T_%U.bkp';
  SET CONTROLFILE AUTOBACKUP FORMAT FOR DEVICE TYPE DISK TO 'C:\backups\XE\%F';
  BACKUP INCREMENTAL LEVEL 1 CUMULATIVE TABLESPACE XEPDB1:VENTAS, XEPDB1:FINANZAS TAG '&1';
  BACKUP CURRENT CONTROLFILE TAG '&1';
  BACKUP SPFILE TAG '&1';
  RELEASE CHANNEL c1;
}
```

`cloudcr script ver EST001 T1` muestra este mismo cuadro campo → cláusula junto al script.

## 2. Vocabulario de la clase → tipos RMAN

| Término de la clase (21/09 §5.2 y §6) | En el sistema | Cláusula |
|---|---|---|
| Completo / Full / total | `COMPLETO` | `BACKUP DATABASE` |
| total+ | `INCREMENTAL_N0` | `BACKUP INCREMENTAL LEVEL 0 DATABASE` |
| Parcial | cualquier tipo con alcance de PDB, tablespace o datafile | `BACKUP … TABLESPACE X` |
| Incremental | `INCREMENTAL_N1_DIFERENCIAL` | `BACKUP INCREMENTAL LEVEL 1` |
| Incremental acumulativo | `INCREMENTAL_N1_ACUMULATIVO` | `BACKUP INCREMENTAL LEVEL 1 CUMULATIVE` |
| Incompleto | no es un tipo: es lo que el validador impide (`ALC_004`, `ALC_005`) | — |

«Parcial» es un **alcance**, no un tipo: se decide en el QUÉ. «Total» y «total+» copian lo mismo; la
diferencia es que el nivel 0 queda registrado como base del ciclo incremental y el completo no.

## 3. Convención de nombres de la clase (21/09 §7.2)

La clase ejecuta `RMAN TARGET … CMDFILE=EST001.BD14.RMAN LOG=EST001.BD14.LOG`. El sistema respeta esa
convención en la carpeta de cada ejecución: `ejecuciones/<id>/EST001.XE.RMAN` y `EST001.XE.LOG`. Cuando la
estrategia tiene varias tareas se agrega la tarea (`EST004.XE.T2.RMAN`). El script aprobado vive en
`scripts/<BD>/<ESTRATEGIA>/<TAREA>_v<N>.rman`.

El comando real es:

```
rman target / cmdfile=EST001.XE.RMAN log=EST001.XE.LOG using EST001_T1_2610041300 CLOUDCR_41
```

Se ejecuta con la carpeta de la ejecución como directorio de trabajo y nombres relativos: RMAN parte sus
argumentos por espacios aunque vayan entre comillas, y la carpeta de trabajo de Windows puede tener espacios.

## 4. Aprobación con hash

1. `cloudcr script generar` inspecciona la base en vivo y guarda su perfil (así se sabe con qué
   `log_mode` se generó). Después construye el script y lo guarda como **BORRADOR** con su SHA-256. Si el
   contenido no cambió, conserva la versión anterior.
2. `cloudcr script aprobar` revisa varias cosas:
   - que la transición sea válida (`BORRADOR → APROBADO`);
   - que el contenido coincida con su hash;
   - que el archivo en disco no se haya tocado;
   - que la validación de la estrategia no tenga errores para esa tarea;
   - y, si el script es CONSISTENTE, que se haya pasado **`--acepto-caida`**.

   La versión aprobada anterior pasa a **OBSOLETO**.
3. El tag y el command id entran como `&1` y `&2`, así el script aprobado **nunca cambia** entre ejecuciones
   y su hash sigue valiendo.

Estados: `BORRADOR → APROBADO | RECHAZADO → OBSOLETO`.

## 5. Ejecución (los 13 pasos)

`execution/pipeline.py` recibe la ejecución en `PROGRAMADA` (del agente o de `cloudcr ejecutar --ahora`):

1. **Bloqueo por base**: un solo RMAN a la vez (candado en el proceso + archivo `.rman_<BD>.lock`).
2. **Preflight**. Cualquier problema deja la ejecución **BLOQUEADA** sin tocar RMAN. Revisa:
   - que el script esté APROBADO, coincida con su hash en el repositorio y **en disco**
     (`SCRIPT_ALTERADO` abre la alerta);
   - que la caída esté aceptada si el respaldo es CONSISTENTE;
   - el perfil actual de la base y que el `log_mode` no haya cambiado desde que se generó el script;
   - las reglas de validación de esa tarea;
   - que el destino sea escribible y tenga espacio.
3. `EN_CURSO`, tag y command id.
4. Copia del script a la carpeta de la ejecución (ASCII, `\n`, sin BOM).
5. `rman target / cmdfile=… log=… using <tag> <command_id>` con `ORACLE_HOME`, `ORACLE_SID`,
   `NLS_LANG=AMERICAN_AMERICA.AL32UTF8` y tiempo máximo (`rman.timeout_max_min`).
6. Si el modo es CONSISTENTE: **siempre** `asegurar_apertura` (aunque el paso 5 haya fallado). Ejecuta
   `STARTUP MOUNT`, `ALTER DATABASE OPEN` y `ALTER PLUGGABLE DATABASE ALL OPEN`, cada uno por separado
   porque RMAN se detiene en el primer error. `ORA-01531`/`ORA-65019` significan que ya estaba abierta. Al
   final se consulta `V$DATABASE` y `V$PDBS`; si no quedó `READ WRITE`, se abre la alerta
   `BASE_NO_REABIERTA`.
7. Lectura del log (`RMAN-`/`ORA-`, advertencias, `piece handle=`, pila de errores,
   `Recovery Manager complete.`).
8. Cruce con `V$RMAN_BACKUP_JOB_DETAILS` por `COMMAND_ID` y con `V$BACKUP_PIECE_DETAILS` por `TAG`.
9. Comprobación de que cada pieza existe en disco y no está vacía.
10. Clasificación (sección 6).
11. `evidencia.json` **primero a disco**, después al repositorio. Si el repositorio no responde (por ejemplo,
    `BKPCAT` cerrada por el respaldo consistente), la evidencia va al **buzón** y el agente la sincroniza en
    el siguiente tick.
12. Si el respaldo fue correcto y `verificacion.automatica` está activo: verificación → columna **Pruebas**.
13. Evaluación de alertas (`services.alertas.evaluar_tras_ejecucion`).

## 6. Clasificación: el código de salida 0 no es éxito

`Recovery Manager complete.` aparece también cuando RMAN falló (evidencia E4: `RMAN-06817` con ese mismo
cierre). El clasificador cruza todas las fuentes:

| Resultado | Cuándo |
|---|---|
| **FALLIDA** | Basta cualquiera de estas condiciones: <br>• tiempo agotado o RMAN no se pudo lanzar; <br>• código de salida ≠ 0; <br>• errores en el log o pila de errores; <br>• el log no llega a `Recovery Manager complete.`; <br>• el trabajo figura `FAILED`/`COMPLETED WITH ERRORS`; <br>• no hay piezas, o alguna falta o está vacía en disco |
| **CON_ADVERTENCIAS** | Sin fallos, pero se da alguna de estas condiciones: <br>• advertencias en el log (códigos de `rman.codigos_advertencia` o mensajes `warning`); <br>• el trabajo figura `COMPLETED WITH WARNINGS`; <br>• no se pudo confirmar el trabajo en las vistas `V$`; <br>• la base no quedó abierta tras un consistente |
| **EXITOSA** | Ninguna de las anteriores |

Cada resultado guarda sus **motivos** en la evidencia y en la columna `mensaje_rman`.

## 7. Verificación: la columna Pruebas

`verification/verificador.py` hace tres pruebas sobre las piezas del tag:

1. **EXISTENCIA**: cada `handle` existe en disco y no está vacío.
2. **CROSSCHECK**: `CROSSCHECK BACKUP TAG '<tag>';`. Una pieza que queda `EXPIRED`, o que desaparece de
   `V$BACKUP_PIECE_DETAILS`, hace fallar la prueba.
3. **VALIDATE**: `VALIDATE BACKUPSET <conjuntos>;` lee las piezas sin restaurarlas.

Las tres en OK → Pruebas **OK**; cualquiera fallida → **FALLIDA**. Si el respaldo falló, Pruebas queda
**NO_APLICA**. `cloudcr verificar <id>` repite la verificación cuando se quiera (E3: al apartar una pieza
quedó FALLIDA y al devolverla volvió a OK).

## 8. Retención

La ventana va **en línea, dentro del comando** (`REPORT OBSOLETE RECOVERY WINDOW OF 30 DAYS`), nunca con
`CONFIGURE RETENTION POLICY`: no se toca la configuración persistente de RMAN en la base del cliente.

- `cloudcr retencion informe XE` calcula las piezas vencidas por estrategia (`vence_en` = fin + ventana,
  o las ejecuciones que exceden la redundancia). Con `--rman` además corre `CROSSCHECK BACKUP` y
  `REPORT OBSOLETE`. **No borra nada.**
- `cloudcr retencion purgar XE EST004 --purgar` solo funciona si la estrategia tiene
  `purga_automatica: true`. Genera `DELETE NOPROMPT OBSOLETE …` y, si hay `archived_logs_dias`,
  `DELETE NOPROMPT ARCHIVELOG ALL BACKED UP 1 TIMES TO DISK COMPLETED BEFORE 'SYSDATE-n'`.

## 9. Recuperación (se genera, nunca se ejecuta)

| Escenario | Requiere | Script |
|---|---|---|
| `pdb` | ARCHIVELOG | `ALTER PLUGGABLE DATABASE X CLOSE IMMEDIATE; RESTORE/RECOVER PLUGGABLE DATABASE X; … OPEN` |
| `tablespace` | ARCHIVELOG | raíz: `OFFLINE IMMEDIATE → RESTORE → RECOVER → ONLINE`; en una PDB se cierra y abre la PDB |
| `datafile` | ARCHIVELOG | igual, por file#; el archivo se toma de `V$RECOVER_FILE`/`V$DATAFILE` si no se indica |
| `controlfile` | autobackup o pieza registrada | `STARTUP NOMOUNT; SET DBID; RESTORE CONTROLFILE FROM '<pieza>' (o FROM AUTOBACKUP); MOUNT; RECOVER; OPEN RESETLOGS` |
| `total-noarchivelog` | respaldo consistente | `SHUTDOWN IMMEDIATE; STARTUP MOUNT; RESTORE DATABASE; RECOVER DATABASE NOREDO; OPEN RESETLOGS` |
| `punto-en-tiempo` | ARCHIVELOG continuo | `SET UNTIL TIME …; RESTORE DATABASE; RECOVER DATABASE; OPEN RESETLOGS` |

Si el escenario no es posible con el modo actual (por ejemplo, `datafile` en NOARCHIVELOG), el comando
**lo explica** en lugar de generar un script inválido. El primer paso de cada procedimiento es la línea de
tiempo de la clase §2: identificar con `V$RECOVER_FILE` qué archivo falta. Después `RECOVER` aplica primero
los archived redo logs y al final los redo logs online.

## 10. Por qué el modo consistente usa `SHUTDOWN IMMEDIATE`

La clase (21/09 §2.1) presenta cuatro modos de apagado:

| Modo | Qué hace | Por qué no (o sí) |
|---|---|---|
| `NORMAL` | espera a que **todos** los usuarios se desconecten | un respaldo programado puede quedar esperando indefinidamente |
| `TRANSACTIONAL` | espera a que terminen las transacciones en curso | igual de impredecible en duración |
| **`IMMEDIATE`** | revierte las transacciones activas, hace checkpoint y cierra los archivos | **cierre ordenado y consistente en tiempo acotado** |
| `ABORT` | detiene la instancia sin checkpoint | deja la base inconsistente y exige *instance recovery* al arrancar; un respaldo «en frío» tomado así no es consistente |

`SHUTDOWN IMMEDIATE` deja todos los datafiles sincronizados en el mismo SCN y sin necesidad de *instance
recovery*. Por eso el respaldo tomado en `MOUNT` es consistente y se puede restaurar en NOARCHIVELOG con
`RECOVER DATABASE NOREDO`, sin aplicar redo. Es la única forma de respaldar una base en NOARCHIVELOG: RMAN
rechaza el respaldo en línea (`RMAN-06817`/`ORA-19602`, evidencia E4).

- **Instance recovery** es la recuperación automática tras una caída de instancia (`ABORT`, corte de
  energía). Aplica los redo logs online para rehacer lo confirmado y deshacer lo no confirmado. No necesita
  respaldos.
- **Media recovery** es la que se hace tras perder o dañar archivos. Restaura desde un respaldo y aplica los
  archived y online redo logs hasta llevar el archivo al presente (o a un punto en el tiempo). Es la que
  necesita ARCHIVELOG.

Como el apagado detiene toda la CDB, incluida la PDB `BKPCAT` del repositorio, la aprobación exige
`--acepto-caida`. Además, la evidencia se escribe primero a disco y el buzón cubre el caso en que el
repositorio no esté disponible al terminar.

## 11. Reglas que se cumplen siempre

- Nunca `CONFIGURE`: solo `SET` de sesión y cláusulas en línea.
- Scripts en ASCII, `\n`, sin BOM (`rman/render.py`). Un carácter no ASCII en el destino se rechaza antes de
  generar.
- `NLS_LANG=AMERICAN_AMERICA.AL32UTF8` en el entorno de cada RMAN, para que los mensajes se puedan leer.
- El cliente thick se inicia antes de abrir el repositorio (`preparar_cliente_oracle`), así no se mezcla con
  thin en el mismo proceso (`DPY-2019`).
- La herramienta recomienda, no impone: no cambia el modo de archivado, no borra respaldos sin
  `purga_automatica` y `--purgar`, y no restaura nada.
