param(
    [switch]$ResetDistro,
    [switch]$SkipTests,
    [switch]$Offline
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Write-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][scriptblock]$Command
    )
    Write-Step $Label
    & $Command | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "$Label falhou com o código $LASTEXITCODE."
    }
}

function Set-EnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Value
    )
    $Text = if (Test-Path -LiteralPath $Path) { Get-Content -LiteralPath $Path -Raw } else { "" }
    $Pattern = "(?m)^\s*" + [regex]::Escape($Name) + "\s*=.*$"
    $Line = "$Name=$Value"
    if ($Text -match $Pattern) {
        $Text = [regex]::Replace($Text, $Pattern, $Line)
    }
    else {
        if ($Text.Length -gt 0 -and -not $Text.EndsWith("`n")) { $Text += "`r`n" }
        $Text += "$Line`r`n"
    }
    [IO.File]::WriteAllText($Path, $Text, [Text.UTF8Encoding]::new($false))
}

function Get-PlainText([Security.SecureString]$Value) {
    $Pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Pointer) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Pointer) }
}

$Root = (Resolve-Path $PSScriptRoot).Path
$Distro = "MatiasAI"
$Installer = Join-Path $Root "scripts\install_local_ai_wsl.sh"
$Worker = Join-Path $Root "scripts\local_ai_worker.py"
$Marker = Join-Path $Root "tools\wsl-ai-install.json"
$LogDir = Join-Path $Root ".matias-install-logs"
$Log = Join-Path $LogDir ("wsl-ai-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
$WslRoot = Join-Path $Root "tools\wsl"
$DistroRoot = Join-Path $WslRoot $Distro
$Rootfs = Join-Path $WslRoot "ubuntu-jammy-wsl.rootfs.tar.gz"

foreach ($Required in @($Installer, $Worker, (Join-Path $Root "backend\app\local_ai.py"))) {
    if (-not (Test-Path -LiteralPath $Required)) { throw "Ficheiro obrigatório em falta: $Required" }
}
New-Item -ItemType Directory -Force -Path $LogDir, $WslRoot, (Split-Path $Marker -Parent) | Out-Null

if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw "WSL2 não está instalado. Ativa-o como Administrador com: wsl.exe --install --no-distribution"
}

$Distros = @(& wsl.exe --list --quiet 2>$null) | ForEach-Object { $_.Trim([char]0).Trim() } | Where-Object { $_ }
if ($ResetDistro -and $Distros -contains $Distro) {
    Write-Step "Recriar a distro isolada $Distro (pedido explícito)"
    & wsl.exe --terminate $Distro 2>$null
    & wsl.exe --unregister $Distro
    if ($LASTEXITCODE -ne 0) { throw "Não foi possível remover a distro $Distro." }
    $Distros = @(& wsl.exe --list --quiet 2>$null) | ForEach-Object { $_.Trim([char]0).Trim() } | Where-Object { $_ }
}

if ($Distros -notcontains $Distro) {
    if (-not (Test-Path -LiteralPath $Rootfs)) {
        Write-Step "Descarregar Ubuntu 22.04 LTS para $Distro"
        & curl.exe -L --fail --retry 4 `
            "https://cloud-images.ubuntu.com/wsl/jammy/current/ubuntu-jammy-wsl-amd64-ubuntu22.04lts.rootfs.tar.gz" `
            -o $Rootfs
        if ($LASTEXITCODE -ne 0) { throw "Falhou o download da rootfs Ubuntu." }
    }
    New-Item -ItemType Directory -Force -Path $DistroRoot | Out-Null
    Invoke-Native "Criar distro WSL2 isolada $Distro" {
        & wsl.exe --import $Distro $DistroRoot $Rootfs --version 2
    }
}

Invoke-Native "Validar WSL2 e GPU NVIDIA" {
    & wsl.exe -d $Distro -u root -- bash -lc 'set -e; (command -v nvidia-smi >/dev/null && nvidia-smi) || /usr/lib/wsl/lib/nvidia-smi'
}

Set-EnvValue -Path (Join-Path $Root ".env") -Name "LOCAL_AI_RUNTIME" -Value "wsl"
Set-EnvValue -Path (Join-Path $Root ".env") -Name "LOCAL_AI_WSL_DISTRO" -Value $Distro

$InstallerWsl = (& wsl.exe -d $Distro -u root -- wslpath -a $Installer).Trim()
$WorkerWsl = (& wsl.exe -d $Distro -u root -- wslpath -a $Worker).Trim()
if (-not $InstallerWsl -or -not $WorkerWsl) { throw "Falhou a conversão dos caminhos Windows para WSL." }

$Token = ""
$LegacyTokenAvailable = $false
& wsl.exe -d $Distro -u root -- test -s /opt/matias-ai/model-cache/token
$LegacyTokenAvailable = $LASTEXITCODE -eq 0
$GatedWeightsMissing = $false
foreach ($ModelCachePath in @(
    "/opt/matias-ai/model-cache/hub/models--stabilityai--stable-point-aware-3d/snapshots",
    "/opt/matias-ai/model-cache/hub/models--stabilityai--stable-fast-3d/snapshots"
)) {
    & wsl.exe -d $Distro -u root -- test -d $ModelCachePath
    if ($LASTEXITCODE -ne 0) { $GatedWeightsMissing = $true }
}
if (-not $Offline -and -not $LegacyTokenAvailable -and $GatedWeightsMissing) {
    if ($env:HF_TOKEN) {
        $Token = $env:HF_TOKEN
    }
    else {
        $SecureToken = Read-Host "Token Hugging Face Read (usado só nesta execução)" -AsSecureString
        $Token = Get-PlainText $SecureToken
    }
    if (-not $Token.StartsWith("hf_")) { throw "Token Hugging Face inválido." }
}

Write-Step "Instalar/retomar SPAR3D Low VRAM e Stable Fast 3D"
$OfflineValue = if ($Offline) { "1" } else { "0" }
$PreviousPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    $Token | & wsl.exe -d $Distro -u root -- bash $InstallerWsl $WorkerWsl $OfflineValue 2>&1 |
        Tee-Object -FilePath $Log | Out-Host
    $InstallExit = $LASTEXITCODE
}
finally {
    $Token = $null
    Remove-Item Env:HF_TOKEN -ErrorAction SilentlyContinue
    $ErrorActionPreference = $PreviousPreference
}
if ($InstallExit -ne 0) { throw "A instalação Linux falhou (código $InstallExit). Log: $Log" }

$Manifest = [ordered]@{
    schema_version = 1
    installed_at = (Get-Date).ToString("o")
    runtime = "wsl"
    distro = $Distro
    model_cache = "/opt/matias-ai/model-cache"
    engines = [ordered]@{
        spar3d = [ordered]@{
            ready = $true
            repository = "/opt/matias-ai/stable-point-aware-3d"
            python = "/opt/matias-ai/spar3d-env/bin/python"
            low_vram = $true
            smoke_test = "/opt/matias-ai/smoke-spar3d.glb"
        }
        stable_fast_3d = [ordered]@{
            ready = $true
            repository = "/opt/matias-ai/stable-fast-3d"
            python = "/opt/matias-ai/sf3d-env/bin/python"
            low_vram = $false
            smoke_test = "/opt/matias-ai/smoke-sf3d.glb"
        }
    }
}
[IO.File]::WriteAllText($Marker, ($Manifest | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))

if (-not $SkipTests) {
    $Python = Join-Path $Root ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $Python)) { $Python = (Get-Command python -ErrorAction Stop).Source }
    $env:PYTHONPATH = Join-Path $Root "backend"
    Invoke-Native "Executar migrations" {
        Push-Location (Join-Path $Root "backend")
        try { & $Python -m alembic upgrade head } finally { Pop-Location }
    }
    Invoke-Native "Validar Python e pytest" {
        & $Python -m compileall -q (Join-Path $Root "backend") (Join-Path $Root "scripts")
        & $Python -m pytest -q (Join-Path $Root "backend\tests")
    }
    Invoke-Native "Validar TypeScript" {
        Push-Location (Join-Path $Root "frontend")
        try { & npx.cmd tsc --noEmit } finally { Pop-Location }
    }
    Invoke-Native "Gerar build de produção" {
        Push-Location (Join-Path $Root "frontend")
        try { & npm.cmd run build } finally { Pop-Location }
    }
}

Write-Host "`nINSTALAÇÃO LOCAL AI CONCLUÍDA." -ForegroundColor Green
Write-Host "SPAR3D: \\wsl$\$Distro\opt\matias-ai\smoke-spar3d.glb"
Write-Host "SF3D:   \\wsl$\$Distro\opt\matias-ai\smoke-sf3d.glb"
Write-Host "Log: $Log"
