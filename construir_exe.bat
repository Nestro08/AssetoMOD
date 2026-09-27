@echo off
rem Crea dist\IngenieroCarrera\IngenieroCarrera.exe (no hace falta Python para usarlo).
rem Requiere las librerías de requirements.txt (incluida pyinstaller) en el venv.
cd /d "%~dp0"
"venv\Scripts\python.exe" -m PyInstaller --noconfirm --windowed --name IngenieroCarrera ^
  --collect-all vosk --collect-data piper --collect-binaries piper --collect-binaries onnxruntime ^
  --collect-all sounddevice --hidden-import pythoncom --hidden-import win32com.client ^
  --hidden-import ingeniero.analisis_ui --hidden-import ingeniero.estrategia_ui --hidden-import ingeniero.ajustes_ui ^
  --hidden-import ingeniero.web --hidden-import ingeniero.voz_neuronal ^
  --exclude-module piper.train --exclude-module onnxruntime.quantization --exclude-module onnxruntime.transformers ^
  --exclude-module win32com.test --exclude-module test --exclude-module pytest ^
  main.py
if errorlevel 1 goto error
rem Modelos de voz y app de AC van al lado del .exe
xcopy /E /I /Y model\vosk-model-small-es-0.42 "dist\IngenieroCarrera\model\vosk-model-small-es-0.42" >nul
if exist model\piper xcopy /E /I /Y model\piper "dist\IngenieroCarrera\model\piper" >nul
xcopy /E /I /Y app_ac "dist\IngenieroCarrera\app_ac" >nul
copy /Y README.md "dist\IngenieroCarrera\" >nul
echo.
echo Listo: dist\IngenieroCarrera\IngenieroCarrera.exe
pause
exit /b 0
:error
echo Error construyendo el ejecutable.
pause
exit /b 1
