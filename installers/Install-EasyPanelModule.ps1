[CmdletBinding()]
param(
    [ValidateSet("core", "lora-tools", "pose", "color", "tags", "models", "all")]
    [string]$Module = "all",
    [string]$ComfyRoot = "",
    [string]$PanelRoot = "",
    [switch]$NonInteractive,
    [switch]$SkipDependencies
)

$ErrorActionPreference = "Stop"

function Write-Title([string]$Text) {
    Write-Host ""
    Write-Host ("=" * 68) -ForegroundColor Cyan
    Write-Host "  $Text" -ForegroundColor Cyan
    Write-Host ("=" * 68) -ForegroundColor Cyan
}

function Write-Step([string]$Text) {
    Write-Host "[Easy Panel] $Text" -ForegroundColor Green
}

function Write-Notice([string]$Text) {
    Write-Host "[提示] $Text" -ForegroundColor Yellow
}

function Invoke-DownloadWithRetry([string]$Uri, [string]$OutFile) {
    $lastError = $null
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try {
            Invoke-WebRequest -Uri $Uri -OutFile $OutFile -TimeoutSec 120
            return
        } catch {
            $lastError = $_
            Write-Notice "下载失败（第 $attempt/3 次）：$Uri"
            if (Test-Path -LiteralPath $OutFile -PathType Leaf) {
                [System.IO.File]::Delete((Resolve-AbsolutePath $OutFile))
            }
            if ($attempt -lt 3) { Start-Sleep -Seconds (2 * $attempt) }
        }
    }
    throw "下载失败：$Uri；$($lastError.Exception.Message)"
}

function Resolve-AbsolutePath([string]$Value) {
    if (-not $Value) { return "" }
    return [System.IO.Path]::GetFullPath($Value)
}

function Test-ComfyRoot([string]$Candidate) {
    if (-not $Candidate) { return $false }
    $resolved = Resolve-AbsolutePath $Candidate
    return ((Test-Path -LiteralPath (Join-Path $resolved "main.py") -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $resolved "models") -PathType Container) -and
            (Test-Path -LiteralPath (Join-Path $resolved "custom_nodes") -PathType Container))
}

function Resolve-ComfyRoot {
    $candidates = @()
    if ($ComfyRoot) { $candidates += $ComfyRoot }
    if ($env:COMFYUI_ROOT) { $candidates += $env:COMFYUI_ROOT }
    $candidates += @(
        (Join-Path $PSScriptRoot "..\..\ComfyUI_windows_portable\ComfyUI"),
        (Join-Path $PSScriptRoot "..\ComfyUI_windows_portable\ComfyUI"),
        (Join-Path $PSScriptRoot "..\..\ComfyUI"),
        "G:\ComfyUI\ComfyUI_windows_portable\ComfyUI"
    )
    foreach ($candidate in $candidates) {
        if (Test-ComfyRoot $candidate) {
            return Resolve-AbsolutePath $candidate
        }
    }
    if ($NonInteractive) {
        throw "找不到 ComfyUI 根目录。请使用 -ComfyRoot 指定包含 main.py、models、custom_nodes 的目录。"
    }
    while ($true) {
        $entered = Read-Host "请输入 ComfyUI 根目录（包含 main.py 的文件夹）"
        if (Test-ComfyRoot $entered) { return Resolve-AbsolutePath $entered }
        Write-Notice "该目录不是有效的 ComfyUI 根目录，请重新输入。"
    }
}

function Get-DefaultPanelRoot([string]$ResolvedComfyRoot) {
    $comfyDir = Get-Item -LiteralPath $ResolvedComfyRoot
    if ($comfyDir.Parent.Name -like "ComfyUI_windows_portable*") {
        return Join-Path $comfyDir.Parent.Parent.FullName "ComfyUI_Easy_Panel"
    }
    return Join-Path $comfyDir.Parent.FullName "ComfyUI_Easy_Panel"
}

function Test-PanelRoot([string]$Candidate) {
    if (-not $Candidate) { return $false }
    $resolved = Resolve-AbsolutePath $Candidate
    return ((Test-Path -LiteralPath (Join-Path $resolved "easy_panel.py") -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $resolved "index.html") -PathType Leaf))
}

function Resolve-PanelRoot([string]$ResolvedComfyRoot, [bool]$AllowCreate) {
    $default = Get-DefaultPanelRoot $ResolvedComfyRoot
    if ($PanelRoot) {
        if (Test-PanelRoot $PanelRoot) { return Resolve-AbsolutePath $PanelRoot }
        if ($AllowCreate) { return Resolve-AbsolutePath $PanelRoot }
        if ($NonInteractive) {
            throw "指定的 Easy Panel 目录无效：$PanelRoot"
        }
    }
    $candidates = @()
    if ($env:EASY_PANEL_ROOT) { $candidates += $env:EASY_PANEL_ROOT }
    $candidates += @(
        $default,
        (Join-Path $PSScriptRoot "..\.."),
        (Join-Path $PSScriptRoot "..")
    )
    foreach ($candidate in $candidates) {
        if (Test-PanelRoot $candidate) { return Resolve-AbsolutePath $candidate }
    }
    if ($AllowCreate) {
        if ($PanelRoot) { return Resolve-AbsolutePath $PanelRoot }
        return Resolve-AbsolutePath $default
    }
    if ($NonInteractive) {
        throw "找不到 Easy Panel 目录。请使用 -PanelRoot 指定包含 easy_panel.py 和 index.html 的目录。"
    }
    while ($true) {
        $entered = Read-Host "请输入 Easy Panel 目录（包含 easy_panel.py 的文件夹）"
        if (Test-PanelRoot $entered) { return Resolve-AbsolutePath $entered }
        Write-Notice "该目录不是有效的 Easy Panel 目录，请重新输入。"
    }
}

function Get-ComfyPython([string]$ResolvedComfyRoot) {
    $comfyDir = Get-Item -LiteralPath $ResolvedComfyRoot
    $candidates = @(
        (Join-Path $comfyDir.Parent.FullName "python_embeded\python.exe"),
        (Join-Path $comfyDir.Parent.Parent.FullName "python_embeded\python.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return Resolve-AbsolutePath $candidate
        }
    }
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($python) { return $python.Source }
    throw "找不到 Python。推荐使用 ComfyUI_windows_portable\python_embeded\python.exe。"
}

function Install-GitRepository([string]$Repository, [string]$Target) {
    $targetFull = Resolve-AbsolutePath $Target
    $customNodesRoot = Resolve-AbsolutePath (Join-Path $script:ResolvedComfyRoot "custom_nodes")
    if (-not ($targetFull.StartsWith($customNodesRoot + [System.IO.Path]::DirectorySeparatorChar,
                                     [System.StringComparison]::OrdinalIgnoreCase))) {
        throw "拒绝在 custom_nodes 之外安装第三方节点：$targetFull"
    }
    if (Test-Path -LiteralPath $targetFull -PathType Container) {
        $children = @(Get-ChildItem -LiteralPath $targetFull -Force -ErrorAction SilentlyContinue)
        if ($children.Count -eq 0) {
            Remove-Item -LiteralPath $targetFull -Force
        } elseif (Test-Path -LiteralPath (Join-Path $targetFull ".git") -PathType Container) {
            $git = Get-Command git.exe -ErrorAction SilentlyContinue
            if ($git) {
                Write-Step "更新 $([System.IO.Path]::GetFileName($targetFull))"
                & $git.Source -C $targetFull pull --ff-only
                if ($LASTEXITCODE -ne 0) { throw "Git 更新失败：$targetFull" }
            } else {
                Write-Notice "$targetFull 已存在，但系统没有 Git；保留现有版本。"
            }
            return
        } else {
            Write-Notice "$targetFull 已存在且不是 Git 仓库；为避免覆盖用户文件，已跳过。"
            return
        }
    }

    $gitCommand = Get-Command git.exe -ErrorAction SilentlyContinue
    if ($gitCommand) {
        Write-Step "克隆 $Repository"
        & $gitCommand.Source clone $Repository $targetFull
        if ($LASTEXITCODE -eq 0) { return }
        Write-Notice "Git 克隆失败，自动改用 GitHub ZIP 下载。"
        if (Test-Path -LiteralPath $targetFull -PathType Container) {
            [System.IO.Directory]::Delete($targetFull, $true)
        }
    }

    $uri = [Uri]$Repository
    $parts = $uri.AbsolutePath.Trim("/").Split("/")
    if ($parts.Count -lt 2 -or $uri.Host -ne "github.com") {
        throw "没有安装 Git，且仓库不是可自动下载的 GitHub 地址：$Repository"
    }
    $owner = $parts[0]
    $repo = $parts[1] -replace "\.git$", ""
    $downloadRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("easy-panel-install-" + [guid]::NewGuid().ToString("N"))
    $zip = Join-Path $downloadRoot "$repo.zip"
    $expanded = Join-Path $downloadRoot "expanded"
    New-Item -ItemType Directory -Path $downloadRoot, $expanded -Force | Out-Null
    try {
        Write-Step "下载 $owner/$repo（系统未安装 Git，使用 ZIP）"
        Invoke-DownloadWithRetry "https://github.com/$owner/$repo/archive/refs/heads/main.zip" $zip
        Expand-Archive -LiteralPath $zip -DestinationPath $expanded -Force
        $source = Get-ChildItem -LiteralPath $expanded -Directory | Select-Object -First 1
        if (-not $source) { throw "下载包中没有找到仓库目录：$Repository" }
        Move-Item -LiteralPath $source.FullName -Destination $targetFull
    } finally {
        if (Test-Path -LiteralPath $downloadRoot) {
            Remove-Item -LiteralPath $downloadRoot -Recurse -Force
        }
    }
}

function Install-PythonRequirements([string]$RepositoryPath) {
    if ($SkipDependencies) {
        Write-Notice "已跳过 Python 依赖安装：$RepositoryPath"
        return
    }
    $requirements = Join-Path $RepositoryPath "requirements.txt"
    if (-not (Test-Path -LiteralPath $requirements -PathType Leaf)) { return }
    Write-Step "安装 $([System.IO.Path]::GetFileName($RepositoryPath)) 的 Python 依赖"
    & $script:ComfyPython -s -m pip install -r $requirements
    if ($LASTEXITCODE -ne 0) { throw "依赖安装失败：$requirements" }
}

function Write-LoraToolLaunchers([string]$Target, [string]$InputPath,
                                  [string]$OutputPath, [string]$LoraPath) {
    $launcherEncoding = New-Object System.Text.UTF8Encoding($false)
    $toolEnvironment = @(
        "set `"EASY_PANEL_ROOT=$Target`"",
        "set `"EASY_PANEL_COMFY_ROOT=$script:ResolvedComfyRoot`"",
        "set `"EASY_PANEL_COMFY_INPUT=$InputPath`"",
        "set `"EASY_PANEL_OUTPUT=$OutputPath`"",
        "set `"EASY_PANEL_LORA_DIR=$LoraPath`""
    )
    $generatorContent = @(
        "@echo off",
        "chcp 65001 >nul",
        "setlocal",
        "cd /d `"$Target`""
    ) + $toolEnvironment + @(
        "`"$script:ComfyPython`" -s `"$Target\lora_txt_generator.py`" %*",
        "set `"EXIT_CODE=%ERRORLEVEL%`"",
        "echo.",
        "pause",
        "exit /b %EXIT_CODE%"
    )
    $txtGeneratorLauncher = Join-Path $Target "生成-LoRA同名TXT.bat"
    $txtGeneratorLegacy = Join-Path $Target "生成-LoRA同名TXT.cmd"
    foreach ($launcher in @($txtGeneratorLauncher, $txtGeneratorLegacy)) {
        [IO.File]::WriteAllLines($launcher, $generatorContent, $launcherEncoding)
    }
    $importerContent = @(
        "@echo off",
        "chcp 65001 >nul",
        "setlocal",
        "cd /d `"$Target`""
    ) + $toolEnvironment + @(
        "`"$script:ComfyPython`" -s `"$Target\lora_txt_to_json.py`" %*",
        "set `"EXIT_CODE=%ERRORLEVEL%`"",
        "echo.",
        "pause",
        "exit /b %EXIT_CODE%"
    )
    $txtImporterLauncher = Join-Path $Target "智能导入-LoRA-TXT到JSON.bat"
    $txtImporterLegacy = Join-Path $Target "智能导入-LoRA-TXT到JSON.cmd"
    foreach ($launcher in @($txtImporterLauncher, $txtImporterLegacy)) {
        [IO.File]::WriteAllLines($launcher, $importerContent, $launcherEncoding)
    }
    return @($txtGeneratorLauncher, $txtImporterLauncher)
}

function Install-CoreModule {
    Write-Title "安装核心面板"
    $payload = Join-Path $PSScriptRoot "payload"
    foreach ($required in "easy_panel.py", "index.html", "pose_editor_workflow.json", "README.md",
                           "lora_txt_generator.py", "lora_txt_to_json.py", "classify_tags.py",
                           "import_all_sidecars.py", "生成-LoRA同名TXT.bat", "智能导入-LoRA-TXT到JSON.bat",
                           "生成-LoRA同名TXT.cmd", "智能导入-LoRA-TXT到JSON.cmd") {
        if (-not (Test-Path -LiteralPath (Join-Path $payload $required) -PathType Leaf)) {
            throw "核心安装包不完整，缺少 payload\$required。"
        }
    }
    foreach ($requiredDirectory in "easy_panel_app", "web", "launchers") {
        if (-not (Test-Path -LiteralPath (Join-Path $payload $requiredDirectory) -PathType Container)) {
            throw "核心安装包不完整，缺少 payload\$requiredDirectory。"
        }
    }
    $target = Resolve-PanelRoot $script:ResolvedComfyRoot $true
    New-Item -ItemType Directory -Path $target -Force | Out-Null
    $coreItems = @(
        "easy_panel.py", "index.html", "pose_editor_workflow.json", "README.md",
        "lora_txt_generator.py", "lora_txt_to_json.py", "classify_tags.py",
        "import_all_sidecars.py", "生成-LoRA同名TXT.bat", "智能导入-LoRA-TXT到JSON.bat",
        "生成-LoRA同名TXT.cmd", "智能导入-LoRA-TXT到JSON.cmd",
        "easy_panel_app", "web"
    )
    $existingCore = @($coreItems | Where-Object { Test-Path -LiteralPath (Join-Path $target $_) })
    if ($existingCore.Count) {
        $backup = Join-Path $target ("backup\installer-" + (Get-Date -Format "yyyy-MM-dd_HHmmss"))
        New-Item -ItemType Directory -Path $backup -Force | Out-Null
        foreach ($item in $existingCore) {
            Copy-Item -LiteralPath (Join-Path $target $item) -Destination (Join-Path $backup $item) -Recurse -Force
        }
        Write-Step "旧核心文件已备份到 $backup"
    }
    foreach ($item in $coreItems) {
        $sourceItem = Join-Path $payload $item
        $destinationItem = Join-Path $target $item
        if (Test-Path -LiteralPath $sourceItem -PathType Container) {
            New-Item -ItemType Directory -Path $destinationItem -Force | Out-Null
            foreach ($child in Get-ChildItem -LiteralPath $sourceItem -Force) {
                Copy-Item -LiteralPath $child.FullName -Destination (Join-Path $destinationItem $child.Name) -Recurse -Force
            }
        } else {
            Copy-Item -LiteralPath $sourceItem -Destination $destinationItem -Force
        }
    }
    $comfyDirectory = Get-Item -LiteralPath $script:ResolvedComfyRoot
    if ($comfyDirectory.Parent.Name -like "ComfyUI_windows_portable*") {
        $workspaceRoot = $comfyDirectory.Parent.Parent.FullName
        if ([System.IO.Path]::GetFullPath((Split-Path -Parent $target)).TrimEnd('\') -eq
            [System.IO.Path]::GetFullPath($workspaceRoot).TrimEnd('\')) {
            $launcherBackup = Join-Path $target ("backup\installer-launchers-" + (Get-Date -Format "yyyy-MM-dd_HHmmss"))
            foreach ($launcherName in "Start_ComfyUI_and_EasyPanel.bat", "Stop_ComfyUI_and_EasyPanel.bat") {
                $existingLauncher = Join-Path $workspaceRoot $launcherName
                if (Test-Path -LiteralPath $existingLauncher -PathType Leaf) {
                    New-Item -ItemType Directory -Path $launcherBackup -Force | Out-Null
                    Copy-Item -LiteralPath $existingLauncher -Destination (Join-Path $launcherBackup $launcherName) -Force
                }
                Copy-Item -LiteralPath (Join-Path $payload "launchers\$launcherName") -Destination $existingLauncher -Force
            }
            Write-Step "一键启动/关闭脚本已更新到 $workspaceRoot（启动时会打开 8190 和 8188）"
        } else {
            Write-Notice "使用了自定义面板目录，未覆盖工作目录中的相对路径启动脚本。"
        }
    }
    $panelScript = Join-Path $target "easy_panel.py"
    $outputPath = Join-Path $script:ResolvedComfyRoot "output"
    $inputPath = Join-Path $script:ResolvedComfyRoot "input"
    $loraPath = Join-Path $script:ResolvedComfyRoot "models\loras"
    $env:EASY_PANEL_ROOT = $target
    $env:EASY_PANEL_COMFY_ROOT = $script:ResolvedComfyRoot
    $env:EASY_PANEL_COMFY_INPUT = $inputPath
    $env:EASY_PANEL_OUTPUT = $outputPath
    $env:EASY_PANEL_LORA_DIR = $loraPath
    $pythonFiles = @(
        $panelScript,
        (Join-Path $target "lora_txt_generator.py"),
        (Join-Path $target "lora_txt_to_json.py"),
        (Join-Path $target "classify_tags.py"),
        (Join-Path $target "import_all_sidecars.py")
    ) + @(Get-ChildItem -LiteralPath (Join-Path $target "easy_panel_app") -Filter "*.py" -File -Recurse |
        ForEach-Object { $_.FullName })
    & $script:ComfyPython -m py_compile @pythonFiles
    if ($LASTEXITCODE -ne 0) { throw "核心脚本语法检查失败。" }
    $launcher = Join-Path $target "启动面板.cmd"
    @(
        "@echo off",
        "cd /d `"$target`"",
        "set `"EASY_PANEL_ROOT=$target`"",
        "set `"EASY_PANEL_COMFY_ROOT=$script:ResolvedComfyRoot`"",
        "set `"EASY_PANEL_COMFY_INPUT=$inputPath`"",
        "set `"EASY_PANEL_OUTPUT=$outputPath`"",
        "set `"EASY_PANEL_LORA_DIR=$loraPath`"",
        "start `"`" powershell.exe -NoProfile -WindowStyle Hidden -Command `"`$deadline=(Get-Date).AddSeconds(30); while ((Get-Date) -lt `$deadline) { if (Get-NetTCPConnection -LocalPort 8190 -State Listen -ErrorAction SilentlyContinue) { Start-Process 'http://127.0.0.1:8190'; Start-Process 'http://127.0.0.1:8188'; exit }; Start-Sleep -Milliseconds 300 }`"",
        "`"$script:ComfyPython`" easy_panel.py",
        "pause"
    ) | Set-Content -LiteralPath $launcher -Encoding ascii
    $toolLaunchers = Write-LoraToolLaunchers $target $inputPath $outputPath $loraPath
    Write-Step "核心面板已安装到 $target"
    Write-Step "以后先启动 ComfyUI，再双击：$launcher（会同时打开 Easy Panel 与 ComfyUI 网页）"
    Write-Step "LoRA TXT 工具：$($toolLaunchers[0])"
    Write-Step "LoRA JSON 工具：$($toolLaunchers[1])"
}

function Install-LoraToolsModule {
    Write-Title "安装 LoRA TXT 智能工具"
    $payload = Join-Path $PSScriptRoot "payload"
    $toolItems = @(
        "README.md",
        "lora_txt_generator.py",
        "lora_txt_to_json.py",
        "classify_tags.py",
        "import_all_sidecars.py",
        "生成-LoRA同名TXT.bat",
        "智能导入-LoRA-TXT到JSON.bat",
        "生成-LoRA同名TXT.cmd",
        "智能导入-LoRA-TXT到JSON.cmd",
        "easy_panel_app\__init__.py",
        "easy_panel_app\config.py",
        "easy_panel_app\tag_classifier.py",
        "easy_panel_app\lora_sidecars.py"
    )
    foreach ($item in $toolItems) {
        if (-not (Test-Path -LiteralPath (Join-Path $payload $item) -PathType Leaf)) {
            throw "LoRA 工具安装包不完整，缺少 payload\$item。"
        }
    }
    $target = Resolve-PanelRoot $script:ResolvedComfyRoot $true
    New-Item -ItemType Directory -Path $target -Force | Out-Null
    $existing = @($toolItems | Where-Object { Test-Path -LiteralPath (Join-Path $target $_) -PathType Leaf })
    if ($existing.Count) {
        $backup = Join-Path $target ("backup\installer-lora-tools-" + (Get-Date -Format "yyyy-MM-dd_HHmmss"))
        foreach ($item in $existing) {
            $backupFile = Join-Path $backup $item
            New-Item -ItemType Directory -Path (Split-Path -Parent $backupFile) -Force | Out-Null
            Copy-Item -LiteralPath (Join-Path $target $item) -Destination $backupFile -Force
        }
        Write-Step "旧 LoRA 工具已备份到 $backup"
    }
    foreach ($item in $toolItems) {
        $destination = Join-Path $target $item
        New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
        Copy-Item -LiteralPath (Join-Path $payload $item) -Destination $destination -Force
    }
    $pythonFiles = @(
        (Join-Path $target "lora_txt_generator.py"),
        (Join-Path $target "lora_txt_to_json.py"),
        (Join-Path $target "classify_tags.py"),
        (Join-Path $target "import_all_sidecars.py"),
        (Join-Path $target "easy_panel_app\config.py"),
        (Join-Path $target "easy_panel_app\tag_classifier.py"),
        (Join-Path $target "easy_panel_app\lora_sidecars.py")
    )
    & $script:ComfyPython -m py_compile @pythonFiles
    if ($LASTEXITCODE -ne 0) { throw "LoRA TXT 工具语法检查失败。" }
    $inputPath = Join-Path $script:ResolvedComfyRoot "input"
    $outputPath = Join-Path $script:ResolvedComfyRoot "output"
    $loraPath = Join-Path $script:ResolvedComfyRoot "models\loras"
    $toolLaunchers = Write-LoraToolLaunchers $target $inputPath $outputPath $loraPath
    Write-Step "LoRA TXT 工具已安装到 $target"
    Write-Step "生成缺失 TXT：$($toolLaunchers[0])"
    Write-Step "智能分区 JSON：$($toolLaunchers[1])"
    Write-Notice "安装器没有生成 TXT，也没有修改 lora_notes.json；运行工具后仍需按提示确认。"
}

function Install-PoseModule {
    Write-Title "安装姿势 / OpenPose 模块"
    $aux = Join-Path $script:ResolvedComfyRoot "custom_nodes\comfyui_controlnet_aux"
    $editor = Join-Path $script:ResolvedComfyRoot "custom_nodes\ComfyUI-openpose-editor"
    Install-GitRepository "https://github.com/Fannovel16/comfyui_controlnet_aux.git" $aux
    Install-PythonRequirements $aux
    Install-GitRepository "https://github.com/huchenlei/ComfyUI-openpose-editor.git" $editor
    Install-PythonRequirements $editor
    $controlDir = Join-Path $script:ResolvedComfyRoot "models\controlnet"
    New-Item -ItemType Directory -Path $controlDir -Force | Out-Null
    $openPoseModels = @(Get-ChildItem -LiteralPath $controlDir -File -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match "openpose" })
    if ($openPoseModels.Count) {
        Write-Step "检测到 OpenPose ControlNet：$($openPoseModels[0].FullName)"
    } else {
        Write-Notice "节点已安装，但没有检测到 OpenPose ControlNet 模型。"
        Write-Notice "请把兼容 SDXL / Illustrious 的 Xinsir OpenPose 模型放到：$controlDir"
    }
    Write-Notice "首次提取骨架时，DWPose / OpenPose 可能继续下载预处理模型。"
}

function Install-ColorModule {
    Write-Title "安装 LayerStyle 调色模块"
    $layerStyle = Join-Path $script:ResolvedComfyRoot "custom_nodes\ComfyUI_LayerStyle"
    Install-GitRepository "https://github.com/chflame163/ComfyUI_LayerStyle.git" $layerStyle
    Install-PythonRequirements $layerStyle
    $repair = Join-Path $layerStyle "repair_dependency.bat"
    if ((-not $SkipDependencies) -and (Test-Path -LiteralPath $repair -PathType Leaf)) {
        Write-Step "执行 LayerStyle 官方依赖修复脚本"
        Push-Location $layerStyle
        try {
            & cmd.exe /c "repair_dependency.bat"
            if ($LASTEXITCODE -ne 0) {
                Write-Notice "LayerStyle 修复脚本返回非零状态；请查看上方输出。"
            }
        } finally {
            Pop-Location
        }
    }
}

function Install-TagsModule {
    Write-Title "安装 Danbooru / Anima 标签数据"
    $panel = Resolve-PanelRoot $script:ResolvedComfyRoot $false
    $vendor = Join-Path $panel "vendor"
    $tagTarget = Join-Path $vendor "tagcomplete-data"
    $animaTarget = Join-Path $vendor "anima-tags"
    New-Item -ItemType Directory -Path $tagTarget, $animaTarget -Force | Out-Null

    Invoke-DownloadWithRetry "https://raw.githubusercontent.com/DominikDoom/a1111-sd-webui-tagcomplete/main/tags/danbooru.csv" (Join-Path $tagTarget "danbooru.csv")
    Invoke-DownloadWithRetry "https://raw.githubusercontent.com/DominikDoom/a1111-sd-webui-tagcomplete/main/LICENSE" (Join-Path $tagTarget "LICENSE.tagcomplete")
    $copied = 1
    $bundledTranslations = Join-Path $PSScriptRoot "tag_payload"
    if (Test-Path -LiteralPath $bundledTranslations -PathType Container) {
        foreach ($name in "danbooru-0-zh.csv", "Tags-zh-full.csv", "Tags-zh-lite.csv", "Tags.csv") {
            $source = Join-Path $bundledTranslations $name
            if (Test-Path -LiteralPath $source -PathType Leaf) {
                Copy-Item -LiteralPath $source -Destination (Join-Path $tagTarget $name) -Force
                $copied++
            }
        }
        $translationSource = Join-Path $bundledTranslations "SOURCE.md"
        if (Test-Path -LiteralPath $translationSource -PathType Leaf) {
            Copy-Item -LiteralPath $translationSource -Destination (Join-Path $tagTarget "SOURCE.translations.md") -Force
        }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $tagTarget "danbooru.csv") -PathType Leaf)) {
        throw "没有找到 danbooru.csv，TagComplete 模块安装不完整。"
    }
    Write-Step "已安装 $copied 个 TagComplete CSV 文件。"

    $animaCsv = Join-Path $animaTarget "anima-1.0.csv"
    Invoke-DownloadWithRetry "https://raw.githubusercontent.com/ShiroEirin/comfyui-good-anima/main/danbooru-tags/anima-1.0.csv" $animaCsv
    Invoke-DownloadWithRetry "https://raw.githubusercontent.com/ShiroEirin/comfyui-good-anima/main/LICENSE" (Join-Path $animaTarget "LICENSE.comfyui-good-anima")
    @(
        "Anima tag index source:",
        "https://github.com/ShiroEirin/comfyui-good-anima/tree/main/danbooru-tags",
        "Installed by Easy Panel module installer on $(Get-Date -Format 'yyyy-MM-dd')."
    ) | Set-Content -LiteralPath (Join-Path $animaTarget "SOURCE.md") -Encoding utf8
    Write-Step "Anima 标签索引已安装：$animaCsv"
}

function Test-ModelComponents {
    Write-Title "模型组件检查"
    $models = Join-Path $script:ResolvedComfyRoot "models"
    $checks = @(
        @{ Name = "完整 checkpoint"; Path = (Join-Path $models "checkpoints"); Pattern = "*.safetensors"; Required = $true },
        @{ Name = "LoRA"; Path = (Join-Path $models "loras"); Pattern = "*.safetensors"; Required = $false },
        @{ Name = "OpenPose ControlNet"; Path = (Join-Path $models "controlnet"); Pattern = "*openpose*"; Required = $false },
        @{ Name = "Anima 文本编码器"; Path = (Join-Path $models "text_encoders"); Pattern = "qwen_3_06b_base.safetensors"; Required = $false },
        @{ Name = "Krea 2 文本编码器"; Path = (Join-Path $models "text_encoders"); Pattern = "qwen3VL4BAbliteratedComfyui_v10.safetensors"; Required = $false },
        @{ Name = "Anima / Krea 2 VAE"; Path = (Join-Path $models "vae"); Pattern = "qwen_image_vae.safetensors"; Required = $false },
        @{ Name = "Anime6B 超分"; Path = (Join-Path $models "upscale_models"); Pattern = "RealESRGAN_x4plus_anime_6B.pth"; Required = $false },
        @{ Name = "FaceDetailer 检测模型"; Path = (Join-Path $models "ultralytics\bbox"); Pattern = "face_yolov8m.pt"; Required = $false },
        @{ Name = "SeedVR2 3B Int8"; Path = (Join-Path $models "diffusion_models"); Pattern = "seedvr2_3b_int8_convrot.safetensors"; Required = $false },
        @{ Name = "SeedVR2 VAE"; Path = (Join-Path $models "vae"); Pattern = "seedvr2_ema_vae_fp16.safetensors"; Required = $false }
    )
    foreach ($check in $checks) {
        $matches = @()
        if (Test-Path -LiteralPath $check.Path -PathType Container) {
            $matches = @(Get-ChildItem -LiteralPath $check.Path -File -Recurse -Filter $check.Pattern -ErrorAction SilentlyContinue)
        }
        if ($matches.Count) {
            Write-Host ("[已找到] {0,-24} {1}" -f $check.Name, $matches[0].FullName) -ForegroundColor Green
        } else {
            $level = if ($check.Required) { "缺少" } else { "可选缺少" }
            Write-Host ("[{0}] {1,-24} 放到 {2}" -f $level, $check.Name, $check.Path) -ForegroundColor Yellow
        }
    }
    $diffusionDirs = @((Join-Path $models "diffusion_models"), (Join-Path $models "unet"))
    $diffusionFiles = @($diffusionDirs | Where-Object { Test-Path -LiteralPath $_ } |
        ForEach-Object { Get-ChildItem -LiteralPath $_ -File -Recurse -Filter "*.safetensors" -ErrorAction SilentlyContinue })
    $anima = @($diffusionFiles | Where-Object { $_.Name -match "anima" })
    $krea = @($diffusionFiles | Where-Object { $_.Name -match "krea.?2" })
    Write-Host ("[{0}] Anima 扩散模型：{1}" -f $(if ($anima.Count) { "已找到" } else { "可选缺少" }), $(if ($anima.Count) { $anima[0].FullName } else { ($diffusionDirs -join " 或 ") }))
    Write-Host ("[{0}] Krea 2 扩散模型：{1}" -f $(if ($krea.Count) { "已找到" } else { "可选缺少" }), $(if ($krea.Count) { $krea[0].FullName } else { ($diffusionDirs -join " 或 ") }))
    foreach ($node in @(
        @{ Name = "Impact Subpack / Face detector"; Path = (Join-Path $script:ResolvedComfyRoot "custom_nodes\ComfyUI-Impact-Subpack") },
        @{ Name = "Ultimate SD Upscale"; Path = (Join-Path $script:ResolvedComfyRoot "custom_nodes\ComfyUI_UltimateSDUpscale") }
    )) {
        $state = if (Test-Path -LiteralPath $node.Path -PathType Container) { "已找到" } else { "可选缺少" }
        Write-Host ("[{0}] {1}：{2}" -f $state, $node.Name, $node.Path)
    }
    Write-Notice "SeedVR2 官方下载：https://huggingface.co/Comfy-Org/SeedVR2"
    Write-Notice "FaceDetailer 节点：https://github.com/ltdrdata/ComfyUI-Impact-Subpack"
    Write-Notice "Ultimate SD Upscale：https://github.com/ssitu/ComfyUI_UltimateSDUpscale"
    Write-Notice "模型权重没有随安装包分发。请从合法来源取得，并遵守各模型许可证。"
}

Write-Title "ComfyUI Easy Panel 模块安装器"
$script:ResolvedComfyRoot = Resolve-ComfyRoot
$script:ComfyPython = Get-ComfyPython $script:ResolvedComfyRoot
Write-Step "ComfyUI：$script:ResolvedComfyRoot"
Write-Step "Python：$script:ComfyPython"

switch ($Module) {
    "core" { Install-CoreModule }
    "lora-tools" { Install-LoraToolsModule }
    "pose" { Install-PoseModule }
    "color" { Install-ColorModule }
    "tags" { Install-TagsModule }
    "models" { Test-ModelComponents }
    "all" {
        Install-CoreModule
        Install-PoseModule
        Install-ColorModule
        Install-TagsModule
        Test-ModelComponents
    }
}

Write-Title "处理完成"
Write-Host "请完整关闭并重新启动 ComfyUI，然后刷新 Easy Panel。" -ForegroundColor Green
if ($Module -in @("core", "all")) {
    Write-Host "核心面板地址：http://127.0.0.1:8190" -ForegroundColor Green
}
