[CmdletBinding()]
param(
    [int]$Puerto = 0,
    [switch]$NoAbrir,
    [switch]$SinAgente
)

$ErrorActionPreference = 'Stop'
$raiz = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location -LiteralPath $raiz

$PlantillaSql = @'
SET DEFINE OFF
SET FEEDBACK OFF
SET SERVEROUTPUT ON
WHENEVER SQLERROR EXIT FAILURE
CONNECT / AS SYSDBA
DECLARE
  v_existe NUMBER;
BEGIN
  SELECT COUNT(*) INTO v_existe FROM v$pdbs WHERE name = '__PDB__';
  IF v_existe = 0 THEN
    EXECUTE IMMEDIATE 'CREATE PLUGGABLE DATABASE __PDB__ ADMIN USER PDB_ADMIN IDENTIFIED BY "__CLAVE__" FILE_NAME_CONVERT = (''pdbseed'', ''__PDB__'')';
    DBMS_OUTPUT.PUT_LINE('PDB __PDB__ creada.');
  END IF;
END;
/
DECLARE
  v_modo VARCHAR2(20);
BEGIN
  SELECT open_mode INTO v_modo FROM v$pdbs WHERE name = '__PDB__';
  IF v_modo = 'MOUNTED' THEN
    EXECUTE IMMEDIATE 'ALTER PLUGGABLE DATABASE __PDB__ OPEN';
  END IF;
  EXECUTE IMMEDIATE 'ALTER PLUGGABLE DATABASE __PDB__ SAVE STATE';
END;
/
ALTER SESSION SET CONTAINER = __PDB__;
DECLARE
  v_existe NUMBER;
  v_ruta_sistema VARCHAR2(400);
  v_ruta_users VARCHAR2(400);
BEGIN
  SELECT COUNT(*) INTO v_existe FROM dba_tablespaces WHERE tablespace_name = 'USERS';
  IF v_existe = 0 THEN
    SELECT file_name INTO v_ruta_sistema FROM dba_data_files WHERE tablespace_name = 'SYSTEM' AND ROWNUM = 1;
    v_ruta_users := REGEXP_REPLACE(v_ruta_sistema, 'SYSTEM01\.DBF$', 'USERS01.DBF', 1, 1, 'i');
    EXECUTE IMMEDIATE 'CREATE TABLESPACE users DATAFILE ''' || v_ruta_users || ''' SIZE 500M AUTOEXTEND ON NEXT 100M MAXSIZE UNLIMITED';
  END IF;
  SELECT COUNT(*) INTO v_existe FROM dba_users WHERE username = '__USUARIO__';
  IF v_existe = 0 THEN
    EXECUTE IMMEDIATE 'CREATE USER __USUARIO__ IDENTIFIED BY "__CLAVE__" DEFAULT TABLESPACE users QUOTA 500M ON users';
    DBMS_OUTPUT.PUT_LINE('Usuario __USUARIO__ creado.');
  ELSE
    EXECUTE IMMEDIATE 'ALTER USER __USUARIO__ IDENTIFIED BY "__CLAVE__" ACCOUNT UNLOCK QUOTA 500M ON users';
  END IF;
END;
/
GRANT CREATE SESSION, CREATE TABLE, CREATE SEQUENCE, CREATE VIEW TO __USUARIO__;
EXIT
'@

function Paso([string]$Texto) {
    Write-Host "==> $Texto" -ForegroundColor Cyan
}

function Fallar([string]$Texto) {
    Write-Host "ERROR: $Texto" -ForegroundColor Red
    exit 1
}

function Ejecutar([string]$Archivo, [string[]]$Argumentos) {
    & $Archivo @Argumentos
    if ($LASTEXITCODE -ne 0) {
        Fallar "Falló el comando: $Archivo $($Argumentos -join ' ')"
    }
}

function CodigoDeSalida([string]$Archivo, [string[]]$Argumentos) {
    $anterior = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & $Archivo @Argumentos 2>&1 | Out-Null
    $codigo = $LASTEXITCODE
    $ErrorActionPreference = $anterior
    return $codigo
}

function LeerEnv([string]$Ruta) {
    $valores = @{}
    foreach ($linea in Get-Content -LiteralPath $Ruta -Encoding UTF8) {
        if ($linea -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') {
            $valores[$Matches[1]] = $Matches[2].Trim('"', "'")
        }
    }
    return $valores
}

function BuscarPython {
    foreach ($nombre in 'python', 'py') {
        $comando = Get-Command $nombre -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($comando) {
            $codigo = CodigoDeSalida $comando.Source @('-c', 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)')
            if ($codigo -eq 0) {
                return $comando.Source
            }
        }
    }
    return $null
}

function PrepararOracle($ajustes) {
    $dsn = $ajustes['CLOUDCR_REPOSITORIO_DSN']
    $usuario = $ajustes['CLOUDCR_REPOSITORIO_USUARIO']
    $clave = $ajustes['CLOUDCR_REPO_CLAVE']
    if (-not $usuario) {
        $usuario = 'BKP_ADMIN'
    }
    if (-not $dsn -or -not $clave) {
        Fallar 'Falta CLOUDCR_REPOSITORIO_DSN o CLOUDCR_REPO_CLAVE en el archivo .env.'
    }
    if ($dsn -match '^(?<host>[^:/]+)(:\d+)?/(?<servicio>[A-Za-z][A-Za-z0-9_$#]*)$') {
        $hostDsn = $Matches['host']
        $servicio = $Matches['servicio'].ToUpper()
    } else {
        Fallar "CLOUDCR_REPOSITORIO_DSN debe tener el formato host:puerto/servicio. Valor actual: $dsn"
    }
    if ($usuario -notmatch '^[A-Za-z][A-Za-z0-9_$#]*$') {
        Fallar "CLOUDCR_REPOSITORIO_USUARIO no es un nombre de usuario Oracle válido: $usuario"
    }
    if ($clave -match '["'']') {
        Fallar 'CLOUDCR_REPO_CLAVE no puede contener comillas.'
    }
    if ($hostDsn -notin @('localhost', '127.0.0.1', $env:COMPUTERNAME)) {
        Paso "El DSN apunta a $hostDsn; se omite la creación local de la PDB y del usuario."
        return
    }
    if (-not (Get-Command sqlplus -ErrorAction SilentlyContinue)) {
        Fallar 'No se encontró sqlplus en el PATH. Agregue la carpeta bin de ORACLE_HOME al PATH y vuelva a ejecutar.'
    }

    $sidOriginal = $env:ORACLE_SID
    if (-not $sidOriginal) {
        $servicioOracle = Get-Service -Name 'OracleService*' -ErrorAction SilentlyContinue |
            Where-Object { $_.Status -eq 'Running' } |
            Select-Object -First 1
        if (-not $servicioOracle) {
            Fallar 'No hay ningún servicio OracleService* en ejecución. Inicie la instancia y vuelva a ejecutar.'
        }
        $env:ORACLE_SID = $servicioOracle.Name -replace '^OracleService', ''
    }

    Paso "Preparando la PDB $servicio y el usuario $($usuario.ToUpper()) en la instancia $env:ORACLE_SID"
    $sql = $PlantillaSql.Replace('__PDB__', $servicio).Replace('__USUARIO__', $usuario.ToUpper()).Replace('__CLAVE__', $clave)
    $carpetaTemporal = Join-Path ([IO.Path]::GetTempPath()) ('cloudcr_' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $carpetaTemporal | Out-Null
    $codigo = 1
    try {
        [IO.File]::WriteAllText((Join-Path $carpetaTemporal 'preparar.sql'), $sql, (New-Object Text.UTF8Encoding($false)))
        Push-Location -LiteralPath $carpetaTemporal
        try {
            & sqlplus -S /nolog '@preparar.sql'
            $codigo = $LASTEXITCODE
        } finally {
            Pop-Location
        }
    } finally {
        Remove-Item -LiteralPath $carpetaTemporal -Recurse -Force -ErrorAction SilentlyContinue
        if (-not $sidOriginal) {
            Remove-Item Env:ORACLE_SID -ErrorAction SilentlyContinue
        }
    }
    if ($codigo -ne 0) {
        Fallar 'sqlplus no pudo crear la PDB o el usuario. Revise el mensaje de Oracle de arriba (el usuario de Windows debe pertenecer al grupo ORA_DBA).'
    }
}

$archivoEnv = Join-Path $raiz '.env'
if (-not (Test-Path -LiteralPath $archivoEnv)) {
    Fallar 'No existe el archivo .env en la carpeta del proyecto. Copie .env.example a .env y complete CLOUDCR_REPO_CLAVE.'
}
$ajustes = LeerEnv $archivoEnv

$pythonVenv = Join-Path $raiz '.venv\Scripts\python.exe'
$cloudcr = Join-Path $raiz '.venv\Scripts\cloudcr.exe'
$archivoHuella = Join-Path $raiz '.venv\.pyproject.sha256'

if (-not (Test-Path -LiteralPath $pythonVenv)) {
    Paso 'Creando el entorno virtual (.venv)'
    $python = BuscarPython
    if (-not $python) {
        Fallar 'No se encontró Python 3.11 o superior. Instálelo desde https://www.python.org/downloads/ y vuelva a ejecutar.'
    }
    Ejecutar $python @('-m', 'venv', '.venv')
}

$huellaActual = (Get-FileHash -LiteralPath (Join-Path $raiz 'pyproject.toml') -Algorithm SHA256).Hash
$huellaInstalada = ''
if (Test-Path -LiteralPath $archivoHuella) {
    $huellaInstalada = (Get-Content -LiteralPath $archivoHuella -Raw).Trim()
}
if (-not (Test-Path -LiteralPath $cloudcr) -or $huellaInstalada -ne $huellaActual) {
    Paso 'Instalando el programa y sus dependencias (necesita internet)'
    Ejecutar $pythonVenv @('-m', 'pip', 'install', '--disable-pip-version-check', '-e', '.[dev]')
    Set-Content -LiteralPath $archivoHuella -Value $huellaActual -Encoding ASCII
}

Paso 'Verificando el repositorio'
if ((CodigoDeSalida $cloudcr @('repo', 'estado')) -ne 0) {
    PrepararOracle $ajustes
    Ejecutar $cloudcr @('repo', 'instalar')
}

Paso 'Cargando la configuración de correo del equipo'
if ((CodigoDeSalida $cloudcr @('alertas', 'configurar-correo')) -ne 0) {
    Write-Host 'AVISO: no se pudo cargar config\notificaciones.yaml; configure el correo en Sistema > Notificaciones por correo.' -ForegroundColor Yellow
}
$claveCorreo = $null
foreach ($nombreArchivo in '.env', '.env.local') {
    $rutaArchivo = Join-Path $raiz $nombreArchivo
    if (Test-Path -LiteralPath $rutaArchivo) {
        $valoresArchivo = LeerEnv $rutaArchivo
        if ($valoresArchivo['CLOUDCR_SMTP_CLAVE']) { $claveCorreo = $valoresArchivo['CLOUDCR_SMTP_CLAVE'] }
    }
}
if (-not $claveCorreo -and -not $env:CLOUDCR_SMTP_CLAVE) {
    Write-Host 'AVISO: falta la contraseña del correo de alertas. Cree el archivo .env.local con la línea CLOUDCR_SMTP_CLAVE=<contraseña> (pídasela al grupo) y vuelva a iniciar. Sin ella, las alertas no se envían por correo.' -ForegroundColor Yellow
}

$argumentosWeb = @('web')
if ($Puerto -gt 0) {
    $argumentosWeb += @('--puerto', "$Puerto")
}
if ($NoAbrir) {
    $argumentosWeb += '--no-abrir'
}
if ($SinAgente) {
    $argumentosWeb += '--sin-agente'
}
Paso 'Iniciando la interfaz web (Ctrl+C para detenerla)'
& $cloudcr @argumentosWeb
exit $LASTEXITCODE
