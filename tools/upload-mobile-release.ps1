<#
.SYNOPSIS
  Publish (or refresh) the Android APK release for Easy Panel.

.DESCRIPTION
  Creates/reuses the GitHub release for the current android-client version and
  uploads release-artifacts/app-debug.apk plus app-debug.apk.sha256.

  The token is NEVER stored in this file: export it for the current shell first.
  A fine-grained token needs "Contents: Read and write" on this repository.

    $env:GITHUB_TOKEN = '<paste your token here>'
    powershell -NoProfile -ExecutionPolicy Bypass -File tools\upload-mobile-release.ps1

  Chinese text is uploaded as UTF-8 bytes on purpose: passing it through the
  terminal/JSON encoders mangles it into "??" (learned the hard way).
#>
[CmdletBinding()]
param(
    [string]$Repo = 'ideal00/web-comfyui-controller',
    [string]$ArtifactsDir = 'android-client/android/app/build/outputs/apk/debug',
    [string]$NotesFile = '',
    [string]$Commit = '',
    [switch]$ReplaceAssets,
    [switch]$Draft,
    [switch]$Prerelease
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$token = [string]$env:GITHUB_TOKEN
if (-not $token.Trim()) {
    throw 'Please set $env:GITHUB_TOKEN (Contents: Read and write) before running this script.'
}

$version = (Get-Content 'android-client/package.json' -Raw | ConvertFrom-Json).version
$tag = "mobile-v$version"
if (-not $NotesFile) { $NotesFile = "docs/releases/$tag.md" }
if (-not $Commit) { $Commit = (git rev-parse HEAD).Trim() }
if ($LASTEXITCODE -ne 0 -or $Commit -notmatch '^[0-9a-f]{40}$') { throw 'A verified full Git commit SHA is required.' }
if (git status --porcelain --untracked-files=no) { throw 'Commit tracked changes before publishing.' }
if (-not (Test-Path -LiteralPath $NotesFile -PathType Leaf)) { throw "Missing release notes: $NotesFile" }
$apk = Join-Path $ArtifactsDir 'app-debug.apk'
$sha = Join-Path $ArtifactsDir 'app-debug.apk.sha256'
foreach ($file in @($apk)) {
    if (-not (Test-Path $file)) { throw "Missing artifact: $file (build it with 'pnpm android:apk' first)." }
}
$metadataPath = Join-Path $ArtifactsDir 'output-metadata.json'
if (-not (Test-Path -LiteralPath $metadataPath)) { throw 'Missing Gradle output-metadata.json; rebuild the APK first.' }
$metadata = Get-Content -LiteralPath $metadataPath -Raw | ConvertFrom-Json
if ($metadata.elements[0].versionName -ne $version -or $metadata.applicationId -ne 'app.rpgbox.mobile.debug') {
    throw 'APK build metadata does not match package.json or the expected Debug package.'
}

$actual = (Get-FileHash $apk -Algorithm SHA256).Hash.ToLower()
"$actual  app-debug.apk" | Set-Content -Path $sha -Encoding ASCII -NoNewline
Write-Host "APK SHA256: $actual"

$headers = @{
    Authorization          = "Bearer $token"
    Accept                 = 'application/vnd.github+json'
    'X-GitHub-Api-Version' = '2022-11-28'
    'User-Agent'           = 'easy-panel-release'
}
$api = "https://api.github.com/repos/$Repo/releases"

function Invoke-GitHub {
    param([string]$Method, [string]$Uri, [byte[]]$Body, [string]$ContentType)
    $params = @{ Method = $Method; Uri = $Uri; Headers = $headers }
    if ($Body) { $params.Body = $Body; $params.ContentType = $ContentType }
    Invoke-RestMethod @params
}

$release = $null
try {
    $release = Invoke-GitHub -Method Get -Uri "$api/tags/$tag"
    Write-Host "Reusing existing release $tag"
} catch {
    if ([int]$_.Exception.Response.StatusCode -ne 404) { throw }
    $body = @{
        tag_name   = $tag
        target_commitish = $Commit
        name       = "Easy Panel Android $tag"
        make_latest = 'false'
        draft      = [bool]$Draft
        prerelease = [bool]$Prerelease
    }
    $release = Invoke-GitHub -Method Post -Uri $api `
        -Body ([Text.Encoding]::UTF8.GetBytes(($body | ConvertTo-Json -Compress))) `
        -ContentType 'application/json; charset=utf-8'
    Write-Host "Created release $tag"
}

if (@($release.assets).Count -gt 0 -and -not $ReplaceAssets) {
    throw 'Release already has assets. Use a new version, or explicitly pass -ReplaceAssets to repair it.'
}

if (Test-Path $NotesFile) {
    $notes = [IO.File]::ReadAllText((Resolve-Path $NotesFile), [Text.Encoding]::UTF8)
    $patch = @{ body = $notes } | ConvertTo-Json -Compress -Depth 3
    Invoke-GitHub -Method Patch -Uri "$api/$($release.id)" `
        -Body ([Text.Encoding]::UTF8.GetBytes($patch)) `
        -ContentType 'application/json; charset=utf-8' | Out-Null
    Write-Host 'Release notes updated.'
}

foreach ($name in @('app-debug.apk', 'app-debug.apk.sha256')) {
    $path = Join-Path $ArtifactsDir $name
    $existing = @($release.assets) | Where-Object { $_.name -eq $name }
    foreach ($asset in $existing) {
        Invoke-GitHub -Method Delete -Uri "https://api.github.com/repos/$Repo/releases/assets/$($asset.id)" | Out-Null
        Write-Host "Removed old asset $name"
    }
    $upload = "https://uploads.github.com/repos/$Repo/releases/$($release.id)/assets?name=$name"
    $bytes = [IO.File]::ReadAllBytes((Resolve-Path $path))
    Invoke-GitHub -Method Post -Uri $upload -Body $bytes -ContentType 'application/octet-stream' | Out-Null
    Write-Host "Uploaded $name"
}

Write-Host ''
Write-Host "Done: https://github.com/$Repo/releases/tag/$tag"
Write-Host "SHA256 file content: $((Get-Content $sha -Raw).Trim())"
