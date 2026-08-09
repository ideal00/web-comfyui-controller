@echo off
setlocal

set "ROOT=%~dp0"
set "PORTABLE=%ROOT%ComfyUI_windows_portable"
set "PYTHON=%PORTABLE%\python_embeded\python.exe"
set "PANEL=%ROOT%ComfyUI_Easy_Panel"
set "COMFY_ROOT=%PORTABLE%\ComfyUI"
set "EDGE=C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
set "COMFY_STARTED=0"

if not exist "%PYTHON%" (
  echo ERROR: ComfyUI portable Python was not found:
  echo %PYTHON%
  pause
  exit /b 1
)

if not exist "%PANEL%\easy_panel.py" (
  echo ERROR: Easy Panel was not found:
  echo %PANEL%\easy_panel.py
  pause
  exit /b 1
)

if not exist "%PANEL%\easy_panel_app\config.py" (
  echo ERROR: The modular Easy Panel backend is incomplete:
  echo %PANEL%\easy_panel_app\config.py
  pause
  exit /b 1
)

if not exist "%PANEL%\easy_panel_app\data\model_profiles.json" (
  echo ERROR: The Easy Panel model profile catalog is missing:
  echo %PANEL%\easy_panel_app\data\model_profiles.json
  pause
  exit /b 1
)

if not exist "%PANEL%\web\assets\js\panel.js" (
  echo ERROR: The modular Easy Panel frontend is incomplete:
  echo %PANEL%\web\assets\js\panel.js
  pause
  exit /b 1
)

if not exist "%PANEL%\web\assets\js\model-advanced.js" (
  echo ERROR: The Easy Panel advanced-model module is missing:
  echo %PANEL%\web\assets\js\model-advanced.js
  pause
  exit /b 1
)

set "EASY_PANEL_ROOT=%PANEL%"
set "EASY_PANEL_COMFY_ROOT=%COMFY_ROOT%"
set "EASY_PANEL_COMFY_INPUT=%COMFY_ROOT%\input"
set "EASY_PANEL_OUTPUT=%COMFY_ROOT%\output"
set "EASY_PANEL_LORA_DIR=%COMFY_ROOT%\models\loras"
set "EASY_PANEL_COMFY_URL=http://127.0.0.1:8188"
set "EASY_PANEL_HOST=127.0.0.1"
set "EASY_PANEL_PORT=8190"

netstat -ano | findstr /R /C:":8188 .*LISTENING" >nul
if errorlevel 1 (
  set "COMFY_STARTED=1"
  echo ComfyUI will run in this terminal: http://127.0.0.1:8188
) else (
  echo ComfyUI is already running on port 8188.
)

netstat -ano | findstr /R /C:":8190 .*LISTENING" >nul
if errorlevel 1 (
  echo Starting Easy Panel in the background: http://127.0.0.1:8190
  powershell -NoProfile -WindowStyle Hidden -Command "Start-Process -FilePath '%PYTHON%' -ArgumentList '-s','easy_panel.py' -WorkingDirectory '%PANEL%' -WindowStyle Hidden"
  call :wait_for_port 8190 20
) else (
  echo Easy Panel is already running on port 8190.
)

if exist "%EDGE%" (
  start "Easy Panel" "%EDGE%" --new-window "http://127.0.0.1:8190"
) else (
  start "" "http://127.0.0.1:8190"
)

if "%COMFY_STARTED%"=="1" (
  start "" powershell.exe -NoProfile -WindowStyle Hidden -Command "$deadline = (Get-Date).AddMinutes(3); while ((Get-Date) -lt $deadline) { if (Get-NetTCPConnection -LocalPort 8188 -State Listen -ErrorAction SilentlyContinue) { Start-Process 'http://127.0.0.1:8188'; exit }; Start-Sleep -Milliseconds 500 }"
) else (
  if exist "%EDGE%" (
    start "ComfyUI" "%EDGE%" "http://127.0.0.1:8188"
  ) else (
    start "" "http://127.0.0.1:8188"
  )
)

if "%COMFY_STARTED%"=="1" (
  pushd "%PORTABLE%"
  "%PYTHON%" -s ComfyUI\main.py --windows-standalone-build
  popd
)

endlocal
exit /b

:wait_for_port
set "WAIT_PORT=%~1"
set /a WAIT_SECONDS=%~2
:wait_for_port_loop
netstat -ano | findstr /R /C:":%WAIT_PORT% .*LISTENING" >nul
if not errorlevel 1 exit /b 0
if %WAIT_SECONDS% LEQ 0 exit /b 1
timeout /t 1 /nobreak >nul
set /a WAIT_SECONDS-=1
goto wait_for_port_loop
