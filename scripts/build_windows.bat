@echo off
setlocal
cd /d "%~dp0.."

if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else if exist "%LocalAppData%\Programs\Python\Python312\python.exe" (
  set "PY=%LocalAppData%\Programs\Python\Python312\python.exe"
) else (
  set "PY=python"
)

echo Using: %PY%
"%PY%" -m pip install -U pip
"%PY%" -m pip install -r requirements.txt pyinstaller

REM Entry script for PyInstaller (package -m form is not valid for PyInstaller)
echo from arrowdl.app import main> _pyi_entry.py
echo if __name__ == "__main__":>> _pyi_entry.py
echo     main()>> _pyi_entry.py

"%PY%" -m PyInstaller --noconfirm --clean --windowed --name ArrowDL --collect-all customtkinter --hidden-import httpx --hidden-import arrowdl --hidden-import arrowdl.ui --hidden-import arrowdl.ui.main_window --hidden-import arrowdl.ui.add_dialog --hidden-import arrowdl.ui.settings_dialog --hidden-import arrowdl.ui.delete_dialog --hidden-import arrowdl.ui.theme --paths . _pyi_entry.py

if errorlevel 1 (
  echo BUILD FAILED
  exit /b 1
)

echo Output: dist\ArrowDL\
dir /b dist\ArrowDL\
