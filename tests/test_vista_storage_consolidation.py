"""删除同权重的单文件副本后，默认配置与真实启动参数仍指向保留的分片版。"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.vision.factory import VisionProviderFactory


ROOT = Path(__file__).resolve().parents[1]
RETAINED = "models/vista-4b-safetensors-sharded"


@pytest.mark.parametrize("provider", ["local", "local_grounding"])
def test_default_vista_config_uses_retained_model(provider: str) -> None:
    config = VisionProviderFactory.load_config(ROOT / "configs" / "vision.json")
    assert config["vision"][provider]["model_path"] == RETAINED


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell launcher")
def test_default_vista_launch_uses_retained_model_without_loading_it(tmp_path: Path) -> None:
    stub = tmp_path / "server_stub.py"
    stub.write_text("import json, sys\nprint(json.dumps(sys.argv))\n", encoding="utf-8")
    command = (
        "$utf8 = [Text.UTF8Encoding]::new($false); "
        "[Console]::OutputEncoding = $utf8; $OutputEncoding = $utf8; "
        "function Resolve-Path { "
        "param([Parameter(ValueFromRemainingArguments = $true)][object[]]$Path); "
        "$candidate = [string]$Path[0]; "
        "if ($candidate.EndsWith('vista_openai_server.py')) { "
        "Microsoft.PowerShell.Management\\Resolve-Path -LiteralPath $env:VISTA_STUB "
        "} else { Microsoft.PowerShell.Management\\Resolve-Path -Path $candidate } }; "
        "& $env:VISTA_TARGET -PythonPath $env:VISTA_PYTHON"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True, text=True, encoding="utf-8", timeout=15,
        creationflags=subprocess.CREATE_NO_WINDOW,
        env={**os.environ, "VISTA_STUB": str(stub), "VISTA_PYTHON": sys.executable,
             "VISTA_TARGET": str(ROOT / "scripts/model_servers/start_transformers_vision_server.ps1")},
    )
    assert result.returncode == 0, result.stderr
    argv = json.loads(result.stdout)
    assert Path(argv[0]) == stub
    assert Path(argv[argv.index("--model-path") + 1]) == ROOT / RETAINED
