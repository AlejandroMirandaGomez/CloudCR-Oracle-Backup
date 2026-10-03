[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string] $Ejecutable,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string] $Configuracion,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string] $Usuario,

    [ValidateNotNullOrEmpty()]
    [string] $NombreTarea = 'CloudCR Agente de respaldos',

    [ValidateNotNullOrEmpty()]
    [string] $GrupoOracle = 'ORA_DBA',

    [ValidateRange(1, 1440)]
    [int] $MinutosEntreReinicios = 1,

    [switch] $Simulado
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Resolve-RutaExistente {
    param([string] $Ruta, [string] $Descripcion)
    if (-not (Test-Path -LiteralPath $Ruta -PathType Leaf)) {
        throw "No existe $Descripcion en '$Ruta'."
    }
    return (Resolve-Path -LiteralPath $Ruta).ProviderPath
}

function Test-MiembroDelGrupo {
    param([string] $Cuenta, [string] $Grupo)
    $miembros = Get-LocalGroupMember -Group $Grupo -ErrorAction Stop
    $corto = ($Cuenta -split '\\')[-1]
    foreach ($miembro in $miembros) {
        $nombre = [string] $miembro.Name
        if ($nombre -ieq $Cuenta -or ($nombre -split '\\')[-1] -ieq $corto) {
            return $true
        }
    }
    return $false
}

function Build-AccionAgente {
    param([string] $RutaEjecutable, [string] $RutaConfiguracion, [bool] $ModoSimulado)
    $argumentosAgente = 'agente ejecutar'
    if ($ModoSimulado) {
        $argumentosAgente += ' --simulado'
    }
    $comando = 'set "CLOUDCR_CONFIG={0}" && set "PYTHONUTF8=1" && "{1}" {2}' -f $RutaConfiguracion, $RutaEjecutable, $argumentosAgente
    $carpeta = Split-Path -Parent $RutaConfiguracion
    return New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\cmd.exe" -Argument "/d /c $comando" -WorkingDirectory $carpeta
}

$rutaEjecutable = Resolve-RutaExistente -Ruta $Ejecutable -Descripcion 'el ejecutable cloudcr'
$rutaConfiguracion = Resolve-RutaExistente -Ruta $Configuracion -Descripcion 'el archivo de configuración'

if (-not (Test-MiembroDelGrupo -Cuenta $Usuario -Grupo $GrupoOracle)) {
    throw "La cuenta '$Usuario' no pertenece al grupo local '$GrupoOracle'; el agente necesita conectarse como SYSDBA."
}

if ($Simulado) {
    Write-Warning 'La tarea correrá el agente en modo SIMULACIÓN: no ejecuta RMAN y sus ejecuciones no son evidencia.'
}

$credencial = Get-Credential -UserName $Usuario -Message "Contraseña de $Usuario para la tarea programada '$NombreTarea'"
if ($null -eq $credencial) {
    throw 'Se canceló el ingreso de la contraseña.'
}

$accion = Build-AccionAgente -RutaEjecutable $rutaEjecutable -RutaConfiguracion $rutaConfiguracion -ModoSimulado $Simulado.IsPresent
$disparador = New-ScheduledTaskTrigger -AtStartup
$ajustes = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -DontStopOnIdleEnd `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes $MinutosEntreReinicios)

$descripcion = 'Agente de CloudCR Oracle Backup: dispara los respaldos programados y evalúa alertas.'
if ($PSCmdlet.ShouldProcess($NombreTarea, "Registrar la tarea programada para $Usuario")) {
    $existente = Get-ScheduledTask -TaskName $NombreTarea -ErrorAction SilentlyContinue
    if ($null -ne $existente) {
        Unregister-ScheduledTask -TaskName $NombreTarea -Confirm:$false
    }
    Register-ScheduledTask `
        -TaskName $NombreTarea `
        -Description $descripcion `
        -Action $accion `
        -Trigger $disparador `
        -Settings $ajustes `
        -User $credencial.UserName `
        -Password $credencial.GetNetworkCredential().Password `
        -RunLevel Highest | Out-Null
    Write-Output "Tarea '$NombreTarea' registrada. Iníciela sin reiniciar con: Start-ScheduledTask -TaskName '$NombreTarea'"
}
