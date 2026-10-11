# Demostración — control correctivo: se borra un datafile y CloudCR lo recupera

Guion reproducible para la presentación. Muestra la línea de tiempo completa de una falla de medios: respaldo →
falla → detección (calendario + alerta) → diagnóstico → procedimiento → aprobación → ejecución → base sana.
Ensáyelo completo al menos dos veces antes de presentar y anote los tiempos reales de su equipo.

> **Solo en una base de PRUEBAS.** Este guion borra un archivo de datos de verdad. CloudCR se niega a ejecutar
> procedimientos de recuperación sobre bases que no estén registradas en ambiente `PRUEBAS`.

## Por qué este escenario y no otro

En Oracle XE el repositorio de CloudCR (`BKPCAT`) es una PDB de la **misma** CDB que se respalda
(`docs/diseno.md` §1.3). Si la CDB se apaga, la web y la CLI pierden el repositorio. Por eso la demo usa el
escenario **1 · `PERDIDA_DATAFILE_NO_CRITICO`** sobre el datafile del tablespace `USERS` del contenedor raíz:

- la CDB sigue abierta todo el tiempo, igual que `BKPCAT`;
- se recupera con el escenario `datafile`: `OFFLINE → RESTORE → RECOVER → ONLINE`;
- en Windows no se puede borrar un datafile abierto, así que primero se deja `OFFLINE` (Oracle cierra el archivo).

La variante de la clase (§3.2: apagar, borrar el archivo y ver que `STARTUP` se queda en `MOUNT`) también es
válida, pero en XE deja montada la CDB entera, `BKPCAT` incluida: CloudCR no podría registrar nada. En ese caso
el DBA aplica a mano el script ya generado (`recuperacion\XE\datafile_*.rman`) con `rman target /` y termina con
`ALTER DATABASE OPEN;`. Se puede contar en la presentación como contraste.

## 0. Requisitos (una sola vez)

1. La base en **ARCHIVELOG** (`sql\archivelog\activar_archivelog.sql`; Sistema → Modo de archivado).
2. La base registrada en ambiente **PRUEBAS**: Sistema → Bases de datos (el formulario propone `PRUEBAS`) o
   `cloudcr db agregar XE --ambiente PRUEBAS` (ojo: en la terminal el valor por defecto es `DESARROLLO`).
   Compruébelo con `cloudcr db listar`. Si ya estaba registrada con otro ambiente, el cambio es una decisión
   del DBA y se hace a mano, conectado a `BKPCAT` como `BKP_ADMIN`:

   ```sql
   UPDATE bd_registrada SET ambiente = 'PRUEBAS' WHERE nombre = 'XE';
   COMMIT;
   ```
3. Un respaldo de la **base completa** ejecutado con éxito y con Pruebas en OK. La estrategia de ejemplo `EST004`
   (base completa + control file + SPFILE + archived logs) sirve: Estrategias → EST004 → generar, aprobar y
   «Ejecutar ahora» su tarea de nivel 0 o completo.
4. Comprobar en `/recuperacion` que aparece en «Puntos de recuperación» y en el **calendario semanal** con su
   símbolo (● completo, ◆ nivel 0).

## 1. Generar actividad posterior al respaldo

Para que `RECOVER` tenga redo que aplicar (`sqlplus / as sysdba`):

```sql
@sql\demo\03_generar_actividad.sql
ALTER SYSTEM ARCHIVE LOG CURRENT;
```

## 2. Provocar la falla

En `sqlplus / as sysdba`, conectado a `CDB$ROOT`:

```sql
-- file# y ruta del datafile de USERS del contenedor raíz (no es SYSTEM ni UNDO: no es crítico)
SELECT df.file#, df.name
FROM v$datafile df JOIN v$tablespace ts ON ts.ts# = df.ts# AND ts.con_id = df.con_id
WHERE ts.name = 'USERS' AND df.con_id = 1;

-- Supongamos file# = 7. Dejarlo fuera de línea (requiere ARCHIVELOG) para que Windows suelte el archivo
ALTER DATABASE DATAFILE 7 OFFLINE;
```

Borrar el archivo desde PowerShell (use la ruta que devolvió la consulta):

```powershell
Remove-Item "C:\app\<usuario>\product\21c\oradata\XE\USERS01.DBF"
```

Intentar volver a usarlo confirma la pérdida de medio:

```sql
ALTER DATABASE DATAFILE 7 ONLINE;
-- ORA-01157: cannot identify/lock data file 7 - see DBWR trace file
-- ORA-01110: data file 7: '...\USERS01.DBF'
```

## 3. Detectar y diagnosticar en CloudCR

1. Abrir `/recuperacion` y elegir `XE`.
2. Pulsar **Diagnosticar ahora**. Debe aparecer:
   - el datafile 7 en «Datafiles que necesitan recuperación» (origen `V$RECOVER_FILE`, estado `OFFLINE`; el
     error suele ser `FILE NOT FOUND`), Crítico: No;
   - **Escenario sugerido:** «Pérdida de un datafile no crítico (PERDIDA_DATAFILE_NO_CRITICO)» (`datafile`).
3. En el **calendario semanal** aparece ⚠ en el día y la hora de la detección (no es el instante exacto de la
   caída: ese solo está en el alert log).
4. En `/alertas` queda abierta la alerta **CAIDA_DETECTADA** («Falla de medios detectada»). Si el canal de
   correo está configurado, llega el aviso.

Equivalente en la terminal: `cloudcr recuperacion diagnostico XE`.

## 4. Generar, aprobar y ejecutar

1. En «Generar un procedimiento», elegir «Pérdida de un datafile no crítico» y dejar «Objeto dañado» vacío (se
   deduce del diagnóstico). Pulsar **Generar procedimiento**. El script debe ser:

   ```
   ALTER DATABASE DATAFILE 7 OFFLINE;
   RESTORE DATAFILE 7;
   RECOVER DATAFILE 7;
   ALTER DATABASE DATAFILE 7 ONLINE;
   ```

2. Escribir el nombre en «Aprobado por», marcar la confirmación y pulsar **Aprobar el procedimiento N**. Queda
   fijada la huella SHA-256 del script.
3. Marcar «Entiendo que la ejecución modifica la base de datos…» y pulsar **Ejecutar en PRUEBAS**. La tarjeta
   muestra «RMAN está ejecutando…» y se actualiza sola; al terminar muestra **Ejecutado sin errores** y el log de
   RMAN (`Finished restore`, `media recovery complete`, `Recovery Manager complete.`).

Equivalente en la terminal:

```powershell
cloudcr recuperacion plan XE datafile                 # muestra "Registrado como procedimiento N"
cloudcr recuperacion aprobar XE N --confirmo --por "Nombre Apellido"
cloudcr recuperacion ejecutar XE N --confirmo
```

## 5. Comprobar que la base quedó sana

1. Pulsar de nuevo **Diagnosticar ahora**: «V$RECOVER_FILE no informa archivos que necesiten recuperación.» La
   alerta `CAIDA_DETECTADA` pasa a RESUELTA.
2. En `sqlplus`:

   ```sql
   SELECT file#, status FROM v$datafile WHERE file# = 7;   -- ONLINE
   ```

Tiempo esperado: el `RESTORE` de `USERS01.DBF` (unos pocos MB) y el `RECOVER` tardan segundos; el paso más largo
es el respaldo previo del punto 0.

## Qué mostrar si algo sale mal (también es parte del control)

| Prueba | Resultado esperado |
|---|---|
| Editar el `.rman` en `recuperacion\XE\` después de aprobarlo y pulsar Ejecutar | Bloqueado: «su huella SHA-256 no coincide» |
| Ejecutar sobre una base registrada en `DESARROLLO` o `PRODUCCION` | Bloqueado: solo se ejecuta en ambiente PRUEBAS |
| Pulsar Ejecutar dos veces | La segunda se rechaza: cada procedimiento aprobado se ejecuta una sola vez |
| No marcar la confirmación | Se rechaza con «Falta confirmar…» |

## Archivos que deja la demo

En `<carpeta de trabajo>\recuperacion\XE\`:

- `datafile_<fecha>.rman` — el script aprobado (su SHA-256 queda en `RECUPERACION_PROCEDIMIENTO`);
- `datafile_<fecha>.log` — el log completo de RMAN;
- `datafile_<fecha>.resultado.json` — el resultado, escrito antes de tocar el repositorio;
- `fallas_detectadas.jsonl` — cada diagnóstico con daños; alimenta las ⚠ del calendario.
