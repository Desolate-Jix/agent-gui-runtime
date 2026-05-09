$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$server = Resolve-Path (Join-Path $root "tools\llama.cpp-b8892-cuda13\llama-server.exe")
$model = Resolve-Path (Join-Path $root "models\qwen3-vl-8b-instruct-gguf\Qwen3VL-8B-Instruct-Q4_K_M.gguf")
$mmproj = Resolve-Path (Join-Path $root "models\qwen3-vl-8b-instruct-gguf\mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf")

& $server.Path `
    -m $model.Path `
    --mmproj $mmproj.Path `
    --host 127.0.0.1 `
    --port 1234 `
    -ngl 99 `
    -c 4096 `
    --image-min-tokens 1024
