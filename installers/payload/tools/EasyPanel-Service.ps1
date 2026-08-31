[CmdletBinding()]
param(
    [ValidateSet("Start", "Stop", "Status")]
    [string]$Mode = "Status",
    [switch]$DryRun,
    [switch]$NoBrowser,
    [string]$WorkspaceRoot = "",
    [string]$PanelRoot = "",
    [string]$ComfyRoot = ""
)

$ErrorActionPreference = "Stop"

function Resolve-FullPath([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return "" }
    return [System.IO.Path]::GetFullPath($Value)
}

function Test-SamePath([string]$Left, [string]$Right) {
    if ([string]::IsNullOrWhiteSpace($Left) -or [string]::IsNullOrWhiteSpace($Right)) {
        return $false
    }
    try {
        $leftFull = (Resolve-FullPath $Left).TrimEnd('\')
        $rightFull = (Resolve-FullPath $Right).TrimEnd('\')
        return $leftFull.Equals($rightFull, [System.StringComparison]::OrdinalIgnoreCase)
    } catch {
        return $false
    }
}

function Test-PathWithin([string]$Path, [string]$Parent) {
    if ([string]::IsNullOrWhiteSpace($Path) -or [string]::IsNullOrWhiteSpace($Parent)) {
        return $false
    }
    try {
        $pathFull = Resolve-FullPath $Path
        $parentFull = (Resolve-FullPath $Parent).TrimEnd('\') + '\'
        return $pathFull.StartsWith($parentFull, [System.StringComparison]::OrdinalIgnoreCase)
    } catch {
        return $false
    }
}

function Get-ServiceConfiguration {
    $scriptRoot = Resolve-FullPath $PSScriptRoot
    $defaultPanel = Resolve-FullPath (Join-Path $scriptRoot "..")
    $defaultWorkspace = Resolve-FullPath (Join-Path $defaultPanel "..")
    $workspace = if ([string]::IsNullOrWhiteSpace($WorkspaceRoot)) {
        $defaultWorkspace
    } else {
        Resolve-FullPath $WorkspaceRoot
    }
    $panel = if ([string]::IsNullOrWhiteSpace($PanelRoot)) {
        Resolve-FullPath (Join-Path $workspace "ComfyUI_Easy_Panel")
    } else {
        Resolve-FullPath $PanelRoot
    }
    $comfy = if ([string]::IsNullOrWhiteSpace($ComfyRoot)) {
        Resolve-FullPath (Join-Path $workspace "ComfyUI_windows_portable\ComfyUI")
    } else {
        Resolve-FullPath $ComfyRoot
    }
    $portable = Resolve-FullPath (Join-Path $workspace "ComfyUI_windows_portable")
    return [pscustomobject]@{
        WorkspaceRoot = $workspace
        PanelRoot = $panel
        PortableRoot = $portable
        ComfyRoot = $comfy
        Python = Resolve-FullPath (Join-Path $portable "python_embeded\python.exe")
        ComfyScript = Resolve-FullPath (Join-Path $comfy "main.py")
        PanelScript = Resolve-FullPath (Join-Path $panel "easy_panel.py")
        PanelConfig = Resolve-FullPath (Join-Path $panel "easy_panel_app\config.py")
        PanelIndex = Resolve-FullPath (Join-Path $panel "index.html")
        TokenPath = Resolve-FullPath (Join-Path $panel "rpg_mobile_token.txt")
        InputPath = Resolve-FullPath (Join-Path $comfy "input")
        OutputPath = Resolve-FullPath (Join-Path $comfy "output")
        LoraPath = Resolve-FullPath (Join-Path $comfy "models\loras")
        ComfyUrl = "http://127.0.0.1:8188"
        PanelUrl = "http://127.0.0.1:8190"
        ComfyPort = 8188
        PanelPort = 8190
    }
}

function Assert-ServiceConfiguration([pscustomobject]$Config) {
    if (-not (Test-Path -LiteralPath $Config.WorkspaceRoot -PathType Container)) {
        throw "Workspace root is missing: $($Config.WorkspaceRoot)"
    }
    $expectedPanel = Resolve-FullPath (Join-Path $Config.WorkspaceRoot "ComfyUI_Easy_Panel")
    $expectedComfy = Resolve-FullPath (Join-Path $Config.WorkspaceRoot "ComfyUI_windows_portable\ComfyUI")
    if (-not (Test-SamePath $Config.PanelRoot $expectedPanel)) {
        throw "Panel root must be the formal workspace panel: $expectedPanel"
    }
    if (-not (Test-SamePath $Config.ComfyRoot $expectedComfy)) {
        throw "Comfy root must be the formal portable ComfyUI root: $expectedComfy"
    }
    foreach ($path in @($Config.PanelRoot, $Config.PortableRoot, $Config.ComfyRoot)) {
        if (-not (Test-Path -LiteralPath $path -PathType Container)) {
            throw "Required directory is missing: $path"
        }
    }
    foreach ($path in @($Config.Python, $Config.ComfyScript, $Config.PanelScript,
                        $Config.PanelConfig, $Config.PanelIndex)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Required file is missing: $path"
        }
    }
    foreach ($path in @($Config.Python, $Config.ComfyScript, $Config.PanelScript,
                        $Config.PanelConfig, $Config.PanelIndex, $Config.TokenPath)) {
        if (-not (Test-PathWithin $path $Config.WorkspaceRoot)) {
            throw "Refusing a path outside the workspace: $path"
        }
    }
    foreach ($path in @($Config.InputPath, $Config.OutputPath, $Config.LoraPath)) {
        if (-not (Test-Path -LiteralPath $path -PathType Container)) {
            throw "Required ComfyUI data directory is missing: $path"
        }
        if (-not (Test-PathWithin $path $Config.ComfyRoot)) {
            throw "Refusing a data path outside ComfyUI: $path"
        }
    }
}

function Get-TokenState([pscustomobject]$Config) {
    $exists = Test-Path -LiteralPath $Config.TokenPath -PathType Leaf
    $nonEmpty = $false
    if ($exists) {
        $raw = [System.IO.File]::ReadAllText($Config.TokenPath)
        $nonEmpty = -not [string]::IsNullOrWhiteSpace($raw)
    }
    return [pscustomobject]@{
        Path = $Config.TokenPath
        Exists = $exists
        NonEmpty = $nonEmpty
    }
}

function Ensure-RpgToken([pscustomobject]$Config) {
    $state = Get-TokenState $Config
    if ($state.Exists -and $state.NonEmpty) {
        return [pscustomobject]@{ Token = ([System.IO.File]::ReadAllText($Config.TokenPath)).Trim(); Generated = $false }
    }
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    } finally {
        $rng.Dispose()
    }
    $token = -join ($bytes | ForEach-Object { $_.ToString("x2") })
    $ascii = New-Object System.Text.ASCIIEncoding
    [System.IO.File]::WriteAllText($Config.TokenPath, $token, $ascii)
    return [pscustomobject]@{ Token = $token; Generated = $true }
}

function Get-ProcessSnapshot([int]$ProcessId) {
    $process = Get-CimInstance -ClassName Win32_Process -Filter ("ProcessId=" + $ProcessId) -ErrorAction SilentlyContinue
    if (-not $process) { return $null }
    return [pscustomobject]@{
        Pid = $ProcessId
        Name = [string]$process.Name
        ExecutablePath = [string]$process.ExecutablePath
        CommandLine = [string]$process.CommandLine
    }
}

function Test-ExpectedProcess([pscustomobject]$Snapshot, [pscustomobject]$Config, [ValidateSet("Comfy", "Panel")][string]$Role) {
    if ($null -eq $Snapshot) { return $false }
    if (-not (Test-PathWithin $Snapshot.ExecutablePath $Config.WorkspaceRoot)) { return $false }
    if (-not (Test-SamePath $Snapshot.ExecutablePath $Config.Python)) { return $false }
    $command = $Snapshot.CommandLine
    if ($Role -eq "Panel") {
        return ($command -match [regex]::Escape($Config.PanelScript))
    }
    $mainMarker = ($command -match [regex]::Escape($Config.ComfyScript)) -or
                  ($command -match '(?i)(^|[\\/\s])ComfyUI[\\/]main\.py([\s"]|$)')
    $listenMarker = $command -match '(?i)--listen\s+127\.0\.0\.1'
    $portMarker = $command -match '(?i)--port\s+8188'
    $standaloneMarker = $command -match '(?i)--windows-standalone-build'
    return ($mainMarker -and $listenMarker -and $portMarker -and $standaloneMarker)
}

function Get-EndpointState([pscustomobject]$Config, [int]$Port, [ValidateSet("Comfy", "Panel")][string]$Role) {
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
    $pids = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
    $snapshots = @()
    foreach ($processId in $pids) {
        $snapshot = Get-ProcessSnapshot ([int]$processId)
        if ($null -ne $snapshot) { $snapshots += $snapshot }
    }
    $correctPids = @()
    $unrelatedPids = @()
    foreach ($processId in $pids) {
        $snapshot = $snapshots | Where-Object { $_.Pid -eq [int]$processId } | Select-Object -First 1
        if (Test-ExpectedProcess $snapshot $Config $Role) {
            $correctPids += [int]$processId
        } else {
            $unrelatedPids += [int]$processId
        }
    }
    return [pscustomobject]@{
        Port = $Port
        Role = $Role
        HasListener = ($listeners.Count -gt 0)
        Pids = @($pids | ForEach-Object { [int]$_ })
        CorrectPids = @($correctPids | Sort-Object -Unique)
        UnrelatedPids = @($unrelatedPids | Sort-Object -Unique)
        Addresses = @($listeners | Select-Object -ExpandProperty LocalAddress -Unique)
        Correct = ($pids.Count -gt 0 -and $unrelatedPids.Count -eq 0 -and $correctPids.Count -eq $pids.Count)
    }
}

function Format-Pids([object[]]$Pids) {
    if ($null -eq $Pids -or @($Pids).Count -eq 0) { return "none" }
    return ((@($Pids) | ForEach-Object { [string]$_ }) -join ",")
}

function Write-EndpointStatus([pscustomobject]$State) {
    $listener = if ($State.HasListener) { "listening" } else { "not-listening" }
    $classification = if ($State.Correct) { "formal-process" } elseif ($State.HasListener) { "unrelated-or-unverifiable" } else { "absent" }
    Write-Output ("{0} {1}: {2}; pids={3}; addresses={4}" -f $State.Role, $State.Port, $classification,
        (Format-Pids $State.Pids), ((@($State.Addresses) -join ",")))
}

function Get-HttpStatus([string]$Url, [hashtable]$Headers) {
    try {
        $request = @{ Uri = $Url; Method = "Get"; UseBasicParsing = $true; TimeoutSec = 8 }
        if ($null -ne $Headers) { $request.Headers = $Headers }
        $response = Invoke-WebRequest @request
        return [int]$response.StatusCode
    } catch {
        if ($null -ne $_.Exception.Response) {
            try { return [int]$_.Exception.Response.StatusCode } catch { return 0 }
        }
        return 0
    }
}

function Wait-ForListener([pscustomobject]$Config, [int]$Port, [ValidateSet("Comfy", "Panel")][string]$Role, [int]$TimeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $state = Get-EndpointState $Config $Port $Role
        if ($state.HasListener) { return $state }
        Start-Sleep -Milliseconds 300
    } while ((Get-Date) -lt $deadline)
    return (Get-EndpointState $Config $Port $Role)
}

function Wait-ForPanelPing([pscustomobject]$Config, [string]$Token, [int]$TimeoutSeconds) {
    $headers = @{ "X-RPG-Token" = $Token }
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        if ((Get-HttpStatus "$($Config.PanelUrl)/api/rpg/ping" $headers) -eq 200) { return $true }
        Start-Sleep -Milliseconds 400
    } while ((Get-Date) -lt $deadline)
    return $false
}

function Invoke-WithPanelEnvironment([hashtable]$Environment, [scriptblock]$Action) {
    $previous = @{}
    foreach ($key in $Environment.Keys) {
        $previous[$key] = [System.Environment]::GetEnvironmentVariable($key, "Process")
        [System.Environment]::SetEnvironmentVariable($key, [string]$Environment[$key], "Process")
    }
    try {
        return (& $Action)
    } finally {
        foreach ($key in $Environment.Keys) {
            [System.Environment]::SetEnvironmentVariable($key, $previous[$key], "Process")
        }
    }
}

function Start-ComfyProcess([pscustomobject]$Config) {
    $arguments = @(
        "-s", "ComfyUI\main.py",
        "--windows-standalone-build",
        "--listen", "127.0.0.1",
        "--port", "8188"
    )
    return (Start-Process -FilePath $Config.Python -ArgumentList $arguments -WorkingDirectory $Config.PortableRoot -WindowStyle Hidden -PassThru)
}

function Start-PanelProcess([pscustomobject]$Config, [string]$Token) {
    $environment = [ordered]@{
        EASY_PANEL_ROOT = $Config.PanelRoot
        EASY_PANEL_COMFY_ROOT = $Config.ComfyRoot
        EASY_PANEL_COMFY_INPUT = $Config.InputPath
        EASY_PANEL_OUTPUT = $Config.OutputPath
        EASY_PANEL_LORA_DIR = $Config.LoraPath
        EASY_PANEL_COMFY_URL = $Config.ComfyUrl
        EASY_PANEL_HOST = "0.0.0.0"
        EASY_PANEL_PORT = "8190"
        EASY_PANEL_RPG_TOKEN = $Token
    }
    return (Invoke-WithPanelEnvironment $environment {
        Start-Process -FilePath $Config.Python -ArgumentList @("-s", $Config.PanelScript) -WorkingDirectory $Config.PanelRoot -WindowStyle Hidden -PassThru
    })
}

function Get-NetworkUrls([pscustomobject]$Config) {
    $addresses = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object {
            $_.IPAddress -notlike "127.*" -and
            $_.IPAddress -notlike "169.254.*" -and
            $_.IPAddress -ne "0.0.0.0"
        } |
        Select-Object IPAddress, InterfaceAlias -Unique)
    $tailscale = @($addresses | Where-Object { $_.InterfaceAlias -match "Tailscale" -or $_.IPAddress -match "^100\." })
    Write-Output ("Local URL: $($Config.PanelUrl)")
    foreach ($address in $addresses) {
        if ($tailscale | Where-Object { $_.IPAddress -eq $address.IPAddress }) { continue }
        Write-Output ("LAN URL: http://{0}:8190" -f $address.IPAddress)
    }
    foreach ($address in $tailscale) {
        Write-Output ("Tailscale URL: http://{0}:8190" -f $address.IPAddress)
    }
}

function Invoke-Status([pscustomobject]$Config) {
    $tokenState = Get-TokenState $Config
    $comfy = Get-EndpointState $Config $Config.ComfyPort "Comfy"
    $panel = Get-EndpointState $Config $Config.PanelPort "Panel"
    Write-Output "Easy Panel service status"
    Write-Output ("Workspace: {0}" -f $Config.WorkspaceRoot)
    Write-Output ("Panel root: {0}" -f $Config.PanelRoot)
    Write-Output ("Python: {0}" -f $Config.Python)
    Write-Output ("Token file: exists={0}; nonempty={1}" -f $tokenState.Exists, $tokenState.NonEmpty)
    Write-EndpointStatus $comfy
    Write-EndpointStatus $panel
    if ($panel.HasListener -and $panel.Correct -and (@($panel.Addresses) -notcontains "0.0.0.0")) {
        Write-Warning "8190 is a formal easy_panel.py process, but its listener is not 0.0.0.0; LAN mode cannot be confirmed. Stop then Start to reload the environment."
    }
    if ($comfy.UnrelatedPids.Count -gt 0 -or $panel.UnrelatedPids.Count -gt 0) { throw "An approved port has an unrelated or unverifiable process." }
    if ($comfy.HasListener -and -not $comfy.Correct) { throw "8188 is listening but is not the formal ComfyUI process." }
    if ($panel.HasListener -and -not $panel.Correct) { throw "8190 is listening but is not the formal Easy Panel process." }
}

function Invoke-StartDryRun([pscustomobject]$Config) {
    $tokenState = Get-TokenState $Config
    $comfy = Get-EndpointState $Config $Config.ComfyPort "Comfy"
    $panel = Get-EndpointState $Config $Config.PanelPort "Panel"
    Write-Output "DRY-RUN Start: no process, token, browser, or file mutation will occur."
    Write-EndpointStatus $comfy
    Write-EndpointStatus $panel
    Write-Output ("DRY-RUN token action: {0}" -f $(if ($tokenState.Exists -and $tokenState.NonEmpty) { "preserve existing token file" } else { "generate 32 random bytes as lowercase hex on real Start" }))
    if ($comfy.UnrelatedPids.Count -gt 0) { throw "DRY-RUN would refuse unrelated process(es) on 8188: $(Format-Pids $comfy.UnrelatedPids)" }
    if ($panel.UnrelatedPids.Count -gt 0) { throw "DRY-RUN would refuse unrelated process(es) on 8190: $(Format-Pids $panel.UnrelatedPids)" }
    if ($comfy.HasListener) {
        Write-Output ("DRY-RUN 8188: {0}" -f $(if ($comfy.Correct) { "keep formal ComfyUI PID(s) $(Format-Pids $comfy.CorrectPids)" } else { "fail; listener is not the formal process" }))
    } else {
        Write-Output "DRY-RUN 8188: start hidden formal ComfyUI with --listen 127.0.0.1 --port 8188."
    }
    if ($panel.HasListener) {
        if (-not $panel.Correct) { throw "DRY-RUN 8190 would fail; listener is not the formal process." }
        Write-Output "DRY-RUN 8190: keep the formal easy_panel.py process; its environment cannot be inspected from a running process, so Stop then Start is required to reload mode/token."
        if (@($panel.Addresses) -notcontains "0.0.0.0") {
            Write-Warning "DRY-RUN 8190: listener is not 0.0.0.0; LAN mode is not confirmed."
        }
    } else {
        Write-Output "DRY-RUN 8190: start hidden easy_panel.py with 0.0.0.0:8190 and the formal token/data paths."
    }
}

function Invoke-StopDryRun([pscustomobject]$Config) {
    $comfy = Get-EndpointState $Config $Config.ComfyPort "Comfy"
    $panel = Get-EndpointState $Config $Config.PanelPort "Panel"
    Write-Output "DRY-RUN Stop: no process will be stopped."
    Write-EndpointStatus $panel
    Write-EndpointStatus $comfy
    foreach ($state in @($panel, $comfy)) {
        if ($state.UnrelatedPids.Count -gt 0) {
            Write-Output ("DRY-RUN {0}: skip unrelated/unverifiable PID(s) {1} and report an error." -f $state.Port, (Format-Pids $state.UnrelatedPids))
        } elseif ($state.CorrectPids.Count -gt 0) {
            Write-Output ("DRY-RUN {0}: stop verified formal PID(s) {1}; normal stop first, force only after revalidation if needed." -f $state.Port, (Format-Pids $state.CorrectPids))
        } else {
            Write-Output ("DRY-RUN {0}: already stopped." -f $state.Port)
        }
    }
    if ($panel.UnrelatedPids.Count -gt 0 -or $comfy.UnrelatedPids.Count -gt 0) {
        throw "DRY-RUN found unrelated or unverifiable process(es); no process was touched."
    }
}

function Wait-EndpointGone([pscustomobject]$Config, [int]$Port, [ValidateSet("Comfy", "Panel")][string]$Role, [int]$TimeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $state = Get-EndpointState $Config $Port $Role
        if (-not $state.HasListener) { return $true }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)
    return $false
}

function Stop-VerifiedEndpoint([pscustomobject]$Config, [int]$Port, [ValidateSet("Comfy", "Panel")][string]$Role) {
    $state = Get-EndpointState $Config $Port $Role
    if (-not $state.HasListener) {
        Write-Host ("{0} {1}: already stopped." -f $Role, $Port)
        return $false
    }
    $hadError = $false
    foreach ($processId in @($state.Pids)) {
        $snapshot = Get-ProcessSnapshot ([int]$processId)
        if (-not (Test-ExpectedProcess $snapshot $Config $Role)) {
            Write-Warning ("{0} {1}: skipped unrelated or unverifiable PID {2}." -f $Role, $Port, $processId)
            $hadError = $true
            continue
        }
        Stop-Process -Id ([int]$processId) -ErrorAction Stop
        if (-not (Wait-EndpointGone $Config $Port $Role 4)) {
            $current = Get-ProcessSnapshot ([int]$processId)
            if (Test-ExpectedProcess $current $Config $Role) {
                Stop-Process -Id ([int]$processId) -Force -ErrorAction Stop
                if (-not (Wait-EndpointGone $Config $Port $Role 4)) {
                    throw ("{0} {1}: formal PID {2} remained after normal and force stop." -f $Role, $Port, $processId)
                }
            } else {
                throw ("{0} {1}: PID {2} changed identity; refused force stop." -f $Role, $Port, $processId)
            }
        }
        Write-Host ("{0} {1}: stopped verified PID {2}." -f $Role, $Port, $processId)
    }
    return $hadError
}

function Invoke-Stop([pscustomobject]$Config) {
    $hadError = $false
    if (Stop-VerifiedEndpoint $Config $Config.PanelPort "Panel") { $hadError = $true }
    if (Stop-VerifiedEndpoint $Config $Config.ComfyPort "Comfy") { $hadError = $true }
    if ($hadError) { throw "One or more unrelated port occupants were skipped; see the error above." }
    Write-Output "Stop complete."
}

function Invoke-Start([pscustomobject]$Config) {
    $comfy = Get-EndpointState $Config $Config.ComfyPort "Comfy"
    $panel = Get-EndpointState $Config $Config.PanelPort "Panel"
    if ($comfy.UnrelatedPids.Count -gt 0) { throw "Refusing to start: unrelated or unverifiable PID(s) occupy 8188: $(Format-Pids $comfy.UnrelatedPids)" }
    if ($panel.UnrelatedPids.Count -gt 0) { throw "Refusing to start: unrelated or unverifiable PID(s) occupy 8190: $(Format-Pids $panel.UnrelatedPids)" }

    if (-not $comfy.HasListener) {
        Write-Output "Starting formal ComfyUI on 127.0.0.1:8188 in a hidden process."
        $null = Start-ComfyProcess $Config
        $comfy = Wait-ForListener $Config $Config.ComfyPort "Comfy" 90
        if (-not $comfy.HasListener -or -not $comfy.Correct) {
            throw "ComfyUI did not become the verified formal listener on 8188."
        }
    } elseif ($comfy.Correct) {
        Write-Output ("ComfyUI already running; keeping PID(s) {0}." -f (Format-Pids $comfy.CorrectPids))
    } else {
        throw "8188 is listening but is not the formal ComfyUI process."
    }

    if (-not $panel.HasListener) {
        $tokenInfo = Ensure-RpgToken $Config
        if ($tokenInfo.Generated) { Write-Output "Generated a missing RPG token file using the system cryptographic RNG (token value is never printed)." }
        Write-Output "Starting formal Easy Panel on 0.0.0.0:8190 in a hidden process."
        $null = Start-PanelProcess $Config $tokenInfo.Token
        $panel = Wait-ForListener $Config $Config.PanelPort "Panel" 45
        if (-not $panel.HasListener -or -not $panel.Correct) {
            throw "Easy Panel did not become the verified formal listener on 8190."
        }
        if (-not (Wait-ForPanelPing $Config $tokenInfo.Token 45)) {
            throw "Easy Panel listener started, but authenticated GET /api/rpg/ping did not return 200."
        }
    } elseif ($panel.Correct) {
        if (@($panel.Addresses) -notcontains "0.0.0.0") {
            Write-Warning "8190 is a formal easy_panel.py process, but its listener is not 0.0.0.0. Stop then Start to reload LAN mode."
        }
        Write-Warning "8190 is already a formal easy_panel.py process; its inherited environment cannot be inspected. Stop then Start if the token or LAN mode is not the expected one."
        $tokenState = Get-TokenState $Config
        if ($tokenState.Exists -and $tokenState.NonEmpty) {
            $token = ([System.IO.File]::ReadAllText($Config.TokenPath)).Trim()
            if (-not (Wait-ForPanelPing $Config $token 8)) {
                Write-Warning "Existing 8190 process did not accept the current token; stop then Start to reload it."
            }
        }
    } else {
        throw "8190 is listening but is not the formal Easy Panel process."
    }

    $finalComfy = Get-EndpointState $Config $Config.ComfyPort "Comfy"
    $finalPanel = Get-EndpointState $Config $Config.PanelPort "Panel"
    if (-not $finalComfy.Correct -or -not $finalPanel.Correct) { throw "Final process verification failed." }
    Get-NetworkUrls $Config
    if (-not $NoBrowser) {
        try { $null = Start-Process $Config.PanelUrl } catch { Write-Warning "Could not open the local Easy Panel browser page." }
    }
    Write-Output "Start complete."
}

try {
    $config = Get-ServiceConfiguration
    Assert-ServiceConfiguration $config
    if ($DryRun) {
        if ($Mode -eq "Start") { Invoke-StartDryRun $config }
        elseif ($Mode -eq "Stop") { Invoke-StopDryRun $config }
        else { Invoke-Status $config }
    } elseif ($Mode -eq "Start") {
        Invoke-Start $config
    } elseif ($Mode -eq "Stop") {
        Invoke-Stop $config
    } else {
        Invoke-Status $config
    }
    exit 0
} catch {
    Write-Error ("Easy Panel service controller failed: " + $_.Exception.Message)
    exit 1
}
