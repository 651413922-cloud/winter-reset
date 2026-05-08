@echo off
chcp 65001 >nul
title 小熊加速器 - VPN自动化脚本

:: 检查是否以管理员权限运行
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo ================================================
    echo  需要管理员权限才能控制鼠标点击
    echo ================================================
    echo.
    echo  正在请求管理员权限...
    echo  请在弹出的 UAC 对话框中点击"是"
    echo.
    
    :: 以管理员权限重新启动自身
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    
    :: 退出当前的非管理员窗口
    exit /b
)

echo ================================================
echo  小熊加速器 VPN 自动化脚本
echo  [以管理员权限运行]
echo ================================================
echo.

cd /d "%~dp0vpn_automation"

echo [INFO] 检查依赖...
pip install -r requirements.txt --quiet

echo.
echo [INFO] 启动脚本...
echo [INFO] 按 Ctrl+C 可随时停止
echo [INFO] 鼠标移到左上角可紧急停止
echo.
python main.py

echo.
echo [INFO] 脚本已退出
pause
