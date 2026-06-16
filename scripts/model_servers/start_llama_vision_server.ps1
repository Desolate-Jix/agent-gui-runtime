param(
    [string]$ModelPath = "",
    [string]$MmprojPath = "",
    [string]$ServerPath = "",
    [int]$Port = 1234,
    [int]$ContextSize = 4096,
    [int]$GpuLayers = 26,
    [int]$ImageMinTokens = 1024,
    [string]$ChatTemplate = ""
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$serverInput = if ($ServerPath) { $ServerPath } else { Join-Path $root "tools\llama.cpp-b8892-cuda13\llama-server.exe" }
$modelInput = if ($ModelPath) { $ModelPath } else { Join-Path $root "models\qwen3-vl-4b-instruct-q4_k_m-gguf\Qwen3VL-4B-Instruct-Q4_K_M.gguf" }
$mmprojInput = if ($MmprojPath) {
    $MmprojPath
} elseif (-not $ModelPath) {
    Join-Path $root "models\qwen3-vl-4b-instruct-q4_k_m-gguf\mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf"
} else {
    ""
}

$server = Resolve-Path $serverInput
$model = Resolve-Path $modelInput
$extraArgs = @()
if ($mmprojInput) {
    $mmproj = Resolve-Path $mmprojInput
    $extraArgs += @("--mmproj", $mmproj.Path)
}
if ($ChatTemplate) {
    $extraArgs += @("--chat-template", $ChatTemplate)
}

& $server.Path `
    -m $model.Path `
    --host 127.0.0.1 `
    --port $Port `
    -ngl $GpuLayers `
    -c $ContextSize `
    --parallel 1 `
    --image-min-tokens $ImageMinTokens `
    --jinja `
    --reasoning off `
    --reasoning-budget 0 `
    @extraArgs
