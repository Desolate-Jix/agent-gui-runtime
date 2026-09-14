# 测试版一键配置：管理员 MCP、本地即时输入、自动安全策略关闭。
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)][string]$ModelDirectory,
    [string]$DataDirectory,
    [string]$Python
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not $Python) { $Python = Join-Path $root '.venv\Scripts\python.exe' }
if (-not $DataDirectory) { $DataDirectory = Join-Path (Split-Path -Parent $root) 'AgentReviewInstantData' }
if ($PSCmdlet.ShouldProcess($root, 'Generate ADMINISTRATOR MCP configuration with automatic interception OFF')) {
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'Python not found. Run setup_instant.ps1 first or supply -Python.' }
    & $Python (Join-Path $PSScriptRoot 'configure_instant_mcp.py') --python $Python --model-directory $ModelDirectory --data-dir $DataDirectory --enable-local-input --administrator
    if ($LASTEXITCODE -ne 0) { throw "Configuration failed (exit $LASTEXITCODE)." }
    Write-Host 'Merge the single agent-review-instant entry into your Agent, then reconnect and confirm UAC.'
    Write-Host 'WARNING: supervised test mode; automatic safety interception is OFF; keyboard/mouse operations are real.'
}
