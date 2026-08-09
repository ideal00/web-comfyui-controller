@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-EasyPanelModule.ps1" -Module color
echo.
pause
