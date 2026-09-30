<#
.SYNOPSIS
    Sobe, derruba e lista os demos web do jev-demos.

.EXAMPLE
    ./demos.ps1                          # sobe todos os demos web
    ./demos.ps1 catalog-ai brand-live    # sobe só esses
    ./demos.ps1 -Fake                    # catalog-ai e brand-live com Jev simulado
    ./demos.ps1 -Open                    # sobe e abre no navegador
    ./demos.ps1 -Status                  # mostra o que está no ar
    ./demos.ps1 -Stop                    # derruba tudo que o script subiu
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0, ValueFromRemainingArguments)]
    [ValidateSet('story-sizer', 'sprint-radar', 'catalog-ai', 'brand-live', 'sport-live')]
    [string[]] $Demo,

    # Jev simulado (catalog-ai, brand-live e sport-live; usam portas próprias).
    [switch] $Fake,
    [switch] $Open,
    [switch] $Stop,
    [switch] $Status,
    [int] $TimeoutSec = 90
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$RunDir = Join-Path $Root '.run'
$PidFile = Join-Path $RunDir 'pids.json'
$SharedEnv = Join-Path $Root 'skill-validator\.env'

# Mesma configuração do .claude/launch.json.
$Demos = [ordered]@{
    'story-sizer'  = @{ Script = 'story-sizer-web'; Port = 8765; Args = @() }
    'sprint-radar' = @{ Script = 'sprint-radar';    Port = 8766; Args = @() }
    'catalog-ai'   = @{ Script = 'catalog-ai';      Port = 8770; FakePort = 8771; UsesEnvFile = $true }
    'sport-live'   = @{ Script = 'sport-live';      Port = 8780; FakePort = 8781; UsesEnvFile = $true }
    'brand-live'   = @{ Script = 'brand-live';      Port = 8775; FakePort = 8776; UsesEnvFile = $true }
}

function Test-Port([int] $Port) {
    $client = [System.Net.Sockets.TcpClient]::new()
    try { return $client.ConnectAsync('127.0.0.1', $Port).Wait(300) } catch { return $false } finally { $client.Dispose() }
}

function Read-Pids {
    if (Test-Path $PidFile) { return @(Get-Content $PidFile -Raw | ConvertFrom-Json) }
    return @()
}

function Write-Pids($Entries) {
    New-Item -ItemType Directory -Force -Path $RunDir | Out-Null
    ConvertTo-Json -InputObject @($Entries) -Depth 3 | Set-Content $PidFile -Encoding utf8
}

function Get-Selected {
    if ($Demo) { return $Demo }
    return @($Demos.Keys)
}

function Show-Status {
    $entries = Read-Pids
    foreach ($name in $Demos.Keys) {
        $cfg = $Demos[$name]
        $ports = @($cfg.Port) + @($cfg.FakePort | Where-Object { $_ })
        foreach ($port in $ports) {
            $up = Test-Port $port
            $entry = $entries | Where-Object { $_.Port -eq $port } | Select-Object -First 1
            $state = if ($up) { 'no ar' } else { 'parado' }
            $owner = if ($entry) { "pid $($entry.Pid)" } elseif ($up) { 'fora do script' } else { '' }
            if ($up -or $entry) {
                '{0,-14} {1,-6} {2,-8} http://127.0.0.1:{1}  {3}' -f $name, $port, $state, $owner
            }
        }
    }
}

function Stop-Demos {
    $entries = Read-Pids
    $selected = Get-Selected
    $keep = @()
    foreach ($entry in $entries) {
        if ($selected -notcontains $entry.Name) { $keep += $entry; continue }
        # /T derruba a árvore (uv -> python/uvicorn).
        & taskkill.exe /PID $entry.Pid /T /F 2>$null | Out-Null
        Write-Host "parado  $($entry.Name) (porta $($entry.Port))"
    }
    if ($keep.Count) { Write-Pids $keep } elseif (Test-Path $PidFile) { Remove-Item $PidFile }
}

if ($Status) { Show-Status; return }
if ($Stop) { Stop-Demos; return }

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'uv não encontrado no PATH. Instale: https://docs.astral.sh/uv/getting-started/installation/'
}

New-Item -ItemType Directory -Force -Path $RunDir | Out-Null
$entries = [System.Collections.Generic.List[object]]::new()
foreach ($e in Read-Pids) { $entries.Add($e) }
$started = @()

foreach ($name in Get-Selected) {
    $cfg = $Demos[$name]
    $port = $cfg.Port
    $uvArgs = @('run', '--directory', $name, $cfg.Script)

    if ($cfg.UsesEnvFile) {
        if ($Fake) {
            $port = $cfg.FakePort
            $uvArgs += @('--fake', '--port', $port)
        }
        else {
            # Usa o .env do próprio demo; senão, o compartilhado do skill-validator.
            $own = Join-Path $Root "$name\.env"
            $envFile = if (Test-Path $own) { $own } else { $SharedEnv }
            if (-not (Test-Path $envFile)) { Write-Warning "$name sem .env; pulando (use -Fake)"; continue }
            $uvArgs += @('--env-file', $envFile)
        }
    }
    elseif (-not (Test-Path (Join-Path $Root "$name\.env"))) {
        Write-Warning "$name sem .env (copie de .env.example)"
    }

    if (Test-Port $port) { Write-Host "já no ar  $name  http://127.0.0.1:$port"; continue }

    $log = Join-Path $RunDir "$name.log"
    $proc = Start-Process uv -ArgumentList $uvArgs -WorkingDirectory $Root -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $log -RedirectStandardError (Join-Path $RunDir "$name.err.log")

    $entries.Add([pscustomobject]@{ Name = $name; Pid = $proc.Id; Port = $port })
    $started += [pscustomobject]@{ Name = $name; Port = $port; Proc = $proc }
    Write-Host "subindo  $name (pid $($proc.Id), porta $port)"
}
Write-Pids $entries

# Espera cada demo abrir a porta (a primeira execução do uv pode instalar dependências).
$deadline = (Get-Date).AddSeconds($TimeoutSec)
foreach ($s in $started) {
    while (-not (Test-Port $s.Port) -and -not $s.Proc.HasExited -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 500
    }
    $url = "http://127.0.0.1:$($s.Port)"
    if (Test-Port $s.Port) {
        Write-Host "no ar    $($s.Name)  $url" -ForegroundColor Green
        if ($Open) { Start-Process $url }
    }
    else {
        Write-Host "falhou   $($s.Name)  veja .run\$($s.Name).err.log" -ForegroundColor Red
    }
}

if ($started) { Write-Host "`nPara derrubar: ./demos.ps1 -Stop" }
