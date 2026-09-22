@echo off
cd /d "%~dp0.."
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --clean --windowed --name ArrowDL --collect-all customtkinter -m arrowdl
echo Output: dist\ArrowDL\
