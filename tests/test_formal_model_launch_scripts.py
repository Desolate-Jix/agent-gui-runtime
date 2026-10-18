from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
LLAMA_SCRIPT = ROOT / "scripts" / "model_servers" / "start_llama_vision_server.ps1"
VISTA_SCRIPT = ROOT / "scripts" / "model_servers" / "start_transformers_vision_server.ps1"
FORMAL_PYTHON = ROOT / ".superpowers" / "sdd" / "2026-09-07-native-formal-release" / ".venv-formal" / "Scripts" / "python.exe"
EVIDENCE = ROOT / ".superpowers" / "sdd" / "2026-09-07-native-formal-release" / "r7r-launch"
PS_UTF8_PREFIX = (
    "$utf8 = [System.Text.UTF8Encoding]::new($false); "
    "[Console]::OutputEncoding = $utf8; $OutputEncoding = $utf8; "
)


def _run_harmless_powershell_harness(
    name: str, command: str, environment: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    """以隐藏、非交互方式运行安全桩，并只保留小型文本日志。"""
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", PS_UTF8_PREFIX + command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, **environment},
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        timeout=15,
    )
    (EVIDENCE / f"{name}.log").write_text(
        f"exit_code={result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        encoding="utf-8",
        newline="\n",
    )
    return result


def _powershell_ast_contract(script: Path) -> dict[str, object]:
    """只读取脚本的 PowerShell AST，绝不执行其中的服务命令。"""
    command = (
        "$tokens = $null; $errors = $null; "
        "$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:AST_TARGET, [ref]$tokens, [ref]$errors); "
        "if ($errors.Count) { $errors | ForEach-Object { $_.Message }; exit 1 }; "
        "[pscustomobject]@{ "
        "parameters = @($ast.ParamBlock.Parameters | ForEach-Object { [pscustomobject]@{ name = $_.Name.VariablePath.UserPath; declaration = $_.Extent.Text } }); "
        "commands = @($ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.CommandAst] }, $true) | ForEach-Object { $_.Extent.Text }) "
        "} | ConvertTo-Json -Depth 4 -Compress"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", PS_UTF8_PREFIX + command],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "AST_TARGET": str(script)},
        timeout=15,
    )
    return json.loads(result.stdout)


def _parameters(contract: dict[str, object]) -> dict[str, str]:
    return {
        item["name"]: item["declaration"]
        for item in contract["parameters"]
    }


def test_llama_script_ast_contract_exposes_model_alias_and_host_override() -> None:
    """仅验证静态 PowerShell AST 合约，不启动 llama-server。"""
    contract = _powershell_ast_contract(LLAMA_SCRIPT)
    parameters = _parameters(contract)

    assert "ModelName" in parameters
    assert "HostName" in parameters
    assert "Alias(\"Host\")" in parameters["HostName"]
    assert '"127.0.0.1"' in parameters["HostName"]

    source = LLAMA_SCRIPT.read_text(encoding="utf-8")
    assert "--host $HostName" in source
    assert "if ($ModelName)" in source
    assert '"--alias", $ModelName' in source


def test_transformers_script_ast_contract_exposes_explicit_python_path() -> None:
    """仅验证静态 PowerShell AST 合约，不启动 VISTA。"""
    contract = _powershell_ast_contract(VISTA_SCRIPT)
    parameters = _parameters(contract)

    assert "PythonPath" in parameters
    source = VISTA_SCRIPT.read_text(encoding="utf-8")
    assert 'Join-Path $root "app\\vision\\model_workers\\vista_openai_server.py"' in source
    assert (ROOT / "app/vision/model_workers/vista_openai_server.py").is_file()
    assert not (ROOT / "scripts/model_servers/vista_openai_server.py").exists()
    assert "if ($PythonPath)" in source
    assert "Resolve-Path $PythonPath" in source
    assert "$venvPython" in source
    assert 'else { "python" }' in source


def test_llama_script_executes_only_the_supplied_harmless_server_stub(tmp_path: Path) -> None:
    """执行真实启动脚本，但用 JSON 安全桩替换 llama-server。"""
    model = tmp_path / "model.gguf"
    server_stub = tmp_path / "llama-server-stub.ps1"
    model.write_bytes(b"")
    server_stub.write_text(
        "@($args) | ConvertTo-Json -Compress\n",
        encoding="utf-8",
        newline="\r\n",
    )

    result = _run_harmless_powershell_harness(
        "llama-argument-harness",
        "& $env:TARGET -ModelPath $env:MODEL -ServerPath $env:SERVER "
        "-ModelName $env:MODEL_NAME -Host $env:HOST -Port 19001",
        {
            "TARGET": str(LLAMA_SCRIPT),
            "MODEL": str(model),
            "SERVER": str(server_stub),
            "MODEL_NAME": "formal-llama-alias",
            "HOST": "127.0.0.77",
        },
    )

    assert result.returncode == 0, result.stderr
    arguments = json.loads(result.stdout)
    assert arguments[arguments.index("--host") + 1] == "127.0.0.77"
    assert arguments[arguments.index("--alias") + 1] == "formal-llama-alias"


def test_llama_script_propagates_supplied_native_server_nonzero_exit(tmp_path: Path) -> None:
    """真实脚本必须把指定安全 .cmd 桩的非零退出码传回调用方。"""
    model = tmp_path / "model.gguf"
    server_stub = tmp_path / "llama-server-exit-23.cmd"
    model.write_bytes(b"")
    server_stub.write_text("@exit /b 23\r\n", encoding="utf-8", newline="")

    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(LLAMA_SCRIPT),
            "-ModelPath",
            str(model),
            "-ServerPath",
            str(server_stub),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        timeout=15,
    )
    (EVIDENCE / "llama-nonzero-exit-harness.log").write_text(
        f"exit_code={result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        encoding="utf-8",
        newline="\n",
    )

    assert result.returncode == 23


def test_transformers_script_executes_only_intercepted_harmless_python_stub(
    tmp_path: Path,
) -> None:
    """运行真实脚本，但只拦截 vista_openai_server.py 的解析。"""
    model = tmp_path / "model"
    model.mkdir()
    server_stub = tmp_path / "vista-server-stub.py"
    server_stub.write_text(
        "import json\nimport sys\nprint(json.dumps({'argv': sys.argv, 'executable': sys.executable}))\n",
        encoding="utf-8",
        newline="\n",
    )
    command = (
        "function Resolve-Path { "
        "param([Parameter(ValueFromRemainingArguments = $true)][object[]]$Path); "
        "$candidate = [string]$Path[0]; "
        "if ($candidate.EndsWith('vista_openai_server.py')) { "
        "Microsoft.PowerShell.Management\\Resolve-Path -LiteralPath $env:VISTA_STUB "
        "} else { Microsoft.PowerShell.Management\\Resolve-Path -Path $candidate } "
        "}; & $env:TARGET -ModelPath $env:MODEL -PythonPath $env:PYTHON "
        "-Host $env:HOST -Port 19002"
    )

    result = _run_harmless_powershell_harness(
        "transformers-argument-harness",
        command,
        {
            "TARGET": str(VISTA_SCRIPT),
            "MODEL": str(model),
            "PYTHON": str(FORMAL_PYTHON),
            "VISTA_STUB": str(server_stub),
            "HOST": "127.0.0.78",
        },
    )

    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout)
    assert Path(observed["argv"][0]).resolve() == server_stub.resolve()
    assert observed["argv"][observed["argv"].index("--host") + 1] == "127.0.0.78"
    assert Path(observed["executable"]).resolve() == FORMAL_PYTHON.resolve()


def test_transformers_explicit_missing_python_path_does_not_fall_back_or_invoke_stub(
    tmp_path: Path,
) -> None:
    """无效的显式解释器必须在拦截服务桩运行前失败。"""
    model = tmp_path / "model"
    model.mkdir()
    marker = tmp_path / "stub-invoked.txt"
    server_stub = tmp_path / "vista-server-stub.py"
    server_stub.write_text(
        "from pathlib import Path\nPath(r'" + str(marker).replace("\\", "\\\\") + "').write_text('invoked')\n",
        encoding="utf-8",
        newline="\n",
    )
    command = (
        "function Resolve-Path { "
        "param([Parameter(ValueFromRemainingArguments = $true)][object[]]$Path); "
        "$candidate = [string]$Path[0]; "
        "if ($candidate.EndsWith('vista_openai_server.py')) { "
        "Microsoft.PowerShell.Management\\Resolve-Path -LiteralPath $env:VISTA_STUB "
        "} else { Microsoft.PowerShell.Management\\Resolve-Path -Path $candidate } "
        "}; & $env:TARGET -ModelPath $env:MODEL -PythonPath $env:MISSING_PYTHON"
    )

    result = _run_harmless_powershell_harness(
        "transformers-invalid-python-harness",
        command,
        {
            "TARGET": str(VISTA_SCRIPT),
            "MODEL": str(model),
            "MISSING_PYTHON": str(tmp_path / "missing-python.exe"),
            "VISTA_STUB": str(server_stub),
        },
    )

    assert result.returncode != 0
    assert not marker.exists()


def test_common_launcher_forwards_existing_python_path_to_powershell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core import model_server

    script = tmp_path / "start.ps1"
    python = tmp_path / "python.exe"
    script.write_text("# synthetic", encoding="utf-8")
    python.write_bytes(b"synthetic")
    captured: dict[str, object] = {}
    monkeypatch.setattr(model_server, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(
        model_server,
        "_launch_model_server_process",
        lambda **kwargs: captured.update(kwargs) or {"pid": 1},
    )

    assert model_server.start_model_server(
        {
            "profile_id": "vista",
            "start_script": str(script),
            "python_path": str(python),
        }
    ) == {"pid": 1}

    command = captured["command"]
    assert command[command.index("-PythonPath") + 1] == str(python.resolve())


def test_common_launcher_rejects_missing_python_path_before_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core import model_server

    script = tmp_path / "start.ps1"
    script.write_text("# synthetic", encoding="utf-8")
    monkeypatch.setattr(model_server, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(
        model_server,
        "_launch_model_server_process",
        lambda **_kwargs: pytest.fail("must not launch"),
    )

    with pytest.raises(FileNotFoundError, match="python_path"):
        model_server.start_model_server(
            {
                "profile_id": "vista",
                "start_script": str(script),
                "python_path": str(tmp_path / "missing-python.exe"),
            }
        )
