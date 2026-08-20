param(
    [switch]$WhatIfOnly
)

$matches = Get-CimInstance Win32_Process |
    Where-Object {
        $_.CommandLine -and
        (
            $_.CommandLine -like '*scripts\seek_mvp_traversal_runner.py*' -or
            $_.CommandLine -like '*scripts/seek_mvp_traversal_runner.py*'
        )
    }

if (-not $matches) {
    Write-Output "No SEEK MVP traversal runner process found."
    exit 0
}

foreach ($proc in $matches) {
    $line = $proc.CommandLine
    Write-Output "Found PID $($proc.ProcessId): $line"
    if (-not $WhatIfOnly) {
        Stop-Process -Id $proc.ProcessId -Force
        Write-Output "Stopped PID $($proc.ProcessId)."
    }
}
