@echo off
rem Igual que Ingeniero.bat pero con consola, para ver mensajes de error
cd /d "%~dp0"
"venv\Scripts\python.exe" main.py %*
pause
