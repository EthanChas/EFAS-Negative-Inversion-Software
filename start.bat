@echo off
rem Starts the PhotoEditor from source with no console window.
rem Run "start.bat console" to keep a console attached (errors and prints show there).
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
if /i "%~1"=="console" (
    python -m photoeditor
) else (
    start "" pythonw -m photoeditor
)
