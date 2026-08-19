@echo off
title Autonomous AI Trading Agent
color 0B

echo.
echo  ============================================
echo   Autonomous AI Trading Agent - Launcher
echo   Paper trading only - never real money
echo  ============================================
echo.

cd /d "%USERPROFILE%\Documents\autonomous-ai-trading-agent"
if not exist "app_ui.py" (
    echo ERROR: Project folder not found at:
    echo   %USERPROFILE%\Documents\autonomous-ai-trading-agent
    echo.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\activate.bat" (
    echo ERROR: Virtual environment missing.
    echo Run setup first, then try again.
    echo.
    pause
    exit /b 1
)

echo Activating environment...
call ".venv\Scripts\activate.bat"

echo Starting control panel...
echo A browser window will open in a few seconds.
echo.
echo KEEP THIS WINDOW OPEN while you use the agent.
echo Close this window (or press Ctrl+C) to stop the agent.
echo.

start "" cmd /c "timeout /t 6 /nobreak >nul && start http://localhost:8501"

streamlit run app_ui.py --server.headless true

echo.
echo Agent stopped.
pause
