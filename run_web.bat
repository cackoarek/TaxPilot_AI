@echo off
rem ==============================================================================
rem TaxPilot AI - Launcher Serwera Webowego (Windows CMD / Explorer)
rem ==============================================================================

chcp 65001 >nul
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

rem Wykrywanie interpretera Python (.venv / venv / aktywny VIRTUAL_ENV / py / python)
set "PYTHON_BIN="
set "IS_PY_LAUNCHER=0"

if exist "%SCRIPT_DIR%.venv\Scripts\python.exe" (
    set "PYTHON_BIN=%SCRIPT_DIR%.venv\Scripts\python.exe"
) else if exist "%SCRIPT_DIR%venv\Scripts\python.exe" (
    set "PYTHON_BIN=%SCRIPT_DIR%venv\Scripts\python.exe"
) else if defined VIRTUAL_ENV (
    if exist "%VIRTUAL_ENV%\Scripts\python.exe" (
        set "PYTHON_BIN=%VIRTUAL_ENV%\Scripts\python.exe"
    ) else (
        set "PYTHON_BIN=python"
    )
) else (
    where py >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON_BIN=py"
        set "IS_PY_LAUNCHER=1"
    ) else (
        where python >nul 2>&1
        if !errorlevel! equ 0 (
            set "PYTHON_BIN=python"
        )
    )
)

if "%PYTHON_BIN%"=="" (
    echo.
    echo ==============================================================================
    echo [BLAD] Nie znaleziono interpretera Python ani srodowiska wirtualnego (.venv)!
    echo ==============================================================================
    echo Aby uruchomic TaxPilot AI, upewnij sie, ze Python jest zainstalowany:
    echo   https://www.python.org/
    echo Nastepnie w folderze projektu wykonaj:
    echo   python -m venv .venv
    echo   .venv\Scripts\pip install -r requirements.txt
    echo ==============================================================================
    echo.
    pause
    exit /b 1
)

echo ==================================================
echo   🚀 TaxPilot AI Web UI (Windows)
echo ==================================================
echo   📍 Adres:       http://127.0.0.1:8000
echo   📂 Katalog:     %SCRIPT_DIR%
if "%IS_PY_LAUNCHER%"=="1" (
    echo   💡 Interpreter: py -3
) else (
    echo   💡 Interpreter: %PYTHON_BIN%
)
echo ==================================================
echo   Nacisnij Ctrl+C, aby zatrzymac serwer.
echo ==================================================
echo.

if "%IS_PY_LAUNCHER%"=="1" (
    py -3 -m uvicorn src.web.app:app --reload --reload-dir src --reload-delay 1.0 --host 127.0.0.1 --port 8000 %*
) else (
    "%PYTHON_BIN%" -m uvicorn src.web.app:app --reload --reload-dir src --reload-delay 1.0 --host 127.0.0.1 --port 8000 %*
)

set EXIT_CODE=%errorlevel%
if %EXIT_CODE% neq 0 (
    echo.
    echo [INFO] Serwer zakonczyl dzialanie z kodem %EXIT_CODE%.
    pause
)
