[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$installerRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $installerRoot ".."))
$payloadRoot = Join-Path $installerRoot "payload"
$packagesRoot = Join-Path $installerRoot "packages"

function Assert-ChildPath([string]$Path, [string]$Parent) {
    $resolvedPath = [System.IO.Path]::GetFullPath($Path)
    $resolvedParent = [System.IO.Path]::GetFullPath($Parent).TrimEnd('\') + '\'
    if (-not $resolvedPath.StartsWith($resolvedParent, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "拒绝操作预期目录以外的路径：$resolvedPath"
    }
    return $resolvedPath
}

function Copy-CleanDirectory([string]$Source, [string]$Destination) {
    $destinationPath = Assert-ChildPath $Destination $installerRoot
    if (Test-Path -LiteralPath $destinationPath) {
        Remove-Item -LiteralPath $destinationPath -Recurse -Force
    }
    New-Item -ItemType Directory -Path $destinationPath -Force | Out-Null
    foreach ($item in Get-ChildItem -LiteralPath $Source -Force -Recurse) {
        $relative = [System.IO.Path]::GetRelativePath($Source, $item.FullName)
        if ($relative -split '[\\/]' -contains "__pycache__") { continue }
        if ($item.Extension -eq ".pyc") { continue }
        $target = Join-Path $destinationPath $relative
        if ($item.PSIsContainer) {
            New-Item -ItemType Directory -Path $target -Force | Out-Null
        } else {
            $parent = Split-Path -Parent $target
            New-Item -ItemType Directory -Path $parent -Force | Out-Null
            Copy-Item -LiteralPath $item.FullName -Destination $target -Force
        }
    }
}

function Sync-CorePayload {
    New-Item -ItemType Directory -Path $payloadRoot -Force | Out-Null
    foreach ($file in "easy_panel.py", "index.html", "pose_editor_workflow.json", "README.md",
                      "lora_txt_generator.py", "lora_txt_to_json.py", "classify_tags.py",
                      "import_all_sidecars.py", "生成-LoRA同名TXT.cmd", "智能导入-LoRA-TXT到JSON.cmd") {
        $source = Join-Path $repositoryRoot $file
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            throw "核心源文件不存在：$source"
        }
        Copy-Item -LiteralPath $source -Destination (Join-Path $payloadRoot $file) -Force
    }
    Copy-CleanDirectory (Join-Path $repositoryRoot "easy_panel_app") (Join-Path $payloadRoot "easy_panel_app")
    Copy-CleanDirectory (Join-Path $repositoryRoot "web") (Join-Path $payloadRoot "web")
}

function New-Package([string]$Name, [string]$CommandFile, [switch]$Core, [switch]$Tags) {
    $temporaryRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("easy-panel-package-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $temporaryRoot -Force | Out-Null
    try {
        Copy-Item -LiteralPath (Join-Path $installerRoot "Install-EasyPanelModule.ps1") -Destination $temporaryRoot
        Copy-Item -LiteralPath (Join-Path $installerRoot $CommandFile) -Destination $temporaryRoot
        Copy-Item -LiteralPath (Join-Path $installerRoot "README.md") -Destination (Join-Path $temporaryRoot "使用说明.md")
        if ($Core) {
            Copy-Item -LiteralPath $payloadRoot -Destination (Join-Path $temporaryRoot "payload") -Recurse -Force
        }
        if ($Tags) {
            Copy-Item -LiteralPath (Join-Path $installerRoot "tag_payload") -Destination (Join-Path $temporaryRoot "tag_payload") -Recurse -Force
        }
        $zipPath = Join-Path $packagesRoot $Name
        Compress-Archive -Path (Join-Path $temporaryRoot "*") -DestinationPath $zipPath -CompressionLevel Optimal -Force
        Write-Host "已生成 $zipPath" -ForegroundColor Green
    } finally {
        $resolvedTemporary = [System.IO.Path]::GetFullPath($temporaryRoot)
        $systemTemporary = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
        if ($resolvedTemporary.StartsWith($systemTemporary, [System.StringComparison]::OrdinalIgnoreCase) -and
            (Split-Path -Leaf $resolvedTemporary).StartsWith("easy-panel-package-")) {
            Remove-Item -LiteralPath $resolvedTemporary -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

Sync-CorePayload
New-Item -ItemType Directory -Path $packagesRoot -Force | Out-Null

New-Package "EasyPanel-Core-OneClick.zip" "安装-核心面板.cmd" -Core
New-Package "EasyPanel-LoRA-Tools-OneClick.zip" "安装-LoRA-TXT智能工具.cmd" -Core
New-Package "EasyPanel-Pose-OneClick.zip" "安装-姿势OpenPose模块.cmd"
New-Package "EasyPanel-Color-OneClick.zip" "安装-LayerStyle调色模块.cmd"
New-Package "EasyPanel-Tags-OneClick.zip" "安装-标签数据模块.cmd" -Tags
New-Package "EasyPanel-Models-Check.zip" "检查-模型组件.cmd"
New-Package "EasyPanel-All-OneClick.zip" "安装-全部模块.cmd" -Core -Tags

$checksums = foreach ($package in Get-ChildItem -LiteralPath $packagesRoot -Filter "*.zip" | Sort-Object Name) {
    $hash = Get-FileHash -LiteralPath $package.FullName -Algorithm SHA256
    "$($hash.Hash)  $($package.Name)"
}
$checksums | Set-Content -LiteralPath (Join-Path $packagesRoot "SHA256SUMS.txt") -Encoding ascii
Write-Host "SHA256 清单已更新。" -ForegroundColor Green
