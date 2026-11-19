@echo off
cd /d "%~dp0"
if exist "DD Monitor Studio.exe" (
  start "DD Monitor Studio" "%~dp0DD Monitor Studio.exe"
  exit /b 0
)
if not exist ".venv\Scripts\pythonw.exe" (
  echo Please run setup-studio.ps1 first.
  pause
  exit /b 1
)
start "DD Monitor Studio" ".venv\Scripts\pythonw.exe" "%~dp0studio_main.py"
