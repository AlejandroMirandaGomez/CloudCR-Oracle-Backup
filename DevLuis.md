# DevLuis — Qué hice y cómo probarlo antes del push

Checklist personal para verificar mi parte (estrategias y validación) antes de subirla. Todo lo que está acá es mío (carril "LUIS" del `PLAN_DE_ACCION.md`, sección 7.2); no toqué nada de `repository/` (Josué), `rman/`/`execution/` (Juan) ni `agent/`/`alerts/`/`scheduling/` (Alejandro).

## 1. Qué se agregó

### Dominio y persistencia en archivo

| Archivo | Qué hace |
|---|---|
| `src/cloudcr_backup/domain/estrategia.py` | Modelo de la estrategia: `Estrategia`, `Tarea`, `Como`, `Programacion`, `Ventana`, `Destino`, `Retencion`, `ObjetoAlcance` |
| `src/cloudcr_backup/domain/enums.py` (ampliado) | 12 enums nuevos: `Prioridad`, `TipoObjeto`, `TipoRespaldo`, `ModoRespaldo`, `Compresion`, `TipoFrecuencia`, `DiaSemana`, `PoliticaOmision`, `EstadoEstrategia`, `EstadoScript`, `EstadoEjecucion`, `EstadoPrueba`, `EstadoAlerta` |
| `src/cloudcr_backup/strategy/yaml_io.py` | Exportar/importar una `Estrategia` a/desde YAML, con errores legibles |
| `src/cloudcr_backup/strategy/servicio.py` | `crear`, `editar` (incrementa versión), `activar`, `desactivar`, `eliminar`, `listar`, `obtener` — llama a `repository/estrategias.py` |

### Validación (28 de 34 reglas del catálogo)

| Archivo | Reglas |
|---|---|
| `src/cloudcr_backup/validation/contexto.py` | `ContextoValidacion` |
| `src/cloudcr_backup/validation/motor.py` | Registro de reglas por decorador, ejecución, `hay_bloqueantes()` |
| `src/cloudcr_backup/validation/reglas/archivado.py` | `ARCH_001`, `ARCH_002`, `ARCH_005` |
| `src/cloudcr_backup/validation/reglas/general.py` | `GEN_001`, `GEN_002` |
| `src/cloudcr_backup/validation/reglas/alcance.py` | `ALC_001`...`ALC_008` |
| `src/cloudcr_backup/validation/reglas/retencion.py` | `RET_001`...`RET_004` |
| `src/cloudcr_backup/validation/reglas/programacion.py` | `PRG_001`, `PRG_002`, `PRG_003`, `PRG_005` (`PRG_007` pendiente: depende de `scheduling/recurrencia.py` de Alejandro) |
| `src/cloudcr_backup/validation/reglas/destino.py` | `DST_001`, `DST_002`, `DST_003`, `DST_004`, `DST_006` |
| `src/cloudcr_backup/validation/reglas/metodo.py` | `MET_001`...`MET_004` |
| `src/cloudcr_backup/oracle/capacidades.py` | Matriz edición → compresiones/canales soportados (usada por `MET_003`/`MET_004`) |

### Criterios y contenido de apoyo

| Archivo | Qué hace |
|---|---|
| `src/cloudcr_backup/strategy/prioridad.py` | RPO/RTO/recencia máxima/esquema sugerido por prioridad (ALTA/MEDIA/BAJA) — entregable que pide el enunciado §1.1 |
| `src/cloudcr_backup/strategy/plantillas_esquema.py` | 5 esquemas predefinidos de respaldo |
| `src/cloudcr_backup/strategy/vocabulario.py` | Equivalencia vocabulario del profesor ↔ tipos RMAN |
| `config/estrategias/est001.yaml`...`est004.yaml` | Las 4 estrategias de demostración de la clase |
| `sql/demo/01_tablespaces_demo.sql`, `02_datos_demo.sql`, `03_generar_actividad.sql` | Tablespaces/datos/actividad de ejemplo (`VENTAS`, `FINANZAS`, `INVENTARIO`, `RRHH`) |

### CLI

| Archivo | Comandos |
|---|---|
| `src/cloudcr_backup/cli/cmd_estrategia.py` | `cloudcr estrategia crear\|validar\|mostrar\|importar\|editar\|exportar\|listar\|activar\|desactivar\|eliminar\|aplicar-recomendacion` |
| `src/cloudcr_backup/cli/cmd_tarea.py` | `cloudcr tarea agregar\|editar\|eliminar` (`proximas` pendiente: depende de Alejandro) |
| `src/cloudcr_backup/cli/asistente_estrategia.py` | Asistente interactivo de 9 pasos, detrás de `cloudcr estrategia crear` |
| `src/cloudcr_backup/cli/app.py` (modificado) | Registra los grupos `estrategia` y `tarea` |

### Pruebas

12 archivos nuevos en `tests/unit/`, uno por módulo de arriba. **202 pruebas en total**, todas corren sin necesitar Oracle instalado.

## 2. Importante: qué funciona hoy y qué no (a propósito)

Varios comandos (`importar`, `listar`, `activar`, `desactivar`, `eliminar`, `exportar`, `editar`, y el paso final de `crear`) llaman a `repository/estrategias.py` y `repository/conexion.py`, que **todavía son solo firmas** (`raise NotImplementedError`) — es la parte de Josué, no terminada aún. Si los corrés vas a ver:

```
Error: La conexión al repositorio todavía no está implementada.
Sugerencia: Este comando necesita 'repository/conexion.py' terminado.
```

**Esto es esperado, no es un bug.** El código ya está completo y probado (con `monkeypatch` simulando el repositorio) — el día que Josué termine su parte, estos comandos van a funcionar sin que yo tenga que tocar nada.

Lo que **sí funciona de punta a punta hoy**, contra tu Oracle real:
- `cloudcr estrategia validar --archivo <ruta>.yaml`
- `cloudcr estrategia mostrar --archivo <ruta>.yaml`
- `cloudcr tarea agregar/editar/eliminar <archivo>.yaml ...`
- El asistente completo (`cloudcr estrategia crear`) hasta el momento de guardar en el repositorio (el archivo YAML sí se guarda siempre).

## 3. Guía paso a paso desde cero

### Paso 0 — Abrir la terminal correcta

Todo esto se hace en **PowerShell** (no Git Bash ni cmd.exe). Botón derecho en el menú inicio → "Windows PowerShell", o Windows Terminal con pestaña PowerShell.

### Paso 1 — Ir a la carpeta del proyecto

```powershell
cd "C:\Users\calvo\OneDrive\Documentos\II Ciclo 2026\Administracion de Bases\Proyecto 2\CloudCR-Oracle-Backup"
```

Confirmá que estás en el lugar correcto:

```powershell
ls
```
Tenés que ver `src`, `sql`, `config`, `tests`, `pyproject.toml`, `README.md`.

### Paso 2 — Verificar Python

```powershell
python --version
```
**Esperado:** `Python 3.11` o superior. Si da error, instalar Python desde python.org marcando "Add to PATH".

### Paso 3 — Verificar que Oracle XE está corriendo

```powershell
Get-Service OracleServiceXE
```
Si `Status` dice `Stopped` (necesita PowerShell como administrador):
```powershell
Start-Service OracleServiceXE
```
**Esperado:** `Status` pasa a `Running`.

### Paso 4 — Crear el entorno virtual (solo si no existe `.venv`)

```powershell
Test-Path .venv
```
Si dice `False`:
```powershell
python -m venv .venv
```
Si dice `True`, saltar este paso.

### Paso 5 — Instalar el proyecto y sus dependencias

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```
Tarda uno o dos minutos la primera vez. **Esperado:** termina con `Successfully installed ...`, sin errores en rojo.

### Paso 6 — Confirmar que el ejecutable `cloudcr` quedó instalado

```powershell
.\.venv\Scripts\cloudcr.exe --version
```
**Esperado:** `cloudcr-oracle-backup 0.1.0`

### Paso 7 — Evitar que los acentos se vean mal en esta consola

```powershell
$env:PYTHONUTF8="1"
```
Dura solo mientras esta ventana de PowerShell esté abierta.

### Paso 8 — Correr las pruebas automatizadas

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```
**Esperado:** `202 passed`.

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests
```
**Esperado:** `All checks passed!`

```powershell
.\.venv\Scripts\python.exe -m mypy src
```
**Esperado:** `Success: no issues found in 76 source files`

Si los tres salen bien, el código está sano. Seguimos a probarlo de verdad.

### Paso 9 — Ver que los comandos nuevos existen

```powershell
.\.venv\Scripts\cloudcr.exe estrategia --help
.\.venv\Scripts\cloudcr.exe tarea --help
```
**Esperado:** 11 comandos bajo `estrategia` (`crear`, `validar`, `mostrar`, `importar`, `editar`, `exportar`, `listar`, `activar`, `desactivar`, `eliminar`, `aplicar-recomendacion`) y 3 bajo `tarea` (`agregar`, `editar`, `eliminar`).

### Paso 10 — (Opcional pero recomendado) Confirmar que los datos de ejemplo existen en tu XE

```powershell
.\.venv\Scripts\cloudcr.exe estrategia validar --archivo config\estrategias\est001.yaml
```
- Si **no aparece** `ALC_002` ("ya no existe en el perfil actual") → los tablespaces de ejemplo (`VENTAS`, etc.) ya están creados en tu XE.
- Si **sí aparece** `ALC_002` → todavía no corriste `sql/demo/*.sql` (ver la sección 5 de este documento, más abajo). No es un error del código, solo falta ese paso.

### Paso 11 — Mostrar las 4 estrategias de ejemplo

```powershell
.\.venv\Scripts\cloudcr.exe estrategia mostrar --archivo config\estrategias\est001.yaml
.\.venv\Scripts\cloudcr.exe estrategia mostrar --archivo config\estrategias\est002.yaml
.\.venv\Scripts\cloudcr.exe estrategia mostrar --archivo config\estrategias\est003.yaml
.\.venv\Scripts\cloudcr.exe estrategia mostrar --archivo config\estrategias\est004.yaml
```
**Esperado:** cada una imprime código, nombre, prioridad, RPO/RTO, alcance y tareas, sin errores.

### Paso 12 — Validar cada una contra tu Oracle real

```powershell
.\.venv\Scripts\cloudcr.exe estrategia validar --archivo config\estrategias\est001.yaml
.\.venv\Scripts\cloudcr.exe estrategia validar --archivo config\estrategias\est002.yaml
.\.venv\Scripts\cloudcr.exe estrategia validar --archivo config\estrategias\est003.yaml
.\.venv\Scripts\cloudcr.exe estrategia validar --archivo config\estrategias\est004.yaml
```
**Esperado:** una tabla de hallazgos por cada una, y al final `Sin errores bloqueantes.` en las cuatro. Ver la sección 6 de este documento para saber qué advertencias son normales y cuáles no.

### Paso 13 — Confirmar que lo que necesita el repositorio falla "bien" (no con traceback)

```powershell
.\.venv\Scripts\cloudcr.exe estrategia listar --bd XE
```
**Esperado:**
```
Error: La conexión al repositorio todavía no está implementada.
Sugerencia: Este comando necesita 'repository/conexion.py' terminado.
```
Correcto — esa parte es de Josué y todavía no está lista. El mensaje claro (en vez de un traceback de Python) confirma que mi código maneja bien ese caso.

### Paso 14 — Agregar, editar y eliminar una tarea

```powershell
copy config\estrategias\est003.yaml est_prueba.yaml
.\.venv\Scripts\cloudcr.exe tarea agregar est_prueba.yaml T2 --tipo-respaldo ARCHIVELOG --modo-respaldo EN_LINEA --destino "C:\backups\XE" --frecuencia INTERVALO --intervalo-minutos 240
.\.venv\Scripts\cloudcr.exe estrategia mostrar --archivo est_prueba.yaml
```
**Esperado:** ahora aparecen `T1` y `T2`.

```powershell
.\.venv\Scripts\cloudcr.exe tarea eliminar est_prueba.yaml T2
.\.venv\Scripts\cloudcr.exe estrategia mostrar --archivo est_prueba.yaml
```
**Esperado:** solo queda `T1`.

```powershell
del est_prueba.yaml
```

### Paso 15 — Probar el asistente interactivo completo

```powershell
.\.venv\Scripts\cloudcr.exe estrategia crear
```
Va preguntando, uno por uno: nombre de la base de datos, código, nombre, descripción, prioridad, responsable, qué respaldar (flechas + espacio para marcar, Enter para confirmar), destino, retención, si usar un esquema predefinido (decir que sí la primera vez es más rápido), día/horas, y al final valida sola y pregunta dónde guardar el archivo. Cuando pregunte **"¿Intentar guardarla también en el repositorio?"** responder que **no** — igual queda guardada como YAML en la ruta indicada.

**Esperado:** termina sin errores y el archivo YAML indicado existe en disco.

### Paso 16 — Limpieza final antes del push

```powershell
git status
```
Revisar que no aparezca nada raro: ni `.venv/`, ni archivos de prueba sueltos (como `est_prueba.yaml` si se olvidó borrarlo), ni contraseñas.

## 4. Correr solo las pruebas de un módulo puntual (más rápido que todo el suite)

Útil si estás iterando sobre algo específico:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_validacion.py -v
.\.venv\Scripts\python.exe -m pytest tests/unit/test_asistente_estrategia.py -v
.\.venv\Scripts\python.exe -m pytest tests/unit/test_cmd_estrategia.py tests/unit/test_cmd_tarea.py -v
```

Todas las pruebas de mi parte corren **sin necesitar Oracle** (no usan el marcador `@pytest.mark.oracle`), así que `pytest -q` siempre debería dar verde aunque Oracle esté apagado.

## 5. Si querés instalar los datos de ejemplo (`VENTAS`, `FINANZAS`, etc.)

Solo si en el Paso 10 viste el `ALC_002`. Conectado como administrador de Oracle (`sqlplus / as sysdba`), en este orden, respondiendo los `ACCEPT PROMPT` con tus propios valores (PDB `XEPDB1`, un usuario como `CLOUDCR_DEMO`, una clave, y el directorio de datafiles de tu instalación):

```powershell
sqlplus "/ as sysdba" "@sql\demo\01_tablespaces_demo.sql"
```
Después, conectado como ese mismo usuario a `XEPDB1` (o usando `ALTER SESSION SET CONTAINER`/`CURRENT_SCHEMA` si preferís no levantar el listener todavía):
```powershell
sqlplus "/ as sysdba"
```
```sql
ALTER SESSION SET CONTAINER = XEPDB1;
ALTER SESSION SET CURRENT_SCHEMA = CLOUDCR_DEMO;
@sql\demo\02_datos_demo.sql
```
Y para generar actividad y archived logs reales:
```powershell
sqlplus "/ as sysdba" "@sql\demo\03_generar_actividad.sql"
```

## 6. Qué esperar al validar (no son errores de código)

El validador va a mostrar `ADVERTENCIA`/`RECOMENDACION`/`INFORMATIVA` en varias de las estrategias de ejemplo — son intencionales, demuestran que el motor funciona:

- `est001.yaml`: `MET_001` (no tiene tarea N0 propia — así la definió el profesor en clase).
- `est003.yaml`: `ALC_004`/`ALC_005` (es un alcance parcial a propósito, el "T4 Parcial" del ejemplo de clase).
- Cualquiera: `DST_004` si el destino de respaldo está en el mismo disco que los datafiles (es tu caso real en esta máquina).

Si alguna vez ves un **ERROR** (no advertencia) que no esperabas, ahí sí revisar — eso bloquea (`Bloqueantes: True` / código de salida 1).

## 7. Problemas comunes

| Síntoma | Causa | Solución |
|---|---|---|
| Tildes, flechas o líneas se ven mal (`Ã³`, cuadrados, etc.) | La consola no está en UTF-8 | `$env:PYTHONUTF8="1"` antes de correr `cloudcr` (Paso 7) |
| `cloudcr` no se reconoce | No usaste la ruta completa ni activaste el entorno | Usar `.\.venv\Scripts\cloudcr.exe` siempre, o `.\.venv\Scripts\Activate.ps1` primero |
| `ModuleNotFoundError: No module named 'cloudcr_backup'` | La instalación del Paso 5 no terminó bien | Repetir `.\.venv\Scripts\python.exe -m pip install -e ".[dev]"` |
| `Error: La conexión al repositorio todavía no está implementada` | Esperado — `repository/` es de Josué | No es un bug, ver sección 2 |
| `ALC_002` al validar `est001-004.yaml` | No corriste `sql/demo/*.sql` todavía | Ver sección 5, o ignorarlo si solo estás probando el código |
| `ORA-01034` / `ORA-12560` ("la instancia no está disponible") | Oracle XE está detenida | `Start-Service OracleServiceXE` (Paso 3, como administrador) |
| Al correr un `.sql` por un pipe de PowerShell (`echo ... \| sqlplus`), sale `ORA-00911: carácter no válido` en la primera línea | PowerShell agrega un BOM invisible al principio del texto que manda por el pipe | No uses pipes para mandarle respuestas a `sqlplus`; corré los scripts `ACCEPT`-interactivos escribiendo las respuestas a mano, o usá `cmd /c "sqlplus ... < archivo.txt"` con un archivo de texto plano en ASCII |
| El asistente (`estrategia crear`) no reacciona a las flechas o se ve raro | Estás corriendo en una terminal que no soporta control de cursor (por ejemplo, un pipe o una tarea automatizada) | Correrlo en una ventana de PowerShell o Windows Terminal normal, interactiva |

## 8. Checklist final antes de hacer push

- [ ] `pytest -q` → 202 passed
- [ ] `ruff check src tests` → All checks passed
- [ ] `mypy src` → Success, no issues
- [ ] `cloudcr estrategia validar --archivo config\estrategias\est001.yaml` corre sin traceback
- [ ] `cloudcr estrategia mostrar --archivo config\estrategias\est00X.yaml` corre bien para las 4 estrategias
- [ ] `cloudcr tarea agregar/editar/eliminar` funciona sobre una copia de prueba
- [ ] `cloudcr estrategia crear` completa los 9 pasos sin crashear y deja el YAML guardado
- [ ] `git status` no muestra nada raro (sin `.venv/`, sin credenciales, sin archivos de otros compañeros a medio hacer, sin `est_prueba.yaml` olvidado)
