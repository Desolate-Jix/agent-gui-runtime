param(
    [int]$Port = 1234,
    [string]$PidFile = ""
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$pidPaths = @()
if ($PidFile) {
    $pidPaths += if ([System.IO.Path]::IsPathRooted($PidFile)) { $PidFile } else { Join-Path $root $PidFile }
}
$profilePorts = @()
$profileDir = Join-Path $root "configs\model_profiles"
if (Test-Path $profileDir) {
    Get-ChildItem -Path $profileDir -Filter "*.json" -File | ForEach-Object {
        try {
            $profile = Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json
            if ($profile.pid_file) {
                $pidPaths += if ([System.IO.Path]::IsPathRooted($profile.pid_file)) {
                    [string]$profile.pid_file
                } else {
                    Join-Path $root ([string]$profile.pid_file)
                }
            }
            if ($profile.port) {
                $profilePorts += [int]$profile.port
            }
        } catch {
            Write-Warning "Could not read model profile $($_.FullName): $($_.Exception.Message)"
        }
    }
}
$pidPaths += @(
    (Join-Path $root "logs\internvl3_5-server.pid"),
    (Join-Path $root "logs\qwen3-vl-server.pid"),
    (Join-Path $root "logs\*-server.pid")
)

$stopped = $false
foreach ($pidPath in ($pidPaths | Select-Object -Unique)) {
    $resolvedPidPaths = @(Get-Item -Path $pidPath -ErrorAction SilentlyContinue)
    if (-not $resolvedPidPaths) {
        continue
    }
    foreach ($resolvedPidPath in $resolvedPidPaths) {
        $pidValue = Get-Content -LiteralPath $resolvedPidPath.FullName
        $process = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
        if ($process) {
            Stop-Process -Id $process.Id -Force
            Write-Output "Stopped local vision server process $($process.Id)."
            $stopped = $true
        }
        Remove-Item -LiteralPath $resolvedPidPath.FullName -Force
    }
}

$ports = @($Port) + $profilePorts | Select-Object -Unique
foreach ($currentPort in $ports) {
    $connections = Get-NetTCPConnection -LocalPort $currentPort -State Listen -ErrorAction SilentlyContinue
    if (-not $connections) {
        continue
    }

    $processIds = $connections | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($processId in $processIds) {
        $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if ($process) {
            Stop-Process -Id $process.Id -Force
            Write-Output "Stopped process $($process.Id) listening on port $currentPort."
            $stopped = $true
        }
    }
}

if (-not $stopped) {
    Write-Output "No local vision server appears to be listening on known model ports."
}
