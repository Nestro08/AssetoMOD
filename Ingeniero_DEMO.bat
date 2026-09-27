@echo off
rem Ingeniero de carrera en modo demo (sin el juego)
cd /d "%~dp0"
start "" "venv\Scripts\pythonw.exe" main.py --demo %*
