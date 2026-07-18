$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$PidFile = Join-Path $PSScriptRoot ".pids.json"
$PythonCandidates = @(
  (Join-Path $env:USERPROFILE "miniconda3\python.exe"),
  (Join-Path $env:USERPROFILE "anaconda3\python.exe")
)
$Python = $PythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $Python) { $Python = (Get-Command python.exe -ErrorAction SilentlyContinue).Source }
$Node = (Get-Command node.exe -ErrorAction SilentlyContinue).Source
$Next = Join-Path $Root "frontend\node_modules\next\dist\bin\next"
if (-not $Python) { throw "Python não foi encontrado." }
if (-not $Node) { throw "Node.js não foi encontrado." }
if (-not (Test-Path -LiteralPath $Next)) { throw "Dependências do frontend em falta. Executa npm install na pasta frontend." }

function Test-ServiceUrl {
  param([string]$Uri)

  try {
    $Response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 2
    return $Response.StatusCode -ge 200 -and $Response.StatusCode -lt 500
  } catch {
    return $false
  }
}

$Backend = $null
$Frontend = $null

if (-not (Test-ServiceUrl "http://127.0.0.1:8000/api/health")) {
  $Backend = Start-Process -FilePath $Python -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000" -WorkingDirectory (Join-Path $Root "backend") -WindowStyle Hidden -PassThru
}

if (-not (Test-ServiceUrl "http://127.0.0.1:3000")) {
  $Frontend = Start-Process -FilePath $Node -ArgumentList $Next, "dev" -WorkingDirectory (Join-Path $Root "frontend") -WindowStyle Hidden -PassThru
}

@{
  backend = if ($Backend) { $Backend.Id } else { $null }
  frontend = if ($Frontend) { $Frontend.Id } else { $null }
} | ConvertTo-Json | Set-Content -LiteralPath $PidFile -Encoding UTF8

$BackendReady = $false
$FrontendReady = $false
for ($Attempt = 0; $Attempt -lt 60; $Attempt++) {
  $BackendReady = Test-ServiceUrl "http://127.0.0.1:8000/api/health"
  $FrontendReady = Test-ServiceUrl "http://127.0.0.1:3000"
  if ($BackendReady -and $FrontendReady) { break }
  Start-Sleep -Milliseconds 500
}

if (-not $BackendReady) {
  throw "O backend não ficou pronto. Executa backend\app\diagnostics.py para obter detalhes."
}
if (-not $FrontendReady) {
  throw "A interface não ficou pronta. Confirma as dependências na pasta frontend."
}

$EdgeCandidates = @(
  (Join-Path ${env:ProgramFiles(x86)} "Microsoft\Edge\Application\msedge.exe"),
  (Join-Path $env:ProgramFiles "Microsoft\Edge\Application\msedge.exe")
)
$Edge = $EdgeCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1

if ($Edge) {
  Start-Process -FilePath $Edge -ArgumentList "--app=http://127.0.0.1:3000", "--start-maximized"
} else {
  Start-Process "http://127.0.0.1:3000"
}
