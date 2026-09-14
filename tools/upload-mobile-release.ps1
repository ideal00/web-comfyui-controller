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
    [string]$ArtifactsDir = 'release-artifacts',
    [string]$NotesFile = 'release-artifacts/mobile-release-notes.md',
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
$apk = Join-Path $ArtifactsDir 'app-debug.apk'
$sha = Join-Path $ArtifactsDir 'app-debug.apk.sha256'
foreach ($file in @($apk, $sha)) {
    if (-not (Test-Path $file)) { throw "Missing artifact: $file (build it with 'pnpm android:apk' first)." }
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
    $body = @{
        tag_name   = $tag
        name       = "Easy Panel Android $tag"
        draft      = [bool]$Draft
        prerelease = [bool]$Prerelease
    }
    $release = Invoke-GitHub -Method Post -Uri $api `
        -Body ([Text.Encoding]::UTF8.GetBytes(($body | ConvertTo-Json -Compress))) `
        -ContentType 'application/json; charset=utf-8'
    Write-Host "Created release $tag"
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
