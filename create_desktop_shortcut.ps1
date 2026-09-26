# Creates a Standalone Native App Desktop Shortcut
$WshShell = New-Object -comObject WScript.Shell
$DesktopPath = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $DesktopPath "ArgusTraffic AI.lnk"
$AppDir = Split-Path -Parent $MyInvocation.MyCommand.Path

$Shortcut = $WshShell.CreateShortcut($ShortcutPath)

# Use Edge or Chrome standalone App Window mode
$EdgePath = "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
if (-not (Test-Path $EdgePath)) {
    $EdgePath = "${env:ProgramFiles}\Microsoft\Edge\Application\msedge.exe"
}

if (Test-Path $EdgePath) {
    $Shortcut.TargetPath = $EdgePath
    $Shortcut.Arguments = '--app="http://127.0.0.1:8080" --window-size=1440,900 --user-data-dir="' + $env:TEMP + '\ArgusTrafficProfile"'
} else {
    $Shortcut.TargetPath = Join-Path $AppDir "Launch_Native_App.bat"
}

$Shortcut.WorkingDirectory = $AppDir
$Shortcut.Description = "ArgusTraffic AI - Enterprise Autonomous Traffic Intelligence Platform"
$Shortcut.Save()

Write-Host "[✓] Desktop shortcut created successfully on your Windows Desktop!"
