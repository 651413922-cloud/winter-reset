@echo off
chcp 65001 >nul
title 网络行为分析引擎 - Behavior VPN Detector

:: 检查管理员权限
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo ================================================
    echo  需要管理员权限才能抓包
    echo ================================================
    echo.
    echo  正在请求管理员权限...
    echo  请在弹出的 UAC 对话框中点击"是"
    echo.
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

echo ╔══════════════════════════════════════════════════════════════╗
echo ║    行为级 VPN 识别引擎 - Behavior Detection Engine         ║
echo ║    无需 VPN 关键词 · 基于流量结构变化判断                  ║
echo ╚══════════════════════════════════════════════════════════════╝
echo.

:: 检查依赖
echo [INFO] 检查 Python 模块依赖...
python -c "import apivpn" 2>nul
if %errorLevel% neq 0 (
    echo [INSTALL] 首次运行，安装依赖...
    python -m pip install -r apivpn\requirements.txt --quiet
    echo [INSTALL] 完成
) else (
    echo [INFO] 依赖已就绪
)

echo.
echo [INFO] 启动行为分析引擎...
echo [INFO] 按 Ctrl+C 可随时停止
echo [INFO] 引擎检测原理：流量爆发 / IP聚簇 / 图谱转移 / 拓扑收缩
echo.

:: 用新的行为引擎启动（bridge模式）
python run_behavior_engine.py

echo.
echo [INFO] 分析引擎已退出
pause