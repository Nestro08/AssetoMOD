@echo off
rem Ingeniero de carrera: se conecta a Assetto Corsa. Los errores quedan en datos\ingeniero.log
cd /d "%~dp0"
start "" "venv\Scripts\pythonw.exe" main.py %*
