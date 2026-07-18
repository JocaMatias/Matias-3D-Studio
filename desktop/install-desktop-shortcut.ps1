$Root = Split-Path -Parent $PSScriptRoot
$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop "Matias 3D Studio.lnk"
$IconPath = Join-Path $PSScriptRoot "icon.ico"

if (-not (Test-Path -LiteralPath $IconPath)) {
  throw "O ícone da aplicação não foi encontrado em $IconPath."
}

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$Shortcut.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$(Join-Path $PSScriptRoot 'start-matias-studio.ps1')`""
$Shortcut.WorkingDirectory = $Root
$Shortcut.IconLocation = "$IconPath,0"
$Shortcut.Description = "Iniciar o Matias 3D Studio local"
$Shortcut.Save()
Write-Host "Atalho criado em $ShortcutPath"
