@echo off
rem ============================================================
rem  STEP 7 AI Agent - Dev Test Launcher
rem  Use system Python 3.11.9 + console window for debug output
rem  ============================================================
setlocal
cd /d "%~dp0"

rem Isolate user site-packages (Roaming\Python)
set PYTHONNOUSERSITE=1

set "PY=C:\Users\16650\AppData\Local\Programs\Python\Python311\python.exe"

if not exist "%PY%" (
    echo [ERROR] Python 3.11.9 not found: %PY%
    echo Please install Python 3.11.x or edit this script.
    pause
    exit /b 1
)

echo [INFO] Python: %PY%
echo [INFO] CWD: %CD%
echo [INFO] Launching main.py ...
echo.

"%PY%" main.py

echo.
echo [INFO] Process exited. Press any key to close.
pause >nul
endlocal
