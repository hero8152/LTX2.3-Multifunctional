@echo off
title LTX-2 Cinematic Workstation

echo =========================================================
echo    LTX-2 Cinematic UI Booting...
echo =========================================================
echo.

set "LTX_PY=%USERPROFILE%\AppData\Local\LTXDesktop\python\python.exe"
set "LTX_UI_URL=http://127.0.0.1:4000/"

if exist "%LTX_PY%" (
    echo [SUCCESS] LTX Bundled Python environment detected!
    echo [INFO] Browser will open automatically when UI is ready...
    start "" powershell -NoProfile -WindowStyle Hidden -Command "$ProgressPreference='SilentlyContinue'; $deadline=(Get-Date).AddSeconds(60); while((Get-Date) -lt $deadline){ try { Invoke-WebRequest -UseBasicParsing '%LTX_UI_URL%' -TimeoutSec 2 | Out-Null; Start-Process '%LTX_UI_URL%'; exit 0 } catch { Start-Sleep -Seconds 1 } }"
    echo [INFO] Starting workspace natively...
    echo ---------------------------------------------------------
    "%LTX_PY%" main.py
    pause
    exit /b
)

python --version >nul 2>&1
if %errorlevel% equ 0 (
    echo [WARNING] LTX Bundled Python not found.
    echo [INFO] Browser will open automatically when UI is ready...
    start "" powershell -NoProfile -WindowStyle Hidden -Command "$ProgressPreference='SilentlyContinue'; $deadline=(Get-Date).AddSeconds(60); while((Get-Date) -lt $deadline){ try { Invoke-WebRequest -UseBasicParsing '%LTX_UI_URL%' -TimeoutSec 2 | Out-Null; Start-Process '%LTX_UI_URL%'; exit 0 } catch { Start-Sleep -Seconds 1 } }"
    echo [INFO] Falling back to global Python environment...
    echo ---------------------------------------------------------
    python main.py
    pause
    exit /b
)

echo [ERROR] FATAL: No Python interpreter found on this system.
echo [INFO] Please run install.bat to download and set up Python!
echo.
pause
