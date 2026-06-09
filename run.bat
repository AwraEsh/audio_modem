@echo off
setlocal enabledelayedexpansion
set "ROOT=%~dp0"
set "VENV=%ROOT%\.venv"

where py >nul 2>nul
if %errorlevel%==0 (
  set "PY=py -3"
) else (
  set "PY=python"
)

if not exist "%VENV%\Scripts\python.exe" (
  %PY% -m venv "%VENV%"
  if errorlevel 1 (
    echo Failed to create venv. Install Python 3 first.
    exit /b 1
  )
)

"%VENV%\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 exit /b 1

"%VENV%\Scripts\python.exe" -m pip install -r "%ROOT%requirements.txt"
if errorlevel 1 exit /b 1

"%VENV%\Scripts\python.exe" "%ROOT%launcher.py"
