$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
& .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& .\.venv\Scripts\python.exe build.py
if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }
Write-Host 'Built: dist\MemeDrop\MemeDrop.exe. Keep the _internal folder beside the executable.'
