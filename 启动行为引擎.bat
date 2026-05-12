@echo off
chcp 65001 >nul
title Behavior VPN Detector

:: Switch to script directory (works even after UAC elevation)
cd /d "%~dp0"
if errorlevel 1 (
    echo [ERROR] Failed to change to script directory
    pause
    exit /b 1
)

:: Check admin rights
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo ================================================
    echo  Admin rights required for packet capture
    echo ================================================
    echo.
    echo  Requesting admin privileges...
    echo  Please click "Yes" on the UAC prompt.
    echo.
    powershell -Command "Start-Process cmd -ArgumentList '/c \"%~f0\"' -Verb RunAs -WorkingDirectory '%~dp0'"
    exit /b
)

:: Double-check we're in the right place
if not exist "run_behavior_engine.py" (
    echo [ERROR] Cannot find run_behavior_engine.py in current directory
    echo Current: %CD%
    echo Expected: %~dp0
    pause
    exit /b 1
)

echo.
echo =======================================================
echo   Behavior VPN Detection Engine
echo   No keywords needed - detects VPN by traffic patterns
echo =======================================================
echo.
echo  [1/3] Checking Python dependencies...
if exist apivpn\requirements.txt (
    pip install -r apivpn\requirements.txt --quiet 2>nul
) else (
    echo  [WARN] requirements.txt not found, skipping
)
echo  [OK] Dependencies ready
echo.
echo  [2/3] Starting packet capture and behavior analysis...
echo  [3/3] Press Ctrl+C to stop at any time
echo.
echo  Detection methods: Traffic bursts / IP clustering /
echo  Graph topology shifts / Connection entropy changes
echo.

python run_behavior_engine.py

echo.
echo [INFO] Engine stopped
echo.
pause