@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Please run setup-studio.ps1 first.
  pause
  exit /b 1
)
start "DD Monitor Studio" ".venv\Scripts\pythonw.exe" "%~dp0studio_main.py"
