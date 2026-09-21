# 依赖和下载缓存留在解压目录所在磁盘，模型不随程序复制。
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)][string]$ModelDirectory,
    [string]$DataDirectory,
    [switch]$DownloadModel,
    [switch]$SkipEnvironment
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
Push-Location $root
try {
    if (-not $SkipEnvironment -and $PSCmdlet.ShouldProcess($root, 'Install locked Python 3.11 runtime and dependencies (large download)')) {
        if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'Install uv first: https://docs.astral.sh/uv/getting-started/installation/' }
        $oldCache = $env:UV_CACHE_DIR
        $oldPython = $env:UV_PYTHON_INSTALL_DIR
        try {
            $env:UV_CACHE_DIR = Join-Path $root '.setup-cache\uv'
            $env:UV_PYTHON_INSTALL_DIR = Join-Path $root '.python'
            & uv python install 3.11
            if ($LASTEXITCODE -ne 0) { throw 'Python installation failed.' }
            & uv sync --frozen --group desktop --group vista
            if ($LASTEXITCODE -ne 0) { throw 'Locked dependency installation failed.' }
        } finally {
            $env:UV_CACHE_DIR = $oldCache
            $env:UV_PYTHON_INSTALL_DIR = $oldPython
        }
    }
    if ($DownloadModel -and $PSCmdlet.ShouldProcess($ModelDirectory, 'Download official inclusionAI/VISTA-4B assets (about 9.1 GB)')) {
        $hf = Join-Path $root '.venv\Scripts\hf.exe'
        if (-not (Test-Path -LiteralPath $hf -PathType Leaf)) { throw 'hf.exe not found; complete dependency installation first.' }
        & $hf download inclusionAI/VISTA-4B --local-dir $ModelDirectory --include '*.json' '*.safetensors' '*.jinja'
        if ($LASTEXITCODE -ne 0) { throw 'Model download incomplete; configuration was not generated.' }
    }
    & (Join-Path $PSScriptRoot 'configure_instant.ps1') -ModelDirectory $ModelDirectory -DataDirectory $DataDirectory -Python $python -WhatIf:$WhatIfPreference
} finally {
    Pop-Location
}
