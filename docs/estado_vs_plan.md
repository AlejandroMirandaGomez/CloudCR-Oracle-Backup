# CloudCR Oracle Backup — Estado del proyecto contra el plan y el enunciado

Rama `Dev_Luis` · 4 de octubre de 2026 · actualizado tras implementar las reglas `ARCH_*`, criterios, evidencias, correo de prueba y observaciones de redo (todo en CLI y web), y producir E3, E5, E6, E8 y E10.

## Resumen

El producto está **construido de punta a punta**, y la web ya opera todo el circuito (el plan la contemplaba solo de lectura). Lo que falta es sobre todo **evidencia real contra la XE**, la presentación y la integración final.

| Comprobación | Resultado |
|---|---|
| `pytest -m "not oracle"` | 998 pasan (69 de Oracle deseleccionadas, **no corridas**; desinstalan el repositorio al terminar) |
| `ruff check src tests` | Limpio |
| `mypy src` | Sin errores en 195 archivos |
| Reglas de validación | 35 (todas las del plan) |
| Tablas del DDL | 12 |
| Comentarios en `src` | 0 |

No se corrió nada contra Oracle real en este análisis y no se confirmó si la XE está hoy en ARCHIVELOG.

## Cobertura del enunciado

| § | Exigencia | Estado | Responsable |
|---|---|---|---|
| 1 | Qué respaldar: base, tablespaces, datafiles, control files, SPFILE, archived logs | Listo | Luis |
| 1.1 | Prioridad alta / media / baja con criterios propios | Listo; visible en la web (`/criterios`) | Luis |
| 2, 2.1–2.4 | Completo, incremental N0, N1 diferencial, N1 acumulativo | Listo, con scripts de oro | Juan |
| 3 | Frecuencia, días, horas, intervalos, ventana de respaldo | Listo | Luis y Alejandro |
| 3 | Conservación por un período determinado | Listo | Juan y Luis |
| 3 | "Respaldo adicional antes de operaciones críticas" | **Cubierto en parte**: `UNA_VEZ` y ejecutar ahora. No existe el concepto "antes de operación crítica" | Luis (decidir) |
| 4 | Estrategia → programación → script → ejecución → resultado → evidencia | Listo | Alejandro y Juan |
| 5 | Evidencia de cada ejecución e historial | Listo: `evidencia.json` con los campos del enunciado | Juan y Alejandro |
| 6 | Los 7 componentes del sistema de gestión | Listo, todos con pantalla web | Todos |
| 7 | Separar estrategia de ejecución | Listo (estrategia versionada, scripts aprobados con hash) | Todos |
| Concl. | Demostrar que el respaldo se hizo y su resultado | Listo en código (verificador, columna Pruebas); evidencias reales E2–E4 y E9 | Juan |

## Josué — repositorio, configuración, registro de BD

| Ítem | Estado |
|---|---|
| J1–J5 SQL de setup (PDB, usuario, 12 tablas, parámetros, monitor) | Listo |
| J6 `config/ajustes.py` y `rutas.py` | Listo |
| J7 `repository/*` (incluye `piezas.py`) | Listo |
| J8–J11 `repo`, `param`, `db`, `doctor` | Listo |
| J12 `.env.example` y `COMO_EJECUTAR.md` | Listo |
| J13 pruebas de repositorio | Listo; la de integración no se corrió |
| `docs/diseno.md` | Listo (435 líneas) |
| Capa `services/` y `Exploracion` en `domain/` | Hecho |
| E1 | Listo |
| Regla de capas (§12.4) | **Documentada como deuda aceptada** en `docs/diseno.md` §1.1: `cli/` y `web/` importan `repository/` u `oracle/` en 11 archivos; no ejecutan SQL ni RMAN |
| `docs/estado_josue.md` | Actualizado |

## Luis — estrategias y validación

| Ítem | Estado |
|---|---|
| L1–L5 dominio, servicio, YAML, prioridad, esquemas | Listo |
| L6–L7 contexto y motor de validación | Listo |
| L8 reglas | **Listo: 35 de 35**, con `ARCH_004`, `ARCH_006`, `ARCH_007` y `ARCH_009` nuevas |
| L9 capacidades | Listo |
| L10–L11 asistente y comandos de estrategia y tarea | Listo |
| L12 `est001`–`est004.yaml` | Listo |
| L13 pruebas positivas y negativas por regla | Listo (`test_reglas_archivado.py` cubre las 4 nuevas) |
| L14 vocabulario del profesor | Listo; también en la web `/criterios` |
| L15 `sql/demo/` | Listo |
| `docs/analisis.md` | **Listo** (secciones del enunciado, 4 de notas de clase, prioridades, matriz de controles) |
| Pantalla web de criterios | Listo |
| `DevLuis.md` | Actualizado |
| **E5** (paso real de la XE a ARCHIVELOG) | **Pendiente**: exige tocar la XE |
| Presentación (con Alejandro) | Guion listo en `docs/presentacion_guion.md`; faltan las diapositivas |
| "Respaldo antes de operaciones críticas" | **Resuelto**: se cubre con «Ejecutar ahora» y la frecuencia «Una sola vez», documentado en `analisis.md` y el manual |
| Cambios sin commitear | Todo lo de esta sesión: reglas `ARCH_*`, criterios, evidencias, correo de prueba, observaciones de redo, documentos y evidencias nuevas |

Limitación conocida: `ARCH_009` solo se dispara al crear o editar estrategias desde la web, porque ahí se conoce el DSN del repositorio. La validación desde la CLI y la de `script generar` no la ejecutan.

## Juan — RMAN, ejecución, verificación, recuperación

| Ítem | Estado |
|---|---|
| U1–U5 objetos, nombres, constructor, plantillas, aprobación con hash | Listo; 6 scripts de oro |
| U6–U12 preflight, runner, parser, correlator, clasificador, evidencia/buzón, pipeline | Listo |
| U13 verificador | Listo |
| U14, U20 recuperación y diagnóstico | Listo |
| U15 comandos `script`, `ejecutar`, `recuperacion`, `retencion` | Listo |
| U16 fixtures de logs reales | Listo |
| U18 `docs/transformacion_estrategia_rman.md` | Listo |
| U19 retención | Listo |
| E2, E3 (consistente), E4, E9 | Listos |
| E3 en línea (ejecución `EN_LINEA` en ARCHIVELOG) | **Listo** (`docs/evidencias/E3_ejecucion_en_linea_v1/`) |
| Aplicar `ARCH_002` y obtener la v2 con archived logs | **Listo** (`E5_aplicar_arch_002_v2/`) |
| Ensayo de la demo | Pendiente |

## Alejandro — agente, alertas, historial, web

| Ítem | Estado |
|---|---|
| A1–A3 recurrencia, ventana, planificador | Listo |
| A4–A5 agente y tarea programada | Listo |
| A6 motor de alertas | Listo |
| A7 notificadores consola y correo | Código listo; **falta probar con una cuenta SMTP real** |
| A8–A10 historial, comandos de monitoreo, `presentacion/` | Listo |
| A11 web | Listo y ampliada (opera todo el circuito) |
| A13 `RED_003` | Listo |
| A14 `docs/afinamiento_redo_archivelog.md` | Existe; falta el "después" con la XE en ARCHIVELOG |
| `docs/manual_usuario.md` | Listo |
| E6 (ejecuciones automáticas del agente) | **Listo**: 3 ejecuciones automáticas de EST005 (`E6_ejecuciones_agente.md`) |
| E8 (historial con Pruebas, exportado a HTML) | **Listo** (`E8_historial.html`; conviene re-exportarlo al final) |
| E10 (afinamiento antes y después) | **Listo**: explorador y mediciones reales; el cambio de modo en sí no quedó registrado (ver `afinamiento_redo_archivelog.md`) |
| Botón de correo de prueba en la web y en la CLI | **Listo** (sin commitear) |
| **E7** (`NO_EJECUTADA` + alerta + correo real) | Pendiente: falta la cuenta remitente (un compañero la crea) |

## Bloqueos y riesgos

| Tema | Detalle |
|---|---|
| **Paso a ARCHIVELOG** | Es el cuello de botella. Sin él no hay E3 en línea, ni E10, ni el paso 12 del guion de demo. Hay que hacerlo con un respaldo antes y otro después |
| Autoría git | Alejandro 68 commits, Juan 30, Josué 8, Luis 3. El plan lo marca como riesgo |
| Rama | `Dev_Luis` no está en `main` |
| Pruebas de integración con Oracle | 66 sin correr |

## Definición de terminado: lo que falta marcar

- **Producto:** todo cumplido en código. Falta confirmar en vivo que el agente ejecuta sin intervención y que una alerta se abre, se notifica y se resuelve sola.
- **Calidad:** `ruff` y `mypy` limpios. Faltan las pruebas de integración contra Oracle y la regla de capas.
- **Documentos:** existen `analisis.md`, `diseno.md`, `afinamiento`, `manual_usuario.md` y `transformacion`. Faltan las evidencias E5, E6, E7, E8 y E10, y la presentación.

## Orden recomendado

1. **Luis y Juan:** pasar la XE a ARCHIVELOG, con respaldo antes y después (E5). Desbloquea todo lo siguiente.
2. **Luis:** commit y merge a `main`.
3. **Juan:** E3 en línea y aplicar `ARCH_002`.
4. **Alejandro:** E6, E7 (con cuenta SMTP real; Gmail pide contraseña de aplicación), E8 y E10.
5. **Josué:** regla de capas y actualizar `estado_josue.md`.
6. **Luis y Alejandro:** presentación.
7. **Todos:** ensayo cronometrado de la demo.
