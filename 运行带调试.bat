@echo off
chcp 65001 >nul
title 以 Debug 文件夹运行 VPN 自动化

:: 请求管理员权限（若未以管理员运行则提升）
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo ================================================
    echo  需要管理员权限来执行点击操作（UAC 提示将出现）
    echo ================================================
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

echo ================================================
echo  使用 debug 文件夹运行 VPN 自动化
echo ================================================
echo.

:: 项目根目录（本 .bat 所在目录）
set ROOT=%~dp0
cd /d "%ROOT%"

:: 确保目录存在
if not exist "%ROOT%vpn_automation\debug\" (
    echo [INFO] 创建 debug 文件夹...
    mkdir "%ROOT%vpn_automation\debug\"
) else (
    echo [INFO] debug 文件夹已存在
)

:: 将 debug 文件夹内的 png 覆盖到 screenshots（如果有）
echo [INFO] 将 debug 文件复制到 screenshots（若存在）...
if exist "%ROOT%vpn_automation\debug\*.png" (
    copy /Y "%ROOT%vpn_automation\debug\*.png" "%ROOT%vpn_automation\screenshots\" >nul
    echo [INFO] 复制完成
) else (
    echo [INFO] debug 文件夹中未找到 PNG 文件，跳过复制
)

cd /d "%ROOT%vpn_automation"

echo [INFO] 安装/检查依赖（若已安装会快速跳过）...
pip install -r requirements.txt --quiet

echo.
echo [INFO] 启动主脚本 main.py（按 Ctrl+C 可中止）...
python main.py

echo.
echo [INFO] 脚本执行结束
pause
