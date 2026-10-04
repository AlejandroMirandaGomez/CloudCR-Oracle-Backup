# Cómo ejecutar CloudCR Oracle Backup desde PowerShell

Guía paso a paso para cualquier equipo Windows con PowerShell (5.1 o 7) y Oracle Database 12.2 o superior.

Todo lo que hace la herramienta se puede usar **desde la terminal (`cloudcr`) y desde la web (`cloudcr web`)**: ambas llaman a la misma lógica. Para recorrer el circuito completo de un respaldo, ver la sección «El circuito de un respaldo».

En los comandos, lo que aparece entre `< >` se reemplaza por el valor de tu equipo:

| Marcador | Qué es | Cómo averiguarlo |
|---|---|---|
| `<CARPETA_PROYECTO>` | Carpeta donde está este proyecto | La ruta donde lo clonaste o descargaste |
| `<SID>` | Nombre de la instancia Oracle | `cloudcr descubrir` o `Get-Service OracleService*` (el SID es lo que sigue a `OracleService`) |
| `<PDB>` | Nombre de una base conectable | Aparece en el árbol que muestra `cloudcr explorar` |
| `<ORACLE_HOME>` | Carpeta de instalación de Oracle | Solo hace falta si no se detecta sola; `cloudcr descubrir` la muestra |

## Requisitos previos

| Requisito | Cómo comprobarlo |
|---|---|
| Python 3.11 o superior | `python --version` |
| Git (solo para clonar) | `git --version` |
| Oracle instalado y la instancia iniciada | `Get-Service OracleService*` debe mostrar `Running` |
| Tu usuario de Windows pertenece al grupo `ORA_DBA` | `whoami /groups \| Select-String ORA_DBA` (el usuario que instaló Oracle ya pertenece) |

## Inicio rápido (equipo nuevo)

Con los requisitos de arriba cumplidos, alcanza con tres comandos:

```powershell
git clone https://github.com/AlejandroMirandaGomez/CloudCR-Oracle-Backup.git
cd CloudCR-Oracle-Backup
.\iniciar.cmd
```

`iniciar.cmd` hace todo lo que falte y se puede volver a ejecutar sin riesgo: crea `.venv`, instala las dependencias (solo si cambió `pyproject.toml`), crea la PDB `BKPCAT` y el usuario `BKP_ADMIN` con los datos del archivo `.env` (solo si todavía no existen), instala las tablas del repositorio y abre la interfaz web. Cuando todo ya está listo, solo abre la web.

Opciones: `.\iniciar.cmd -Puerto <PUERTO>` para usar otro puerto, `.\iniciar.cmd -NoAbrir` para no abrir el navegador y `.\iniciar.cmd -SinAgente` para que el agente de respaldos no arranque junto con la web (por defecto arranca solo y ejecuta las tareas activas con script aprobado cuando les toca; se puede detener o desactivar en Sistema → Agente). Si el `.env` ya trae otra clave para `BKP_ADMIN`, el script deja el usuario con esa clave.

## Primera vez: instalación

**1. Obtener el proyecto** (si ya lo tenés, pasá al paso 2)

```powershell
git clone https://github.com/AlejandroMirandaGomez/CloudCR-Oracle-Backup.git
```

**2. Entrar a la carpeta del proyecto**

```powershell
cd <CARPETA_PROYECTO>
```

**3. Crear el entorno virtual** (solo la primera vez, si todavía no existe la carpeta `.venv` dentro del proyecto; si ya existe, pasá al paso 4)

```powershell
python -m venv .venv
```

**4. Instalar el programa y sus dependencias** (solo la primera vez, o cuando cambie `pyproject.toml`; necesita internet)

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Al terminar existe el ejecutable `.\.venv\Scripts\cloudcr.exe`.

## Ejecutar

Siempre desde `<CARPETA_PROYECTO>`. Hay dos formas; elegí una.

### Forma A: sin activar el entorno (la más simple)

```powershell
.\.venv\Scripts\cloudcr.exe
```

### Forma B: activando el entorno (después se escribe solo `cloudcr`)

```powershell
.\.venv\Scripts\Activate.ps1
```

El prompt pasa a mostrar `(.venv)`. A partir de ahí:

```powershell
cloudcr
```

Para salir del entorno:

```powershell
deactivate
```

Si `Activate.ps1` da un error de "ejecución de scripts deshabilitada", habilitalo solo para esa ventana de PowerShell y volvé a activar:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

## Qué hace cada comando

Los ejemplos usan la forma B (`cloudcr`). Con la forma A, reemplazá `cloudcr` por `.\.venv\Scripts\cloudcr.exe`.

**Explorar la instancia automáticamente** (busca las instancias del equipo; si hay una sola en ejecución la muestra, si hay varias pregunta cuál)

```powershell
cloudcr
```

**Ver qué instancias Oracle hay en el equipo**

```powershell
cloudcr descubrir
```

**Explorar una instancia concreta**

```powershell
cloudcr explorar <SID>
```

**Explorar una instancia cuyo ORACLE_HOME no se detecta solo**

```powershell
cloudcr explorar <SID> --oracle-home <ORACLE_HOME>
```

**Ver solo una PDB** (siempre se muestran también los archivos de la instancia: control files, redo logs, parámetros)

```powershell
cloudcr explorar --pdb <PDB>
```

**Ocultar PDB$SEED**

```powershell
cloudcr explorar --sin-seed
```

**Ver la ruta completa de cada archivo**

```powershell
cloudcr explorar --rutas-completas
```

**Exportar el árbol a un archivo** (HTML para abrir en el navegador, Markdown para documentos, JSON para datos). La carpeta `exportaciones` se crea sola dentro del proyecto y está excluida de git.

```powershell
cloudcr explorar --salida html --archivo exportaciones\instancia.html
```

```powershell
cloudcr explorar --salida md --archivo exportaciones\instancia.md
```

```powershell
cloudcr explorar --salida json --archivo exportaciones\instancia.json
```

Abrir el HTML exportado:

```powershell
Start-Process exportaciones\instancia.html
```

**Explorar una base remota** (usuario y contraseña; la contraseña se pide por teclado o se toma de la variable de entorno `CLOUDCR_ORACLE_CLAVE`)

```powershell
cloudcr explorar --dsn <HOST>:<PUERTO>/<SERVICIO> --usuario <USUARIO>
```

**Ver la ayuda y la versión**

```powershell
cloudcr --help
```

```powershell
cloudcr explorar --help
```

```powershell
cloudcr --version
```

## El circuito de un respaldo

Es la secuencia que pide el enunciado: **estrategia → programación → script RMAN → ejecución → resultado → evidencia**. Cada paso existe en la terminal y en la web. Reemplazá `XE` por el SID de tu instancia.

| # | Paso | Terminal | Web |
|---|---|---|---|
| 1 | Comprobar el entorno | `cloudcr doctor` | Sistema → Diagnóstico del entorno |
| 2 | Instalar el repositorio | `cloudcr repo instalar` · `cloudcr repo estado` | Sistema → Repositorio BKPCAT |
| 3 | Registrar la base y guardar su perfil | `cloudcr db agregar XE` · `cloudcr db inspeccionar XE` | Sistema → Bases de datos |
| 4 | Definir la estrategia (qué, cómo, cuándo, destino, retención) | `cloudcr estrategia crear` (asistente) o `cloudcr estrategia importar config\estrategias\est001.yaml --bd XE` | Instancias → «Crear estrategia de respaldo», o Estrategias → Importar |
| 5 | Validar | `cloudcr estrategia validar --bd XE --codigo EST001` | Detalle de la estrategia → Validar |
| 6 | Generar el script RMAN | `cloudcr script generar EST001 --bd XE` · `cloudcr script ver EST001 T1 --bd XE` | Pantalla «Script RMAN» de la tarea |
| 7 | Aprobar el script (hash SHA-256) | `cloudcr script aprobar EST001 T1 --bd XE` (un respaldo `CONSISTENTE` exige `--acepto-caida`) | «Aprobar» en la misma pantalla |
| 8 | Activar la estrategia | `cloudcr estrategia activar EST001 --bd XE` | Detalle de la estrategia → Activar |
| 9 | Probar sin ejecutar | `cloudcr ejecutar EST001 T1 --bd XE --simular` | «Simular la ejecución» |
| 10 | Ejecutar ahora | `cloudcr ejecutar EST001 T1 --bd XE --ahora` | «Ejecutar ahora» |
| 11 | Dejar que el agente ejecute por horario | `cloudcr agente ejecutar` | Sistema → Agente → Iniciar |
| 12 | Ver el resultado y la evidencia | `cloudcr historial --bd XE` · `cloudcr historial mostrar <ID>` | Historial → detalle de la ejecución |
| 13 | Recomendaciones del validador | `cloudcr estrategia aplicar-recomendacion EST001 ARCH_002 --bd XE` | Detalle de la estrategia → aplicar recomendación |
| 14 | Retención (informa; borrar es decisión del administrador) | `cloudcr retencion informe XE` | Retención |
| 15 | Recuperación (genera el procedimiento, nunca lo ejecuta) | `cloudcr recuperacion puntos XE` · `cloudcr recuperacion plan XE tablespace` | Recuperación |

Otras pantallas y comandos de consulta:

| Qué | Terminal | Web |
|---|---|---|
| Criterios de prioridad, esquemas y vocabulario del curso frente a RMAN | (mostrados en `cloudcr estrategia mostrar`) | Criterios |
| Evidencias E1 a E10 y cuáles están capturadas | `cloudcr evidencias` | Evidencias |
| Observaciones de redo logs y archivado de cada base | `cloudcr estado` | Estado → «Redo logs y archivado» |
| Correo de prueba para las alertas | `cloudcr alertas probar-correo` | Sistema → Notificaciones por correo |

El paso a ARCHIVELOG **no lo ejecuta la herramienta**: Sistema → Modo de archivado muestra el procedimiento (`sql\archivelog\activar_archivelog.sql`) para que lo corra el administrador, con un respaldo antes y otro después.

## Agente, historial, alertas y estado

Guía completa en `docs/manual_usuario.md`. Resumen:

**Estado general** (semáforo por estrategia, ejecuciones en curso, alertas vigentes, agente)

```powershell
cloudcr estado
```

```powershell
cloudcr estado --bd XE --json
```

**Historial** (filtros opcionales; horas en la zona de cada tarea)

```powershell
cloudcr historial --bd XE --estrategia EST001 --estado FALLIDA --desde 2026-10-01 --hasta 2026-10-04
```

```powershell
cloudcr historial mostrar <ID>
```

**Exportar el historial** (CSV para Excel, Markdown, o HTML autocontenido para entregar como evidencia)

```powershell
cloudcr reporte historial --formato html --archivo exportaciones
```

```powershell
cloudcr reporte evidencia <ID> --formato md --archivo exportaciones
```

**Alertas**

```powershell
cloudcr alertas
```

```powershell
cloudcr alertas reconocer <ID>
```

```powershell
cloudcr alertas evaluar
```

**Próximas ejecuciones de una tarea**

```powershell
cloudcr tarea proximas EST001 T1 --bd XE -n 10
```

**Agente** (reclama las ejecuciones vencidas y las despacha al pipeline real de RMAN; `--simulado` ensaya sin ejecutar RMAN y rotula cada ejecución como SIMULACION)

```powershell
cloudcr agente ejecutar
```

```powershell
cloudcr agente ejecutar --una-vez
```

El servidor web (`cloudcr web`) arranca su propio agente. No corras además `cloudcr agente ejecutar` salvo que sepas lo que haces: no se duplican ejecuciones, pero habría dos agentes vivos. Se desactiva con `.\iniciar.cmd -SinAgente` o en Sistema → Agente.

```powershell
cloudcr agente estado
```

**Agente como tarea programada de Windows** (al iniciar el sistema, con reinicio automático; pide la contraseña de la cuenta con `Get-Credential`)

```powershell
.\deploy\windows\registrar_tarea_agente.ps1 -Ejecutable "$PWD\.venv\Scripts\cloudcr.exe" -Configuracion "$env:USERPROFILE\cloudcr.yaml" -Usuario "$env:COMPUTERNAME\$env:USERNAME"
```

## Interfaz web

Muestra lo mismo que `cloudcr explorar`, pero en el navegador: resumen de la instancia, árbol plegable, filtros, búsqueda, observaciones con "Ir al nodo" y botones para exportar.

**Abrir la interfaz** (abre el navegador automáticamente)

```powershell
cloudcr web
```

La terminal muestra la dirección (por defecto `http://127.0.0.1:8765/`; si el puerto está ocupado usa el siguiente libre). La interfaz funciona mientras esa ventana de PowerShell siga abierta; para detenerla, presionar **Ctrl+C**.

**Opciones**

| Opción | Para qué |
|---|---|
| `--puerto <PUERTO>` | Usar otro puerto |
| `--no-abrir` | No abrir el navegador automáticamente |
| `--cache <SEGUNDOS>` | Cuánto tiempo se reutiliza una inspección antes de volver a consultar la base (por defecto 60). El botón "Actualizar" siempre vuelve a consultar |
| `--host <INTERFAZ>` | Escuchar en otra interfaz de red (por ejemplo `0.0.0.0` para permitir el acceso desde otros equipos) |
| `--token <TOKEN>` | Token de acceso para el uso desde otros equipos |

**Uso desde otro equipo** (solo en redes de confianza: la interfaz se conecta a Oracle como SYSDBA)

```powershell
cloudcr web --host 0.0.0.0 --no-abrir
```

La terminal muestra una dirección con `?token=...`. Esa dirección es la que se abre desde el otro equipo, reemplazando `127.0.0.1` por la IP o el nombre de este equipo. Sin el token, el acceso se rechaza.

**Qué se puede hacer en la pantalla**

- Cambiar de instancia con las pastillas de arriba (si hay varias).
- Filtrar por contenedor, ocultar `PDB$SEED` o ver rutas completas: el árbol se actualiza sin recargar la página, y la dirección del navegador guarda los filtros.
- Buscar un archivo, tablespace o contenedor por nombre.
- "Expandir todo" / "Contraer todo".
- En el panel de observaciones, "Ir al nodo" despliega y resalta el elemento del árbol al que se refiere.
- Exportar a JSON, Markdown o HTML con los filtros aplicados.
- Crear una estrategia de respaldo con el botón **Crear estrategia de respaldo** (ver la sección siguiente).

### Crear una estrategia de respaldo desde la web

El botón **Crear estrategia de respaldo** del explorador abre un asistente de cinco pasos sobre la instancia que se está viendo:

1. **General**: código (se sugiere el siguiente libre), nombre, descripción, responsable y prioridad.
2. **Qué respaldar**: el mismo árbol del explorador, con datos reales de la instancia y casillas para marcar la base completa, una PDB, tablespaces, datafiles, control files, SPFILE o archived logs. Al marcar un elemento quedan incluidos los que contiene (la base completa incluye también control files y SPFILE; los archived logs se eligen aparte), y cada objeto marcado lleva su propia prioridad.
3. **Cómo y cuándo**: un esquema predefinido (se sugiere uno según la prioridad y el modo de archivado) o tareas definidas a mano, con frecuencia, horas, días, intervalo, ventana de respaldo, política de omisión y zona horaria.
4. **Destino y retención**: se escribe la ruta o se elige con el explorador de carpetas de este equipo (con opción de crear una carpeta nueva), y se define la retención.
5. **Revisar y guardar**: se valida la estrategia contra la instancia real, se muestran los hallazgos por severidad y la vista previa en YAML. Un ERROR impide guardar. Si alguna tarea se ejecuta en modo consistente (apaga la base) hay que aceptar la caída del servicio.

La estrategia se guarda siempre como YAML en `<carpeta de trabajo>\estrategias\<SID>\<CODIGO>.yaml` (por defecto `%LOCALAPPDATA%\cloudcr`) y, si el repositorio está disponible, también en él. Ese archivo se puede abrir con `cloudcr estrategia mostrar --archivo <ruta>`.

Los mismos pasos están disponibles como endpoints JSON, para usarlos sin la pantalla:

| Método y ruta | Para qué |
|---|---|
| `GET /api/instancias/<SID>/estrategias/catalogo` | Prioridades, esquemas, tipos de respaldo, frecuencias y valores sugeridos |
| `POST /api/instancias/<SID>/estrategias/validar` | Valida una estrategia y devuelve los hallazgos y el YAML, sin guardar |
| `POST /api/instancias/<SID>/estrategias` | Valida y guarda la estrategia |
| `GET /api/carpetas?ruta=<RUTA>` | Lista las subcarpetas de una ruta de este equipo (sin `ruta`, las unidades) |
| `POST /api/carpetas` | Crea una carpeta (`{"padre": "...", "nombre": "..."}`) |

Las escrituras rechazan las solicitudes que no vengan de la propia interfaz (cabeceras `Origin` y `Sec-Fetch-Site`).

Por seguridad, la web solo acepta un `ORACLE_HOME` detectado en el equipo. Para usar otro, hay que usar la terminal: `cloudcr explorar <SID> --oracle-home <ORACLE_HOME>`. Si en el equipo hay instancias con distintos `ORACLE_HOME`, cada `cloudcr web` explora las de un solo `ORACLE_HOME`; para las otras, abrir otro `cloudcr web` con otro `--puerto`.

### Estado, estrategias, historial y alertas

La barra superior de la interfaz tiene **Estado · Estrategias · Historial · Alertas · Retención · Recuperación · Criterios · Evidencias · Instancias · Sistema**:

| Pantalla | Qué muestra | API JSON equivalente |
|---|---|---|
| `/estado` | Semáforo por estrategia, ejecuciones en curso, alertas vigentes y agente (se actualiza cada 30 s) | `GET /api/estado`, `GET /api/agente` |
| `/estrategias` y `/estrategias/<BD>/<CÓDIGO>` | Estrategias registradas; detalle con próximas ejecuciones por tarea, retención y vocabulario de clase; botones Activar/Desactivar | `GET /api/estrategias`, `GET /api/estrategias/<BD>/<CÓDIGO>`, `GET …/tareas/<TAREA>/proximas?n=`, `POST …/activar`, `POST …/desactivar` |
| `/historial` y `/historial/<ID>` | Historial con filtros, paginación y exportación (CSV, MD, HTML); detalle de una ejecución | `GET /api/historial`, `GET /api/historial/<ID>`, `GET /historial/exportar/<formato>` |
| `/alertas` | Alertas con filtros por estado y severidad; Reconocer, Resolver, Evaluar ahora | `GET /api/alertas`, `POST /api/alertas/<ID>/reconocer`, `POST /api/alertas/<ID>/resolver`, `POST /api/alertas/evaluar` |
| `/criterios` | Prioridades (RPO, RTO, recencia), esquemas predefinidos y vocabulario del curso frente a RMAN | — |
| `/evidencias` | Las 10 evidencias del proyecto, su estado y descarga de cada archivo | `GET /api/evidencias` |
| `/sistema` | Diagnóstico, repositorio, bases, parámetros, agente, modo de archivado y correo de prueba | — |

Si el repositorio no está configurado o no responde, las pantallas muestran un panel con la sugerencia y la API responde `503` con el mismo mensaje.

## Instalar el repositorio (PDB BKPCAT)

El repositorio guarda estrategias, scripts RMAN, ejecuciones y alertas en una PDB propia (`BKPCAT`) dentro de la misma XE, con su propio usuario (`BKP_ADMIN`). Se crea una sola vez por instalación de Oracle, conectado como `SYSDBA` con `sqlplus`.

**1. Crear la PDB** (pide el nombre de la PDB, un usuario administrador temporal y su clave)

```powershell
sqlplus / as sysdba @sql\setup\01_crear_pdb_bkpcat.sql
```

**2. Crear el usuario del repositorio dentro de esa PDB** (pide el nombre de la PDB, el usuario del repositorio, su clave y la cuota)

```powershell
sqlplus / as sysdba @sql\setup\02_crear_usuario_repositorio.sql
```

**3. Crear las 12 tablas**, conectado ya como el usuario del repositorio en la PDB (reemplazando `<PDB>` y `<USUARIO>`)

```powershell
sqlplus <USUARIO>/<CLAVE>@localhost:1521/<PDB> @sql\setup\03_esquema_bkp_admin.sql
```

Este script es idempotente: si las tablas ya existen las elimina primero, así que se puede ejecutar de nuevo sin dejar el esquema a medias.

**4. Cargar los parámetros iniciales** (mismo usuario y conexión que el paso 3)

```powershell
sqlplus <USUARIO>/<CLAVE>@localhost:1521/<PDB> @sql\setup\04_parametros_iniciales.sql
```

**5. (Opcional) Usuario común de solo lectura para inspección sin SYSDBA**

```powershell
sqlplus / as sysdba @sql\setup\05_usuario_monitor.sql
```

**6. Configurar las credenciales del repositorio**

Copiar `.env.example` a `.env` (o exportar las variables en la sesión de PowerShell) y completar al menos `CLOUDCR_REPO_CLAVE` con la clave del usuario del repositorio. Esta clave **nunca** va en `cloudcr.yaml` ni en el código.

> **Atención:** en este repositorio el archivo `.env` está versionado en git (se compartió como configuración de desarrollo del equipo), así que `.gitignore` no lo protege. **No escribas en él contraseñas personales**, como la de la cuenta de correo (`CLOUDCR_SMTP_CLAVE`), sin antes dejar de rastrearlo (`git rm --cached .env`) o sin exportarlas solo en la sesión de PowerShell.

## Pruebas

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Corre las pruebas que no necesitan Oracle (la gran mayoría). Además:

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m mypy src
```

> **Cuidado con las pruebas marcadas `oracle`** (`pytest -m oracle`). Instalan el esquema en el repositorio y lo **desinstalan al terminar**: si se corren contra el repositorio real, se pierden estrategias, ejecuciones y evidencias. Solo se deben correr contra un repositorio de pruebas.

## Problemas comunes

| Síntoma | Causa | Solución |
|---|---|---|
| `python` no se reconoce | Python no está en el PATH | Instalar Python 3.11+ marcando "Add to PATH", o usar `py -3 -m venv .venv` |
| `No se encontró ninguna instancia Oracle` | No hay Oracle en el equipo o no se detectó | Revisar `Get-Service OracleService*`; indicar la instancia a mano: `cloudcr explorar <SID> --oracle-home <ORACLE_HOME>` |
| `ORA-01031` / "no tiene privilegios de administrador" | Tu usuario no está en `ORA_DBA` | Agregarlo (Administración de equipos → Usuarios y grupos locales → Grupos → ORA_DBA), cerrar sesión y volver a entrar |
| `ORA-01034` / `ORA-12560` / "la instancia no está disponible" | La instancia está detenida | `Start-Service OracleService<SID>` (PowerShell como administrador) |
| El árbol se corta o se ve apretado | La ventana es angosta | Agrandar la ventana o usar Windows Terminal; también se puede exportar a HTML |
| Tildes o líneas del árbol se ven mal | Consola antigua con otra página de códigos | Usar Windows Terminal, o ejecutar `chcp 65001` antes |
| `cloudcr` no se reconoce | No se activó el entorno | Usar `.\.venv\Scripts\cloudcr.exe` o activar con `.\.venv\Scripts\Activate.ps1` |
| `python -m venv .venv` muestra `Unable to copy ... python.exe` | Hay un `cloudcr` (por ejemplo `cloudcr web`) abierto que está usando el entorno | Cerrarlo (Ctrl+C en su ventana). Si `.venv` ya existía, no hace falta volver a crearlo |
| `ModuleNotFoundError: No module named 'cloudcr_backup'` | El programa no quedó instalado en el entorno (instalación interrumpida o entorno recreado) | Cerrar cualquier `cloudcr` abierto y repetir el paso 4: `.\.venv\Scripts\python.exe -m pip install -e ".[dev]"` |
| `cloudcr web` dice que no hay puertos libres | Los puertos siguientes al indicado están ocupados | `cloudcr web --puerto <PUERTO>` con otro número |
| El navegador muestra "Acceso denegado: token inválido o ausente" | Se abrió desde otro equipo sin el token | Usar la dirección completa con `?token=...` que muestra la terminal |
| El navegador muestra "Host no permitido" | Se entró con un nombre distinto de `127.0.0.1`/`localhost` en modo local | Usar `http://127.0.0.1:<PUERTO>/`, o iniciar con `--host 0.0.0.0` para el acceso desde la red |
