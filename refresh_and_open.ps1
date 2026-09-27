# refresh_and_open.ps1
#
# Desktop-shortcut entry point: regenerates fuel_map.html from whatever
# is the newest UpdatedFuelPrice-*.csv in Downloads, opens it locally,
# then commits and pushes it so the live copy at
# andymac76.github.io/fuel-price-map/fuel_map.html stays in sync - same
# pattern as Player Stats Hub's run_weekly_scrape.ps1. Non-fatal if the
# push fails (e.g. no internet), just logged and skipped.
# MAPTILER_KEY is read from your permanent user environment variable -
# not stored in any file here (fuel_map.html does bake the key into its
# JS source, same as any client-side map has to - that's why the key is
# domain-restricted to andymac76.github.io in the MapTiler account
# instead of being kept out of git).
# Console window waits for a keypress at the end so it doesn't vanish
# before you've seen the result.

$ProjectDir = "C:\Users\andym\OneDrive\Projects\Fuel Price Map"
$PythonExe  = "C:\Users\andym\AppData\Local\Programs\Python\Python314\python.exe"

Set-Location $ProjectDir

& $PythonExe "generate_fuel_map.py"

if (Test-Path (Join-Path $ProjectDir "fuel_map.html")) {
    Write-Output "`n=== Opening map ==="
    Start-Process (Join-Path $ProjectDir "fuel_map.html")

    Write-Output "`n=== Publishing fuel_map.html to GitHub Pages ==="
    try {
        git add fuel_map.html
        git diff --cached --quiet
        $hasChanges = ($LASTEXITCODE -ne 0)
        if ($hasChanges) {
            $Timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm"
            git commit -m "Auto-update fuel_map.html ($Timestamp)"
            git push
        } else {
            Write-Output "No changes to fuel_map.html - nothing to publish."
        }
    } catch {
        Write-Output "WARNING: publishing to GitHub failed: $_"
    }
}

Write-Output "`nDone - press any key to close this window."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
