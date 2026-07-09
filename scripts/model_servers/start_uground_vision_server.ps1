param(
    [string]$ModelPath = "",
    [string]$ModelName = "osunlp/UGround-V1-7B",
    [Alias("Host")]
    [string]$HostName = "127.0.0.1",
    [int]$Port = 1246,
    [string]$Device = "auto",
    [string]$DType = "float16",
    [int]$MaxNewTokens = 32
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$modelInput = if ($ModelPath) { $ModelPath } else { Join-Path $root "models\uground-v1-7b" }
$model = Resolve-Path $modelInput
$serverScript = Resolve-Path (Join-Path $PSScriptRoot "uground_openai_server.py")
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$python = if (Test-Path $venvPython) { $venvPython } else { "python" }

& $python `
    $serverScript.Path `
    --model-path $model.Path `
    --model-name $ModelName `
    --host $HostName `
    --port $Port `
    --device $Device `
    --dtype $DType `
    --max-new-tokens $MaxNewTokens

exit $LASTEXITCODE
