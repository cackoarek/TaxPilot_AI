<#
==============================================================================
TaxPilot AI - Launcher Serwera Webowego (Windows PowerShell)
==============================================================================
#>

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$PythonBin = $null
$UsePyLauncher = $false

if (Test-Path "$ScriptDir\.venv\Scripts\python.exe") {
    $PythonBin = "$ScriptDir\.venv\Scripts\python.exe"
} elseif (Test-Path "$ScriptDir\venv\Scripts\python.exe") {
    $PythonBin = "$ScriptDir\venv\Scripts\python.exe"
} elseif ($env:VIRTUAL_ENV -and (Test-Path "$env:VIRTUAL_ENV\Scripts\python.exe")) {
    $PythonBin = "$env:VIRTUAL_ENV\Scripts\python.exe"
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $PythonBin = "py"
    $UsePyLauncher = $true
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $PythonBin = "python"
}

if (-not $PythonBin) {
    Write-Host ""
    Write-Host "==============================================================================" -ForegroundColor Red
    Write-Host "[BŁĄD] Nie znaleziono interpretera Python ani środowiska wirtualnego (.venv)!" -ForegroundColor Red
    Write-Host "==============================================================================" -ForegroundColor Red
    Write-Host "Aby uruchomić TaxPilot AI, upewnij się, że Python jest zainstalowany:"
    Write-Host "  https://www.python.org/"
    Write-Host "Następnie w folderze projektu wykonaj:"
    Write-Host "  python -m venv .venv"
    Write-Host "  .venv\Scripts\pip install -r requirements.txt"
    Write-Host "=============================================================================="
    Write-Host ""
    Read-Host "Naciśnij Enter, aby zakończyć..."
    exit 1
}

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  🚀 TaxPilot AI Web UI (Windows PowerShell)" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  📍 Adres:       http://127.0.0.1:8000" -ForegroundColor Green
Write-Host "  📂 Katalog:     $ScriptDir"
if ($UsePyLauncher) {
    Write-Host "  💡 Interpreter: py -3"
} else {
    Write-Host "  💡 Interpreter: $PythonBin"
}
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  Naciśnij Ctrl+C, aby zatrzymać serwer."
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

if ($UsePyLauncher) {
    & py -3 -m uvicorn src.web.app:app --reload --reload-dir src --reload-delay 1.0 --host 127.0.0.1 --port 8000 @args
} else {
    & $PythonBin -m uvicorn src.web.app:app --reload --reload-dir src --reload-delay 1.0 --host 127.0.0.1 --port 8000 @args
}
