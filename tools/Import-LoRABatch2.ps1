param(
    [string]$ManifestPath = 'G:\ComfyUI\ComfyUI_Easy_Panel\lora_imports\2026-08-27_batch2_civitai_downloads.json',
    [string]$DownloadRoot = 'G:\edge download',
    [string]$LoraRoot = 'G:\ComfyUI\ComfyUI_windows_portable\ComfyUI\models\loras',
    [string]$PanelUrl = 'http://127.0.0.1:8190',
    [string]$BackupPath = 'G:\ComfyUI\ComfyUI_Easy_Panel\backup\lora_notes.before-batch2-move-2026-08-27.json',
    [string]$AuditPath = 'G:\ComfyUI\ComfyUI_Easy_Panel\lora_imports\2026-08-27_batch2_move_audit.json'
)

$ErrorActionPreference = 'Stop'
$utf8 = [Text.UTF8Encoding]::new($false)
$classFields = @{
    character = 'subject'; appearance = 'appearance'; clothing = 'clothing'; pose = 'pose'
    composition = 'composition'; scene = 'scene'; lighting = 'lighting'; style = 'style'
    coloring = 'coloring'; negative = 'negative'; other = 'other'
}
$classNames = @{
    character = '角色'; appearance = '外貌'; clothing = '服装'; pose = '姿势'
    composition = '构图'; scene = '场景'; lighting = '光线'; style = '画风'
    coloring = '上色'; negative = '负面'; other = '其他'
}
$promptFields = @('subject','appearance','clothing','pose','composition','scene','lighting','style','coloring','negative','other')

$downloadResolved = (Resolve-Path -LiteralPath $DownloadRoot).Path.TrimEnd('\')
$loraResolved = (Resolve-Path -LiteralPath $LoraRoot).Path.TrimEnd('\')
$manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
$items = @($manifest.PSObject.Properties)
if ($items.Count -eq 0) { throw '导入清单为空。' }

$prepared = foreach ($item in $items) {
    $source = Join-Path $downloadResolved $item.Name
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "缺少源文件：$source" }
    if ([IO.Path]::GetDirectoryName($source) -ne $downloadResolved) { throw "源文件不在下载根目录：$source" }
    $actualHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
    if ($actualHash -ne $item.Value.sha256) { throw "源文件哈希不符：$source" }
    if ($item.Value.installed_name -notmatch '[\u3400-\u9fff]') { throw "安装名没有中文：$($item.Value.installed_name)" }
    if (-not [string]::IsNullOrEmpty([string]$item.Value.note.trigger)) { throw "顶层触发词必须为空：$($item.Name)" }

    foreach ($preset in @($item.Value.note.presets)) {
        if (-not $classFields.ContainsKey([string]$preset.class)) { throw "无效主类：$($preset.class)" }
        if ([string]$preset.value -match '[\u3400-\u9fff]') { throw "提示词含中文：$($item.Name) / $($preset.name)" }
    }

    $targetDir = Join-Path $loraResolved (($item.Value.destination -replace '/', '\'))
    $target = Join-Path $targetDir $item.Value.installed_name
    $targetFull = [IO.Path]::GetFullPath($target)
    if (-not $targetFull.StartsWith($loraResolved + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "目标越出 LoRA 根目录：$targetFull"
    }
    if (Test-Path -LiteralPath $targetFull) {
        $targetHash = (Get-FileHash -LiteralPath $targetFull -Algorithm SHA256).Hash
        if ($targetHash -ne $actualHash) { throw "目标存在但哈希不同：$targetFull" }
    }
    [pscustomobject]@{ Source=$source; Target=$targetFull; TargetDir=$targetDir; Hash=$actualHash; Data=$item.Value }
}

$notesResponse = Invoke-RestMethod -Uri "$PanelUrl/api/lora-notes" -TimeoutSec 30
$notes = $notesResponse.notes
Copy-Item -LiteralPath 'G:\ComfyUI\ComfyUI_Easy_Panel\lora_notes.json' -Destination $BackupPath

foreach ($entry in $prepared) {
    $note = $entry.Data.note
    $outfits = foreach ($preset in @($note.presets)) {
        $record = [ordered]@{
            name = [string]$preset.name
            subject = ''; appearance = ''; clothing = ''; pose = ''; composition = ''
            scene = ''; lighting = ''; style = ''; coloring = ''; negative = ''; other = ''
            main_class = [string]$preset.class
        }
        $record[$classFields[[string]$preset.class]] = [string]$preset.value
        [pscustomobject]$record
    }
    $fullNote = [ordered]@{
        title = [string]$note.title
        base_model = [string]$note.base_model
        weight = [string]$note.weight
        trigger = ''
        url = [string]$note.url
        outfits = @($outfits)
    }
    $notes | Add-Member -NotePropertyName $entry.Data.installed_name -NotePropertyValue ([pscustomobject]$fullNote) -Force
}

$body = @{notes=$notes} | ConvertTo-Json -Depth 12
$save = Invoke-RestMethod -Uri "$PanelUrl/api/lora-notes" -Method Post -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 30
if (-not $save.ok) { throw '面板备忘保存失败。' }

$writtenTxt = [Collections.Generic.List[string]]::new()
$moved = [Collections.Generic.List[object]]::new()
try {
    foreach ($entry in $prepared) {
        New-Item -ItemType Directory -Path $entry.TargetDir -Force | Out-Null
        $txtPath = [IO.Path]::ChangeExtension($entry.Target, '.txt')
        if (Test-Path -LiteralPath $txtPath) { throw "目标 TXT 已存在，拒绝覆盖：$txtPath" }
        $note = $entry.Data.note
        $relative = $entry.Target.Substring($loraResolved.Length + 1)
        $lines = [Collections.Generic.List[string]]::new()
        $lines.Add("标题：$($note.title)")
        $lines.Add("模型文件：$($entry.Data.installed_name)")
        $lines.Add("相对路径：$relative")
        $lines.Add("SHA256：$($entry.Hash)")
        $lines.Add("底模：$($note.base_model)")
        $lines.Add("建议权重：$($note.weight)")
        $lines.Add("页面：$($note.url)")
        $lines.Add('顶层触发词：')
        if (@($note.presets).Count -eq 0) {
            $lines.Add('说明：Civitai trainedWords 为空，未确认独立触发词；加载 LoRA 本身即可生效。')
        }
        foreach ($preset in @($note.presets)) {
            $mainClass = [string]$preset.class
            $lines.Add('')
            $lines.Add("[$($classNames[$mainClass])]")
            $lines.Add("名称：$($preset.name)")
            $lines.Add("主类：$mainClass")
            $lines.Add("字段：$($classFields[$mainClass])")
            $lines.Add('提示词：')
            $lines.Add([string]$preset.value)
        }
        [IO.File]::WriteAllText($txtPath, (($lines -join "`r`n") + "`r`n"), $utf8)
        $writtenTxt.Add($txtPath)
    }

    foreach ($entry in $prepared) {
        if (Test-Path -LiteralPath $entry.Target) {
            Remove-Item -LiteralPath $entry.Source
        } else {
            Move-Item -LiteralPath $entry.Source -Destination $entry.Target
            $moved.Add($entry)
        }
        if (Test-Path -LiteralPath $entry.Source) { throw "下载目录仍保留源文件：$($entry.Source)" }
        if ((Get-FileHash -LiteralPath $entry.Target -Algorithm SHA256).Hash -ne $entry.Hash) {
            throw "移动后目标哈希不符：$($entry.Target)"
        }
    }
}
catch {
    foreach ($entry in @($moved) | Select-Object -Last 999) {
        if ((Test-Path -LiteralPath $entry.Target) -and -not (Test-Path -LiteralPath $entry.Source)) {
            Move-Item -LiteralPath $entry.Target -Destination $entry.Source
        }
    }
    foreach ($txt in $writtenTxt) { if (Test-Path -LiteralPath $txt) { Remove-Item -LiteralPath $txt } }
    $oldNotes = Get-Content -LiteralPath $BackupPath -Raw | ConvertFrom-Json
    $restoreBody = @{notes=$oldNotes} | ConvertTo-Json -Depth 12
    Invoke-RestMethod -Uri "$PanelUrl/api/lora-notes" -Method Post -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($restoreBody)) -TimeoutSec 30 | Out-Null
    throw
}

$audit = [ordered]@{
    moved_at = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ssK')
    source_root = $downloadResolved
    target_root = $loraResolved
    moved_count = $prepared.Count
    source_files_remaining = @($prepared | Where-Object { Test-Path -LiteralPath $_.Source }).Count
    verified_targets = @($prepared | Where-Object { (Test-Path -LiteralPath $_.Target) -and ((Get-FileHash -LiteralPath $_.Target -Algorithm SHA256).Hash -eq $_.Hash) }).Count
    files = @($prepared | ForEach-Object { [ordered]@{ source=[IO.Path]::GetFileName($_.Source); target=($_.Target.Substring($loraResolved.Length+1) -replace '\\','/'); sha256=$_.Hash } })
}
[IO.File]::WriteAllText($AuditPath, (($audit | ConvertTo-Json -Depth 6) + "`r`n"), $utf8)
$audit | ConvertTo-Json -Depth 4
