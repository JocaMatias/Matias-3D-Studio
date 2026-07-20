param(
    [switch]$ResetDistro,
    [switch]$SkipTests,
    [switch]$Offline
)

$Installer = Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..")).Path "install_matias_local_ai_wsl_final.ps1"
if (-not (Test-Path -LiteralPath $Installer)) {
    throw "Instalador WSL não encontrado: $Installer"
}

& $Installer -ResetDistro:$ResetDistro -SkipTests:$SkipTests -Offline:$Offline
exit $LASTEXITCODE
