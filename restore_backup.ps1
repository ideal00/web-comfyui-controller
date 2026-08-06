# ============================================================
#  恢复脚本：将 backup\<时间戳>\ 中的快照还原到面板目录
#  用法：
#    1. 直接运行：自动恢复最新一份备份
#    2. 带参数：  .\restore_backup.ps1 -Backup "2026-08-05_2110"
#  建议在恢复前先关闭面板服务器（Start 脚本中的 easy_panel）
# ============================================================

param(
    [string]$Backup = ""
)

$ErrorActionPreference = "Stop"
$PanelDir   = "g:\ComfyUI\ComfyUI_Easy_Panel"
$BackupRoot = Join-Path $PanelDir "backup"

if (-not (Test-Path $BackupRoot)) {
    Write-Host "找不到备份目录：$BackupRoot" -ForegroundColor Red
    exit 1
}

$snapshots = Get-ChildItem $BackupRoot -Directory | Sort-Object Name -Descending

if ($snapshots.Count -eq 0) {
    Write-Host "备份目录为空，没有可恢复的快照。" -ForegroundColor Red
    exit 1
}

# 选择要恢复的快照
if ($Backup -ne "") {
    $snapshot = Join-Path $BackupRoot $Backup
    if (-not (Test-Path $snapshot)) {
        Write-Host "指定的备份不存在：$Backup" -ForegroundColor Red
        exit 1
    }
} else {
    $snapshot = $snapshots[0].FullName
}

Write-Host "======================================" -ForegroundColor Cyan
Write-Host "  将恢复以下快照：" -ForegroundColor Cyan
Write-Host "  $snapshot" -ForegroundColor Yellow
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "可用备份列表（最新的在上）：" -ForegroundColor Green
$snapshots | ForEach-Object { Write-Host "  $($_.Name)" }
Write-Host ""
Write-Host "确认恢复？此操作会覆盖当前 easy_panel.py / index.html / lora_notes.json / pose_editor_workflow.json / vendor" -ForegroundColor Yellow
$answer = Read-Host "输入 Y 继续，其他任意键取消"
if ($answer -notmatch '^[Yy]$') {
    Write-Host "已取消。" -ForegroundColor Cyan
    exit 0
}

# 备份当前状态（防止恢复后想反悔）
$stamp = Get-Date -Format "yyyy-MM-dd_HHmm"
$preRestore = Join-Path $BackupRoot "pre-restore_$stamp"
New-Item -ItemType Directory -Path $preRestore -Force | Out-Null
Copy-Item (Join-Path $PanelDir "easy_panel.py")   $preRestore
Copy-Item (Join-Path $PanelDir "index.html")      $preRestore
Copy-Item (Join-Path $PanelDir "lora_notes.json") $preRestore
if (Test-Path (Join-Path $PanelDir "pose_editor_workflow.json")) {
    Copy-Item (Join-Path $PanelDir "pose_editor_workflow.json") $preRestore
}
if (Test-Path (Join-Path $PanelDir "vendor")) {
    Copy-Item (Join-Path $PanelDir "vendor") (Join-Path $preRestore "vendor") -Recurse
}
Write-Host "已先将当前状态备份到：$preRestore" -ForegroundColor Green

# 执行恢复
$files = @("easy_panel.py", "index.html", "lora_notes.json", "pose_editor_workflow.json")
foreach ($file in $files) {
    $src = Join-Path $snapshot $file
    if (Test-Path $src) {
        Copy-Item $src (Join-Path $PanelDir $file) -Force
        Write-Host "  已恢复：$file" -ForegroundColor Green
    }
}
if (Test-Path (Join-Path $snapshot "vendor")) {
    Remove-Item (Join-Path $PanelDir "vendor") -Recurse -Force
    Copy-Item (Join-Path $snapshot "vendor") (Join-Path $PanelDir "vendor") -Recurse
    Write-Host "  已恢复：vendor\" -ForegroundColor Green
}

Write-Host ""
Write-Host "恢复完成！" -ForegroundColor Green
Write-Host "  如需反悔，可用 pre-restore_$stamp 再恢复一次。" -ForegroundColor Yellow
