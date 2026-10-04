# Análisis — CloudCR Oracle Backup

Sistema de gestión de estrategias de respaldo de bases de datos Oracle con RMAN.
Curso EIF402 Administración de Bases de Datos · UNA · II ciclo 2026.

## 1. El problema

Una base de datos Oracle concentra la información de una organización. Respaldarla no es copiar archivos: hay que decidir **qué** proteger, **cómo** copiarlo, **cuándo** y por **cuánto tiempo** conservarlo, y después **demostrar** que el respaldo se hizo y que sirve. En la práctica esas decisiones viven en la cabeza del administrador o en scripts sueltos, y no queda evidencia de qué se decidió ni de qué pasó.

El enunciado pide una herramienta que separe la **estrategia** (la decisión) de la **ejecución** (RMAN) y que deje evidencia de cada corrida (enunciado §7 y conclusión).

## 2. Riesgos

### Disponibilidad

| Riesgo | Consecuencia |
|---|---|
| Respaldo en frío en una base 24/7 | Hay que apagar el servicio. El modo `CONSISTENTE` lo hace con `SHUTDOWN IMMEDIATE` |
| Respaldo que no corre a su hora | Ventana de pérdida mayor a la tolerada; lo cubre la alerta `RESPALDO_NO_EJECUTADO` |
| Disco de destino lleno | El respaldo falla a mitad; lo cubren `DST_002`, `DST_003` y la alerta `ESPACIO_INSUFICIENTE` |
| Repositorio dentro de la CDB que se apaga | Se pierde dónde escribir el resultado; lo cubre `ARCH_009` y el buzón de evidencia |

### Integridad

| Riesgo | Consecuencia |
|---|---|
| Respaldo "exitoso" que no sirve | `Recovery Manager complete.` aparece también cuando RMAN falló. Se clasifica cruzando código de salida, pila de errores, piezas y `V$RMAN_BACKUP_JOB_DETAILS` |
| Pieza borrada o corrupta después del respaldo | `CROSSCHECK` + `VALIDATE BACKUPSET` llenan la columna **Pruebas** |
| Script modificado a mano | El hash SHA-256 del script aprobado se compara antes de ejecutar; si cambió, la ejecución queda `BLOQUEADA` |
| Copia en el mismo disco que los datos | Se pierden datos y respaldo juntos; lo cubre `DST_004` |
| Acumulación sin límite | Sin retención el disco se llena; lo cubren `RET_001`–`RET_004` y el informe de obsoletos |

## 3. Justificación

RMAN es la herramienta nativa de Oracle: conoce la estructura de la base, hace respaldos en línea consistentes, es incremental a nivel de bloque y lleva su propio catálogo de piezas. La herramienta no reemplaza a RMAN: **genera, valida, aprueba, ejecuta y documenta** los scripts RMAN, y recomienda sin imponer (nunca cambia el modo de archivado, nunca ejecuta `CONFIGURE` persistente, nunca borra respaldos sin confirmación y nunca restaura por sí sola).

## 4. Objetivos

**General.** Gestionar estrategias de respaldo Oracle de punta a punta: definición, validación, generación del script RMAN, ejecución automática, evidencia e historial, retención y recuperación.

**Específicos.**

1. Modelar una estrategia con QUÉ, CÓMO, CUÁNDO, DESTINO, prioridad y retención.
2. Validar la estrategia contra el estado real de la base con cuatro severidades.
3. Generar el script RMAN desde la estrategia y aprobarlo con hash.
4. Ejecutar por horario con un agente propio y clasificar el resultado con motivos.
5. Verificar el respaldo y registrar evidencia (13 campos mínimos del enunciado §5).
6. Mantener una política de retención y generar procedimientos de recuperación sin ejecutarlos.

## 5. Requerimientos

### Funcionales

| Enunciado | Requerimiento |
|---|---|
| §1 | Elegir qué respaldar: base completa, PDB, tablespaces, datafiles, control file, SPFILE, archived logs |
| §1.1 | Asignar prioridad alta, media o baja (criterios en la sección 7) |
| §2 | Elegir el tipo: completo, incremental nivel 0, incremental nivel 1 diferencial o acumulativo |
| §3 | Definir frecuencia, días, horas, intervalos y ventana de respaldo, y el período de conservación |
| §4 | Automatizar: estrategia → programación → script RMAN → ejecución → resultado → evidencia |
| §5 | Registrar evidencia de cada ejecución y consultar el historial |
| §6 | Administrar estrategias (crear, modificar, activar, desactivar, consultar), monitorear y recuperar |

### No funcionales

- Repositorio propio en Oracle (PDB `BKPCAT`, esquema `BKP_ADMIN`), separado de la base respaldada.
- Mínimo privilegio: usuario `C##BKP_MON` de solo lectura para inspección; sin contraseñas en el código.
- Capas: la CLI y la web solo llaman a `services/`; los resultados se definen en `domain/`.
- Todo archivo que lee RMAN es ASCII, sin BOM, con `\n`; `NLS_LANG` fijo para que los mensajes sean parseables.
- Escritura de evidencia a disco **antes** de tocar el repositorio.

## 6. Modelo de la estrategia

Una **estrategia** es la decisión; una **tarea** es una operación concreta que la despliega. Una estrategia puede tener varias tareas (por eso `EST004 (a)` y `EST004 (b)` de la clase son una sola estrategia con dos tareas).

```
Estrategia ── prioridad, estado, versión, retención
 ├── alcance[]   QUÉ     tipo de objeto + identificador + prioridad propia
 └── tareas[]
      ├── como           CÓMO     tipo, modo (AUTO / EN_LINEA / CONSISTENTE), opciones
      ├── programacion   CUÁNDO   frecuencia, horas, días, intervalo, ventana, zona, política de omisión
      └── destino        DÓNDE    ruta y etiqueta
```

La estrategia es dato versionado: editarla incrementa `version` y deja `OBSOLETO` solo los scripts que cambiaron. RMAN solo ejecuta el script **aprobado**.

## 7. Criterios de prioridad del grupo

El enunciado §1.1 pide que el grupo defina sus propios criterios. Se implementan en `strategy/prioridad.py` y se muestran en la web, pantalla **Criterios**.

| Prioridad | Criterio | RPO | RTO | Recencia máxima | Esquema sugerido |
|---|---|---|---|---|---|
| **Alta** | Su pérdida detiene o afecta significativamente la operación | 1 h | 4 h | 24 h | N0 semanal + N1 acumulativo diario + archived logs cada 4 h |
| **Media** | Importante, pero su pérdida temporal es tolerable | 24 h | 24 h | 72 h | N0 semanal + N1 diferencial diario |
| **Baja** | Se puede reconstruir o su pérdida tiene impacto menor | 168 h | 72 h | 192 h | Completo semanal |

La prioridad se elige directamente (no hay cuestionario con puntaje). La recencia máxima alimenta la alerta `SIN_RESPALDO_RECIENTE`, y la regla `PRG_005` avisa si la frecuencia programada no alcanza la que exige la prioridad. Cada objeto del alcance puede llevar prioridad propia; la clase lo ejemplifica con T1→1, T2→2, T3→1, T4→3, y `ALC_007` avisa de un objeto de prioridad alta dentro de una estrategia de prioridad baja.

## 8. Comparación de los cuatro tipos de respaldo

| Tipo (sistema) | Cláusula RMAN | Qué copia | Ventajas | Desventajas | Cuándo usarlo |
|---|---|---|---|---|---|
| Completo | `BACKUP DATABASE` | Todos los bloques usados del alcance | Restauración simple, un solo juego de piezas | Más lento y más grande; **no sirve de base para incrementales** | Bases pequeñas, alcance parcial, prioridad baja |
| Incremental nivel 0 | `BACKUP INCREMENTAL LEVEL 0` | Igual que el completo | Es la base del ciclo incremental | Mismo costo que el completo | Domingo o inicio de ciclo |
| Incremental nivel 1 diferencial | `BACKUP INCREMENTAL LEVEL 1` | Bloques cambiados desde el último respaldo de **cualquier** nivel | Piezas pequeñas y rápidas | Restaurar exige encadenar todos los diarios | Respaldo diario con poco cambio |
| Incremental nivel 1 acumulativo | `BACKUP INCREMENTAL LEVEL 1 CUMULATIVE` | Bloques cambiados desde el último **nivel 0** | Restaurar usa solo el N0 y el último acumulativo | Las piezas crecen durante el ciclo | Cuando importa recuperar rápido (prioridad alta) |

Las reglas `MET_001` y `MET_002` avisan de un incremental nivel 1 sin nivel 0 previo y de incrementales sobre una base `COMPLETO`.

## 9. Equivalencia con el vocabulario del profesor

La clase enumera los métodos como *parcial, incompleto, completo, incremental, total, total+*. El sistema usa los nombres de RMAN y **muestra siempre las dos etiquetas**.

| Término de la clase | Tipo en el sistema | Cláusula RMAN | Significado |
|---|---|---|---|
| Completo / Full / **total** | `COMPLETO` | `BACKUP DATABASE` | Todos los bloques usados; no es base de incrementales |
| **total+** | `INCREMENTAL_N0` | `BACKUP INCREMENTAL LEVEL 0 DATABASE` | Igual de completo y además punto de partida incremental |
| **Parcial** | cualquier tipo con alcance de tablespace, datafile o PDB | `BACKUP ... TABLESPACE X` | **No es un tipo: es un alcance reducido.** Se modela en el QUÉ |
| **Incremental** | `INCREMENTAL_N1_DIFERENCIAL` | `BACKUP INCREMENTAL LEVEL 1` | Cambios desde el último respaldo de cualquier nivel |
| **Incremental acumulativo** | `INCREMENTAL_N1_ACUMULATIVO` | `BACKUP INCREMENTAL LEVEL 1 CUMULATIVE` | Cambios desde el último nivel 0 |
| **Incompleto** | — | — | **No es una opción: es un defecto.** Describe un respaldo que no alcanza para recuperar; el validador lo previene con `ALC_004` y `ALC_005` |

## 10. ARCHIVELOG frente a NOARCHIVELOG

| | NOARCHIVELOG | ARCHIVELOG |
|---|---|---|
| Qué hace Oracle con un grupo de redo lleno | Lo sobrescribe | ARCn lo copia como *archived redo log* antes de reutilizarlo |
| Respaldo en línea | **No es posible** (`RMAN-06817` / `ORA-19602`) | Sí, sin apagar nada |
| Respaldo en frío | Único posible: apaga la base | Posible, pero innecesario |
| Recuperación | Solo hasta el último respaldo | Hasta un punto en el tiempo |
| Alcance parcial (tablespace, datafile, PDB) | Riesgoso | Soportado |
| Costo | Ninguno | Espacio de archivado y política de purga obligatoria |

Cómo lo tratan las reglas:

| Código | Severidad | Condición |
|---|---|---|
| `ARCH_001` | Advertencia | Base en NOARCHIVELOG |
| `ARCH_002` | Recomendación | Base en ARCHIVELOG sin archived logs en la estrategia (aplicable con *aplicar recomendación*) |
| `ARCH_004` | Error | Archived logs pedidos con la base en NOARCHIVELOG |
| `ARCH_005` | Error | Modo `EN_LINEA` con la base en NOARCHIVELOG |
| `ARCH_006` | Advertencia | Alcance parcial en NOARCHIVELOG |
| `ARCH_007` | Advertencia | Modo efectivo `CONSISTENTE`: implica caída del servicio y exige aceptarla para aprobar el script |
| `ARCH_009` | Advertencia | El repositorio vive en la misma CDB que se respalda en modo consistente |

El paso a ARCHIVELOG **nunca lo ejecuta la herramienta**: la pantalla *Sistema → Modo de archivado* muestra el procedimiento (`sql/archivelog/activar_archivelog.sql`) para que lo ejecute el administrador, con un respaldo antes y otro después. Ver `docs/afinamiento_redo_archivelog.md`.

## 11. Qué proteger y con qué mecanismo

La clase enumera cuatro grupos de archivos. Cada uno se protege de forma distinta:

| Archivo | Mecanismo |
|---|---|
| Datafiles | `BACKUP` de RMAN (tablespace, datafile o base completa) |
| Control file | `BACKUP CURRENT CONTROLFILE` y autobackup |
| SPFILE / init | `BACKUP SPFILE` |
| **Redo logs online** | **RMAN no los respalda.** Se protegen **multiplexándolos** (observación `RED_001`) y **archivándolos** (ARCHIVELOG) |

Un respaldo que "incluyera" los redo logs online sería inconsistente por definición: están en uso y cambian mientras se copian. Lo que se respalda son los **archived** redo logs, que son copias cerradas y estables de los grupos ya llenos. `RED_003` revisa además la cantidad y el tamaño de los grupos y el ritmo de *log switch*.

Por qué importa el redo: LGWR escribe la bitácora en cada `COMMIT`; DBWn escribe los datafiles cuando le conviene. Un commit garantiza el redo, no el datafile. Por eso, tras una falla, Oracle reconstruye lo que faltaba en los datafiles **desde el redo**, y por eso conservarlo (archivado) es lo que permite recuperar hasta un punto en el tiempo.

## 12. Respaldo físico frente a lógico

Se eligió el respaldo **físico con RMAN** y se descartó Data Pump (EXP/IMP) como mecanismo de recuperación ante desastre.

| | Físico (RMAN) | Lógico (Data Pump) |
|---|---|---|
| Qué copia | Bloques de los archivos de la base | Sentencias y datos de objetos |
| Si falla a mitad | RMAN deja las piezas registradas y verificables | El archivo queda incompleto y **solo se descubre al importar** |
| Recuperación | Hasta un punto en el tiempo (con ARCHIVELOG) | Solo al instante de la exportación |
| Velocidad de restauración | Alta | Baja: reconstruye objetos e índices |
| Verificación | `CROSSCHECK` y `VALIDATE` sin restaurar | Solo importando |

El export sigue siendo útil para migrar, compactar o mover un esquema, pero no para recuperar ante un desastre.

## 13. Por qué no basta con copiar archivos

El escenario 24/7: sin poder apagar la base, un administrador podría poner un datafile `OFFLINE`, copiarlo y devolverlo `ONLINE`, uno por uno. El resultado son datafiles copiados **en momentos distintos** y, por tanto, **desincronizados entre sí**: no hay un instante común al que restaurar, y el redo necesario para sincronizarlos se sobrescribe si no hay ARCHIVELOG.

La solución es **ARCHIVELOG más respaldo en caliente con RMAN**: RMAN conoce el SCN de cada bloque y los archived logs permiten llevar todos los datafiles al mismo punto consistente. Es el problema que la herramienta resuelve.

## 14. Modos de apagado y tipos de recuperación

| Modo | Espera usuarios | Cierra transacciones | Deja la base consistente |
|---|---|---|---|
| `NORMAL` | Sí, a que se desconecten | — | Sí |
| `TRANSACTIONAL` | Espera a que terminen sus transacciones | Al terminar | Sí |
| `IMMEDIATE` | No | Hace *rollback* | Sí |
| `ABORT` | No | No | **No**: exige *instance recovery* al abrir |

El modo `CONSISTENTE` usa **`SHUTDOWN IMMEDIATE`** porque cierra de forma ordenada (la base queda consistente, sin *instance recovery* al abrir) y no espera a los usuarios, a diferencia de `NORMAL`, que podría no terminar nunca. `ABORT` se descarta porque dejaría una copia que exige recuperación.

- ***Instance recovery*:** automática al abrir tras una caída; aplica el redo online. No requiere respaldos.
- ***Media recovery*:** manual tras perder archivos; restaura desde respaldo y aplica archived logs. Es lo que la herramienta ayuda a planificar (`recuperacion plan`).

Tras un respaldo consistente se corre siempre `asegurar_apertura`, aunque el respaldo haya fallado, para que la base no quede cerrada.

## 15. Retención

El enunciado §3 pide la conservación "durante un período determinado". Cada estrategia define:

| Campo | Efecto |
|---|---|
| `ventana_dias` | `RECOVERY WINDOW OF n DAYS` |
| `redundancia` | `REDUNDANCY n` (excluyente con la ventana; `RET_002`) |
| `archived_logs_dias` | Antigüedad máxima de los archived logs ya respaldados |
| `purga_automatica` | Si es falso, **solo informa**; nunca borra |

La ventana va **dentro del comando**, nunca con `CONFIGURE RETENTION POLICY`, para no alterar la configuración persistente de RMAN en la base del cliente. Los valores de las estrategias de demostración (30 días, 7 días de archived logs, redundancia 2) son **de demostración**; la clase habla de 6, 8 o 12 meses para producción.

## 16. Estrategias de demostración

Reproducen la tabla del §6 de la clase del 21/09.

| Código | Qué | Tareas | Prioridad |
|---|---|---|---|
| `EST001` | `VENTAS` y `FINANZAS` + control file + SPFILE | T1: N1 acumulativo a las 13, 15, 18 y 21 h, ventana 12:30–22:00 | Alta |
| `EST002` | CDB completa | T1: N0 en modo `CONSISTENTE`, una sola vez (escenario NOARCHIVELOG) | Alta |
| `EST003` | `RRHH` | T1: completo parcial a las 18:00 y 02:00 | Baja |
| `EST004` | CDB + control file + SPFILE + archived logs | T1: N0 ("total+") domingo 02:00 · T2: N1 diferencial lunes a sábado 15:00 · T3: archived logs cada 4 h | Alta |

## 17. Matriz de controles preventivos

| Momento | Control | Dónde se aplica |
|---|---|---|
| **Antes** | Validación de la estrategia con cuatro severidades; un Error bloquea | Motor de validación (`GEN`, `ALC`, `ARCH`, `MET`, `PRG`, `DST`, `RET`) |
| **Antes** | Script generado desde la estrategia, revisado y **aprobado con hash** | Aprobación de scripts |
| **Antes** | Aceptación explícita de la caída en modo `CONSISTENTE` | `ARCH_007` y `--acepto-caida` |
| **Antes** | *Preflight*: script aprobado, hash, revalidación contra el perfil actual, modo de archivado, destino escribible y con espacio | Pipeline de ejecución |
| **Durante** | Un solo RMAN por base; tiempo máximo; `COMMAND ID` y `TAG` únicos | Runner |
| **Durante** | Reapertura garantizada tras un respaldo consistente | `asegurar_apertura` |
| **Durante** | Evidencia a disco primero; buzón si el repositorio no responde | `evidencia` y `buzon` |
| **Después** | Clasificación Exitosa / Con advertencias / Fallida cruzando log, piezas y `V$RMAN_BACKUP_JOB_DETAILS` | Clasificador |
| **Después** | `CROSSCHECK` + `VALIDATE BACKUPSET` → columna **Pruebas** | Verificador |
| **Después** | Alertas por evento y por condición, con correo al DBA | Motor de alertas |
| **Después** | Informe de obsoletos y purga solo bajo confirmación | Retención |
| **Siempre** | Procedimientos de recuperación **generados, nunca ejecutados**; solo en ambiente `PRUEBAS` | Recuperación |

## 18. Cobertura de las notas de clase

| Concepto | Dónde se resuelve |
|---|---|
| Cuatro archivos a proteger | Sección 11 |
| Línea de tiempo de una falla, `V$RECOVER_FILE` | `recuperacion diagnostico` |
| Modos de SHUTDOWN, instance vs. media recovery | Sección 14 |
| Copia en frío y en caliente | Modos `CONSISTENTE` y `EN_LINEA` |
| Política de retención, etiquetado, verificación | Sección 15, `TAG`, columna Pruebas |
| Exportación lógica | Sección 12 |
| Escenario 24/7 | Sección 13 |
| Prioridad por tablespace, vocabulario del profesor | Secciones 7 y 9 |
| Varias estrategias por BD | Sección 16 |
| Robot en bucle y correo al DBA | Agente y notificador de correo |
| Tabla BD · Estrategia · Resultado · Pruebas | Historial |
| Tarea de afinamiento en 4 pasos | `docs/afinamiento_redo_archivelog.md` |
| Tablespaces READ ONLY | `ALC_008` y `SKIP READONLY` |
| Umbral de capacidad (85 %) | Parámetro `alertas.disco_uso_pct` |
| Mínimo privilegio | `C##BKP_MON` de solo lectura |

## 19. Puntos que se deben confirmar con el profesor

1. **Redo logs online.** La clase los lista entre los archivos a proteger, pero RMAN no los respalda. Aquí se cubren por multiplexado y por ARCHIVELOG (sección 11). Confirmar que esa lectura es la esperada.
2. **Valores de retención.** Son de demostración, no de producción.
3. **Cantidad de reglas.** La tabla del plan enumera 35 códigos (34 más `PRG_007`); el catálogo implementado los incluye todos.
