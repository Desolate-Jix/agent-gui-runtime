param(
    [string]$ModelPath = "",
    [string]$MmprojPath = "",
    [string]$ServerPath = "",
    [int]$Port = 1234,
    [int]$ContextSize = 8192
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$serverInput = if ($ServerPath) { $ServerPath } else { Join-Path $root "tools\llama.cpp-b8892-cuda13\llama-server.exe" }
$modelInput = if ($ModelPath) { $ModelPath } else { Join-Path $root "models\internvl3_5-8b-gguf\InternVL3_5-8B-Q4_K_M.gguf" }
$mmprojInput = if ($MmprojPath) { $MmprojPath } else { Join-Path $root "models\internvl3_5-8b-gguf\mmproj-model-f16.gguf" }

$server = Resolve-Path $serverInput
$model = Resolve-Path $modelInput
$mmproj = Resolve-Path $mmprojInput

& $server.Path `
    -m $model.Path `
    --mmproj $mmproj.Path `
    --host 127.0.0.1 `
    --port $Port `
    -ngl 99 `
    -c $ContextSize `
    --parallel 1 `
    --image-min-tokens 1024
