# 依赖和下载缓存留在解压目录所在磁盘，模型不随程序复制。
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$ModelDirectory,
    [ValidateSet('local', 'agent_current', 'agent_delegate')][string]$RecognitionSource = 'local',
    [string]$DelegateProfile,
    [string]$DataDirectory,
    [switch]$DownloadModel,
    [switch]$SkipEnvironment
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$agentSource = $RecognitionSource -ne 'local'
if (-not $agentSource -and -not $ModelDirectory) { throw 'local requires -ModelDirectory.' }
if ($agentSource -and ($ModelDirectory -or $DownloadModel)) { throw 'Agent sources do not accept -ModelDirectory or -DownloadModel.' }
if ($RecognitionSource -eq 'agent_delegate' -and [string]::IsNullOrWhiteSpace($DelegateProfile)) { throw 'agent_delegate requires -DelegateProfile.' }
if ($RecognitionSource -ne 'agent_delegate' -and $DelegateProfile) { throw '-DelegateProfile is only valid for agent_delegate.' }
$environmentName = if ($agentSource) { '.venv-agent' } else { '.venv' }
$environmentPath = Join-Path $root $environmentName
$python = Join-Path $environmentPath 'Scripts\python.exe'
Push-Location $root
try {
    $installDescription = if ($agentSource) { 'Install Python 3.11 Agent-only dependencies (no local model/OCR/UI)' } else { 'Install locked Python 3.11 runtime and local-model dependencies (large download)' }
    if (-not $SkipEnvironment -and $PSCmdlet.ShouldProcess($root, $installDescription)) {
        if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'Install uv first: https://docs.astral.sh/uv/getting-started/installation/' }
        $oldCache = $env:UV_CACHE_DIR
        $oldPython = $env:UV_PYTHON_INSTALL_DIR
        try {
            $env:UV_CACHE_DIR = Join-Path $root '.setup-cache\uv'
            $env:UV_PYTHON_INSTALL_DIR = Join-Path $root '.python'
            & uv python install 3.11 --no-bin --no-registry
            if ($LASTEXITCODE -ne 0) { throw 'Python installation failed.' }
            if ($agentSource) {
                # 使用独立环境，不改写用户已有的本地模型环境。
                if (-not (Test-Path -LiteralPath $environmentPath)) {
                    & uv venv --python 3.11 $environmentPath
                    if ($LASTEXITCODE -ne 0) { throw 'Agent environment creation failed.' }
                }
                if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Existing Agent environment is incomplete; inspect .venv-agent before retrying.' }
                & $python -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 11) else 1)'
                if ($LASTEXITCODE -ne 0) { throw 'Agent environment requires Python 3.11.' }
                & uv pip install --python $python -r (Join-Path $root 'requirements\agent-runtime-win311.txt')
                if ($LASTEXITCODE -ne 0) { throw 'Agent dependency installation failed.' }
            } else {
                & uv sync --frozen --group desktop --group vista
                if ($LASTEXITCODE -ne 0) { throw 'Locked dependency installation failed.' }
            }
        } finally {
            $env:UV_CACHE_DIR = $oldCache
            $env:UV_PYTHON_INSTALL_DIR = $oldPython
        }
    }
    if ($DownloadModel -and $PSCmdlet.ShouldProcess($ModelDirectory, 'Download official inclusionAI/VISTA-4B assets (about 9.1 GB)')) {
        $hf = Join-Path $root '.venv\Scripts\hf.exe'
        if (-not (Test-Path -LiteralPath $hf -PathType Leaf)) { throw 'hf.exe not found; complete dependency installation first.' }
        & $hf download inclusionAI/VISTA-4B --local-dir $ModelDirectory --include '*.json' --include '*.safetensors' --include '*.jinja'
        if ($LASTEXITCODE -ne 0) { throw 'Model download incomplete; configuration was not generated.' }
    }
    $configuration = @{RecognitionSource = $RecognitionSource; DataDirectory = $DataDirectory; Python = $python}
    if ($ModelDirectory) { $configuration.ModelDirectory = $ModelDirectory }
    if ($DelegateProfile) { $configuration.DelegateProfile = $DelegateProfile }
    & (Join-Path $PSScriptRoot 'configure_instant.ps1') @configuration -WhatIf:$WhatIfPreference
} finally {
    Pop-Location
}
