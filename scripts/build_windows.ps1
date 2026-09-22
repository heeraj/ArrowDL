# Build portable ArrowDL folder with PyInstaller (run on Windows in the project venv)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$py = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }
& $py -m pip install -U pip
& $py -m pip install -r requirements.txt pyinstaller
@"
from arrowdl.app import main
if __name__ == "__main__":
    main()
"@ | Set-Content -Encoding UTF8 _pyi_entry.py
& $py -m PyInstaller --noconfirm --clean --windowed --name ArrowDL --collect-all customtkinter --hidden-import httpx --hidden-import arrowdl --hidden-import arrowdl.ui --hidden-import arrowdl.ui.main_window --hidden-import arrowdl.ui.add_dialog --hidden-import arrowdl.ui.settings_dialog --hidden-import arrowdl.ui.delete_dialog --hidden-import arrowdl.ui.theme --paths . _pyi_entry.py
Write-Host "Output: dist\ArrowDL\"
