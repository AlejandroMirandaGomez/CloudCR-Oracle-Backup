# Cómo ejecutar CloudCR Oracle Backup desde PowerShell

Guía paso a paso para cualquier equipo Windows con PowerShell (5.1 o 7) y Oracle Database 12.2 o superior.

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

Por seguridad, la web solo acepta un `ORACLE_HOME` detectado en el equipo. Para usar otro, hay que usar la terminal: `cloudcr explorar <SID> --oracle-home <ORACLE_HOME>`. Si en el equipo hay instancias con distintos `ORACLE_HOME`, cada `cloudcr web` explora las de un solo `ORACLE_HOME`; para las otras, abrir otro `cloudcr web` con otro `--puerto`.

## Pruebas

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Incluyendo la prueba contra la instancia Oracle local del equipo:

```powershell
.\.venv\Scripts\python.exe -m pytest -m "oracle or not oracle"
```

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
