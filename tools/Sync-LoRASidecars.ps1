param(
    [string]$LoraRoot = 'G:\ComfyUI\ComfyUI_windows_portable\ComfyUI\models\loras',
    [string]$NotesPath = 'G:\ComfyUI\ComfyUI_Easy_Panel\lora_notes.json',
    [string]$AuditPath = 'G:\ComfyUI\ComfyUI_Easy_Panel\lora_imports\2026-08-27_sidecar_sync.json'
)

$ErrorActionPreference = 'Stop'
$utf8 = [System.Text.UTF8Encoding]::new($false)
$notes = Get-Content -LiteralPath $NotesPath -Raw | ConvertFrom-Json
$models = @(Get-ChildItem -LiteralPath $LoraRoot -Filter '*.safetensors' -File -Recurse)
$created = [System.Collections.Generic.List[object]]::new()
$preserved = [System.Collections.Generic.List[string]]::new()

$classNames = @{
    character = '角色'
    appearance = '外貌'
    clothing = '服装'
    pose = '姿势'
    composition = '构图'
    scene = '场景'
    lighting = '光线'
    style = '画风'
    coloring = '上色'
    negative = '负面'
    other = '其他'
}
$fieldNames = @{
    character = 'subject'
    appearance = 'appearance'
    clothing = 'clothing'
    pose = 'pose'
    composition = 'composition'
    scene = 'scene'
    lighting = 'lighting'
    style = 'style'
    coloring = 'coloring'
    negative = 'negative'
    other = 'other'
}

foreach ($model in $models) {
    $txtPath = [IO.Path]::ChangeExtension($model.FullName, '.txt')
    if ((Test-Path -LiteralPath $txtPath) -and (Get-Item -LiteralPath $txtPath).Length -gt 0) {
        $preserved.Add($txtPath)
        continue
    }

    $relative = $model.FullName.Substring($LoraRoot.Length + 1)
    $hash = (Get-FileHash -LiteralPath $model.FullName -Algorithm SHA256).Hash
    $noteProperty = $notes.PSObject.Properties[$model.Name]
    $note = if ($null -ne $noteProperty) { $noteProperty.Value } else { $null }
    $lines = [System.Collections.Generic.List[string]]::new()

    if ($null -ne $note) {
        $lines.Add("标题：$($note.title)")
        $lines.Add("模型文件：$($model.Name)")
        $lines.Add("相对路径：$relative")
        $lines.Add("SHA256：$hash")
        $lines.Add("底模：$($note.base_model)")
        $lines.Add("建议权重：$($note.weight)")
        $lines.Add("页面：$($note.url)")
        $lines.Add('顶层触发词：')

        foreach ($preset in @($note.outfits)) {
            $mainClass = [string]$preset.main_class
            if ([string]::IsNullOrWhiteSpace($mainClass)) { continue }
            $fieldName = if ($fieldNames.ContainsKey($mainClass)) { $fieldNames[$mainClass] } else { 'other' }
            $prompt = [string]$preset.$fieldName
            $className = if ($classNames.ContainsKey($mainClass)) { $classNames[$mainClass] } else { '其他' }
            $lines.Add('')
            $lines.Add("[$className]")
            $lines.Add("名称：$($preset.name)")
            $lines.Add("主类：$mainClass")
            $lines.Add("字段：$fieldName")
            $lines.Add('提示词：')
            $lines.Add($prompt)
        }
    }
    elseif ($model.Name -eq '雪糕.safetensors' -and $hash -eq 'C1781C594B08E52C9926B511E0E591D8CE7DBD637E912E2260C179B0FAD630A8') {
        $lines.Add('标题：雪糕XL（可爱足部画风）')
        $lines.Add("模型文件：$($model.Name)")
        $lines.Add("相对路径：$relative")
        $lines.Add("SHA256：$hash")
        $lines.Add('底模：Illustrious')
        $lines.Add('建议权重：0.7–1.0')
        $lines.Add('页面：https://civitai.com/models/157091?modelVersionId=1094983')
        $lines.Add('顶层触发词：')
        $lines.Add('说明：Civitai trainedWords 为空，未确认独立触发词。')
    }
    else {
        $lines.Add("标题：$($model.BaseName)")
        $lines.Add("模型文件：$($model.Name)")
        $lines.Add("相对路径：$relative")
        $lines.Add("SHA256：$hash")
        $lines.Add('底模：')
        $lines.Add('建议权重：')
        $lines.Add('页面：')
        $lines.Add('顶层触发词：')
        $lines.Add('说明：缺少可靠来源信息，等待人工核对；未生成任何提示词。')
    }

    [IO.File]::WriteAllText($txtPath, (($lines -join "`r`n") + "`r`n"), $utf8)
    $created.Add([ordered]@{
        model = ($relative -replace '\\', '/')
        sidecar = (($txtPath.Substring($LoraRoot.Length + 1)) -replace '\\', '/')
        sha256 = $hash
        source = if ($null -ne $note) { 'lora_notes.json' } elseif ($model.Name -eq '雪糕.safetensors') { 'Civitai hash lookup' } else { 'file identity only' }
    })
}

$remaining = @($models | Where-Object {
    $path = [IO.Path]::ChangeExtension($_.FullName, '.txt')
    -not (Test-Path -LiteralPath $path) -or (Get-Item -LiteralPath $path).Length -eq 0
})

$audit = [ordered]@{
    generated_at = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ssK')
    lora_root = $LoraRoot
    total_safetensors = $models.Count
    existing_sidecars_preserved = $preserved.Count
    sidecars_created = $created.Count
    missing_or_empty_after_sync = $remaining.Count
    created = $created
}
[IO.File]::WriteAllText($AuditPath, (($audit | ConvertTo-Json -Depth 6) + "`r`n"), $utf8)

$audit | ConvertTo-Json -Depth 3
