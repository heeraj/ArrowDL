@echo off
setlocal
cd /d "%~dp0.."
if not exist "dist\ArrowDL\ArrowDL.exe" (
  echo Missing dist\ArrowDL\ArrowDL.exe — run build_windows.bat first
  exit /b 1
)
if not exist "dist\release" mkdir dist\release
powershell -NoProfile -Command "Compress-Archive -Path 'dist\ArrowDL\*' -DestinationPath 'dist\release\ArrowDL-0.1.0-alpha-windows-portable.zip' -Force"
echo Created dist\release\ArrowDL-0.1.0-alpha-windows-portable.zip
dir dist\release\
