# Dot-source this in PowerShell to point the shell at Firebird for ONE window:
#   . "E:\WorkProjects\Info HR\scripts\fb_env.ps1"
# It sets variables for this window only; it does not touch .env. Default target is a FILE COPY (never db\MACSXE4DB.FDB).
# For the real database, set FIREBIRD_NAME / FIREBIRD_USER / FIREBIRD_PASSWORD / FIREBIRD_HOST yourself afterwards.
$env:DB_ENGINE = "firebird"
$env:FIREBIRD_NAME = "E:\WorkProjects\Info HR\db\work\MACS_COPY.FDB"
Set-Location "E:\WorkProjects\Info HR\app"
Write-Host "Firebird mode on, database: $env:FIREBIRD_NAME"
