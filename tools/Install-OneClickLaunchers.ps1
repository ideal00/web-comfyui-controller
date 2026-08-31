[CmdletBinding()]
param(
    [string]$WorkspaceRoot = "",
    [string]$PanelRoot = "",
    [string]$ComfyRoot = "",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function Resolve-FullPath([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return "" }
    return [System.IO.Path]::GetFullPath($Value)
}

function Test-SamePath([string]$Left, [string]$Right) {
    if ([string]::IsNullOrWhiteSpace($Left) -or [string]::IsNullOrWhiteSpace($Right)) { return $false }
    return (Resolve-FullPath $Left).TrimEnd('\').Equals((Resolve-FullPath $Right).TrimEnd('\'),
        [System.StringComparison]::OrdinalIgnoreCase)
}

function Assert-LauncherPaths {
    if (-not (Test-Path -LiteralPath $script:Workspace -PathType Container)) {
        throw "Workspace root is missing: $script:Workspace"
    }
    $expectedPanel = Resolve-FullPath (Join-Path $script:Workspace "ComfyUI_Easy_Panel")
    $expectedComfy = Resolve-FullPath (Join-Path $script:Workspace "ComfyUI_windows_portable\ComfyUI")
    if (-not (Test-SamePath $script:Panel $expectedPanel)) { throw "Panel root must be $expectedPanel" }
    if (-not (Test-SamePath $script:Comfy $expectedComfy)) { throw "Comfy root must be $expectedComfy" }
    foreach ($path in @(
        $script:Panel,
        $script:Comfy,
        $script:Python,
        (Join-Path $script:Panel "tools\EasyPanel-Service.ps1"),
        (Join-Path $script:Panel "easy_panel.py"),
        (Join-Path $script:Panel "index.html"),
        (Join-Path $script:Comfy "main.py")
    )) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf) -and
            -not (Test-Path -LiteralPath $path -PathType Container)) {
            throw "Required install path is missing: $path"
        }
    }
}

function Get-WrapperContent([ValidateSet("Start", "Stop")][string]$Action) {
    $mode = $Action
    return @(
        "@echo off",
        "setlocal",
        "set `"CONTROLLER=%~dp0ComfyUI_Easy_Panel\tools\EasyPanel-Service.ps1`"",
        "if not exist `"%CONTROLLER%`" (",
        "  echo ERROR: Easy Panel service controller was not found:",
        "  echo %CONTROLLER%",
        "  endlocal",
        "  exit /b 1",
        ")",
        "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"%CONTROLLER%`" -Mode $mode %*",
        "set `"EXIT_CODE=%ERRORLEVEL%`"",
        "endlocal & exit /b %EXIT_CODE%"
    )
}

$scriptRoot = Resolve-FullPath $PSScriptRoot
$defaultPanel = Resolve-FullPath (Join-Path $scriptRoot "..")
$script:Workspace = if ([string]::IsNullOrWhiteSpace($WorkspaceRoot)) {
    Resolve-FullPath (Join-Path $defaultPanel "..")
} else {
    Resolve-FullPath $WorkspaceRoot
}
$script:Panel = if ([string]::IsNullOrWhiteSpace($PanelRoot)) {
    Resolve-FullPath (Join-Path $script:Workspace "ComfyUI_Easy_Panel")
} else {
    Resolve-FullPath $PanelRoot
}
$script:Comfy = if ([string]::IsNullOrWhiteSpace($ComfyRoot)) {
    Resolve-FullPath (Join-Path $script:Workspace "ComfyUI_windows_portable\ComfyUI")
} else {
    Resolve-FullPath $ComfyRoot
}
$script:Python = Resolve-FullPath (Join-Path $script:Workspace "ComfyUI_windows_portable\python_embeded\python.exe")

try {
    Assert-LauncherPaths
    $startPath = Join-Path $script:Workspace "EasyPanel_一键启动.bat"
    $stopPath = Join-Path $script:Workspace "EasyPanel_一键关闭.bat"
    if ($DryRun) {
        Write-Output "DRY-RUN: no launcher file will be written."
        Write-Output ("DRY-RUN start wrapper: {0}" -f $startPath)
        Write-Output ("DRY-RUN stop wrapper: {0}" -f $stopPath)
        exit 0
    }
    $ascii = New-Object System.Text.ASCIIEncoding
    [System.IO.File]::WriteAllLines($startPath, (Get-WrapperContent "Start"), $ascii)
    [System.IO.File]::WriteAllLines($stopPath, (Get-WrapperContent "Stop"), $ascii)
    Write-Output ("Installed: {0}" -f $startPath)
    Write-Output ("Installed: {0}" -f $stopPath)
    exit 0
} catch {
    Write-Error ("One-click launcher installation failed: " + $_.Exception.Message)
    exit 1
}
