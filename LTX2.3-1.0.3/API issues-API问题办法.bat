@echo off
chcp 65001 >nul
title LTX 本地显卡模式修复工具

echo ========================================
echo    LTX 本地显卡模式修复工具
echo ========================================
echo.

:: 检查管理员权限
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] 请右键选择"以管理员身份运行"此脚本
    pause
    exit /b 1
)

echo [1/2] 正在修改 VRAM 阈值...
set "policy_file=C:\Program Files\LTX Desktop\resources\backend\runtime_config\runtime_policy.py"

if exist "%policy_file%" (
    powershell -Command "(Get-Content '%policy_file%') -replace 'vram_gb &lt; 31', 'vram_gb &lt; 6' | Set-Content '%policy_file%'"
    echo     ^_^ VRAM 阈值已修改为 6GB
) else (
    echo     [!] 未找到 runtime_policy.py，请确认 LTX Desktop 已安装
)

echo.
echo [2/2] 正在清空 API Key...
set "settings_file=%USERPROFILE%\AppData\Local\LTXDesktop\settings.json"

if exist "%settings_file%" (
    powershell -Command "$content = Get-Content '%settings_file%' -Raw; $content = $content -replace '\"fal_api_key\": \"[^\"]*\"', '\"fal_api_key\": \"\"'; Set-Content -Path '%settings_file%' -Value $content -NoNewline"
    echo     ^_^ API Key 已清空
) else (
    echo     [!] 未找到 settings.json，首次运行后会自动创建
)

echo.
echo ========================================
echo    修复完成！请重启 LTX Desktop
echo ========================================
pause
