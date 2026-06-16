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
$pidPaths += @(
    (Join-Path $root "logs\internvl3_5-server.pid"),
    (Join-Path $root "logs\qwen3-vl-server.pid")
)

$stopped = $false
foreach ($pidPath in ($pidPaths | Select-Object -Unique)) {
    if (-not (Test-Path $pidPath)) {
        continue
    }
    $pidValue = Get-Content $pidPath
    $process = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
    if ($process) {
        Stop-Process -Id $process.Id -Force
        Write-Output "Stopped local vision server process $($process.Id)."
        $stopped = $true
    }
    Remove-Item $pidPath -Force
}

$connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if (-not $connections) {
    if (-not $stopped) {
        Write-Output "No local vision server appears to be listening on port $Port."
    }
    return
}

$processIds = $connections | Select-Object -ExpandProperty OwningProcess -Unique
foreach ($processId in $processIds) {
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($process) {
        Stop-Process -Id $process.Id -Force
        Write-Output "Stopped process $($process.Id) listening on port $Port."
    }
}
