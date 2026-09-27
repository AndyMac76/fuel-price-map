# refresh_and_open.ps1
#
# Desktop-shortcut entry point: regenerates fuel_map.html from whatever
# is the newest UpdatedFuelPrice-*.csv in Downloads, then opens it.
# MAPTILER_KEY is read from your permanent user environment variable -
# not stored in any file here. Console window waits for a keypress at
# the end so it doesn't vanish before you've seen the result.

$ProjectDir = "C:\Users\andym\OneDrive\Projects\Fuel Price Map"
$PythonExe  = "C:\Users\andym\AppData\Local\Programs\Python\Python314\python.exe"

Set-Location $ProjectDir

& $PythonExe "generate_fuel_map.py"

if (Test-Path (Join-Path $ProjectDir "fuel_map.html")) {
    Write-Output "`n=== Opening map ==="
    Start-Process (Join-Path $ProjectDir "fuel_map.html")
}

Write-Output "`nDone - press any key to close this window."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
