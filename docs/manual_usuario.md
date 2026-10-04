# Manual de usuario — CloudCR Oracle Backup

Herramienta para definir, programar, ejecutar y vigilar estrategias de respaldo de bases de datos Oracle con RMAN. Este manual explica cómo instalarla en una máquina limpia, cómo configurarla y cómo usarla desde la **interfaz web** (la interfaz principal) y desde la **terminal** (`cloudcr`).

> Convenciones: los comandos son para **PowerShell** en Windows. `cloudcr` equivale a `.\.venv\Scripts\cloudcr.exe` si no activó el entorno virtual.

---

## 1. Qué hace el sistema

| Pieza | Qué hace | Dónde se ve |
|---|---|---|
| **Explorador** | Inspecciona la instancia (contenedores, tablespaces, datafiles, redo, control files) y emite observaciones (`ARCH_001`, `RED_001`, `RED_003`…). | Web `/instancias/<SID>` · `cloudcr explorar` |
| **Estrategias** | Qué se respalda, cómo (tipo y modo RMAN) y cuándo (programación, ventana, política de omisión), con validación de 31 reglas. | Web `/estrategias` · `cloudcr estrategia …` |
| **Agente** | Proceso que corre en el servidor: cada *tick* reclama las ejecuciones vencidas, las despacha al ejecutor de RMAN y evalúa las alertas. | `cloudcr agente ejecutar` · tarea programada de Windows |
| **Historial** | Cada ejecución (o no ejecución) con su hora programada, inicio real, fin, resultado y estado de las pruebas. | Web `/historial` · `cloudcr historial` |
| **Alertas** | 11 reglas que vigilan respaldos fallidos, no ejecutados, sin respaldo reciente, espacio, modo de archivado… Se abren, se notifican una sola vez y se resuelven solas. | Web `/alertas` · `cloudcr alertas` |
| **Estado** | Semáforo por estrategia, ejecuciones en curso, alertas vigentes y salud del agente. | Web `/estado` · `cloudcr estado` |

---

## 2. Instalación en una máquina limpia

### 2.1 Requisitos

| Requisito | Comprobación |
|---|---|
| Windows 10/11 o Windows Server con Oracle Database 19c/21c (XE sirve) | `Get-Service OracleService*` → `Running` |
| Listener activo | `lsnrctl status` |
| Python 3.11 o superior | `python --version` |
| Su usuario de Windows en el grupo local `ORA_DBA` | `Get-LocalGroupMember ORA_DBA` |

### 2.2 Pasos

```powershell
git clone https://github.com/AlejandroMirandaGomez/CloudCR-Oracle-Backup.git
cd CloudCR-Oracle-Backup
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\cloudcr.exe --version
```

Luego instale el repositorio de la herramienta (PDB `BKPCAT`, usuario `BKP_ADMIN`, 12 tablas y parámetros iniciales) siguiendo la sección «Instalar el repositorio» de `COMO_EJECUTAR.md`, o con `cloudcr repo instalar` si la PDB y el usuario ya existen.

Verifique todo con:

```powershell
cloudcr doctor
```

---

## 3. Configuración

La configuración se toma en este orden de precedencia: **opción de la línea de comandos → variable `CLOUDCR_*` → `cloudcr.yaml` → valor por defecto**.

### 3.1 Archivo `.env` (en la carpeta del proyecto)

Copie `.env.example` a `.env` y complete:

| Variable | Para qué | Ejemplo |
|---|---|---|
| `CLOUDCR_REPOSITORIO_DSN` | Conexión al repositorio | `localhost:1521/BKPCAT` |
| `CLOUDCR_REPOSITORIO_USUARIO` | Usuario del repositorio | `BKP_ADMIN` |
| `CLOUDCR_REPO_CLAVE` | Clave del repositorio | *(la suya; nunca se versiona)* |
| `CLOUDCR_WORK_DIR` | Carpeta de trabajo (scripts, ejecuciones, latido, logs) | vacío = `%LOCALAPPDATA%\cloudcr` |
| `CLOUDCR_DESTINO_DEFECTO` | Destino sugerido para respaldos | `C:\backups\XE` |
| `CLOUDCR_SMTP_CLAVE` | Clave de la cuenta de correo para las alertas (ver §8) | *(contraseña de aplicación)* |

`.env` está en `.gitignore`: **no lo suba nunca**.

### 3.2 `cloudcr.yaml` (opcional)

Mismos campos que las variables, sin el prefijo: `repositorio_dsn`, `repositorio_usuario`, `work_dir`, `destino_defecto`, `zona_horaria` (por defecto `America/Costa_Rica`). Se busca en `%USERPROFILE%\cloudcr.yaml` o donde indique `CLOUDCR_CONFIG`.

### 3.3 Parámetros del repositorio

Se ven con `cloudcr param listar` y se cambian con `cloudcr param set <clave> <valor>`. **El agente los relee en cada tick**: un cambio surte efecto sin reiniciarlo.

| Parámetro | Por defecto | Qué controla |
|---|---|---|
| `agente.tick_segundos` | 30 | Cada cuánto despierta el agente |
| `agente.gracia_omision_min` | 15 | Cuánto retraso se tolera antes de considerar perdida una ocurrencia |
| `agente.max_paralelo_host` | 1 *(no está en la semilla)* | Ejecuciones simultáneas en este servidor |
| `agente.horizonte_perdidas_horas` | 24 *(no está en la semilla)* | Cuánto mira hacia atrás el planificador al arrancar (ver §11) |
| `alertas.eval_minutos` | 5 | Cada cuánto se evalúan las alertas (además de al terminar cada ejecución) |
| `alertas.disco_uso_pct` | 85 | Umbral de `ESPACIO_INSUFICIENTE` |
| `alertas.recencia_horas.ALTA/MEDIA/BAJA` | 24 / 72 / 192 | Umbral de `SIN_RESPALDO_RECIENTE` por prioridad |
| `alertas.archivelogs_max` | 100 *(no está en la semilla)* | Umbral de `ARCHIVELOG_ACUMULADO` |
| `notificacion.canales` | `["consola"]` | Canales: `consola`, `email` |
| `notificacion.email.*` | ver §8 | Servidor, puerto, TLS, remitente, destinatarios, severidad mínima |

---

## 4. Flujo de trabajo en la interfaz web

```powershell
cloudcr web
```

Se abre el navegador en `http://127.0.0.1:8765/`. La barra superior tiene **Estado · Estrategias · Historial · Alertas · Retención · Recuperación · Instancias · Sistema**. Todo funciona con teclado, en tema claro u oscuro (según el sistema) y en pantallas angostas.

**Todo el circuito se puede probar desde la web**, sin abrir la terminal:

| Paso | Dónde |
|---|---|
| 1. Registrar la base y guardar su perfil | **Sistema → Bases de datos**: «Registrar» e «Inspeccionar y guardar perfil» |
| 2. Crear la estrategia | **Instancias → Crear estrategia de respaldo**, o **Estrategias → Importar YAML** (incluye los ejemplos EST001 a EST004) |
| 3. Validar contra la base real y aplicar recomendaciones | Detalle de la estrategia → «Validar contra la base real» → «Aplicar esta recomendación» (ARCH_002) |
| 4. Generar, revisar y aprobar el script | Detalle de la estrategia → «Generar los scripts RMAN» → «Script RMAN» de cada tarea → «Aprobar» |
| 5. Probar sin ejecutar y ejecutar | Pantalla del script → «Simular la ejecución» → «Ejecutar ahora» |
| 6. Seguir la ejecución y verificarla | **Historial** → detalle (se actualiza solo mientras corre) → «Verificar de nuevo» |
| 7. Automatizar | **Sistema → Agente**: «Iniciar» (o «Ejecutar un ciclo»), con o sin SIMULACIÓN |
| 8. Retención y recuperación | **Retención** (informe, consulta a RMAN, purga controlada) y **Recuperación** (puntos, diagnóstico, procedimientos) |

### 4.1 Instancias → crear una estrategia

1. **Instancias** → elija la instancia → se abre el explorador con las observaciones de la base.
2. **Crear estrategia de respaldo** → asistente de cinco pasos (general, qué, cómo y cuándo, destino y retención, revisar y guardar). Un ERROR del validador impide guardar; una tarea en modo consistente exige aceptar la caída del servicio.

### 4.2 Estrategias

`/estrategias` lista las estrategias del repositorio con su semáforo, si están activas, cuántas tareas tienen script aprobado y la próxima ejecución. El detalle de una estrategia muestra:

- RPO, RTO y frecuencia mínima que exige su prioridad.
- Alcance y retención.
- Por tarea: el tipo con **las dos etiquetas** (sistema y clase, p. ej. «Incremental nivel 0 (total+)»), el modo, la programación en palabras, el destino, el script RMAN vigente y **las próximas 5 ejecuciones**.
- Botones **Activar / Desactivar** (piden confirmación).
- **Validar contra la base real**: inspecciona la base en vivo (o usa el último perfil guardado si no responde) y muestra los hallazgos por severidad. Las recomendaciones aplicables (ARCH_002) tienen su botón: la estrategia sube de versión.
- **Generar los scripts RMAN**: un borrador por tarea; las tareas imposibles (por ejemplo, en línea con la base en NOARCHIVELOG) se informan sin bloquear las demás.
- **Exportar YAML** y, desde la lista, **Importar YAML** (pegado o de los ejemplos del proyecto; «Reemplazar si ya existe» sube la versión).
- **Editar estrategia** (`/estrategias/{bd}/{codigo}/editar`): muestra la definición completa en YAML (alcance, tareas, retención, estado). **Validar sin guardar** la revisa contra la base real sin tocar nada; **Guardar como versión N+1** la graba. El código de la estrategia no se puede cambiar.
- **Agregar tarea**: abre el mismo editor con una tarea de ejemplo ya agregada (código siguiente libre, completo, diario a las 02:00, destino por defecto) para que la ajuste y guarde.
- **Eliminar tarea** (en cada tarea, pide confirmación): crea una versión nueva sin ella. No se permite eliminar la única tarea ni una tarea que ya tiene ejecuciones registradas, porque esas ejecuciones son la evidencia de lo que se respaldó.
- Al editar, el script de una tarea queda **obsoleto** solo si cambió lo que se respalda (el alcance) o cómo se respalda (la tarea o su destino): hay que generar y aprobar uno nuevo. Cambiar solo los horarios no afecta el script aprobado.

### 4.2.1 Script RMAN de una tarea

Desde «Script RMAN» de cada tarea (`/estrategias/{bd}/{codigo}/scripts/{tarea}`):

- Estado (borrador, aprobado, rechazado, obsoleto), modo, **SHA-256** y si el archivo en disco sigue intacto.
- El contenido exacto, la tabla **configuración → cláusula RMAN** y la validación de la tarea.
- **Aprobar** (un respaldo CONSISTENTE exige marcar «Acepto la caída del servicio») y **Rechazar** con motivo.
- **Respaldo antes de una operación crítica** (enunciado §3): no necesita nada especial. Ejecute «Ejecutar ahora» sobre una tarea ya aprobada, o cree una estrategia con frecuencia «Una sola vez». En la terminal: `cloudcr ejecutar EST001 T1 --ahora`. Queda en el historial como cualquier otra ejecución.
- Con el script aprobado: **Simular la ejecución** (preflight y comando, sin RMAN) y **Ejecutar ahora** (corre en segundo plano; el enlace lleva al detalle del historial, que se actualiza solo).
- **Regenerar** y la lista de versiones.

> Un respaldo CONSISTENTE apaga la base, y con ella el repositorio `BKPCAT` si vive en la misma CDB: la web deja de responder unos minutos y vuelve sola. La evidencia queda primero en disco y en el buzón.

### 4.3 Estado

`/estado` se actualiza solo cada 30 segundos y muestra:

- Conteo de estrategias por color y alertas vigentes.
- Semáforo por estrategia con sus motivos (ver §6).
- Ejecuciones en curso o por iniciar.
- Alertas vigentes.
- Agente: equipo, último tick, si está vivo y si corre en modo **SIMULACIÓN**.

### 4.4 Historial

`/historial` tiene filtros por base, estrategia, resultado y rango de fechas (se aplican sin recargar y quedan en la dirección del navegador), paginación y exportación a **CSV, Markdown y HTML** con los mismos filtros. El número de la columna *Id* abre el detalle de la ejecución: script y versión, quién lo aprobó, log de RMAN (primeras y últimas líneas), piezas, verificaciones y la evidencia del pipeline cuando existe. Desde el detalle se puede **verificar de nuevo** el respaldo y **descargar la evidencia** de esa ejecución en HTML o Markdown (equivale a `cloudcr reporte evidencia`).

### 4.5 Alertas

`/alertas` filtra por estado (vigentes, abiertas, reconocidas, resueltas, todas) y severidad. Cada alerta muestra el mensaje y la **acción sugerida**. Acciones (con confirmación):

- **Reconocer**: «ya lo vi»; la alerta sigue vigente hasta que la condición desaparezca.
- **Resolver**: la cierra a mano; si la condición sigue, se vuelve a abrir en la próxima evaluación.
- **Evaluar ahora**: corre todas las reglas en el momento.

### 4.6 Retención y recuperación

- `/retencion`: por estrategia, la política (ventana o redundancia), las piezas vencidas y el script que se usaría. «Consultar a RMAN» corre `CROSSCHECK BACKUP` + `REPORT OBSOLETE`. El botón de purga **solo aparece** si la estrategia tiene `purga_automatica` activa, y pide confirmación.
- `/recuperacion`: puntos de recuperación (respaldos correctos con piezas), **Diagnosticar ahora** (`V$RECOVER_FILE`/`V$DATAFILE`) y el generador de procedimientos por escenario. El procedimiento se muestra y se guarda en la carpeta de trabajo; **nunca se ejecuta**.

### 4.7 Sistema

- **Agente**: **arranca solo al abrir la web** (con el pipeline real de RMAN) mientras la casilla «Iniciar el agente automáticamente al abrir la web» esté marcada; se puede desmarcar ahí mismo, o abrir con `.\iniciar.cmd -SinAgente`. También se puede iniciar a mano (real o SIMULACIÓN), ejecutar un solo ciclo, detenerlo, y ver latidos y mensajes recientes. No deja iniciar otro si ya hay un agente vivo (por ejemplo, uno abierto con `cloudcr agente ejecutar`). Al cerrar la web, el agente se detiene esperando las ejecuciones en curso.
- **Bases de datos**: instancias detectadas y bases registradas; registrar (con ambiente), inspeccionar y guardar el perfil, activar o desactivar.
- **Diagnóstico del entorno**: lo mismo que `cloudcr doctor`.
- **Modo de archivado**: el modo de cada base según su último perfil y el procedimiento para pasar a ARCHIVELOG. CloudCR **nunca** cambia el modo de archivado: la decisión y la ejecución son del administrador, porque el procedimiento apaga la base unos minutos.
- **Repositorio**: tablas y filas. «Instalar» solo se ofrece si el esquema **no** está instalado, porque instalar recrea las 12 tablas y borra sus datos. «Borrar todo el repositorio» (equivale a `cloudcr repo desinstalar`) exige escribir `BORRAR TODO`, se niega si hay respaldos en curso o el agente de la web está corriendo, y puede volver a instalarlo vacío. Los archivos de respaldo en disco no se tocan.
- **Parámetros globales**: editar, restablecer al valor inicial o agregar.

### 4.8 API JSON (uso sin pantalla)

Todo lo anterior tiene su equivalente JSON. Las escrituras (`POST`) solo se aceptan desde la propia interfaz o con la misma cabecera `Origin`.

| Método y ruta | Devuelve o hace |
|---|---|
| `GET /api/estado?bd=` | Semáforos, en curso, alertas, agentes |
| `GET /api/agente` | Latidos de los agentes |
| `GET /api/estrategias` · `GET /api/estrategias/{bd}/{codigo}?n=` | Lista y detalle con próximas ejecuciones |
| `GET /api/estrategias/{bd}/{codigo}/tareas/{tarea}/proximas?n=` | Próximas `n` ejecuciones de una tarea |
| `POST /api/estrategias/{bd}/{codigo}/activar` · `…/desactivar` | Cambia el estado |
| `GET /api/historial?bd=&estrategia=&estado=&desde=&hasta=&limite=&pagina=` | Filas (dominio) y la misma tabla que ve la CLI |
| `GET /api/historial/{id}` | Detalle de una ejecución |
| `GET /historial/exportar/{csv,md,html}?…` | Descarga |
| `GET /api/alertas?estado=&severidad=` | Alertas |
| `POST /api/alertas/{id}/reconocer` · `…/resolver` · `POST /api/alertas/evaluar` | Acciones |
| `GET /api/estrategias/{bd}/{codigo}/validar` · `POST …/recomendaciones/{codigo}/aplicar` | Validación en vivo y recomendación aplicada |
| `GET /api/estrategias/ejemplos` · `POST /api/estrategias/importar` · `GET /api/estrategias/{bd}/{codigo}/yaml` | Importar y exportar YAML |
| `PUT /api/estrategias/{bd}/{codigo}` · `POST …/editar/validar` · `DELETE …/tareas/{tarea}` | Editar (YAML), validar un borrador y eliminar una tarea |
| `GET /api/sistema/entorno` · `GET /api/sistema/repositorio` | Diagnóstico y estado del repositorio |
| `GET /api/sistema/parametros` · `PUT /api/sistema/parametros/{clave}` · `POST …/{clave}/restablecer` | Parámetros |
| `GET /api/sistema/bases` · `POST /api/sistema/bases` · `POST /api/sistema/bases/{nombre}/inspeccionar` | Registro y perfil |
| `GET /api/sistema/agente` · `POST /api/sistema/agente/{iniciar,ciclo,detener}` | Control del agente de la web |

Los scripts, ejecuciones, retención y recuperación tienen su propia API (§13.4).

Errores: `503` con sugerencia si el repositorio no está configurado o no responde; `404` si no existe; `409` si la acción no se permite; `422` si un filtro es inválido. La pantalla muestra el mismo mensaje en un panel, nunca una traza.

---

## 5. Flujo de trabajo en la terminal

| Comando | Qué hace |
|---|---|
| `cloudcr estado [--bd XE] [--json]` | Semáforo, ejecuciones en curso, alertas y agente |
| `cloudcr historial [--bd --estrategia --estado --desde --hasta --limite --pagina] [--salida tabla\|json\|csv\|md\|html] [--archivo]` | Historial |
| `cloudcr historial mostrar <id> [--json]` | Detalle de una ejecución |
| `cloudcr alertas [--estado vigentes\|todas\|ABIERTA\|RECONOCIDA\|RESUELTA] [--severidad]` | Lista |
| `cloudcr alertas reconocer <id>` · `resolver <id>` · `evaluar [--sin-notificar]` | Acciones |
| `cloudcr agente ejecutar [--una-vez] [--simulado]` · `cloudcr agente estado` | Agente |
| `cloudcr reporte historial --formato csv\|md\|html --archivo <ruta o carpeta>` | Exportación (E8) |
| `cloudcr reporte evidencia <id> [--formato md\|html]` | Evidencia de una ejecución |
| `cloudcr tarea proximas EST001 T1 [--bd XE] -n 10` | Próximas ejecuciones desde el repositorio |
| `cloudcr tarea proximas T1 --archivo config\estrategias\est001.yaml -n 10` | Próximas ejecuciones desde un YAML |

La tabla del historial en la terminal sale **del mismo modelo** que la de la web (`presentacion/historial.py`): mismas columnas, mismo orden, mismos textos.

---

## 6. Cómo leer el historial y el semáforo

### 6.1 Columnas del historial

`Fecha · BD · Estrategia · Tarea · Hora (programada) · ◆ · Tipo · Inicio (real) · Fin · Duración · Resultado · Pruebas`

| ◆ | Resultado | Significado |
|---|---|---|
| ● | Exitoso | RMAN terminó bien |
| ▲ | Con advertencias | Terminó, con avisos de RMAN conocidos |
| ✕ | Error / Bloqueada | Falló, o el preflight impidió iniciar RMAN |
| ○ | No ejecutada / Cancelada | Correspondía y no corrió (con el motivo en el detalle) |
| ◐ | En curso | RMAN está corriendo |
| ◌ | Programada | Reclamada, todavía sin iniciar |

El símbolo siempre va acompañado de texto: la información no depende solo del color ni del símbolo.

- **Tipo** muestra las dos etiquetas: el nombre del sistema y el término de clase.
- **Pruebas**: OK / Fallida / Pendiente (la verificación todavía no corrió) / No aplica.
- **Horas** en la zona horaria de la tarea, no en UTC.
- Si **Inicio** es más de `agente.gracia_omision_min` posterior a **Hora**, la fila se marca como *tardía* (+N min): es la prueba de que la ejecución se recuperó tarde.
- Las ejecuciones con mensaje **SIMULACION** vienen del agente en modo `--simulado`: no ejecutaron RMAN y **no son evidencia**.

### 6.2 Regla del semáforo

| Color | Cuándo |
|---|---|
| ✕ **Rojo** | Hay una alerta de severidad ALERTA vigente de la estrategia (abierta o reconocida), o la última ejecución de alguna tarea terminó con error, bloqueada o no se ejecutó |
| ▲ **Amarillo** | Hay una ADVERTENCIA vigente, o la última ejecución terminó con advertencias, o sus pruebas están pendientes o fallidas |
| ● **Verde** | Todo lo demás (incluye «sin ejecuciones todavía») |
| ○ **Sin datos** | Estrategia inactiva o sin ninguna tarea con script aprobado |

---

## 7. Alertas

| Código | Severidad | Se abre cuando | Se resuelve sola cuando |
|---|---|---|---|
| `BD_NOARCHIVELOG` | ADVERTENCIA | El último perfil de la base está en NOARCHIVELOG | Se inspecciona de nuevo con la base en ARCHIVELOG (`cloudcr db inspeccionar`) |
| `ESTRATEGIA_SIN_PROGRAMACION` | ADVERTENCIA | Estrategia activa sin tareas, o sin ninguna programación utilizable | Se agrega o completa la programación |
| `RESPALDO_NO_EJECUTADO` | ALERTA | La última ejecución de la tarea es NO_EJECUTADA, o hay ocurrencias vencidas sin reclamar (agente detenido) | Una ocurrencia posterior de la misma tarea termina bien |
| `EJECUCION_FALLIDA` / `EJECUCION_BLOQUEADA` | ALERTA | La última ejecución concluyente falló / quedó bloqueada | La siguiente termina EXITOSA con Pruebas OK (o No aplica) |
| `VERIFICACION_FALLIDA` | ALERTA | La última ejecución concluyente tiene Pruebas = Fallida | Idem |
| `ESPACIO_INSUFICIENTE` | ADVERTENCIA / ALERTA | Disco del destino sobre `alertas.disco_uso_pct` / libre menor que el último respaldo | Hay espacio otra vez |
| `SIN_RESPALDO_RECIENTE` | ALERTA | Pasaron más de `alertas.recencia_horas.<PRIORIDAD>` desde el último respaldo correcto (o desde que se aprobó el primer script, para no alertar el primer día) | Hay un respaldo correcto |
| `MODO_ARCHIVADO_CAMBIO` | ADVERTENCIA / ALERTA | El modo de archivado actual difiere del que tenía la base al generar el script (NOARCHIVELOG→ARCHIVELOG: regenerar; ARCHIVELOG→NOARCHIVELOG con script en línea o de archived logs: va a fallar) | Se regenera y aprueba el script |
| `RETENCION_VENCIDA` | RECOMENDACION | Hay piezas vencidas sin marcar obsoletas y la estrategia no tiene purga automática | Se purgan |
| `ARCHIVELOG_ACUMULADO` | ADVERTENCIA | Más de `alertas.archivelogs_max` archived logs sin respaldar | Se respaldan |
| `SCRIPT_ALTERADO`, `BASE_NO_REABIERTA` | ALERTA | Los informa el pipeline de ejecución | Solo a mano (son eventos) |

- **Una alerta por condición**: la clave de deduplicación es `CÓDIGO:BD/ESTRATEGIA/TAREA`. Mientras siga vigente (abierta **o reconocida**) solo se actualiza su mensaje; no se duplica ni se vuelve a notificar.
- **Notificación solo cuando la alerta es nueva**. Un fallo del correo se registra en `logs/cloudcr.log` y nunca detiene al agente.

---

## 8. Correo de alertas

1. Cree una **contraseña de aplicación** en su cuenta (Gmail la exige con verificación en dos pasos).
2. Póngala en `.env`: `CLOUDCR_SMTP_CLAVE=<contraseña>` (nunca en el repositorio ni en el chat).
3. Configure los parámetros:

```powershell
cloudcr param set notificacion.email.servidor smtp.gmail.com
cloudcr param set notificacion.email.puerto 587
cloudcr param set notificacion.email.tls true
cloudcr param set notificacion.email.remitente su.cuenta@gmail.com
cloudcr param set notificacion.email.destinatarios '["dba@ejemplo.com"]'
cloudcr param set notificacion.email.severidad_minima ALERTA
cloudcr param set notificacion.canales '["consola","email"]'
```

4. Compruebe la configuración con un correo de prueba, desde la terminal o desde la web:

| Terminal | Web |
|---|---|
| `cloudcr alertas probar-correo` | **Sistema → Notificaciones por correo**: «Enviar correo de prueba» (muestra además si el canal está activo, si la configuración está completa y si la contraseña está definida) |

Si falta algún parámetro o el servidor rechaza las credenciales, ambos explican qué revisar.

El asunto incluye el alcance de la tarea, por ejemplo: `[CloudCR][ALERTA] EJECUCION_FALLIDA XE EST001/T1 · VENTAS, FINANZAS, CONTROLFILE`.

---

## 9. El agente

### 9.1 Arrancarlo a mano

```powershell
cloudcr agente ejecutar
```

En cada tick (por defecto cada 30 s): escribe el latido → sincroniza el buzón del pipeline → reclama las ocurrencias vencidas → las despacha → evalúa alertas cada `alertas.eval_minutos` y siempre después de que termina una ejecución. Ctrl+C lo detiene **esperando** a que termine la ejecución en curso.

- `--una-vez`: un solo tick y termina (pruebas y demostración).
- `--simulado`: usa el ejecutor de prueba (no corre RMAN). Cada ejecución queda con mensaje `SIMULACION` en el historial y el agente se muestra como SIMULACIÓN en `/estado`. **Sin pipeline real y sin `--simulado`, el agente se niega a correr y explica por qué.**

### 9.2 Qué garantiza

- **Una ejecución por ocurrencia**: el reclamo usa la restricción única `(tarea, hora programada)` del repositorio; dos agentes contra el mismo repositorio nunca duplican.
- **Ocurrencias perdidas**: si el agente estuvo detenido, todas las ocurrencias perdidas menos la última quedan como NO_EJECUTADA con el motivo. La última se ejecuta si está dentro de la gracia; si no, según la política de omisión:

| Política | Ocurrencia perdida |
|---|---|
| `EJECUTAR_EN_VENTANA` | Se ejecuta tarde solo si ahora seguimos dentro de **la misma** ventana de respaldo de la ocurrencia; si no hay ventana o ya pasó, NO_EJECUTADA |
| `OMITIR` | NO_EJECUTADA |
| `EJECUTAR_SIEMPRE` | Se ejecuta tarde |

- **Caídas**: al arrancar, las ejecuciones propias que quedaron EN_CURSO pasan a FALLIDA («interrumpida»); si eran consistentes, se pide al pipeline que asegure la reapertura de la base. Las reclamadas que nadie inició pasan a NO_EJECUTADA.
- **Repositorio caído**: el tick falla, se registra en `logs\cloudcr.log` y se reintenta en el siguiente; el agente no muere.

### 9.3 Estado del agente

```powershell
cloudcr agente estado
```

Lee `<carpeta de trabajo>\agente\latido_<equipo>.json`. Un agente se da por **detenido** si su último latido tiene más de 3 ticks.

### 9.4 Tarea programada de Windows

```powershell
.\deploy\windows\registrar_tarea_agente.ps1 `
  -Ejecutable "C:\ruta\al\proyecto\.venv\Scripts\cloudcr.exe" `
  -Configuracion "C:\ruta\a\cloudcr.yaml" `
  -Usuario "EQUIPO\usuario_del_grupo_ORA_DBA"
```

Crea la tarea «CloudCR Agente de respaldos»: se inicia **al arrancar el sistema**, se reinicia sola si falla, no tiene límite de duración y corre con la cuenta indicada (que debe pertenecer a `ORA_DBA`). La contraseña se pide con `Get-Credential` y no se guarda en ningún archivo. Opciones: `-NombreTarea`, `-GrupoOracle`, `-MinutosEntreReinicios`, `-Simulado` (solo para demostraciones), `-WhatIf`.

Para iniciarla sin reiniciar: `Start-ScheduledTask -TaskName 'CloudCR Agente de respaldos'`.

---

## 10. Próximas ejecuciones

```powershell
cloudcr tarea proximas EST001 T1 --bd XE -n 10
```

Para `EST001/T1` devuelve las 13:00, 15:00, 18:00 y 21:00 de cada día (hora de Costa Rica). El validador agrega la regla informativa **PRG_007** con las próximas 5 ejecuciones de cada tarea.

Semántica de la programación:

- `DIARIA`, `SEMANAL`, `MENSUAL`: una regla por cada hora (así `13:00, 15:30` no genera `13:30`). La **hora de pared** se respeta aunque cambie el horario de verano: «13:00» es 13:00 local. Una hora que no existe por el cambio de horario se corre una hora; una hora repetida corre una sola vez.
- `INTERVALO`: se calcula aritméticamente desde la fecha de inicio (o desde el 1/1/2000 a medianoche) y **la ventana filtra** las ocurrencias. En horas fijas la ventana solo informa (`PRG_003`) y gobierna la política de omisión.
- `UNA_VEZ`: la fecha de inicio a la primera hora (o a medianoche si no hay hora).
- El intervalo de búsqueda es `(desde, hasta]`: dos ticks seguidos nunca devuelven la misma ocurrencia.

---

## 11. Limitaciones conocidas

| Limitación | Detalle |
|---|---|
| **`MENSUAL` usa el día del mes de `fecha_inicio`** | `PROGRAMACION` no tiene columna `dias_mes` (no se altera el DDL). Sin `fecha_inicio`, se usa el día 1. Un día 31 no ocurre en meses de 30 días. |
| **Sin `fecha_fin` ni `disparador`** | El DDL no las tiene. El motivo de una ejecución no realizada va en `EJECUCION.mensaje_rman`; la próxima ejecución se calcula al vuelo. |
| **Sin fecha de activación de la estrategia** | Al reactivar una estrategia después de mucho tiempo, el planificador mira hacia atrás como máximo `agente.horizonte_perdidas_horas` (24 h por defecto) para no generar miles de NO_EJECUTADA. |
| **`ARCHIVELOG_ACUMULADO` cuenta, no mide antigüedad** | El perfil solo trae la cantidad de archived logs sin respaldo, tomada en la última inspección. |
| **Ritmo de log switch (`RED_003`)** | Se mide con `V$LOG_HISTORY` de las últimas 24 h; con menos de 4 cambios se informa que no hay datos suficientes. Los perfiles guardados antes de esta versión no traen el dato. |
| **Pruebas «Pendiente»** | Solo queda así si `verificacion.automatica` está en `false`; en ese caso use `cloudcr verificar <id>` (CROSSCHECK + existencia + `VALIDATE BACKUPSET`). |
| **Horas en UTC** | El repositorio guarda horas en UTC (`SYS_EXTRACT_UTC(SYSTIMESTAMP)`); la web y la CLI las muestran en la zona de cada tarea. `perfil_bd.capturado_en` y `script_rman.creado_en` siguen usando el valor por defecto del DDL (hora del servidor); solo se comparan entre sí. |

---

## 12. Solución de problemas

| Síntoma | Causa | Solución |
|---|---|---|
| `Error: No hay un DSN configurado…` / web: «El repositorio no está disponible» (503) | Falta `.env` o está incompleto | §3.1 y `cloudcr doctor` |
| `ORA-12541` / `ORA-12514` | Listener detenido o PDB no registrada | `lsnrctl status`; `ALTER SYSTEM REGISTER;` |
| La ejecución queda BLOQUEADA | El preflight encontró un problema (script alterado, modo de archivado distinto, destino, validación) | `cloudcr historial mostrar <id>` muestra el motivo; `cloudcr ejecutar EST T1 --simular` lo revisa sin ejecutar |
| `cloudcr agente estado` dice que nunca corrió | La carpeta de trabajo del agente y la de la consulta son distintas | Use el mismo `CLOUDCR_WORK_DIR` (o el mismo `cloudcr.yaml`) en ambos |
| El semáforo queda amarillo con todo exitoso | Pruebas «Pendiente» | La verificación automática está desactivada: `cloudcr verificar <id>` |
| `DPY-2019` (thin/thick) | Se abrió el repositorio antes que una conexión SYSDBA local | El agente y `cloudcr web` ya inician el cliente thick primero; reporte el comando exacto si reaparece |
| Acentos o símbolos raros en la terminal | Consola sin UTF-8 | `$env:PYTHONUTF8 = "1"`; el texto del resultado siempre acompaña al símbolo |
| El correo no llega | Clave o parámetros SMTP | Revise `logs\cloudcr.log`; `cloudcr alertas evaluar` muestra los avisos de configuración |

---

## 13. Scripts RMAN, ejecución, retención y recuperación

Detalle técnico completo en `docs/transformacion_estrategia_rman.md`.

### 13.1 Del script aprobado a la ejecución

```powershell
cloudcr script generar EST001 --bd XE          # borrador con su SHA-256, a partir de la estrategia
cloudcr script ver EST001 T1                   # script + cuadro campo -> cláusula RMAN + validación
cloudcr script aprobar EST001 T1               # un respaldo CONSISTENTE exige --acepto-caida
cloudcr script rechazar EST001 T1 --motivo "falta el SPFILE"
cloudcr script listar EST001                   # versiones: BORRADOR, APROBADO, RECHAZADO, OBSOLETO
cloudcr ejecutar EST001 T1 --simular           # preflight y comando, sin ejecutar RMAN
cloudcr ejecutar EST001 T1 --ahora             # ejecuta ya; el agente hace lo mismo a la hora programada
cloudcr verificar 41                           # repite CROSSCHECK + existencia + VALIDATE
cloudcr historial mostrar 41                   # evidencia, log de RMAN, piezas y Pruebas
```

- La ejecución queda **BLOQUEADA**, sin tocar RMAN, si pasa cualquiera de estas cosas: el script en disco no
  coincide con el hash aprobado (alerta `SCRIPT_ALTERADO`), cambió el modo de archivado, el destino no es
  escribible o la validación tiene errores para la tarea.
- Cada ejecución deja `<carpeta de trabajo>\ejecuciones\<id>\` con `EST001.XE.RMAN`, `EST001.XE.LOG`,
  `verificacion.log` y `evidencia.json`.
- Resultado: **EXITOSA**, **CON_ADVERTENCIAS** o **FALLIDA**, cada uno con sus motivos.
  `Recovery Manager complete.` no basta para declarar éxito.
- **Pruebas** queda en OK solo si las piezas existen, `CROSSCHECK` las encuentra `AVAILABLE` y
  `VALIDATE BACKUPSET` las lee sin errores.
- Si el repositorio no responde al terminar (por ejemplo, `BKPCAT` apagada por un respaldo consistente), la
  evidencia queda en `buzon\` y el agente la sincroniza en el siguiente tick.

### 13.2 Retención

```powershell
cloudcr retencion informe XE           # obsoletos según la ventana o redundancia de cada estrategia; no borra
cloudcr retencion informe XE --rman    # además CROSSCHECK + REPORT OBSOLETE en RMAN
cloudcr retencion purgar XE EST004 --purgar   # solo con purga_automatica: true; borra solo piezas propias obsoletas
```

### 13.3 Recuperación (se genera, nunca se ejecuta)

```powershell
cloudcr recuperacion puntos XE         # respaldos correctos desde los que se puede recuperar
cloudcr recuperacion diagnostico XE    # V$RECOVER_FILE / V$DATAFILE: qué archivo falta o está dañado
cloudcr recuperacion plan XE datafile  # toma el archivo del diagnóstico sin que haya que escribirlo
cloudcr recuperacion plan XE punto-en-tiempo --hasta "2026-10-04 13:00"
```

Escenarios: `pdb`, `tablespace`, `datafile`, `controlfile`, `total-noarchivelog` y `punto-en-tiempo`. Si el
modo de archivado no permite un escenario, el comando lo explica en lugar de generar un script inválido. Los
scripts quedan en `recuperacion\<BD>\`.

### 13.4 API JSON

| Método y ruta | Qué hace |
|---|---|
| `GET /api/scripts/{bd}/{estrategia}` y `/{tarea}` | Versiones y detalle de los scripts |
| `POST /api/scripts/{bd}/{estrategia}/generar?tarea=T1` | Genera borradores |
| `POST /api/scripts/{bd}/{estrategia}/{tarea}/aprobar` | `{"acepto_caida": true, "aprobado_por": "juan"}` |
| `POST /api/scripts/{bd}/{estrategia}/{tarea}/rechazar` | `{"motivo": "…"}` |
| `GET /api/ejecuciones/simular/{bd}/{estrategia}/{tarea}` | Preflight sin ejecutar |
| `POST /api/ejecuciones` | `{"bd": "XE", "estrategia": "EST001", "tarea": "T1"}` → 202 y corre en segundo plano |
| `POST /api/ejecuciones/{id}/verificar` | Repite la verificación (202) |
| `GET /api/retencion/{bd}?rman=false` / `POST /api/retencion/{bd}/{estrategia}/purgar` | Informe y purga (`{"confirmar": true}`) |
| `GET /api/recuperacion/{bd}/puntos`, `/diagnostico`, `/plan/{escenario}?objetivo=&hasta=` | Recuperación |
