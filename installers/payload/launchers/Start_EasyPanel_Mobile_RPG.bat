@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Easy Panel - Mobile RPG Mode

set "HERE=%~dp0"
for %%I in ("%HERE%..") do set "PANEL=%%~fI"
set "BASE=%PANEL%\.."
set "PORTABLE=%BASE%\ComfyUI_windows_portable"
set "PYTHON=%PORTABLE%\python_embeded\python.exe"
set "COMFY_ROOT=%PORTABLE%\ComfyUI"

if not exist "%PANEL%\easy_panel.py" (
  echo ERROR: easy_panel.py was not found at:
  echo %PANEL%\easy_panel.py
  pause
  exit /b 1
)

if not exist "%PYTHON%" (
  where python >nul 2>nul
  if errorlevel 1 (
    echo ERROR: ComfyUI portable Python and system Python were both not found.
    echo Expected: %PYTHON%
    pause
    exit /b 1
  )
  set "PYTHON=python"
)

if not exist "%PANEL%\rpg_mobile_token.txt" (
  powershell.exe -NoProfile -Command "$bytes=New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes); $token=-join ($bytes ^| ForEach-Object { $_.ToString('x2') }); [IO.File]::WriteAllText('%PANEL%\rpg_mobile_token.txt',$token,[Text.Encoding]::ASCII)"
)
set /p RPG_TOKEN=<"%PANEL%\rpg_mobile_token.txt"
if "%RPG_TOKEN%"=="" (
  echo ERROR: Could not create RPG API token.
  pause
  exit /b 1
)

set "EASY_PANEL_ROOT=%PANEL%"
if exist "%COMFY_ROOT%\main.py" (
  set "EASY_PANEL_COMFY_ROOT=%COMFY_ROOT%"
  set "EASY_PANEL_COMFY_INPUT=%COMFY_ROOT%\input"
  set "EASY_PANEL_OUTPUT=%COMFY_ROOT%\output"
  set "EASY_PANEL_LORA_DIR=%COMFY_ROOT%\models\loras"
)
set "EASY_PANEL_COMFY_URL=http://127.0.0.1:8188"
set "EASY_PANEL_HOST=0.0.0.0"
set "EASY_PANEL_PORT=8190"
set "EASY_PANEL_RPG_TOKEN=%RPG_TOKEN%"

netstat -ano | findstr /R /C:":8190 .*LISTENING" >nul
if errorlevel 1 (
  echo Starting Easy Panel mobile RPG API on port 8190...
  start "Easy Panel Mobile RPG" /min "%PYTHON%" -s "%PANEL%\easy_panel.py"
  timeout /t 2 /nobreak >nul
) else (
  echo Easy Panel is already listening on port 8190.
  echo If it was started in local-only mode, stop it first and run this file again.
)

echo.
echo ============================================================
echo Easy Panel Mobile RPG API
echo ============================================================
echo Token: [stored locally; not displayed]
echo.
echo Phone URL candidates:
for /f "usebackq delims=" %%A in (`powershell -NoProfile -Command "Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue ^| Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } ^| Select-Object -ExpandProperty IPAddress"`) do (
  echo   http://%%A:8190
)
echo.
echo Test endpoint: /api/rpg/ping
echo Use header: X-RPG-Token: [stored locally; not displayed]
echo.
echo Keep ComfyUI on 127.0.0.1:8188; only Easy Panel needs LAN access.
echo If Windows Firewall blocks the phone, allow Python on Private networks.
echo ============================================================
echo.
start "" "http://127.0.0.1:8190"
pause
endlocal
