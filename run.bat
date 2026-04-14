@echo off
setlocal
cd /d "%~dp0"

if defined VIRTUAL_ENV if exist "%VIRTUAL_ENV%\Scripts\python.exe" (
    "%VIRTUAL_ENV%\Scripts\python.exe" "%~dp0__main__.py" --gui
) else if exist "%~dp0.venvs\global\Scripts\python.exe" (
    "%~dp0.venvs\global\Scripts\python.exe" "%~dp0__main__.py" --gui
) else if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" "%~dp0__main__.py" --gui
) else (
    python "%~dp0__main__.py" --gui
)