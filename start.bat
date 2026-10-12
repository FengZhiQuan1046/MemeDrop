@echo off
cd /d "%~dp0"
if exist "MemeDrop.exe" (
    start "" "MemeDrop.exe"
    exit /b
)
if exist "dist\MemeDrop\MemeDrop.exe" (
    start "" "dist\MemeDrop\MemeDrop.exe" --library "%~dp0."
    exit /b
)
if not exist ".venv\Scripts\pythonw.exe" (
    echo Please run setup.bat first.
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "main.py"
