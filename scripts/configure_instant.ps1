# 测试版一键配置：管理员 MCP、本地即时输入、自动安全策略关闭。
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$ModelDirectory,
    [ValidateSet('local', 'agent_current', 'agent_delegate')][string]$RecognitionSource = 'local',
    [string]$DelegateProfile,
    [string]$DataDirectory,
    [string]$Python
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if ($RecognitionSource -eq 'local' -and -not $ModelDirectory) { throw 'local requires -ModelDirectory.' }
if ($RecognitionSource -ne 'local' -and $ModelDirectory) { throw 'Agent sources do not accept -ModelDirectory.' }
if ($RecognitionSource -eq 'agent_delegate' -and [string]::IsNullOrWhiteSpace($DelegateProfile)) { throw 'agent_delegate requires -DelegateProfile.' }
if ($RecognitionSource -ne 'agent_delegate' -and $DelegateProfile) { throw '-DelegateProfile is only valid for agent_delegate.' }
if (-not $Python) {
    $environmentName = if ($RecognitionSource -eq 'local') { '.venv' } else { '.venv-agent' }
    $Python = Join-Path (Join-Path $root $environmentName) 'Scripts\python.exe'
}
if (-not $DataDirectory) { $DataDirectory = Join-Path (Split-Path -Parent $root) 'AgentReviewInstantData' }
if ($PSCmdlet.ShouldProcess($root, 'Generate ADMINISTRATOR MCP configuration with automatic interception OFF')) {
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'Python not found. Run setup_instant.ps1 first or supply -Python.' }
    $arguments = @((Join-Path $PSScriptRoot 'configure_instant_mcp.py'), '--python', $Python,
        '--recognition-source', $RecognitionSource, '--data-dir', $DataDirectory, '--enable-local-input', '--administrator')
    if ($ModelDirectory) { $arguments += @('--model-directory', $ModelDirectory) }
    if ($DelegateProfile) { $arguments += @('--delegate-profile', $DelegateProfile) }
    & $Python @arguments
    if ($LASTEXITCODE -ne 0) { throw "Configuration failed (exit $LASTEXITCODE)." }
    Write-Host 'Merge the single agent-review-instant entry into your Agent, then reconnect and confirm UAC.'
    Write-Host 'WARNING: supervised test mode; automatic safety interception is OFF; keyboard/mouse operations are real.'
}
