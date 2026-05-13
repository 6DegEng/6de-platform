@echo off
REM ===========================================================================
REM 6DE Company Platform -- Launcher Build Script
REM ===========================================================================
REM Builds a standalone "6DE Platform.exe" via PyInstaller.
REM
REM Run this once after pulling a new launcher.py.  The resulting .exe is in
REM the dist\ subfolder; copy it next to streamlit_app\ (i.e. into this
REM folder) to use it.  The .exe is dependency-free and works on any machine
REM that has Python + the platform requirements installed.
REM ===========================================================================

setlocal

REM Make sure we're running from this script's directory regardless of cwd.
cd /d "%~dp0"

REM Verify Python is on PATH.
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python is not on your PATH.  Install Python 3.11+ first.
    exit /b 1
)

REM Install / upgrade PyInstaller if missing.  Idempotent.
python -m pip install --upgrade pyinstaller >nul
if errorlevel 1 (
    echo [ERROR] Failed to install PyInstaller.
    exit /b 1
)

REM Clean any previous build artefacts so we don't ship stale binaries.
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist

echo Building 6DE Platform.exe ...
python -m PyInstaller launcher.spec --clean --noconfirm
if errorlevel 1 (
    echo [ERROR] PyInstaller failed.  See output above.
    exit /b 1
)

echo.
echo [OK] Built: dist\6DE Platform.exe
echo.
echo Next step: copy "dist\6DE Platform.exe" into this folder (next to
echo            streamlit_app\) and double-click it to launch.
echo.

endlocal
