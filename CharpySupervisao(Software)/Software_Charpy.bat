@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo ERRO: nao encontrei .venv\Scripts\python.exe nesta pasta.
    echo Coloque este arquivo na mesma pasta de main.py e da pasta .venv.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" "main.py"
if errorlevel 1 pause
