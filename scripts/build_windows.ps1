# Build portable ArrowDL folder with PyInstaller (run on Windows in the project venv)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --clean --windowed --name ArrowDL --collect-all customtkinter -m arrowdl
Write-Host "Output: dist\ArrowDL\"
