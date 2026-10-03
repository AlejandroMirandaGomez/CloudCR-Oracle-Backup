# Guía de prueba completa — de cero a un repositorio funcionando

Esta guía recorre **todo el sistema tal como está hoy**: entorno Python, instalación del repositorio Oracle (`BKPCAT`), registro e inspección de bases de datos, y el ciclo completo de estrategias (crear, validar, activar, exportar) contra una base real. Es la misma secuencia que se usó para probar el trabajo de Josué y Luis juntos, consolidada en un solo documento.

Sirve para dos cosas: dejar el sistema funcionando en una máquina nueva, o confirmar que nada se rompió después de un cambio grande.

---

## 0. Qué cubre esta guía (y qué no)

**Cubre:** entorno Python, `repository/` completo, `cloudcr repo`, `cloudcr db`, `cloudcr param`, `cloudcr doctor`, `cloudcr estrategia` (crear, importar, listar, mostrar, validar, activar, desactivar, exportar, aplicar-recomendacion), y la suite de pruebas automatizadas.

**Cubre también** (carril de Alejandro, §8b): próximas ejecuciones, el agente (`cloudcr agente`), las alertas, el historial, el estado con semáforo y las pantallas web de estado, estrategias, historial y alertas.

**No cubre todavía** (porque todavía no existe en el código): generación y ejecución real de scripts RMAN, verificación posterior y recuperación (carril de Juan). Mientras tanto, el agente se prueba con `--simulado` y cada ejecución queda rotulada SIMULACION.

---

## 1. Requisitos previos

| Requisito | Cómo comprobarlo |
|---|---|
| Python 3.11 o superior | `python --version` |
| Git | `git --version` |
| Oracle Database 12.2+ instalado y la instancia iniciada | `Get-Service OracleService*` o `sc query OracleServiceXE` debe mostrar `RUNNING` |
| El listener de Oracle corriendo | `lsnrctl status` |
| Tu usuario de Windows pertenece al grupo `ORA_DBA` | Lo trae por defecto quien instaló Oracle |

---

## 2. Preparar el entorno Python

```powershell
cd "C:\ruta\a\CloudCR-Oracle-Backup"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Confirmá que no haya errores de instalación (todas las dependencias, incluido `oracledb`, tienen wheels para Python 3.11–3.14; no hace falta bajar de versión).

---

## 3. Instalar el repositorio (`BKPCAT`)

Todo esto con `sqlplus`, **parado siempre en la carpeta del proyecto** (si no, `sqlplus @archivo` falla con `SP2-0310`).

```powershell
cd "C:\ruta\a\CloudCR-Oracle-Backup"
```

**3.1 — Crear la PDB**

```powershell
sqlplus / as sysdba @sql\setup\01_crear_pdb_bkpcat.sql
```

Pide: nombre de la PDB (`BKPCAT`), un usuario admin temporal y su clave.

**3.2 — Crear el usuario del repositorio**

```powershell
sqlplus / as sysdba @sql\setup\02_crear_usuario_repositorio.sql
```

Pide: la PDB (`BKPCAT`), el usuario (`BKP_ADMIN`), su clave (**anotala**) y la cuota (`500`). Este script ya crea el tablespace `USERS` solo si la PDB no lo trae — no debería dar `ORA-02236` ni `ORA-00959`.

**3.3 — Crear las 12 tablas**

```powershell
sqlplus BKP_ADMIN/<CLAVE>@localhost:1521/BKPCAT @sql\setup\03_esquema_bkp_admin.sql
```

Si da `ORA-12514` o `ORA-12541`, el listener puede estar escuchando en otra dirección que no es `localhost` — ver la sección de problemas comunes al final.

**3.4 — Cargar los parámetros iniciales**

```powershell
sqlplus BKP_ADMIN/<CLAVE>@localhost:1521/BKPCAT @sql\setup\04_parametros_iniciales.sql
```

**3.5 — Verificar a mano (opcional, el paso 6 ya lo confirma mejor)**

```sql
sqlplus BKP_ADMIN/<CLAVE>@localhost:1521/BKPCAT
SELECT COUNT(*) FROM user_tables;  -- 12
SELECT COUNT(*) FROM parametro;    -- 13
EXIT;
```

---

## 4. Configurar `.env`

```powershell
Copy-Item .env.example .env
notepad .env
```

Completá:

```
CLOUDCR_REPO_CLAVE=<la clave de BKP_ADMIN del paso 3.2>
CLOUDCR_REPOSITORIO_DSN=localhost:1521/BKPCAT
CLOUDCR_REPOSITORIO_USUARIO=BKP_ADMIN
```

`.env` nunca se sube a git (ya está en `.gitignore`).

---

## 5. Verificación general con `doctor`

```powershell
.\.venv\Scripts\cloudcr.exe doctor
```

Tiene que mostrar los 7 chequeos en verde: Python, dependencias, configuración, instancias Oracle, `rman.exe`, destino de respaldo y esquema del repositorio. Si algo falla, el mensaje trae la sugerencia — no sigas al paso 6 hasta que esto esté todo en verde.

---

## 6. Instalar el esquema desde la CLI (alternativa a los pasos SQL manuales)

Una vez que `.env` está configurado, `cloudcr repo instalar` hace lo mismo que los pasos 3.3 y 3.4, y es idempotente (lo podés correr de nuevo sin romper nada):

```powershell
.\.venv\Scripts\cloudcr.exe repo instalar
.\.venv\Scripts\cloudcr.exe repo estado
```

`repo estado` tiene que listar las 12 tablas con sus filas (`PARAMETRO` con 13, el resto en 0 si es la primera vez).

---

## 7. Registrar e inspeccionar una base de datos

```powershell
.\.venv\Scripts\cloudcr.exe db agregar XE --ambiente PRUEBAS
.\.venv\Scripts\cloudcr.exe db listar
.\.venv\Scripts\cloudcr.exe db mostrar XE
.\.venv\Scripts\cloudcr.exe db inspeccionar XE
```

`inspeccionar` guarda un perfil nuevo cada vez que se corre — ejecutalo dos veces y confirmá con `repo estado` que `PERFIL_BD` tiene dos filas.

---

## 8. Ciclo completo de estrategias

El repositorio trae 4 estrategias de demostración en `config/estrategias/` (reproducen la tabla de la clase del 21/09).

**8.1 — Importar las cuatro**

```powershell
.\.venv\Scripts\cloudcr.exe estrategia importar config\estrategias\est001.yaml --bd XE
.\.venv\Scripts\cloudcr.exe estrategia importar config\estrategias\est002.yaml --bd XE
.\.venv\Scripts\cloudcr.exe estrategia importar config\estrategias\est003.yaml --bd XE
.\.venv\Scripts\cloudcr.exe estrategia importar config\estrategias\est004.yaml --bd XE
.\.venv\Scripts\cloudcr.exe estrategia listar --bd XE
```

Tiene que listar las 4, todas en versión 1, estado `INACTIVA`.

**8.2 — Mostrar el detalle** (confirma que el alcance y las tareas se reconstruyen bien desde la base)

```powershell
.\.venv\Scripts\cloudcr.exe estrategia mostrar --bd XE --codigo EST004
```

`EST004` tiene que mostrar sus **tres** tareas (T1 incremental nivel 0, T2 incremental nivel 1 diferencial, T3 archived logs), cada una con su propia frecuencia.

**8.3 — Validar contra el perfil real**

```powershell
.\.venv\Scripts\cloudcr.exe estrategia validar --bd XE --codigo EST001
```

Con la XE en NOARCHIVELOG tiene que aparecer, como mínimo, `ARCH_001` (advertencia) y, si `EST001` tiene alguna tarea en modo `EN_LINEA`, `ARCH_005` (error bloqueante). El mensaje final tiene que decir "Hay errores que bloquean la aprobación" en ese caso, o "Sin errores bloqueantes" si no hay ninguno.

**8.4 — Activar, exportar y aplicar una recomendación**

```powershell
.\.venv\Scripts\cloudcr.exe estrategia activar EST001 --bd XE
.\.venv\Scripts\cloudcr.exe estrategia exportar EST001 --bd XE --archivo exportaciones\est001.yaml
.\.venv\Scripts\cloudcr.exe estrategia aplicar-recomendacion EST001 ARCH_002 --bd XE
.\.venv\Scripts\cloudcr.exe estrategia mostrar --bd XE --codigo EST001
```

Después de `aplicar-recomendacion`, `EST001` tiene que quedar en **versión 2**, con `ARCHIVELOG` agregado al alcance.

**8.5 — Desactivar** (para dejar todo como estaba antes de la prueba, si hace falta)

```powershell
.\.venv\Scripts\cloudcr.exe estrategia desactivar EST001 --bd XE
```

---

## 8b. Agente, alertas, historial, estado y web (carril de Alejandro)

Requiere los pasos 1 a 8: repositorio instalado, la base registrada e inspeccionada y al menos una estrategia importada.

**8b.1 — Próximas ejecuciones** (no necesita Oracle):

```powershell
.\.venv\Scripts\cloudcr.exe tarea proximas T1 --archivo config\estrategias\est001.yaml -n 10
.\.venv\Scripts\cloudcr.exe tarea proximas EST001 T1 --bd XE -n 10
```

Las dos deben listar solo las 13:00, 15:00, 18:00 y 21:00 de cada día.

**8b.2 — Preparar una tarea que el agente pueda disparar.** El agente solo programa tareas de estrategias ACTIVAS que tengan un script RMAN **aprobado**. Mientras el pipeline de Juan no genere scripts, apruebe uno de prueba (es solo una fila en `SCRIPT_RMAN`; con `--simulado` RMAN no se ejecuta):

```powershell
.\.venv\Scripts\cloudcr.exe estrategia activar EST001 --bd XE
.\.venv\Scripts\python.exe -c "from cloudcr_backup.config.ajustes import cargar_ajustes; from cloudcr_backup.repository import conexion, estrategias, bases_datos, scripts; c = conexion.abrir_repositorio(cargar_ajustes()); bd = bases_datos.obtener(c, 'XE'); t = estrategias.obtener_tarea_id(c, bd.id, 'EST001', 'T1'); s = scripts.guardar_borrador(c, t, 'RUN { BACKUP DATABASE; }'); print(scripts.aprobar(c, s.id, 'demo'))"
```

Para ver disparos seguidos, cree una estrategia de demostración con una tarea `INTERVALO` de 5 minutos (asistente web o `cloudcr tarea agregar … --frecuencia INTERVALO --intervalo-minutos 5`).

**8b.3 — Agente en simulación:**

```powershell
.\.venv\Scripts\cloudcr.exe agente ejecutar --simulado --una-vez
.\.venv\Scripts\cloudcr.exe agente estado
```

Sin `--simulado` debe negarse a correr explicando que falta el pipeline. Con `--simulado` reclama la ocurrencia vencida, la marca EXITOSA con mensaje `SIMULACION` y deja el latido en `%LOCALAPPDATA%\cloudcr\agente\`.

**8b.4 — Ocurrencia perdida (base de E7):** deje el agente corriendo (`cloudcr agente ejecutar --simulado`), deténgalo con Ctrl+C antes de una ocurrencia, espere a que pase la ocurrencia más la gracia (`agente.gracia_omision_min`, 15 min; se puede bajar con `cloudcr param set agente.gracia_omision_min 2`) y vuelva a arrancarlo. Debe registrar `NO_EJECUTADA` con el motivo y abrir `RESPALDO_NO_EJECUTADO` (en consola: `NUEVA ALERTA [ALERTA] RESPALDO_NO_EJECUTADO …`).

**8b.5 — Historial, alertas y estado:**

```powershell
.\.venv\Scripts\cloudcr.exe historial --bd XE
.\.venv\Scripts\cloudcr.exe historial mostrar <id>
.\.venv\Scripts\cloudcr.exe alertas
.\.venv\Scripts\cloudcr.exe alertas evaluar
.\.venv\Scripts\cloudcr.exe estado
.\.venv\Scripts\cloudcr.exe reporte historial --formato html --archivo exportaciones
```

**8b.6 — Web:** `cloudcr web` y recorra Estado, Estrategias, Historial (filtre por resultado y exporte), Alertas (reconozca una) e Instancias. Pruebe el tema oscuro del sistema y el ancho de teléfono (herramientas de desarrollo del navegador). En la consola del navegador no debe aparecer ningún error de CSP. Abra primero `/historial` y después `/instancias/XE`: el explorador debe seguir funcionando (orden thick/thin, G9).

---

## 9. Pruebas automatizadas

**9.1 — Suite sin Oracle** (rápida, corre siempre)

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Tiene que terminar en verde (ahora mismo: 659 pruebas recolectadas. Se verificó en Linux, donde fallan 13 pruebas de rutas Windows que dependen de `os.name`; en Windows deben pasar todas — confirmarlo al correrla).

**9.2 — Suite con Oracle** (usa tu `BKPCAT` real; instala y desinstala el esquema como parte de la prueba, así que dejalo correr sin interrumpir)

```powershell
.\.venv\Scripts\python.exe -m pytest -m oracle -v
```

Al terminar, el esquema queda **desinstalado** (el fixture de `tests/integration/test_repositorio_oracle.py` lo borra al final, **con todos sus datos**). Repetí el paso 6 (`cloudcr repo instalar`) para dejar el repositorio listo de nuevo. Si solo querés las pruebas del agente sin tocar tus datos, corré `pytest -m oracle tests/integration/test_agente_oracle.py`: crean una base de prueba con nombre único y borran solo lo que crearon.

---

## 10. Checklist final — tiene que ser cierto todo esto

- [ ] `cloudcr doctor` sale todo en verde.
- [ ] `cloudcr repo estado` muestra las 12 tablas.
- [ ] `cloudcr db listar` muestra al menos una base de datos registrada.
- [ ] `cloudcr db inspeccionar` corrido dos veces deja dos filas en `PERFIL_BD`.
- [ ] Las 4 estrategias de demostración se importan sin error.
- [ ] `cloudcr estrategia mostrar EST004` muestra sus 3 tareas completas.
- [ ] `cloudcr estrategia validar EST001` dispara observaciones reales (no una lista vacía) si la base está en NOARCHIVELOG.
- [ ] `cloudcr estrategia aplicar-recomendacion EST001 ARCH_002` sube la versión a 2.
- [ ] `pytest -q` (sin Oracle) y `pytest -m oracle` (con Oracle) terminan ambas en verde.
- [ ] `cloudcr tarea proximas EST001 T1 -n 10` devuelve solo 13, 15, 18 y 21 h.
- [ ] `cloudcr agente ejecutar --una-vez` sin `--simulado` se niega a correr; con `--simulado` deja una ejecución SIMULACION en `cloudcr historial`.
- [ ] Detener y reiniciar el agente durante una ocurrencia produce `NO_EJECUTADA` y la alerta `RESPALDO_NO_EJECUTADO`.
- [ ] `cloudcr estado` muestra el semáforo y las alertas vigentes; `/estado` muestra lo mismo.
- [ ] `cloudcr reporte historial --formato html` genera un HTML que se abre sin conexión a internet.

Si todo esto se cumple, el sistema está en el mismo estado verificado que se documentó en `docs/estado_josue.md`.

---

## 11. Problemas comunes (los que de verdad aparecieron probando esto)

| Síntoma | Causa | Solución |
|---|---|---|
| `SP2-0310: no se ha podido abrir el archivo` | `sqlplus` no estaba parado en la carpeta del proyecto | `cd` a la carpeta del proyecto antes de cualquier `sqlplus @archivo` |
| Escribiste `sqlplus ...` y salió `SP2-0734: inicio "sqlplus..." de comando desconocido` | Estabas dentro de una sesión de `SQL>` y pegaste un comando de terminal | `EXIT;` primero, y corré el comando desde PowerShell/cmd, no desde `SQL>` |
| `ORA-02236: nombre de archivo no válido` al crear un tablespace | La instalación no tiene `DB_CREATE_FILE_DEST` configurado | Usar una ruta de datafile explícita (ya resuelto en `02_crear_usuario_repositorio.sql`) |
| `ORA-00959: el tablespace 'USERS' no existe` | La PDB se creó desde un seed sin tablespace `USERS` (pasa en instalaciones nuevas de XE 21c) | Ya resuelto: el script 02 lo crea solo |
| `ORA-01918: el usuario 'BKP_ADMIN' no existe` al intentar cambiarle la clave | El usuario nunca se llegó a crear (falló un paso anterior sin que se notara) | Conectate como sysdba, `ALTER SESSION SET CONTAINER = BKPCAT;` y creá el usuario a mano con `CREATE USER` |
| `ORA-12541: TNS:no hay ningún listener` | El listener está detenido, o escuchando en una IP que no es `localhost` | `lsnrctl status` para ver dónde escucha; si es una IP de red, hay que corregir `listener.ora` y `tnsnames.ora` para que diga `localhost`, y reiniciar el servicio del listener **como administrador** |
| `ORA-12514: el listener no conoce actualmente el servicio solicitado` | El servicio (PDB) todavía no se registró con el listener (tarda hasta un minuto después de un reinicio) | Esperar, o forzarlo: `sqlplus / as sysdba` → `ALTER SYSTEM REGISTER;` |
| `DPY-2019: python-oracledb thick mode cannot be used because thin mode has already been enabled` | Un mismo comando intentó conectar primero al repositorio (thin) y después a una instancia local por SYSDBA (thick) — `oracledb` no permite mezclar los dos modos en el mismo proceso | Hay que invertir el orden: primero toda la inspección local (thick), recién después conectar al repositorio (thin). Ya corregido en `cloudcr db inspeccionar` y `cloudcr estrategia validar` |
| `PermissionError: [Errno 13] Permission denied: '.'` al cargar la configuración | Una variable de entorno vacía (por ejemplo `CLOUDCR_CONFIG=` en `.env`) se interpretaba como una ruta válida (`Path('.')`) | Ya corregido: una variable de entorno vacía ahora se trata como si no estuviera puesta |
| `net stop`/`net start` del listener da "Acceso denegado" | La terminal no es de administrador | Abrir PowerShell o cmd como administrador para reiniciar servicios de Windows |
