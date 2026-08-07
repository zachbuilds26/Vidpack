# restart.ps1 ??? restart the vidpack dev server fast and reliably.
# Uses netstat (fast) instead of Get-NetTCPConnection (which can hang for
# minutes), waits for the port to actually free up, starts uvicorn, then
# polls /api/health until it answers.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$log = Join-Path $env:TEMP "opencode\uvicorn8000.log"
$err = Join-Path $env:TEMP "opencode\uvicorn8000.err.log"
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $log) | Out-Null

# 1. Kill whatever is listening on :8000
$listeners = netstat -ano -p tcp | Select-String ":8000\s+.*LISTENING"
foreach ($line in $listeners) {
    $procId = ($line.ToString().Trim() -split "\s+")[-1]
    if ($procId -and $procId -ne "0") {
        Stop-Process -Id ([int]$procId) -Force -ErrorAction SilentlyContinue
        Write-Output "stopped pid $procId"
    }
}

# 2. Wait until the port is actually free (old process may linger)
for ($i = 0; $i -lt 40; $i++) {
    $still = netstat -ano -p tcp | Select-String ":8000\s+.*LISTENING"
    if (-not $still) { break }
    Start-Sleep -Milliseconds 500
}
$busy = netstat -ano -p tcp | Select-String ":8000\s+.*LISTENING"
if ($busy) {
    Write-Output "port 8000 still in use ??? aborting"
    exit 1
}

# 3. Start fresh
Start-Process -FilePath (Join-Path $root ".venv\Scripts\python.exe") `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000" `
    -WorkingDirectory $root -WindowStyle Hidden `
    -RedirectStandardOutput $log -RedirectStandardError $err

# 4. Poll /api/health until it answers (max ~20s)
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $h = curl.exe -s -m 2 http://127.0.0.1:8000/api/health
        if ($h) { Write-Output $h; exit 0 }
    } catch { }
}
Write-Output "server did not come up ??? check $err"
exit 1

