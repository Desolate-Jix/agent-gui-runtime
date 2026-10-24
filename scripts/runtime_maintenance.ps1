# Dot-source from maintained setup only; no process termination or stale-lock deletion.
function Open-RuntimeMaintenance {
    param([Parameter(Mandatory = $true)][string]$InstallationRoot)
    if (-not ('AgentRuntimeMaintenanceNative' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class AgentRuntimeMaintenanceNative {
    [StructLayout(LayoutKind.Sequential)]
    public struct Overlap { public UIntPtr Internal, InternalHigh; public uint Offset, OffsetHigh; public IntPtr Event; }
    [DllImport("kernel32.dll", SetLastError=true)]
    public static extern bool LockFileEx(IntPtr file, uint flags, uint reserved, uint low, uint high, ref Overlap overlap);
}
'@
    }
    $canonicalRoot = [IO.Path]::GetFullPath($InstallationRoot).TrimEnd([IO.Path]::DirectorySeparatorChar)
    $parent = [IO.Path]::GetDirectoryName($canonicalRoot)
    $prefix = '.' + [IO.Path]::GetFileName($canonicalRoot)
    $lockPath = Join-Path $parent ($prefix + '.runtime-maintenance.lock')
    $pendingPath = Join-Path $parent ($prefix + '.runtime-update-pending.json')
    $sessionsPath = Join-Path $parent ($prefix + '.runtime-sessions')
    foreach ($candidate in @($canonicalRoot, $lockPath, $pendingPath, $sessionsPath)) {
        $ancestor = $candidate
        while ($ancestor) {
            if ((Test-Path -LiteralPath $ancestor) -and
                ((Get-Item -LiteralPath $ancestor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
                throw 'Runtime maintenance rejects reparse points.'
            }
            $ancestor = [IO.Path]::GetDirectoryName($ancestor)
        }
    }
    $lease = [IO.File]::Open($lockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::ReadWrite)
    try {
        $overlap = New-Object AgentRuntimeMaintenanceNative+Overlap
        if (-not [AgentRuntimeMaintenanceNative]::LockFileEx($lease.SafeFileHandle.DangerousGetHandle(), 3, 0, 1, 0, [ref]$overlap)) {
            throw 'Runtime is running or maintenance is active. Close Runtime before setup.'
        }
        if (Test-Path -LiteralPath $pendingPath) { throw 'Interrupted Runtime update requires recovery before setup.' }
        if ((Test-Path -LiteralPath $sessionsPath) -and -not (Test-Path -LiteralPath $sessionsPath -PathType Container)) {
            throw 'Runtime session registry is invalid. Maintenance refused.'
        }
        if ((Test-Path -LiteralPath $sessionsPath) -and (Get-ChildItem -LiteralPath $sessionsPath -Force | Select-Object -First 1)) {
            throw 'Runtime session cleanup is unresolved. Settle its original receipts before setup.'
        }
        return $lease
    } catch { $lease.Dispose(); throw }
}
