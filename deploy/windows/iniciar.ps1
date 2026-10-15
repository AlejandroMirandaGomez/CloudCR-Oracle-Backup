[CmdletBinding()]
param(
    [int]$Puerto = 0,
    [switch]$NoAbrir,
    [switch]$SinAgente
)

$ErrorActionPreference = 'Stop'
$raiz = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location -LiteralPath $raiz

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

function EsAdministrador {
    $identidad = [Security.Principal.WindowsIdentity]::GetCurrent()
    return ([Security.Principal.WindowsPrincipal]$identidad).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function PuertoAbierto([string]$Servidor, [int]$Puerto) {
    $cliente = New-Object System.Net.Sockets.TcpClient
    try {
        $conexion = $cliente.ConnectAsync($Servidor, $Puerto)
        return ($conexion.Wait(1500) -and $cliente.Connected)
    } catch {
        return $false
    } finally {
        $cliente.Dispose()
    }
}

function EsperarPuerto([string]$Servidor, [int]$Puerto, [int]$Segundos) {
    $limite = (Get-Date).AddSeconds($Segundos)
    while ((Get-Date) -lt $limite) {
        if (PuertoAbierto $Servidor $Puerto) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function AsegurarMySql($ajustes) {
    $servidor = if ($ajustes['CLOUDCR_REPOSITORIO_HOST']) { $ajustes['CLOUDCR_REPOSITORIO_HOST'] } else { 'localhost' }
    $puerto = if ($ajustes['CLOUDCR_REPOSITORIO_PUERTO']) { [int]$ajustes['CLOUDCR_REPOSITORIO_PUERTO'] } else { 3306 }
    $nombreServicio = if ($ajustes['CLOUDCR_MYSQL_SERVICIO']) { $ajustes['CLOUDCR_MYSQL_SERVICIO'] } else { 'MySQL80' }

    if ($servidor -notin @('localhost', '127.0.0.1', '::1', $env:COMPUTERNAME)) {
        Paso "MySQL está en ${servidor}:${puerto}; se omite el control del servicio local."
        if (-not (EsperarPuerto $servidor $puerto 10)) {
            Fallar "No se pudo llegar a MySQL en ${servidor}:${puerto}. Verifique que el servidor esté encendido y que el puerto esté abierto."
        }
        return
    }

    Paso "Verificando el servicio $nombreServicio de MySQL"
    $servicio = Get-Service -Name $nombreServicio -ErrorAction SilentlyContinue
    if (-not $servicio) {
        Fallar "No existe el servicio de Windows '$nombreServicio'. Instale MySQL Server o indique el nombre de su servicio en CLOUDCR_MYSQL_SERVICIO (archivo .env)."
    }
    if ($servicio.Status -ne 'Running') {
        Paso "Iniciando el servicio $nombreServicio"
        try {
            Start-Service -Name $nombreServicio -ErrorAction Stop
            $servicio.WaitForStatus('Running', [TimeSpan]::FromSeconds(30))
        } catch {
            if (-not (EsAdministrador)) {
                Fallar "El servicio $nombreServicio está detenido y para iniciarlo se necesita ejecutar esta terminal como administrador. Ábrala con «Ejecutar como administrador» y vuelva a ejecutar iniciar.cmd, o inicie el servicio a mano con: Start-Service $nombreServicio"
            }
            Fallar "No se pudo iniciar el servicio ${nombreServicio}: $($_.Exception.Message)"
        }
    }
    if (-not (EsperarPuerto $servidor $puerto 30)) {
        Fallar "El servicio $nombreServicio está en ejecución, pero MySQL no responde en ${servidor}:${puerto}. Revise el registro de errores de MySQL."
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

AsegurarMySql $ajustes

Paso 'Verificando el repositorio'
if ((CodigoDeSalida $cloudcr @('repo', 'estado')) -ne 0) {
    Paso 'Preparando la base y el usuario del repositorio en MySQL'
    Ejecutar $cloudcr @('repo', 'preparar')
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
