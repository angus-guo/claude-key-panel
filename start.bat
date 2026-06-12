@echo off
title Claude Key Panel

echo.
echo   Claude Key Usage Panel
echo   ======================
echo.

REM -- Check Python --
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo   [ERROR] Python 3 not found.
    echo   Download: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

REM -- Start proxy --
echo   [1/2] Starting local proxy on localhost:8899...
start "Claude Proxy" /MIN python "%~dp0proxy.py"

echo   Waiting for proxy to be ready...
timeout /t 3 /nobreak >nul

REM -- Open HTML dashboard --
set HTML=%~dp0claude-key-panel.html
echo   [2/2] Opening dashboard...

REM Try Chrome first, then Edge, then default
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    echo         Using Chrome...
    start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" "%HTML%"
    goto :done
)
if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" (
    echo         Using Chrome...
    start "" "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" "%HTML%"
    goto :done
)
if exist "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" (
    echo         Using Edge...
    start "" "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" "%HTML%"
    goto :done
)

REM Fallback: let Windows decide
echo         Using default browser...
start "" "%HTML%"

:done
echo.
echo   ==============================================
echo   If the page shows JSON instead of the panel,
echo   please manually open this file in Chrome:
echo   %HTML%
echo   ==============================================
echo.
echo   Close "Claude Proxy" window to stop proxy.
echo.
pause
