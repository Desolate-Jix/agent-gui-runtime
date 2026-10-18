"""在全新目录内构建原生程序，保留真实构建输出与失败证据。"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any
REPO_ROOT = Path(__file__).resolve().parent.parent
RELEASE_ROOT = REPO_ROOT / ".superpowers" / "sdd" / "2026-09-07-native-formal-release"
FORMAL_PYTHON = RELEASE_ROOT / ".venv-formal" / "Scripts" / "python.exe"
DEFAULT_BUILD_TOOLS = RELEASE_ROOT / "build-tools-r7a"
_METADATA_QUERY = """import importlib.metadata as m, json, sys
p=[]
for d in sorted(m.distributions(), key=lambda x: x.metadata[\"Name\"].lower()):
 n=d.metadata[\"Name\"]
 p.append({\"name\":n,\"version\":d.version,\"license\":d.metadata.get(\"License\",\"\") or d.metadata.get(\"License-Expression\",\"\")})
print(json.dumps({\"python\":sys.version,\"packages\":p}, ensure_ascii=False, sort_keys=True))"""
def _json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
def _sha256_bytes(value: bytes) -> str: return hashlib.sha256(value).hexdigest()
def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""): digest.update(chunk)
    return digest.hexdigest()
def _require_new_output(path: Path, release_root: Path = RELEASE_ROOT) -> Path:
    resolved, allowed = path.resolve(), release_root.resolve()
    if resolved == allowed or allowed not in resolved.parents: raise ValueError(f"--output-root must be a new directory below {allowed}")
    if resolved.exists(): raise FileExistsError(f"--output-root already exists: {resolved}")
    return resolved
def _probe(command: list[str], *, environment: dict[str, str], logs: Path, label: str) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(command, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=False)
    except subprocess.TimeoutExpired as error:
        (logs / f"{label}.stdout.bin").write_bytes(error.stdout or b"")
        (logs / f"{label}.stderr.bin").write_bytes(error.stderr or b"")
        raise
    (logs / f"{label}.stdout.bin").write_bytes(result.stdout)
    (logs / f"{label}.stderr.bin").write_bytes(result.stderr)
    if result.returncode != 0:
        raise RuntimeError(f"{label} failed with exit {result.returncode}; see preserved binary logs")
    return result
def _runtime_manifest(runtime_python: Path, environment: dict[str, str], logs: Path) -> dict[str, Any]:
    result = _probe([str(runtime_python), "-c", _METADATA_QUERY], environment=environment, logs=logs, label="runtime-metadata")
    observed = json.loads(result.stdout.decode("utf-8", errors="strict"))
    if not isinstance(observed, dict) or not isinstance(observed.get("packages"), list):
        raise ValueError("runtime metadata must contain a package list")
    return {"schema": "agent-review-runtime-manifest-v1", **observed, "payload_sha256": _sha256_bytes(result.stdout), "external_model_resources": {"bundled_wheel_assets": "Installed OCR wheel package data can contain default weights; see final payload hashes.", "external_assets": ["VISTA model assets", "Qwen model assets", "PP-OCRv5 model assets"], "status": "External assets are not downloaded or verified by this build; model inference remains unverified."}, "exclusions": ["user data", "secrets", "user configuration", "external model directories", "test data", "user history"], "runtime_verified": False}
def _build_tools_manifest(runtime_python: Path, environment: dict[str, str], logs: Path) -> dict[str, Any]:
    query = "import PyInstaller, json; print(json.dumps({\"pyinstaller\": PyInstaller.__version__}, sort_keys=True))"
    result = _probe([str(runtime_python), "-c", query], environment=environment, logs=logs, label="build-tools")
    return json.loads(result.stdout.decode("utf-8", errors="strict"))
def _build_environment(runtime_python: Path) -> dict[str, str]:
    environment = os.environ.copy()
    for key in tuple(environment):
        if key.upper() in {"PATH", "PYTHONHOME", "PYTHONPATH"}:
            environment.pop(key)
    system_root_value = next((value for key, value in environment.items() if key.upper() == "SYSTEMROOT"), None)
    if not system_root_value:
        raise ValueError("SystemRoot must be set to an absolute Windows directory")
    system_root = Path(system_root_value)
    if not system_root.is_absolute():
        raise ValueError(f"SystemRoot must be an absolute Windows directory: {system_root_value}")
    system32 = system_root / "System32"
    if not system32.is_dir():
        raise ValueError(f"SystemRoot System32 directory does not exist: {system32}")
    environment["PATH"] = os.pathsep.join((str(runtime_python.resolve().parent), str(system32), str(system_root)))
    environment.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "PIP_NO_INDEX": "1"})
    return environment
def _write_output_hashes(dist: Path, artifact_dir: Path) -> list[dict[str, str]]:
    return [{"path": str(item.relative_to(artifact_dir)), "sha256": _sha256(item)} for item in sorted(dist.rglob("*")) if item.is_file()]
def build(output_root: Path, build_tools: Path, runtime_python: Path, *, timeout: float | None = None, output_parent: Path | None = None) -> int:
    allowed = RELEASE_ROOT
    if output_parent is not None:
        if not output_parent.is_absolute() or not output_parent.is_dir():
            raise ValueError("--output-parent must be an existing absolute directory")
        allowed = output_parent.resolve()
    # 显式选择输出盘仍只允许新子目录，不扩大默认范围或覆盖已有产物。
    output_root = _require_new_output(output_root, allowed)
    output_root.mkdir(parents=True, exist_ok=False)
    logs, work, dist = output_root / "logs", output_root / "work", output_root / "dist"
    timeout = 1800.0 if timeout is None else timeout
    started = time.time()
    record: dict[str, Any] = {"started_at_epoch": started, "succeeded": False}
    try:
        for directory in (logs, work, dist): directory.mkdir(exist_ok=False)
        environment = _build_environment(runtime_python)
        if not build_tools.is_dir(): raise FileNotFoundError(f"build tools directory does not exist: {build_tools}")
        if not runtime_python.is_file(): raise FileNotFoundError(f"formal runtime Python does not exist: {runtime_python}")
        runtime_manifest = _runtime_manifest(runtime_python, environment, logs)
        environment = {**environment, "PYTHONPATH": str(build_tools.resolve())}
        tools_manifest = _build_tools_manifest(runtime_python, environment, logs)
        manifest_path = output_root / "runtime-manifest.json"; _json(manifest_path, runtime_manifest); _json(output_root / "build-tools-manifest.json", tools_manifest)
        command = [str(runtime_python), "-m", "PyInstaller", str(REPO_ROOT / "packaging" / "agent_review.spec"), "--noconfirm", "--distpath", str(dist), "--workpath", str(work)]
        environment["AGENT_REVIEW_RUNTIME_MANIFEST"] = str(manifest_path)
        _json(logs / "command.json", {"command": command, "build_tools": str(build_tools), "runtime_python": str(runtime_python), "started_at_epoch": started})
        # 输出实时落盘，超时或父进程中断也不会丢失已经收到的错误。
        with (logs / "stdout.bin").open("wb") as stdout, (logs / "stderr.bin").open("wb") as stderr:
            result = subprocess.run(command, cwd=REPO_ROOT, env=environment, stdout=stdout, stderr=stderr, timeout=timeout, check=False)
        expected = [dist / "AgentReview" / "AgentReview.exe", dist / "AgentReview" / "AgentReviewBridge.exe"]
        record.update({"returncode": result.returncode, "expected_artifacts": [str(item.relative_to(output_root)) for item in expected], "missing_artifacts": [str(item.relative_to(output_root)) for item in expected if not item.is_file()]})
        if result.returncode == 0 and not record["missing_artifacts"]:
            record["artifacts"] = _write_output_hashes(dist, output_root)
            record["succeeded"] = True
    except (subprocess.TimeoutExpired, RuntimeError, UnicodeDecodeError, ValueError, OSError) as error:
        record["succeeded"] = False
        record["failure"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        ended = time.time(); record.update({"ended_at_epoch": ended, "duration_seconds": ended - started}); _json(output_root / "build-result.json", record)
    return 0 if record["succeeded"] else 1
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", required=True, type=Path); parser.add_argument("--build-tools", type=Path, default=DEFAULT_BUILD_TOOLS); parser.add_argument("--runtime-python", type=Path, default=FORMAL_PYTHON); parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--output-parent", type=Path, help="Explicit existing absolute parent for a new build directory; defaults to the project release root.")
    args = parser.parse_args(argv)
    try: return build(args.output_root, args.build_tools, args.runtime_python, timeout=args.timeout, output_parent=args.output_parent)
    except (ValueError, FileExistsError, FileNotFoundError) as error: parser.error(str(error))
    return 2
if __name__ == "__main__": raise SystemExit(main())
