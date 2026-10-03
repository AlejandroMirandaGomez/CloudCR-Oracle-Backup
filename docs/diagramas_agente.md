# Diagramas del agente, la ejecución y las alertas

Diagramas del carril de Alejandro para integrar en `docs/diseno.md` (Josué). Están en Mermaid; GitHub y VS Code los dibujan directamente.

## 1. Secuencia de un tick del agente

```mermaid
sequenceDiagram
    autonumber
    participant A as Agente (agent/bucle.py)
    participant L as Latido (archivo)
    participant B as Buzón (pipeline)
    participant R as Repositorio BKPCAT
    participant P as Planificador
    participant E as Ejecutor (pipeline de Juan)
    participant M as Motor de alertas
    participant N as Notificadores

    A->>L: escribir latido (estado activo, último tick)
    A->>B: sincronizar buzón (no-op si no existe)
    A->>R: abrir sesión y releer PARAMETRO
    A->>P: reclamar_vencidas(ahora, excluir = cola local)
    P->>R: tareas programables (estrategia ACTIVA, BD activa, script APROBADO)
    P->>R: última programada por tarea
    loop por cada tarea
        P->>P: ocurrencias en (max(última, aprobado_en), ahora]
        P->>R: registrar_no_ejecutada (todas menos la última)
        alt última dentro de la gracia o recuperable por política
            P->>R: reclamar (INSERT con UQ tarea+hora)
            R-->>P: id, o None si otro agente ganó
        else perdida
            P->>R: registrar_no_ejecutada (motivo)
        end
    end
    P->>R: PROGRAMADA huérfanas → NO_EJECUTADA
    P-->>A: reclamadas
    A->>E: despachar en ThreadPoolExecutor (max_paralelo_host)
    E->>R: marcar_en_curso … RMAN … registrar_resultado
    E-->>A: terminó (adelanta la próxima evaluación)
    alt pasaron eval_minutos o terminó una ejecución
        A->>M: evaluar(ahora)
        M->>R: instantánea (bases, perfiles, estrategias, ejecuciones, piezas)
        M->>M: 11 reglas → condiciones
        M->>R: abrir (dedup por clave, ABIERTA o RECONOCIDA)
        M->>N: notificar solo si es nueva
        M->>R: resolver las vigentes cuya condición desapareció
    end
```

## 2. Estados de una ejecución (`EJECUCION.estado`)

```mermaid
stateDiagram-v2
    [*] --> PROGRAMADA: planificador.reclamar
    [*] --> NO_EJECUTADA: ocurrencia perdida (agente detenido, OMITIR, fuera de ventana)
    PROGRAMADA --> EN_CURSO: pipeline.marcar_en_curso
    PROGRAMADA --> NO_EJECUTADA: huérfana (nadie la inició antes de la gracia)
    PROGRAMADA --> BLOQUEADA: preflight impide RMAN
    PROGRAMADA --> CANCELADA: cancelación manual
    EN_CURSO --> EXITOSA: RMAN sin errores
    EN_CURSO --> CON_ADVERTENCIAS: RMAN con avisos conocidos
    EN_CURSO --> FALLIDA: RMAN con error
    EN_CURSO --> FALLIDA: el agente se reinició durante la ejecución
    EXITOSA --> [*]
    CON_ADVERTENCIAS --> [*]
    FALLIDA --> [*]
    BLOQUEADA --> [*]
    NO_EJECUTADA --> [*]
    CANCELADA --> [*]
```

`estado_prueba` evoluciona aparte: `PENDIENTE → OK | FALLIDA` cuando corre la verificación; `NO_APLICA` para NO_EJECUTADA, interrumpidas y simulaciones.

## 3. Estados de un script RMAN (`SCRIPT_RMAN.estado`)

```mermaid
stateDiagram-v2
    [*] --> BORRADOR: guardar_borrador (versión n+1, hash SHA-256)
    BORRADOR --> APROBADO: aprobar (aprobado_por, aprobado_en en UTC)
    BORRADOR --> RECHAZADO: rechazar (motivo)
    APROBADO --> OBSOLETO: se aprueba una versión nueva o cambia la estrategia
    RECHAZADO --> [*]
    OBSOLETO --> [*]
```

Solo un script `APROBADO` por tarea hace que la tarea sea programable. `aprobado_en` es la cota inferior desde la que el planificador busca ocurrencias perdidas.

## 4. Estados de una alerta (`ALERTA.estado`)

```mermaid
stateDiagram-v2
    [*] --> ABIERTA: regla se cumple y no hay otra vigente con la misma clave (se notifica)
    ABIERTA --> ABIERTA: la regla se sigue cumpliendo (se actualiza el mensaje, no se notifica)
    ABIERTA --> RECONOCIDA: reconocer (web o CLI)
    RECONOCIDA --> RECONOCIDA: la regla se sigue cumpliendo
    ABIERTA --> RESUELTA: la condición desaparece o resolución manual
    RECONOCIDA --> RESUELTA: la condición desaparece o resolución manual
    RESUELTA --> [*]
```

`ABIERTA` y `RECONOCIDA` son «vigentes»: ambas cuentan para la deduplicación y para la resolución automática. Las alertas de evento (`SCRIPT_ALTERADO`, `BASE_NO_REABIERTA`) no se resuelven solas.

## 5. Dependencias entre paquetes (medidas)

```mermaid
flowchart LR
    cli --> services
    web --> services
    cli --> presentacion
    web --> presentacion
    services --> agent
    services --> alerts
    services --> scheduling
    services --> repository
    services --> reports
    agent --> alerts
    agent --> scheduling
    alerts --> scheduling
    alerts --> strategy
    validation --> scheduling
    reports --> presentacion
    scheduling --> domain
    alerts --> domain
    agent --> domain
    repository --> domain
```

Medido con un análisis de imports el 03/10/2026: sin ciclos; `scheduling` y `alerts` no importan `web`, `cli` ni `presentacion`; los archivos nuevos de `cli` y `web` no importan `repository`, `oracle` ni `execution`.
