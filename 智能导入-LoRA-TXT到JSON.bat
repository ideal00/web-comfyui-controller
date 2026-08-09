@echo off
chcp 65001 >nul
setlocal
set "PANEL_ROOT=%~dp0"
set "PORTABLE_ROOT=%~dp0..\ComfyUI_windows_portable"
set "PYTHON=%PORTABLE_ROOT%\python_embeded\python.exe"
set "COMFY_ROOT=%PORTABLE_ROOT%\ComfyUI"
if not exist "%PYTHON%" (
  echo [ERROR] ComfyUI portable Python was not found:
  echo %PYTHON%
  echo Keep this panel folder next to ComfyUI_windows_portable, or reinstall LoRA Tools.
  pause
  exit /b 1
)
if not exist "%PANEL_ROOT%lora_txt_to_json.py" (
  echo [ERROR] lora_txt_to_json.py is missing. Reinstall LoRA Tools.
  pause
  exit /b 1
)
set "EASY_PANEL_ROOT=%PANEL_ROOT%"
set "EASY_PANEL_COMFY_ROOT=%COMFY_ROOT%"
set "EASY_PANEL_COMFY_INPUT=%COMFY_ROOT%\input"
set "EASY_PANEL_OUTPUT=%COMFY_ROOT%\output"
set "EASY_PANEL_LORA_DIR=%COMFY_ROOT%\models\loras"
cd /d "%PANEL_ROOT%"
"%PYTHON%" -s "%PANEL_ROOT%lora_txt_to_json.py" %*
set "EXIT_CODE=%ERRORLEVEL%"
echo.
pause
exit /b %EXIT_CODE%
