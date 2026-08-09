@echo off
setlocal
title Stop ComfyUI and Easy Panel

echo Closing the modular Easy Panel on port 8190 and ComfyUI on port 8188...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$listeners = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -in 8188,8190 }); if (-not $listeners.Count) { Write-Host 'No ComfyUI or Easy Panel process is listening on ports 8188/8190.'; exit 0 }; foreach ($listener in $listeners) { $process = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $listener.OwningProcess) -ErrorAction SilentlyContinue; $command = [string]$process.CommandLine; $isPanel = $listener.LocalPort -eq 8190 -and $command -match 'easy_panel\.py'; $isComfy = $listener.LocalPort -eq 8188 -and $command -match 'ComfyUI[\\/]main\.py'; if (-not ($isPanel -or $isComfy)) { Write-Host ('Skipped unrelated process on port ' + $listener.LocalPort + ' (PID ' + $listener.OwningProcess + ').'); continue }; try { Stop-Process -Id $listener.OwningProcess -Force -ErrorAction Stop; Write-Host ('Stopped ' + $(if ($isPanel) {'Easy Panel'} else {'ComfyUI'}) + ' PID ' + $listener.OwningProcess) } catch { Write-Host ('Could not stop PID ' + $listener.OwningProcess + ': ' + $_.Exception.Message) } }"

echo.
echo Done. You can close this window.
pause
endlocal
