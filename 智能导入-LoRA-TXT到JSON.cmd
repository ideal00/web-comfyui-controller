@echo off
chcp 65001 >nul
setlocal
set "PYTHON=%~dp0..\ComfyUI_windows_portable\python_embeded\python.exe"
if not exist "%PYTHON%" (
  echo 找不到 ComfyUI 便携版 Python：
  echo %PYTHON%
  pause
  exit /b 1
)
"%PYTHON%" -s "%~dp0lora_txt_to_json.py" %*
echo.
pause
endlocal
