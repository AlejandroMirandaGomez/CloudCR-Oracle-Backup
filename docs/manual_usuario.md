# Manual de usuario — CloudCR Oracle Backup

Herramienta para definir, programar, ejecutar y vigilar estrategias de respaldo de bases de datos Oracle con RMAN. Este manual explica cómo instalarla en una máquina limpia, cómo configurarla y cómo usarla desde la **interfaz web** (la interfaz principal) y desde la **terminal** (`cloudcr`).

> Convenciones: los comandos son para **PowerShell** en Windows. `cloudcr` equivale a `.\.venv\Scripts\cloudcr.exe` si no activó el entorno virtual. Los marcadores `[PENDIENTE: …]` indican capturas o pasos que todavía no se pudieron producir con una ejecución real; no se reemplazan con imágenes inventadas.

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

Luego instale el repositorio de la herramienta (PDB `BKPCAT`, usuario `BKP_ADMIN`, 12 tablas y parámetros iniciales) siguiendo `docs/guia_prueba_completa.md` §3, o con `cloudcr repo instalar` si la PDB y el usuario ya existen.

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

Se abre el navegador en `http://127.0.0.1:8765/`. La barra superior tiene **Estado · Estrategias · Historial · Alertas · Instancias**. Todo funciona con teclado, en tema claro u oscuro (según el sistema) y en pantallas angostas.

### 4.1 Instancias → crear una estrategia

1. **Instancias** → elija la instancia → se abre el explorador con las observaciones de la base.
2. **Crear estrategia de respaldo** → asistente de cinco pasos (general, qué, cómo y cuándo, destino y retención, revisar y guardar). Un ERROR del validador impide guardar; una tarea en modo consistente exige aceptar la caída del servicio.

`[PENDIENTE: captura real del explorador y del asistente sobre la XE]`

### 4.2 Estrategias

`/estrategias` lista las estrategias del repositorio con su semáforo, si están activas, cuántas tareas tienen script aprobado y la próxima ejecución. El detalle de una estrategia muestra:

- RPO, RTO y frecuencia mínima que exige su prioridad.
- Alcance y retención.
- Por tarea: el tipo con **las dos etiquetas** (sistema y clase, p. ej. «Incremental nivel 0 (total+)»), el modo, la programación en palabras, el destino, el script RMAN vigente y **las próximas 5 ejecuciones**.
- Botones **Activar / Desactivar** (piden confirmación).

`[PENDIENTE: captura real de /estrategias y del detalle de EST001]`

### 4.3 Estado

`/estado` se actualiza solo cada 30 segundos y muestra:

- Conteo de estrategias por color y alertas vigentes.
- Semáforo por estrategia con sus motivos (ver §6).
- Ejecuciones en curso o por iniciar.
- Alertas vigentes.
- Agente: equipo, último tick, si está vivo y si corre en modo **SIMULACIÓN**.

`[PENDIENTE: captura real de /estado con el agente corriendo]`

### 4.4 Historial

`/historial` tiene filtros por base, estrategia, resultado y rango de fechas (se aplican sin recargar y quedan en la dirección del navegador), paginación y exportación a **CSV, Markdown y HTML** con los mismos filtros. El número de la columna *Id* abre el detalle de la ejecución: script y versión, quién lo aprobó, log de RMAN (primeras y últimas líneas), piezas, verificaciones y la evidencia del pipeline cuando existe.

`[PENDIENTE: captura real de /historial con ejecuciones del agente]`

### 4.5 Alertas

`/alertas` filtra por estado (vigentes, abiertas, reconocidas, resueltas, todas) y severidad. Cada alerta muestra el mensaje y la **acción sugerida**. Acciones (con confirmación):

- **Reconocer**: «ya lo vi»; la alerta sigue vigente hasta que la condición desaparezca.
- **Resolver**: la cierra a mano; si la condición sigue, se vuelve a abrir en la próxima evaluación.
- **Evaluar ahora**: corre todas las reglas en el momento.

`[PENDIENTE: captura real de /alertas]`

### 4.6 API JSON (uso sin pantalla)

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

El asunto incluye el alcance de la tarea, por ejemplo: `[CloudCR][ALERTA] EJECUCION_FALLIDA XE EST001/T1 · VENTAS, FINANZAS, CONTROLFILE`.

`[PENDIENTE: E7 — correo real recibido; requiere la cuenta SMTP del usuario]`

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
| **Pruebas «Pendiente»** | La verificación de respaldos (`RESTORE VALIDATE`) es del pipeline de ejecución; mientras no la llene, el semáforo queda en amarillo. |
| **Horas en UTC** | El repositorio guarda horas en UTC (`SYS_EXTRACT_UTC(SYSTIMESTAMP)`); la web y la CLI las muestran en la zona de cada tarea. `perfil_bd.capturado_en` y `script_rman.creado_en` siguen usando el valor por defecto del DDL (hora del servidor); solo se comparan entre sí. |

---

## 12. Solución de problemas

| Síntoma | Causa | Solución |
|---|---|---|
| `Error: No hay un DSN configurado…` / web: «El repositorio no está disponible» (503) | Falta `.env` o está incompleto | §3.1 y `cloudcr doctor` |
| `ORA-12541` / `ORA-12514` | Listener detenido o PDB no registrada | `lsnrctl status`; `ALTER SYSTEM REGISTER;` |
| `El agente no puede ejecutar respaldos reales: todavía no existe el pipeline…` | El módulo de ejecución RMAN no está instalado | Use `--simulado` para probar el agente (queda rotulado) |
| `cloudcr agente estado` dice que nunca corrió | La carpeta de trabajo del agente y la de la consulta son distintas | Use el mismo `CLOUDCR_WORK_DIR` (o el mismo `cloudcr.yaml`) en ambos |
| El semáforo queda amarillo con todo exitoso | Pruebas «Pendiente» | Esperado hasta que exista la verificación |
| `DPY-2019` (thin/thick) | Se abrió el repositorio antes que una conexión SYSDBA local | El agente y `cloudcr web` ya inician el cliente thick primero; reporte el comando exacto si reaparece |
| Acentos o símbolos raros en la terminal | Consola sin UTF-8 | `$env:PYTHONUTF8 = "1"`; el texto del resultado siempre acompaña al símbolo |
| El correo no llega | Clave o parámetros SMTP | Revise `logs\cloudcr.log`; `cloudcr alertas evaluar` muestra los avisos de configuración |
