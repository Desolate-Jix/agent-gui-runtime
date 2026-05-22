param(
    [string]$ModelPath = "",
    [string]$MmprojPath = "",
    [string]$ServerPath = "",
    [int]$Port = 1234,
    [int]$ContextSize = 4096,
    [int]$GpuLayers = 26,
    [int]$ImageMinTokens = 1024
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$serverInput = if ($ServerPath) { $ServerPath } else { Join-Path $root "tools\llama.cpp-b8892-cuda13\llama-server.exe" }
$modelInput = if ($ModelPath) { $ModelPath } else { Join-Path $root "models\qwen3_6-35b-a3b-iq4_xs-gguf\Qwen-Qwen3.6-35B-A3B-IQ4_XS.gguf" }
$mmprojInput = if ($MmprojPath) { $MmprojPath } else { Join-Path $root "models\qwen3_6-35b-a3b-iq4_xs-gguf\mmproj-Qwen3.6-35B-A3B-Q6_K.gguf" }

$server = Resolve-Path $serverInput
$model = Resolve-Path $modelInput
$mmproj = Resolve-Path $mmprojInput

& $server.Path `
    -m $model.Path `
    --mmproj $mmproj.Path `
    --host 127.0.0.1 `
    --port $Port `
    -ngl $GpuLayers `
    -c $ContextSize `
    --parallel 1 `
    --image-min-tokens $ImageMinTokens `
    --jinja `
    --reasoning off `
    --reasoning-budget 0
