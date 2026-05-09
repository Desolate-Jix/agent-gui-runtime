$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$pidPath = Join-Path $root "logs\qwen3-vl-server.pid"

if (Test-Path $pidPath) {
    $pidValue = Get-Content $pidPath
    $process = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
    if ($process) {
        Stop-Process -Id $process.Id -Force
        Write-Output "Stopped Qwen3-VL server process $($process.Id)."
    }
    Remove-Item $pidPath -Force
    return
}

$connections = Get-NetTCPConnection -LocalPort 1234 -State Listen -ErrorAction SilentlyContinue
if (-not $connections) {
    Write-Output "No Qwen3-VL server appears to be listening on port 1234."
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
