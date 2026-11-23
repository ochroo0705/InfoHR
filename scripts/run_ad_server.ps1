# Starts the MACS Human Capital server on the ad database (Firebird copy) and publishes it through the Tailscale funnel.
#
#   powershell -ExecutionPolicy Bypass -File scripts\run_ad_server.ps1           start the server, open the funnel
#   powershell -ExecutionPolicy Bypass -File scripts\run_ad_server.ps1 -Build    run "npm run build" in web\ first, then start
#   powershell -ExecutionPolicy Bypass -File scripts\run_ad_server.ps1 -Stop     stop the server, close the funnel
#
# Three layers, one public address:
#   funnel   https://ochroo-1.tail9a560e.ts.net:10000/   ->  this PC, port 8015
#   front    127.0.0.1:8015   answers the React pages (web\dist), proxies every other request to Django
#   Django   127.0.0.1:8016   runserver, not public; only the front server calls it
# The welcome page is https://ochroo-1.tail9a560e.ts.net:10000/welcome (PUBLIC_WELCOME is set by this script only).
# -Build runs "npm run build" in web\. Run it again after any change under web\ (CSS, JS, React pages).
# Without -Build the script needs web\dist\ported.json from an earlier build.
# Django runs with --noreload: after a change to a .py file or a template, run this script again.
# The MCP server runs beside it on 127.0.0.1:8765 (the address Claude's "macs-hr" connection uses).
param([switch]$Stop, [switch]$Build)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$frontPort = 8015   # the front server; the funnel points here
$djangoPort = 8016  # Django, behind the front server (inner port)
$host_ = "ochroo-1.tail9a560e.ts.net"
$funnelPort = 10000
$mcpPort = 8765   # MCP server, local only (127.0.0.1), the address Claude's "macs-hr" connection uses

# Build (or check the build) before anything is stopped, so a failed build or a missing web\dist leaves the running site untouched.
if (-not $Stop) {
    if ($Build) {
        Push-Location (Join-Path $root "web")
        try {
            npm run build
            if ($LASTEXITCODE -ne 0) { throw "npm run build failed in web\. Fix the error above, then run this script again. The running server was not touched." }
        } finally {
            Pop-Location
        }
    } elseif (-not (Test-Path (Join-Path $root "web\dist\ported.json"))) {
        throw "web\dist is missing: run this script with -Build first"
    }
}

# Whatever is listening on the ports now (an earlier run of this script, or the previous version that ran Django on 8015) is stopped first.
Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
    Where-Object { $_.CommandLine -match "runserver ($frontPort|$djangoPort)" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
# The front server (an earlier run of this script) is stopped too.
Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
    Where-Object { $_.CommandLine -match "front_server" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
# The MCP server (an earlier run of this script) is stopped too.
Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
    Where-Object { $_.CommandLine -match "run_mcp" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

if ($Stop) {
    tailscale funnel --https=$funnelPort off
    "Stopped: front server on :$frontPort, Django on :$djangoPort, MCP on :$mcpPort and funnel :$funnelPort"
    return
}

Set-Location $root

$env:DB_ENGINE = "firebird"
$env:FIREBIRD_NAME = Join-Path $root "db\work\ad_demo.fdb"
$env:DJANGO_DEBUG = "true"
$env:PYTHONIOENCODING = "utf-8"
# Django refuses a login or any POST from an address that is not listed here (the 403 CSRF page).
$env:DJANGO_CSRF_TRUSTED_ORIGINS = "https://${host_}:${funnelPort},https://${host_}:8443,https://${host_}"

# InfoSystems only: the public welcome page and its demo-request form (app/welcome). Off everywhere else.
# Set for the Django process only; removed right after it starts, so the MCP process and the front server do not inherit it.
# The mail settings are not set here: django-environ reads them from .env.
$env:PUBLIC_WELCOME = "true"
$p = Start-Process -FilePath (Join-Path $root ".venv\Scripts\python.exe") `
    -ArgumentList "app/manage.py", "runserver", "$djangoPort", "--noreload" `
    -WorkingDirectory $root -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput ".tmp_runserver.log" -RedirectStandardError ".tmp_runserver.log.err"
Remove-Item Env:PUBLIC_WELCOME

# Front server: answers the React pages and proxies everything else to Django. Its settings are FRONT_* and DJANGO_URL,
# set for this process only (Start-Process copies the environment at launch, so Django above keeps its own copy).
$env:FRONT_HOST = "127.0.0.1"
$env:FRONT_PORT = "$frontPort"
$env:DJANGO_URL = "http://127.0.0.1:$djangoPort"
$env:WEB_DIST = Join-Path $root "web\dist"
$f = Start-Process -FilePath (Join-Path $root ".venv\Scripts\python.exe") `
    -ArgumentList "-m", "front_server" `
    -WorkingDirectory $root -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput ".tmp_front.log" -RedirectStandardError ".tmp_front.log.err"
Remove-Item Env:FRONT_HOST, Env:FRONT_PORT, Env:DJANGO_URL, Env:WEB_DIST

# MCP server on the same database. It is off unless MCP_ENABLED=true, so set it for this process only.
$env:MCP_ENABLED = "true"
$env:PYTHONUTF8 = "1"
$m = Start-Process -FilePath (Join-Path $root ".venv\Scripts\python.exe") `
    -ArgumentList "app/manage.py", "run_mcp" `
    -WorkingDirectory $root -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput ".tmp_mcp.log" -RedirectStandardError ".tmp_mcp.log.err"

Start-Sleep 15
if ($p.HasExited) { throw "The server stopped at once. Read .tmp_runserver.log.err in $root" }
if ($f.HasExited) { throw "The front server stopped at once. Read .tmp_front.log.err in $root" }
if ($m.HasExited) { throw "The MCP server stopped at once. Read .tmp_mcp.log.err in $root" }

# Public (Funnel). For tailnet-only access use "tailscale serve" instead of "tailscale funnel".
tailscale funnel --bg --https=$funnelPort "http://127.0.0.1:$frontPort"
"Up: https://${host_}:${funnelPort}/   (funnel -> front server :$frontPort -> Django :$djangoPort)"
"Welcome page: https://${host_}:${funnelPort}/welcome"
"Logs: .tmp_runserver.log.err (Django), .tmp_front.log.err (front server)"
"MCP: http://127.0.0.1:${mcpPort}/mcp   (logs: .tmp_mcp.log.err)"
