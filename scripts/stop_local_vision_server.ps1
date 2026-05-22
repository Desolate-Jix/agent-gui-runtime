$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$pidPaths = @(
    (Join-Path $root "logs\qwen3_6-iq4_xs-server.pid"),
    (Join-Path $root "logs\internvl3_5-server.pid"),
    (Join-Path $root "logs\qwen3-vl-server.pid")
)

$stopped = $false
foreach ($pidPath in $pidPaths) {
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

$connections = Get-NetTCPConnection -LocalPort 1234 -State Listen -ErrorAction SilentlyContinue
if (-not $connections) {
    if (-not $stopped) {
        Write-Output "No local vision server appears to be listening on port 1234."
    }
    return
}

$processIds = $connections | Select-Object -ExpandProperty OwningProcess -Unique
foreach ($processId in $processIds) {
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($process) {
        Stop-Process -Id $process.Id -Force
        Write-Output "Stopped process $($process.Id) listening on port 1234."
    }
}
