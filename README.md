# CloudCR-Oracle-Backup

Sistema de Gestión de Estrategias de Respaldo de Bases de Datos Oracle con RMAN (Curso EIF402 Administración de Bases de Datos, UNA, II ciclo 2026).

Una estrategia se define por **qué respaldar** (alcance y prioridad), **cómo** (completo, incremental nivel 0, nivel 1 diferencial o acumulativo), **cuándo** (frecuencia, días, horas, ventana) y **por cuánto tiempo conservarlo** (retención). La herramienta valida la estrategia, genera y aprueba el script RMAN, lo ejecuta de forma automática, verifica el respaldo y guarda la evidencia de cada ejecución. RMAN solo ejecuta el script aprobado: la estrategia es la decisión.

```
Estrategia → programación → script RMAN → ejecución → resultado → evidencia
```

Todo se usa desde la **terminal** (`cloudcr`) y desde la **web** (`cloudcr web`), con las mismas funciones.

## Qué incluye

- **Explorador de la instancia**: control files, redo logs, SPFILE, archived logs, contenedores, tablespaces y datafiles, con observaciones (NOARCHIVELOG, redo sin multiplexar, ritmo de log switch, control files en el mismo directorio, etc.). Exporta a JSON, Markdown y HTML.
- **Repositorio** en una PDB propia (`BKPCAT`, esquema `BKP_ADMIN`, 12 tablas).
- **Estrategias** con alcance y prioridad por objeto, varias tareas, versionado, retención e importación/exportación YAML. Cinco esquemas predefinidos y un asistente (terminal y web).
- **Validación** con cuatro severidades (Error, Advertencia, Recomendación, Informativa) y 35 reglas.
- **Scripts RMAN** generados desde la estrategia, aprobados con hash SHA-256 y versionados.
- **Ejecución** con preflight, clasificación Exitosa / Con advertencias / Fallida cruzando el log con la vista de RMAN, y evidencia en disco antes de tocar el repositorio.
- **Verificación** posterior (`CROSSCHECK` y `VALIDATE`) que llena la columna Pruebas del historial.
- **Agente** que dispara las tareas por horario, registra las no ejecutadas y se recupera de caídas.
- **Alertas** (11 reglas) con deduplicación, resolución automática y aviso por consola y correo.
- **Historial y reportes**: semáforo por estrategia, historial con exportación a CSV, Markdown y HTML.
- **Retención**: informe de respaldos obsoletos y purga solo con confirmación explícita.
- **Recuperación**: puntos de recuperación, diagnóstico con `V$RECOVER_FILE` y procedimientos por escenario. Se generan, nunca se ejecutan.

La herramienta **recomienda, no impone**: nunca cambia el modo de archivado, nunca ejecuta `CONFIGURE` persistente, nunca borra respaldos sin confirmación y nunca restaura por sí sola.

## Requisitos

- Python 3.11 o superior.
- Oracle Database 12.2 o superior instalado en el equipo (Windows o Linux).
- Para la conexión local sin contraseña, el usuario del sistema operativo debe pertenecer al grupo `ORA_DBA` (Windows) o `dba` (Linux).

## Instalación y uso

**Paso a paso para Windows / PowerShell, con el circuito completo de un respaldo: ver [COMO_EJECUTAR.md](COMO_EJECUTAR.md).**

Resumen para Linux (desde la carpeta del proyecto):

```bash
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/cloudcr --help
.venv/bin/cloudcr web
```

La web abre `http://127.0.0.1:8765/` y se detiene con Ctrl+C. Con un host distinto de `127.0.0.1` queda accesible desde la red, exige token y se conecta a Oracle como SYSDBA: usarlo solo en redes de confianza.

## Documentación

| Documento | Contenido |
|---|---|
| [COMO_EJECUTAR.md](COMO_EJECUTAR.md) | Instalación y ejecución, terminal y web |
| [docs/analisis.md](docs/analisis.md) | Problema, riesgos, objetivos, requerimientos, modelo de estrategia, prioridades, tipos de respaldo, ARCHIVELOG, controles preventivos |
| [docs/diseno.md](docs/diseno.md) | Arquitectura, módulos, modelo de datos, máquinas de estado, diagramas, diseño de interfaz |
| [docs/manual_usuario.md](docs/manual_usuario.md) | Manual de usuario |
| [docs/transformacion_estrategia_rman.md](docs/transformacion_estrategia_rman.md) | De la configuración de la estrategia a las cláusulas RMAN |
| [docs/afinamiento_redo_archivelog.md](docs/afinamiento_redo_archivelog.md) | Afinamiento de redo logs y archivado, en cuatro pasos |
| [docs/presentacion_guion.md](docs/presentacion_guion.md) | Guion de la demostración |
| [docs/evidencias/](docs/evidencias/) | Evidencias capturadas sobre una XE real |

## Estructura

```
src/cloudcr_backup/
├── domain/        modelos del dominio (estrategia, perfil, ejecución, alertas, evidencias)
├── oracle/        descubrimiento, conexión, inspector, observaciones, explorador
├── repository/    acceso SQL al repositorio BKPCAT
├── strategy/      estrategias QUÉ-CÓMO-CUÁNDO, prioridades, esquemas y vocabulario
├── validation/    motor y reglas de validación
├── rman/          constructor de scripts RMAN, plantillas y aprobación
├── execution/     preflight, ejecución de RMAN, clasificación, evidencia y buzón
├── verification/  verificación de respaldos
├── retention/     política de retención
├── recovery/      puntos, diagnóstico y procedimientos de recuperación
├── scheduling/    reloj, recurrencias, ventanas y planificador
├── agent/         bucle del agente y latido
├── alerts/        reglas de alerta, motor y notificadores (consola, correo)
├── services/      casos de uso que llaman la CLI y la web
├── presentacion/  modelos de presentación compartidos por terminal y web
├── reports/       exportación de la instancia, el historial y la evidencia
├── cli/           comandos de terminal
└── web/           interfaz web: FastAPI, rutas, plantillas Jinja2, CSS/JS y htmx incluidos
sql/               setup del repositorio, datos de demostración y activación de ARCHIVELOG
config/estrategias/  estrategias de demostración en YAML
deploy/windows/    registro del agente como tarea programada
tests/             unitarias, web e integración
```

## Pruebas

```bash
.venv/bin/python -m pytest
```

Corre las pruebas que no necesitan Oracle. Las marcadas `oracle` instalan y **desinstalan** el esquema del repositorio: no correrlas contra un repositorio con datos reales.

## Terceros

`src/cloudcr_backup/web/estaticos/htmx.min.js` es htmx 2.0.11 (https://htmx.org, licencia 0BSD), incluido sin modificaciones para que la interfaz funcione sin internet.
