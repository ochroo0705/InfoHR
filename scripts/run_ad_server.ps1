# Starts the Django server on the ad database (Firebird copy) and publishes it through the Tailscale funnel.
#
#   powershell -ExecutionPolicy Bypass -File scripts\run_ad_server.ps1          start the server, open the funnel
#   powershell -ExecutionPolicy Bypass -File scripts\run_ad_server.ps1 -Stop    stop the server, close the funnel
#
# Public address: https://ochroo-1.tail9a560e.ts.net:10000/   (funnel port 10000 -> this PC, port 8015)
# The server runs with --noreload: after a change to a template, a view or any .py file, run this script again.
# (CSS and JS files are read from disk on every request and need no restart.)
param([switch]$Stop)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$port = 8015
$host_ = "ochroo-1.tail9a560e.ts.net"
$funnelPort = 10000

# Whatever is listening on the port now (an earlier run of this script, or the old server) is stopped first.
Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
    Where-Object { $_.CommandLine -match "runserver $port" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

if ($Stop) {
    tailscale funnel --https=$funnelPort off
    "Stopped: server on :$port and funnel :$funnelPort"
    return
}

Set-Location $root
$env:DB_ENGINE = "firebird"
$env:FIREBIRD_NAME = Join-Path $root "db\work\ad_demo.fdb"
$env:DJANGO_DEBUG = "true"
$env:PYTHONIOENCODING = "utf-8"
# Django refuses a login or any POST from an address that is not listed here (the 403 CSRF page).
$env:DJANGO_CSRF_TRUSTED_ORIGINS = "https://${host_}:${funnelPort},https://${host_}:8443,https://${host_}"

$p = Start-Process -FilePath (Join-Path $root ".venv\Scripts\python.exe") `
    -ArgumentList "app/manage.py", "runserver", "$port", "--noreload" `
    -WorkingDirectory $root -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput ".tmp_runserver.log" -RedirectStandardError ".tmp_runserver.log.err"

Start-Sleep 15
if ($p.HasExited) { throw "The server stopped at once. Read .tmp_runserver.log.err in $root" }

# Public (Funnel). For tailnet-only access use "tailscale serve" instead of "tailscale funnel".
tailscale funnel --bg --https=$funnelPort "http://127.0.0.1:$port"
"Up: https://${host_}:${funnelPort}/   (logs: .tmp_runserver.log.err)"
