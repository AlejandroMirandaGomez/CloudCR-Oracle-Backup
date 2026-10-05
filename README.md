# CloudCR-Oracle-Backup

Curso EIF402 Administración de Bases de Datos, UNA, II ciclo 2026.

## Integrantes

- Luis Hidalgo Calvo
- Juan Sanchez Bermudez
- Josue Sanchez Salazar
- Alejandro Miranda Gomez

## Qué es el sistema

CloudCR-Oracle-Backup es un sistema para gestionar estrategias de respaldo de bases de datos Oracle con RMAN, usado desde una interfaz web.

Una estrategia define **qué respaldar**, **cómo** (completo, incremental nivel 0, nivel 1 diferencial o acumulativo), **cuándo** (frecuencia, días, horas y ventana) y **por cuánto tiempo conservarlo** (retención). El sistema valida la estrategia, genera y aprueba el script RMAN, lo ejecuta de forma automática según el horario, verifica el respaldo y guarda la evidencia de cada ejecución.

```
Estrategia → programación → script RMAN → ejecución → resultado → evidencia
```

Sirve para que el administrador de la base de datos tenga el respaldo bajo control: sabe qué se respalda, cuándo corrió cada tarea, si salió bien, cuánto tiempo se conserva y cómo recuperar la base ante una falla. Además recomienda, pero no impone: nunca cambia el modo de archivado, nunca borra respaldos sin confirmación y nunca restaura por sí solo.

## Cómo ejecutar

```
.\iniciar.cmd
```
