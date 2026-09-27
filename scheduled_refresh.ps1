# scheduled_refresh.ps1
#
# Unattended entry point for Windows Task Scheduler (see refresh_and_open.ps1
# for the interactive desktop-shortcut version - opens a browser and waits
# for a keypress, neither of which belong in a task with nobody watching).
#
# Regenerates fuel_map.html via the Fuel Finder API (FUEL_FINDER_CLIENT_ID/
# SECRET are already set as permanent user environment variables, so this
# runs with zero manual input) and publishes it to GitHub Pages if it
# changed. Logs to a timestamped file so a failed run is easy to check on
# later rather than needing to be watched live.

$env:PYTHONIOENCODING = "utf-8"

$ProjectDir = "C:\Users\andym\OneDrive\Projects\Fuel Price Map"
$PythonExe  = "C:\Users\andym\AppData\Local\Programs\Python\Python314\python.exe"
$LogDir     = Join-Path $ProjectDir "logs"

if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir | Out-Null
}

$Timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm"
$LogFile   = Join-Path $LogDir "refresh_$Timestamp.log"

Set-Location $ProjectDir

Write-Output "=== Starting scheduled refresh: $Timestamp ===" | Tee-Object -FilePath $LogFile -Append

& $PythonExe "generate_fuel_map.py" 2>&1 | Tee-Object -FilePath $LogFile -Append

if (Test-Path (Join-Path $ProjectDir "fuel_map.html")) {
    Write-Output "=== Publishing fuel_map.html to GitHub Pages ===" | Tee-Object -FilePath $LogFile -Append
    try {
        git add fuel_map.html 2>&1 | Tee-Object -FilePath $LogFile -Append
        git diff --cached --quiet
        $hasChanges = ($LASTEXITCODE -ne 0)
        if ($hasChanges) {
            git commit -m "Auto-update fuel_map.html ($Timestamp)" 2>&1 | Tee-Object -FilePath $LogFile -Append
            git push 2>&1 | Tee-Object -FilePath $LogFile -Append
        } else {
            Write-Output "No changes to fuel_map.html - nothing to publish." | Tee-Object -FilePath $LogFile -Append
        }
    } catch {
        Write-Output "WARNING: publishing to GitHub failed: $_" | Tee-Object -FilePath $LogFile -Append
    }
} else {
    Write-Output "WARNING: fuel_map.html wasn't written - generate_fuel_map.py must have failed." | Tee-Object -FilePath $LogFile -Append
}

Write-Output "=== Done: $(Get-Date -Format 'yyyy-MM-dd_HH-mm') ===" | Tee-Object -FilePath $LogFile -Append
