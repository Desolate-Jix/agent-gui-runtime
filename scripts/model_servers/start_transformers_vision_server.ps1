param(
    [string]$ModelPath = "",
    [string]$ModelName = "inclusionAI/VISTA-4B",
    [Alias("Host")]
    [string]$HostName = "127.0.0.1",
    [int]$Port = 1244,
    [string]$Device = "auto",
    [string]$DType = "bfloat16",
    [int]$MaxNewTokens = 32
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$modelInput = if ($ModelPath) { $ModelPath } else { Join-Path $root "models\vista-4b-safetensors" }
$model = Resolve-Path $modelInput
$serverScript = Resolve-Path (Join-Path $PSScriptRoot "vista_openai_server.py")
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
