[CmdletBinding()]
param(
    [string]$PanelUrl = 'http://127.0.0.1:8190',
    [string]$NotesPath = 'G:\ComfyUI\ComfyUI_Easy_Panel\lora_notes.json',
    [string]$BackupRoot = 'G:\ComfyUI\ComfyUI_Easy_Panel\backup',
    [string]$AuditRoot = 'G:\ComfyUI\ComfyUI_Easy_Panel\lora_imports'
)

$ErrorActionPreference = 'Stop'
$promptFields = @(
    'subject', 'appearance', 'clothing', 'pose', 'composition', 'scene',
    'lighting', 'style', 'coloring', 'negative', 'other'
)
$triggerMigrations = @{
    'ill_Estella动画风格.safetensors' = [pscustomobject]@{
        name = 'Estella动画风格'; main_class = 'style'; field = 'style'; value = 'estella'
    }
    'sd15_云朵风格.safetensors' = [pscustomobject]@{
        name = '云朵风格'; main_class = 'style'; field = 'style'; value = 'cloud style'
    }
}
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backupPath = Join-Path $BackupRoot "lora_notes.before-cjk-prompt-cleanup-$stamp.json"
$auditPath = Join-Path $AuditRoot "cjk_prompt_cleanup_$stamp.json"

$response = Invoke-RestMethod -Uri "$PanelUrl/api/lora-notes" -TimeoutSec 30
$notes = $response.notes
Copy-Item -LiteralPath $NotesPath -Destination $backupPath

$changes = [Collections.Generic.List[object]]::new()
$removedPresets = [Collections.Generic.List[object]]::new()
foreach ($noteProperty in $notes.PSObject.Properties) {
    $topTrigger = [string]$noteProperty.Value.trigger
    if ($topTrigger -match '[\u3400-\u9fff]') {
        $changes.Add([pscustomobject]@{
            file = $noteProperty.Name
            preset = ''
            field = 'trigger'
            old_value = $topTrigger
            new_value = ''
        })
        $noteProperty.Value.trigger = ''
        if ($triggerMigrations.ContainsKey($noteProperty.Name)) {
            $migration = $triggerMigrations[$noteProperty.Name]
            if ($null -eq $noteProperty.Value.PSObject.Properties['outfits']) {
                $noteProperty.Value | Add-Member -NotePropertyName outfits -NotePropertyValue @()
            }
            $exists = @($noteProperty.Value.outfits | Where-Object {
                [string]$_.$($migration.field) -eq $migration.value
            }).Count -gt 0
            if (-not $exists) {
                $record = [ordered]@{
                    name = $migration.name
                    subject = ''; appearance = ''; clothing = ''; pose = ''; composition = ''
                    scene = ''; lighting = ''; style = ''; coloring = ''; negative = ''; other = ''
                    main_class = $migration.main_class
                }
                $record[$migration.field] = $migration.value
                $noteProperty.Value.outfits = @($noteProperty.Value.outfits) + [pscustomobject]$record
            }
        }
    }
    if ($null -eq $noteProperty.Value.PSObject.Properties['outfits']) { continue }
    foreach ($outfit in @($noteProperty.Value.outfits)) {
        foreach ($field in $promptFields) {
            $oldValue = [string]$outfit.$field
            if ($oldValue -match '[\u3400-\u9fff]') {
                $changes.Add([pscustomobject]@{
                    file = $noteProperty.Name
                    preset = [string]$outfit.name
                    field = $field
                    old_value = $oldValue
                    new_value = ''
                })
                $outfit.$field = ''
            }
        }
    }
    $keptOutfits = [Collections.Generic.List[object]]::new()
    foreach ($outfit in @($noteProperty.Value.outfits)) {
        $hasPrompt = $false
        foreach ($field in $promptFields) {
            if (-not [string]::IsNullOrWhiteSpace([string]$outfit.$field)) {
                $hasPrompt = $true
                break
            }
        }
        if ($hasPrompt) {
            $keptOutfits.Add($outfit)
        } else {
            $removedPresets.Add([pscustomobject]@{
                file = $noteProperty.Name
                preset = [string]$outfit.name
                reason = '所有实际提示词字段均为空'
            })
        }
    }
    $noteProperty.Value.outfits = @($keptOutfits)
}

$body = @{ notes = $notes } | ConvertTo-Json -Depth 14
$save = Invoke-RestMethod -Uri "$PanelUrl/api/lora-notes" -Method Post `
    -ContentType 'application/json; charset=utf-8' `
    -Body ([Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 60
if (-not $save.ok) { throw '面板备忘保存失败。' }

$verify = (Invoke-RestMethod -Uri "$PanelUrl/api/lora-notes" -TimeoutSec 30).notes
$remaining = [Collections.Generic.List[string]]::new()
foreach ($noteProperty in $verify.PSObject.Properties) {
    foreach ($outfit in @($noteProperty.Value.outfits)) {
        foreach ($field in $promptFields) {
            if ([string]$outfit.$field -match '[\u3400-\u9fff]') {
                $remaining.Add("$($noteProperty.Name) / $($outfit.name) / $field")
            }
        }
    }
}
if ($remaining.Count -ne 0) { throw "清理后仍有 $($remaining.Count) 个中文提示词字段。" }

$audit = [ordered]@{
    cleaned_at = (Get-Date).ToString('o')
    backup = $backupPath
    changed_fields = $changes.Count
    removed_empty_presets = $removedPresets.Count
    remaining_cjk_prompt_fields = $remaining.Count
    policy = '含中文的提示词字段整体清空；不从中文说明中猜测或提取触发词。'
    changes = @($changes)
    removed_presets = @($removedPresets)
}
[IO.File]::WriteAllText(
    $auditPath,
    (($audit | ConvertTo-Json -Depth 8) + "`r`n"),
    [Text.UTF8Encoding]::new($false)
)

$audit | ConvertTo-Json -Depth 4
