@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" python -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo Ready. Double-click start.bat to launch MemeDrop.
pause
exit /b 0
:failed
echo Setup failed. Python 3.9 or later and internet access are required.
pause
exit /b 1
