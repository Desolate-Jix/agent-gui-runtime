[CmdletBinding()]
param([ValidateSet('status', 'check', 'stage', 'apply', 'recover', 'rollback', 'settle', 'enable-checks', 'disable-checks')]
      [string]$Action = 'status')
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv-agent\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { $python = Join-Path $root '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Complete Runtime environment setup before using the updater.' }
$arguments = @('-I', '-B', '-X', 'utf8', (Join-Path $PSScriptRoot 'update_runtime.py'), '--root', $root)
if ($Action -eq 'enable-checks') { $arguments += @('settings', '--auto-check', 'on') }
elseif ($Action -eq 'disable-checks') { $arguments += @('settings', '--auto-check', 'off') }
else { $arguments += $Action }
& $python @arguments
if ($LASTEXITCODE -ne 0) { throw "Runtime maintenance stopped (exit $LASTEXITCODE). See the result above; no automatic retry." }
