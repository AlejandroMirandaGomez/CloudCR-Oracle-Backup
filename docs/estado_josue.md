# Estado del carril de Josué — repositorio Oracle, configuración y registro de bases de datos

Última actualización: 30 de septiembre de 2026 (Día 2 del cronograma).

Este documento resume qué quedó terminado y probado en el carril de Josué (secciones 6 y 7.1 del `PLAN_DE_ACCION.md`), y qué necesita el resto del equipo saber para seguir trabajando sin pisarse ni repetir trabajo.

---

## 1. Qué se pudo completar

### 1.1 Entorno y dependencias

- Se verificó que **Python 3.14** (el que ya tenían instalado) funciona sin problemas con `oracledb`, `pydantic`, `fastapi` y el resto de dependencias. No hizo falta instalar Python 3.12 como preveía el plan.
- `pyproject.toml` quedó con todas las dependencias necesarias: `PyYAML`, `python-dateutil`, `tzdata`, `questionary`, `python-dotenv`, `types-PyYAML`.
- Se corrigió que `.env` **no se estaba cargando nunca** (faltaba `python-dotenv`). Ahora cualquier `cloudcr` que se corra desde la carpeta del proyecto lee el `.env` automáticamente.

### 1.2 `config/`

- `config/ajustes.py`: precedencia flag → variable `CLOUDCR_*` → `cloudcr.yaml` → valor por defecto. Corregido un bug donde una variable de entorno vacía (por ejemplo `CLOUDCR_CONFIG=` en `.env`) rompía la carga de configuración.
- `config/rutas.py`: layout de la carpeta de trabajo (`scripts/`, `ejecuciones/`, `recuperacion/`, `buzon/`, `logs/`).

### 1.3 `repository/` — las 8 funciones del contrato 6.3, implementadas y probadas contra Oracle real (no solo mocks)

| Archivo | Qué hace | Probado contra Oracle real |
|---|---|---|
| `conexion.py` | Conexión real (reutiliza el traductor de errores de `oracle/connection.py`) + manejador de CLOBs | Sí |
| `esquema.py` | `instalar` / `estado` / `desinstalar`, con el DDL de las 12 tablas embebido, idempotente | Sí |
| `parametros.py` | `obtener` / `listar` / `asignar` | Sí |
| `bases_datos.py` | `registrar` / `listar` / `obtener` / `desactivar` / `guardar_perfil` | Sí |
| `estrategias.py` | CRUD completo con alcance y tareas anidadas; `editar` reemplaza hijos y sube versión | Sí — `EST001` real, incluyendo `aplicar-recomendacion` subiendo de v1 a v2 |
| `scripts.py` | Ciclo borrador → aprobado/rechazado → obsoleto, con hash SHA-256 | Sí |
| `ejecuciones.py` | `reclamar` (con la restricción que evita duplicar una ejecución), historial, últimas | Sí |
| `alertas.py` | Upsert por `clave_dedup`, reconocer, resolver | Sí |

### 1.4 CLI nueva (J8–J11 del plan)

- `cloudcr repo instalar | estado | desinstalar`
- `cloudcr db descubrir | agregar | listar | mostrar | inspeccionar | desactivar`
- `cloudcr param listar | obtener | set | restablecer`
- `cloudcr doctor` — diagnóstico de Python, dependencias, configuración, instancias Oracle, `rman.exe`, destino de respaldo y esquema del repositorio.

### 1.5 SQL (`sql/setup/`)

- Los 5 scripts (`01` a `05`) ya se corrieron contra una XE 21c real y crearon `BKPCAT` con las 12 tablas y los 13 parámetros iniciales.
- `02_crear_usuario_repositorio.sql` se corrigió para crear el tablespace `USERS` automáticamente si la PDB no lo trae (pasa en instalaciones nuevas de XE 21c).
- `03_esquema_bkp_admin.sql` se corrigió en dos columnas: `script_rman.motivo_rechazo` (faltaba) y `estrategia_objeto.identificador` (ya no es `NOT NULL`, ver bug #2 abajo).

### 1.6 Pruebas

- `tests/unit/test_ajustes.py` (de Día 0).
- `tests/integration/test_repositorio_oracle.py`: 13 pruebas nuevas, todas corridas contra la XE real, cubren los 8 archivos de `repository/`.
- Suite completa: 202 pruebas unitarias (sin Oracle) + 14 de integración (con Oracle), `mypy --strict` limpio, `ruff` limpio.

### 1.7 Documentación

- `COMO_EJECUTAR.md`: sección nueva de instalación del repositorio.
- `.env.example` y `.gitignore` (faltaba ignorar `.env` — importante, evita subir contraseñas por accidente).

---

## 2. Tres bugs reales que solo aparecieron al probar contra Oracle de verdad

Estos no se ven con mocks ni con `mypy`/`ruff`; si alguien más conecta algo nuevo al repositorio, puede toparse con la misma clase de problema:

1. **Oracle trata `''` (string vacío) como `NULL`.** La convención del equipo es usar `identificador=""` para "toda la base" (ver `ObjetoAlcance`), pero la columna era `NOT NULL`. Se corrigió quitando el `NOT NULL`. **Si alguien agrega una columna nueva que puede recibir un string vacío con este mismo significado, no la declare `NOT NULL`.**
2. **Thin mode y thick mode de `oracledb` no se pueden mezclar en el mismo proceso.** Si un comando necesita conectar al repositorio (thin, usuario/clave) **y** a una instancia local por SYSDBA (thick, `oracle/connection.py`), hay que hacer primero toda la parte thick (SYSDBA local) y recién después abrir la conexión al repositorio — nunca al revés, porque la segunda conexión falla con `DPY-2019`. Esto le va a importar directamente a **Juan** cuando construya `execution/pipeline.py` si en el mismo proceso necesita inspeccionar la instancia local y después escribir al repositorio.
3. El PDB de una instalación nueva de XE 21c puede no traer un tablespace `USERS` (solo trae `SYSTEM`, `SYSAUX`, `UNDOTBS1`, `TEMP`). Ya está resuelto en `02_crear_usuario_repositorio.sql`.

---

## 3. Qué necesita cada Dev para tener el contexto completo

### Luis

- Se tocaron **dos archivos tuyos** (`cli/cmd_estrategia.py` y `cli/asistente_estrategia.py`): el único cambio fue reemplazar `except NotImplementedError` por el manejo real de errores (`RepositorioNoConfigurado`, `ErrorConexionOracle`), porque `repository/conexion.py` ya dejó de ser un stub. No se tocó nada de tu lógica de negocio — igual revisalo.
- Tu CLI de estrategias (`crear`, `importar`, `exportar`, `listar`, `mostrar`, `activar`, `desactivar`, `aplicar-recomendacion`) ya corre de punta a punta contra Oracle real. Se probó con `config/estrategias/est001.yaml` completo, incluyendo el flujo de versión (v1 → v2 al aplicar `ARCH_002`).
- `domain/estrategia.py` y `domain/enums.py` quedaron como el contrato definitivo contra el que se construyó todo `repository/`; si les agregás un campo, avisá antes de hacerlo porque `repository/estrategias.py` lo tiene mapeado campo por campo.

### Juan

- `repository/scripts.py` y `repository/ejecuciones.py` están listos y probados: guardar borrador, aprobar, rechazar (con motivo), marcar obsoleto; reclamar una ejecución (con la restricción anti-duplicados), marcar en curso, registrar resultado, historial, últimas.
- **Falta a propósito**: no hay funciones de repositorio para `EJECUCION_PIEZA` ni `VERIFICACION` todavía. No se armaron porque no existe todavía `execution/evidencia.py` ni `verification/verificador.py` para saber la forma exacta que necesitás — avisame cuando llegues a esa parte y las diseñamos juntos sobre tu caso real en lugar de adivinar.
- Importante: lee el bug #2 de la sección anterior antes de escribir `execution/pipeline.py` — te va a afectar directamente si mezclás conexión local (SYSDBA) y conexión al repositorio en el mismo proceso.
- `repository.estrategias.obtener_tarea_id(conexion, bd_id, estrategia_codigo, tarea_codigo)` es una función que agregué (no estaba en el contrato original 6.3) porque la ibas a necesitar para saber el `tarea_id` interno antes de guardar un script o reclamar una ejecución.

### Alejandro

- `repository/alertas.py` y `repository/ejecuciones.py` están listos para `agent/bucle.py` y `alerts/motor.py`.
- `cli/cmd_explorar.py` sigue siendo tuyo (ya te lo dejé armado desde el Día 0 con `descubrir`, `explorar` y `web` movidos ahí); no hubo cambios nuevos ahí.

### Todos

- El repositorio quedó **reinstalado limpio** (12 tablas, 13 parámetros, 0 filas de datos) — listo para que cada quien registre su propia base de datos de prueba con `cloudcr db agregar`.
- Revisen `.env.example` si todavía no configuraron su `.env` local — sin eso, `cloudcr repo`, `cloudcr db` y `cloudcr estrategia` (contra el repositorio) no van a conectar.

---

## 4. Lo que queda pendiente del carril de Josué

- `docs/diseno.md` (arquitectura, modelo de datos con diagrama ER, máquinas de estado, diagramas de secuencia) — entregable de Día 2/5, todavía no empezado.
- Funciones de repositorio para `EJECUCION_PIEZA` y `VERIFICACION`, a definir junto con Juan cuando las necesite.
- Nada de `rman/`, `execution/`, `agent/` ni `scheduling/` — corresponde a Juan y Alejandro.
