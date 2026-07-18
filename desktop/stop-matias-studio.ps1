$PidFile = Join-Path $PSScriptRoot ".pids.json"
if (-not (Test-Path -LiteralPath $PidFile)) { Write-Host "O Matias 3D Studio não parece estar iniciado."; exit 0 }
$Processes = Get-Content -LiteralPath $PidFile -Raw | ConvertFrom-Json
foreach ($Id in @($Processes.backend, $Processes.frontend)) {
  if ($Id) { Stop-Process -Id $Id -ErrorAction SilentlyContinue }
}
Remove-Item -LiteralPath $PidFile -Force
Write-Host "Matias 3D Studio terminado."
