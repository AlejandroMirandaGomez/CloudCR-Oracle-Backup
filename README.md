# CloudCR-Oracle-Backup

Herramienta para la Gestión de Estrategias de Respaldo de Bases de Datos Oracle usando RMAN (Curso EIF402 Administración de Bases de Datos, UNA, II ciclo 2026).

## Estado actual

Implementado: **descubrimiento y explorador de la instancia**, en la terminal y en una **interfaz web**.

- Busca solo las instancias Oracle de la máquina (servicios y registro de Windows, `/etc/oratab` y procesos en Linux, variables de entorno).
- Se conecta sin contraseña con autenticación del sistema operativo (`/ AS SYSDBA`) usando las bibliotecas del propio `ORACLE_HOME`, o por red con usuario y contraseña.
- Muestra la estructura física de la instancia como árbol:
  - archivos de la instancia, compartidos por todos los contenedores: control files, redo logs (grupos y miembros), SPFILE/PFILE y destino de archived logs;
  - cada contenedor (`CDB$ROOT`, `PDB$SEED`, PDBs) → tablespaces → datafiles/tempfiles, con tamaño, uso y ubicación.
- Señala advertencias y recomendaciones sobre la instancia (NOARCHIVELOG, redo sin multiplexar, control files en el mismo directorio, datafiles cerca de su límite, etc.).
- Exporta a JSON, Markdown o HTML.
- Interfaz web (FastAPI + HTMX) con árbol plegable, resumen, filtros, búsqueda, panel de observaciones con "Ir al nodo" y exportaciones. Por defecto solo es accesible desde el mismo equipo.

También implementado:

- **Repositorio** (`BKPCAT`), **estrategias** QUÉ-CÓMO-CUÁNDO y su **validación** (31 reglas), con CLI y asistente web.
- **Programación**: recurrencias (diaria, semanal, mensual, una vez, intervalo) con zona horaria y horario de verano, ventanas de respaldo y próximas ejecuciones (`cloudcr tarea proximas`).
- **Agente** (`cloudcr agente ejecutar`): reclama las ejecuciones vencidas sin duplicarlas, registra las no ejecutadas, se recupera de caídas y se instala como tarea programada de Windows.
- **Alertas** (11 reglas) con deduplicación, resolución automática y notificación por consola y correo.
- **Historial, estado y reportes**: semáforo por estrategia, historial con columna Pruebas, exportación a CSV, Markdown y HTML; en la terminal y en la web (`/estado`, `/estrategias`, `/historial`, `/alertas`) con API JSON.

Pendiente (carril de Juan): constructor de scripts RMAN, pipeline de ejecución, verificación y recuperación. Mientras no exista, el agente solo corre con `--simulado` y lo rotula. Ver `docs/manual_usuario.md`.

## Requisitos

- Python 3.11 o superior.
- Oracle Database 12.2 o superior instalado en el equipo (Windows o Linux).
- Para la conexión local sin contraseña, el usuario del sistema operativo debe pertenecer al grupo `ORA_DBA` (Windows) o `dba` (Linux).

## Instalación

**Paso a paso para Windows / PowerShell: ver [COMO_EJECUTAR.md](COMO_EJECUTAR.md).**

Resumen para Linux (desde la carpeta del proyecto):

```bash
python -m venv .venv
```

```bash
.venv/bin/python -m pip install -e ".[dev]"
```

## Uso

Los ejemplos son para Linux; en Windows reemplazar `.venv/bin/cloudcr` por `.\.venv\Scripts\cloudcr.exe` (ver [COMO_EJECUTAR.md](COMO_EJECUTAR.md)). Lo que aparece entre `< >` se reemplaza por los datos del equipo.

```bash
.venv/bin/cloudcr
```

Sin argumentos busca las instancias, elige la que está en ejecución (o pregunta si hay varias) y muestra el explorador.

```bash
.venv/bin/cloudcr descubrir
```

```bash
.venv/bin/cloudcr explorar <SID> --pdb <PDB>
```

```bash
.venv/bin/cloudcr explorar --sin-seed --rutas-completas
```

```bash
.venv/bin/cloudcr explorar --salida html --archivo exportaciones/instancia.html
```

```bash
.venv/bin/cloudcr explorar --dsn <HOST>:<PUERTO>/<SERVICIO> --usuario <USUARIO>
```

Para la conexión por red, la contraseña se pide por teclado o se toma de la variable de entorno `CLOUDCR_ORACLE_CLAVE`.

### Interfaz web

```bash
.venv/bin/cloudcr web
```

Abre el navegador en `http://127.0.0.1:8765/` (si el puerto está ocupado usa el siguiente libre). Se detiene con Ctrl+C. Opciones: `--puerto <PUERTO>`, `--no-abrir`, `--cache <SEGUNDOS>`, `--host <INTERFAZ>` y `--token <TOKEN>`. Con un host distinto de `127.0.0.1` la interfaz queda accesible desde la red, exige token (se genera y se muestra en la terminal si no se indica) y se conecta a Oracle como SYSDBA: usarlo solo en redes de confianza.

## Estructura

```
src/cloudcr_backup/
├── domain/        modelos del dominio (perfil de la instancia, hallazgos, enumerados)
├── oracle/        descubrimiento, conexión, consultas, inspector, observaciones, explorador
├── presentacion/  capa compartida por terminal y web (árbol neutral, formato, resumen, dibujo con Rich)
├── cli/           comandos de terminal
├── web/           interfaz web: FastAPI, rutas, plantillas Jinja2, CSS/JS y htmx incluidos
├── repository/    repositorio de estrategias, scripts, ejecuciones y alertas (Oracle BKPCAT)
├── strategy/      estrategias QUÉ-CÓMO-CUÁNDO, prioridades, esquemas y vocabulario
├── validation/    reglas de validación
├── services/      casos de uso que llaman la CLI y la web (agente, alertas, historial, estado)
├── scheduling/    reloj, recurrencias, ventanas y planificador
├── agent/         bucle del agente, latido y puerto del ejecutor
├── alerts/        reglas de alerta, motor y notificadores (consola, correo)
├── rman/          (pendiente) constructor de scripts RMAN
├── execution/     (pendiente) ejecución de RMAN y evidencia
├── verification/  (pendiente) verificación de respaldos
├── recovery/      (pendiente) puntos y procedimientos de recuperación
└── reports/       exportación de la instancia y del historial (JSON, CSV, Markdown, HTML)
deploy/windows/    registro del agente como tarea programada
docs/              manual de usuario, afinamiento, diagramas, guías y evidencias
tests/
├── unit/          pruebas sin Oracle
├── web/           pruebas de la interfaz web con un servicio falso (sin Oracle)
├── integration/   pruebas contra una instancia real (pytest -m oracle)
└── fixtures/      perfil de instancia de ejemplo y salidas de referencia (datos ficticios)
```

## Pruebas

```bash
.venv/bin/python -m pytest
```

```bash
.venv/bin/python -m pytest -m oracle
```

## Terceros

`src/cloudcr_backup/web/estaticos/htmx.min.js` es htmx 2.0.11 (https://htmx.org, licencia 0BSD), incluido sin modificaciones para que la interfaz funcione sin internet.
