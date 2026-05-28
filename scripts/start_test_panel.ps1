param(
    [string]$RuntimeUrl = "http://127.0.0.1:8000",
    [bool]$StartRuntime = $true,
    [switch]$PrepareRuntime,
    [int]$WaitForModelsSeconds = 0,
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$logs = Join-Path $root "logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null

function Test-CommandExists {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Test-RuntimeReady {
    param([string]$BaseUrl)
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri "$BaseUrl/health" -TimeoutSec 2
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 500
    }
    catch {
        return $false
    }
}

function Invoke-RuntimePrepare {
    param(
        [string]$BaseUrl,
        [int]$WaitSeconds
    )
    $body = @{
        start_models = $true
        stages = @("observe", "locate")
        wait_until_ready = $WaitSeconds -gt 0
        wait_seconds = $WaitSeconds
    } | ConvertTo-Json
    return Invoke-RestMethod -Uri "$BaseUrl/runtime/prepare" -Method Post -Body $body -ContentType "application/json" -TimeoutSec ([Math]::Max(30, $WaitSeconds + 10))
}

if (-not (Test-CommandExists "uv")) {
    throw "uv is not available on PATH. Install uv or run this script from an environment where uv works."
}

Push-Location $root
try {
    if ($CheckOnly) {
        uv run python -m py_compile scripts\settings_panel.py app\settings_panel\desktop.py | Out-Host
        Write-Output "Test panel startup check passed."
        return
    }

    $runtimeProcess = $null
    $startedRuntime = $false

    if ($StartRuntime -and -not (Test-RuntimeReady $RuntimeUrl)) {
        $runtimeLog = Join-Path $logs ("test-panel-runtime-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".log")
        $arguments = @(
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            "cd `"$root`"; uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 *> `"$runtimeLog`""
        )
        $runtimeProcess = Start-Process -FilePath "powershell" -ArgumentList $arguments -WindowStyle Hidden -PassThru
        $startedRuntime = $true

        $deadline = (Get-Date).AddSeconds(25)
        while ((Get-Date) -lt $deadline) {
            if (Test-RuntimeReady $RuntimeUrl) {
                break
            }
            Start-Sleep -Milliseconds 500
        }

        if (-not (Test-RuntimeReady $RuntimeUrl)) {
            throw "Runtime did not become ready at $RuntimeUrl. See log: $runtimeLog"
        }
    }

    if ($PrepareRuntime) {
        Invoke-RuntimePrepare -BaseUrl $RuntimeUrl -WaitSeconds $WaitForModelsSeconds | Out-Host
    }

    try {
        uv run python scripts\settings_panel.py
    }
    finally {
        if ($startedRuntime -and $runtimeProcess -and -not $runtimeProcess.HasExited) {
            Stop-Process -Id $runtimeProcess.Id -Force -ErrorAction SilentlyContinue
        }
    }
}
finally {
    Pop-Location
}
