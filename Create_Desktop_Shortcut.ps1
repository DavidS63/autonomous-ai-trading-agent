# Creates a Desktop shortcut that runs Start_Trading_Agent.bat
$ErrorActionPreference = "Stop"

$project = Join-Path $env:USERPROFILE "Documents\autonomous-ai-trading-agent"
$bat = Join-Path $project "Start_Trading_Agent.bat"
$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "Trading Agent.lnk"

if (-not (Test-Path $bat)) {
    Write-Host "ERROR: Cannot find $bat"
    Write-Host "Make sure the project is in Documents\autonomous-ai-trading-agent"
    exit 1
}

$wsh = New-Object -ComObject WScript.Shell
$sc = $wsh.CreateShortcut($shortcutPath)
$sc.TargetPath = $bat
$sc.WorkingDirectory = $project
$sc.WindowStyle = 1
$sc.Description = "Start Autonomous AI Trading Agent (paper trading control panel)"
$sc.IconLocation = "%SystemRoot%\System32\shell32.dll,165"
$sc.Save()

Write-Host ""
Write-Host "Desktop shortcut created:"
Write-Host "  $shortcutPath"
Write-Host ""
Write-Host "Double-click 'Trading Agent' on your Desktop to start."
Write-Host ""
