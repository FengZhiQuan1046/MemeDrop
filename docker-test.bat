@echo off
cd /d "%~dp0"
docker compose run --build --rm test
if errorlevel 1 exit /b 1
docker compose run --rm smoke
if errorlevel 1 exit /b 1
echo Docker checks passed. Preview: .memedrop\docker-preview\.memedrop\smoke-test.png
