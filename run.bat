#run file for windows

@echo off
setlocal enabledelayedexpansion

set "ROOT_DIR=%~dp0"
set "VENV_DIR=%ROOT_DIR%.venv"

if not exist "%VENV_DIR%" (
    py -3 -m venv "%VENV_DIR%"
)

call "%VENV_DIR%\Scripts\activate.bat"
python -m pip install --upgrade pip
python -m pip install -r "%ROOT_DIR%requirements.txt"

python "%ROOT_DIR%launcher.py"
