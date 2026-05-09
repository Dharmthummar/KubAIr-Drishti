@echo off
setlocal
echo ============================================================
echo   FINANCE AUTOMATION SYSTEM - PRODUCTION READY
echo ============================================================

:: Check for venv
if not exist "venv" (
    echo [INFO] Virtual environment not found. Running initial setup...
    powershell -ExecutionPolicy Bypass -File setup.ps1
)

:: Activate and Run
echo.
echo Starting the web server...
echo NOTE: Do not close this window.
echo.

:: Automatically open browser after a short delay
start "" http://localhost:5000

:: Run using venv python
venv\Scripts\python.exe app.py

if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Application crashed. Checking dependencies...
    powershell -ExecutionPolicy Bypass -File setup.ps1
    pause
)

pause
