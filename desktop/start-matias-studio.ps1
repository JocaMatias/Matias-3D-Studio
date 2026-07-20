param([switch]$NoLaunch)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$PidFile = Join-Path $PSScriptRoot ".pids.json"
$ExpectedApiVersion = "0.4.0"

function Get-ListeningProcessId {
  param([int]$Port)

  foreach ($Line in (& netstat.exe -ano -p tcp)) {
    if ($Line -match "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+(\d+)\s*$") {
      return [int]$Matches[1]
    }
  }
  return $null
}

function Get-BackendHealth {
  try {
    return Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/health" -TimeoutSec 2
  } catch {
    return $null
  }
}

function Get-FrontendResponse {
  try {
    return Invoke-WebRequest -Uri "http://127.0.0.1:3000" -UseBasicParsing -TimeoutSec 2
  } catch {
    return $null
  }
}

function Stop-ProcessTree {
  param([int]$ProcessId)

  if (-not $ProcessId) { return }
  # Reconstruction commands may own CUDA memory. Stopping only uvicorn can
  # leave COLMAP/Hunyuan running invisibly, so always close the validated
  # Studio process and its descendants as one tree.
  & taskkill.exe /PID $ProcessId /T /F 2>$null | Out-Null
}

# Prefer the process trees recorded by the previous Studio launch. They remain
# identifiable even when a broken frontend can no longer render the brand text
# used by the listener safety check.
if (Test-Path -LiteralPath $PidFile) {
  try {
    $KnownProcesses = Get-Content -LiteralPath $PidFile -Raw | ConvertFrom-Json
    Stop-ProcessTree ([int]$KnownProcesses.backend)
    Stop-ProcessTree ([int]$KnownProcesses.frontend)
  } catch {
    # A truncated PID file falls back to the validated port checks below.
  }
  Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
  Start-Sleep -Milliseconds 500
}

function Stop-StudioListener {
  param(
    [int]$Port,
    [ValidateSet("backend", "frontend")][string]$Kind
  )

  $Listener = Get-ListeningProcessId $Port
  if (-not $Listener) { return }

  if ($Kind -eq "backend") {
    $Health = Get-BackendHealth
    $IsStudio = $Health -and $Health.status -eq "ok" -and $null -ne $Health.reconstruction
  } else {
    $Response = Get-FrontendResponse
    $IsStudio = $Response -and $Response.Content -match "Matias 3D Studio"
  }

  if (-not $IsStudio) {
    throw "A porta $Port já está a ser usada por outra aplicação. Fecha-a ou altera a porta antes de iniciar o Matias 3D Studio."
  }

  Stop-ProcessTree $Listener
  for ($Attempt = 0; $Attempt -lt 20; $Attempt++) {
    if (-not (Get-ListeningProcessId $Port)) { return }
    Start-Sleep -Milliseconds 250
  }
  throw "Não foi possível terminar a versão anterior do Matias 3D Studio na porta $Port."
}

# Reinicia sempre os serviços do Studio. Assim o atalho nunca mistura uma
# interface nova com uma API antiga que permaneceu aberta em segundo plano.
Stop-StudioListener -Port 3000 -Kind frontend
Stop-StudioListener -Port 8000 -Kind backend

# O processo filho do compilador SWC pode sobreviver ao listener do Next.js e
# manter node_modules bloqueado. Identifica-o pelo módulo carregado dentro deste
# projeto, sem interferir com outros processos Node do utilizador ou do Codex.
$FrontendModulesRoot = Join-Path $Root "frontend\node_modules"
Get-Process node -ErrorAction SilentlyContinue | ForEach-Object {
  $NodeProcess = $_
  try {
    $UsesStudioModule = $NodeProcess.Modules | Where-Object {
      $_.FileName.StartsWith($FrontendModulesRoot, [System.StringComparison]::OrdinalIgnoreCase)
    } | Select-Object -First 1
    if ($UsesStudioModule) {
      Stop-Process -Id $NodeProcess.Id -Force -ErrorAction SilentlyContinue
    }
  } catch {
    # Processos protegidos que não pertencem ao Studio são ignorados.
  }
}
Start-Sleep -Milliseconds 500

$PythonCandidates = @(
  (Join-Path $Root ".venv\Scripts\python.exe"),
  (Join-Path $Root "backend\.venv\Scripts\python.exe"),
  (Join-Path $env:USERPROFILE "miniconda3\python.exe"),
  (Join-Path $env:USERPROFILE "anaconda3\python.exe")
)
$Python = $PythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $Python) { $Python = (Get-Command python.exe -ErrorAction SilentlyContinue).Source }
$Node = (Get-Command node.exe -ErrorAction SilentlyContinue).Source
$Npm = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
if (-not $Python) { throw "Python não foi encontrado." }
if (-not $Node) { throw "Node.js não foi encontrado." }
if (-not $Npm) { throw "npm não foi encontrado." }

$FrontendRoot = Join-Path $Root "frontend"
$DatabasePath = Join-Path $Root "backend\studio.db"
$StoragePath = Join-Path $Root "backend\storage"
$DatabaseUriPath = $DatabasePath.Replace("\", "/")
# Pin persistent state to one absolute location. This makes launching from the
# desktop shortcut, VS Code or another working directory behave identically.
$env:DATABASE_URL = "sqlite:///$DatabaseUriPath"
$env:STORAGE_ROOT = $StoragePath
$FrontendPackage = Get-Content -LiteralPath (Join-Path $FrontendRoot "package.json") -Raw | ConvertFrom-Json
$ExpectedNext = [string]$FrontendPackage.dependencies.next
$InstalledNextPath = Join-Path $FrontendRoot "node_modules\next\package.json"
$InstalledNext = if (Test-Path -LiteralPath $InstalledNextPath) {
  [string](Get-Content -LiteralPath $InstalledNextPath -Raw | ConvertFrom-Json).version
} else {
  ""
}

if ($InstalledNext -ne $ExpectedNext) {
  Push-Location $FrontendRoot
  try {
    & $Npm ci
    if ($LASTEXITCODE -ne 0) { throw "npm ci terminou com o código $LASTEXITCODE." }
  } finally {
    Pop-Location
  }
}

$Next = Join-Path $FrontendRoot "node_modules\next\dist\bin\next"
if (-not (Test-Path -LiteralPath $Next)) {
  throw "As dependências do frontend não ficaram disponíveis após npm ci."
}

$Backend = Start-Process -FilePath $Python -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000" -WorkingDirectory (Join-Path $Root "backend") -WindowStyle Hidden -PassThru
$Frontend = Start-Process -FilePath $Npm -ArgumentList "run", "dev" -WorkingDirectory $FrontendRoot -WindowStyle Hidden -PassThru

@{
  backend = $Backend.Id
  frontend = $Frontend.Id
  api_version = $ExpectedApiVersion
} | ConvertTo-Json | Set-Content -LiteralPath $PidFile -Encoding UTF8

$BackendReady = $false
$FrontendReady = $false
for ($Attempt = 0; $Attempt -lt 120; $Attempt++) {
  $Health = Get-BackendHealth
  $BackendReady = $Health -and
    $Health.api_version -eq $ExpectedApiVersion -and
    (@($Health.generation_modes) -join ",") -eq "ai_generation,reality_scan"
  $FrontendReady = $null -ne (Get-FrontendResponse)
  if ($BackendReady -and $FrontendReady) { break }
  Start-Sleep -Milliseconds 500
}

if (-not $BackendReady) {
  Stop-Process -Id $Backend.Id -Force -ErrorAction SilentlyContinue
  Stop-Process -Id $Frontend.Id -Force -ErrorAction SilentlyContinue
  throw "O backend atual não ficou pronto. Confirma as dependências Python e consulta o terminal para obter detalhes."
}
if (-not $FrontendReady) {
  Stop-Process -Id $Backend.Id -Force -ErrorAction SilentlyContinue
  Stop-Process -Id $Frontend.Id -Force -ErrorAction SilentlyContinue
  throw "A interface não ficou pronta. Confirma as dependências na pasta frontend."
}

$EdgeCandidates = @(
  (Join-Path ${env:ProgramFiles(x86)} "Microsoft\Edge\Application\msedge.exe"),
  (Join-Path $env:ProgramFiles "Microsoft\Edge\Application\msedge.exe")
)
$Edge = $EdgeCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1

if (-not $NoLaunch) {
  if ($Edge) {
    Start-Process -FilePath $Edge -ArgumentList "--app=http://127.0.0.1:3000", "--start-maximized"
  } else {
    Start-Process "http://127.0.0.1:3000"
  }
}
