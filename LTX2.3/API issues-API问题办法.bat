@echo off
chcp 65001 >nul
title LTX Local GPU Fix Tool

echo ========================================
echo    LTX Local GPU Fix Tool
echo ========================================
echo.

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Please run as Administrator
    pause
    exit /b 1
)

echo [1/2] Reading LTX from shortcut...

:: Run PowerShell script to handle everything
powershell -ExecutionPolicy Bypass -File "%~dp0fix_ltx.ps1"

echo.
echo [2/2] Clearing API Key...
set "settings_file=%USERPROFILE%\AppData\Local\LTXDesktop\settings.json"

if exist "%settings_file%" (
    powershell -Command "(Get-Content '%settings_file%' -Raw) -replace '\"fal_api_key\": \"[^\"]*\"', '\"fal_api_key\": \"\"' | Set-Content '%settings_file%'"
    echo     ^_^ API Key cleared
) else (
    echo     [!] settings.json not found
)

echo.
echo ========================================
echo    Done! Please restart LTX Desktop
echo ========================================
pause
