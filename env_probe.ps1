<#
.SYNOPSIS
  Collects an environment snapshot for OSGuard AI (and optionally exports every command name on this machine).

.EXAMPLE
  .\env_probe.ps1                          # writes env.json
  .\env_probe.ps1 -ExportCommands          # also writes kb\known_commands.txt (do this once, on a Windows 11 machine)
#>
param(
    [string]$Out = "env.json",
    [switch]$ExportCommands,
    [string]$CommandsOut = "kb\known_commands.txt"
)

$cv = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'
$os = Get-CimInstance Win32_OperatingSystem
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

# installed software (name -> version) from the registry uninstall keys
$paths = @(
    'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*'
)
$installed = [ordered]@{}
Get-ItemProperty $paths -ErrorAction SilentlyContinue |
    Where-Object { $_.DisplayName -and $_.DisplayVersion } |
    Sort-Object DisplayName |
    ForEach-Object { $installed[$_.DisplayName] = [string]$_.DisplayVersion }

$snapshot = [ordered]@{
    os_build           = "10.0.$($cv.CurrentBuild).$($cv.UBR)"
    edition            = $os.Caption
    is_admin           = $isAdmin
    powershell_version = $PSVersionTable.PSVersion.ToString()
    installed          = $installed
}

$snapshot | ConvertTo-Json -Depth 4 | Set-Content -Path $Out -Encoding UTF8
Write-Host "Wrote environment snapshot to $Out  (build $($snapshot.os_build), admin=$isAdmin, $($installed.Count) apps)"

if ($ExportCommands) {
    New-Item -ItemType Directory -Force -Path (Split-Path $CommandsOut) | Out-Null
    Get-Command -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty Name -Unique |
        Sort-Object |
        Set-Content -Path $CommandsOut -Encoding UTF8
    $n = (Get-Content $CommandsOut).Count
    Write-Host "Wrote $n command names to $CommandsOut"
}
