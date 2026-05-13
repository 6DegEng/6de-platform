@echo off
REM ===========================================================================
REM 6DE Company Platform -- Quick Launcher (no .exe build required)
REM ===========================================================================
REM Double-click this file to start the platform.  Uses pythonw so no cmd
REM window stays open.  Equivalent to running the compiled "6DE Platform.exe"
REM but works without a PyInstaller build step.
REM ===========================================================================

cd /d "%~dp0"

REM Prefer pythonw (no console).  Fall back to python if pythonw missing.
where pythonw >nul 2>nul
if not errorlevel 1 (
    start "" pythonw launcher.py
    exit /b 0
)

where python >nul 2>nul
if not errorlevel 1 (
    start "" python launcher.py
    exit /b 0
)

echo [ERROR] Python is not on your PATH.  Install Python 3.11+ first, then run:
echo         pip install -r requirements.txt
pause
exit /b 1
