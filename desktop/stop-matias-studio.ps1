$ErrorActionPreference = "Stop"
$PidFile = Join-Path $PSScriptRoot ".pids.json"
$FrontendPort = 3100
$BackendPort = 8100
$FrontendUrl = "http://127.0.0.1:$FrontendPort"
$BackendUrl = "http://127.0.0.1:$BackendPort"

function Get-ListeningProcessId {
  param([int]$Port)

  foreach ($Line in (& netstat.exe -ano -p tcp)) {
    if ($Line -match "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+(\d+)\s*$") {
      return [int]$Matches[1]
    }
  }
  return $null
}

function Stop-KnownProcess {
  param([object]$ProcessId)
  if ($ProcessId) {
    & taskkill.exe /PID ([int]$ProcessId) /T /F 2>$null | Out-Null
  }
}

if (Test-Path -LiteralPath $PidFile) {
  $Processes = Get-Content -LiteralPath $PidFile -Raw | ConvertFrom-Json
  Stop-KnownProcess $Processes.backend
  Stop-KnownProcess $Processes.frontend
}

# Next.js pode criar um processo filho que sobrevive ao processo registado.
# Termina também os listeners conhecidos, mas apenas se responderem como Studio.
$BackendListener = Get-ListeningProcessId $BackendPort
if ($BackendListener) {
  try {
    $Health = Invoke-RestMethod -Uri "$BackendUrl/api/health" -TimeoutSec 2
    if ($Health.status -eq "ok" -and $null -ne $Health.reconstruction) {
      Stop-KnownProcess $BackendListener
    }
  } catch {}
}

$FrontendListener = Get-ListeningProcessId $FrontendPort
if ($FrontendListener) {
  try {
    $Response = Invoke-WebRequest -Uri $FrontendUrl -UseBasicParsing -TimeoutSec 2
    if ($Response.Content -match "Matias 3D Studio") {
      Stop-KnownProcess $FrontendListener
    }
  } catch {}
}

Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
Write-Host "Matias 3D Studio terminado."
