"""学习 Omni→GUIActor→VISTA 路径的有界无模型元数据预检。"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAX_JSON_BYTES = 1_000_000


def _read_small_source(path: Path) -> tuple[str | None, str]:
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_JSON_BYTES + 1)
    except OSError as exc:
        return None, f"unreadable: {exc.__class__.__name__}"
    if len(raw) > MAX_JSON_BYTES:
        return None, f"invalid: source exceeds {MAX_JSON_BYTES} byte safety cap"
    try:
        return raw.decode("utf-8"), ""
    except UnicodeDecodeError:
        return None, "invalid: source is not UTF-8"


def _runner_artifact_root() -> tuple[Path | None, str]:
    source_path = PROJECT_ROOT / "scripts" / "run_learning_gui_actor_once.py"
    source, error = _read_small_source(source_path)
    if source is None:
        return None, error
    try:
        tree = ast.parse(source, filename=str(source_path))
    except SyntaxError:
        return None, "invalid: runner source cannot be parsed"
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "add_argument" or not node.args:
            continue
        if not isinstance(node.args[0], ast.Constant) or node.args[0].value != "--artifact-root":
            continue
        default = next((item.value for item in node.keywords if item.arg == "default"), None)
        if isinstance(default, ast.BinOp) and isinstance(default.op, ast.Div):
            left, right = default.left, default.right
            if (
                isinstance(left, ast.Call)
                and isinstance(left.func, ast.Name)
                and left.func.id == "Path"
                and len(left.args) == 1
                and isinstance(left.args[0], ast.Constant)
                and isinstance(left.args[0].value, str)
                and isinstance(right, ast.Constant)
                and isinstance(right.value, str)
            ):
                return Path(left.args[0].value) / right.value, ""
    return None, "invalid: runner artifact-root default was not found"


def _check(check_id: str, status: str, path: Path | None, detail: str, **extra: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"id": check_id, "status": status, "detail": detail}
    if path is not None:
        result["path"] = str(path)
    result.update(extra)
    return result


def _read_small_json(path: Path) -> tuple[dict[str, Any] | None, str]:
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_JSON_BYTES + 1)
    except OSError as exc:
        return None, f"unreadable: {exc.__class__.__name__}"
    if len(raw) > MAX_JSON_BYTES:
        return None, f"invalid: JSON exceeds {MAX_JSON_BYTES} byte safety cap"
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"invalid JSON: {exc.__class__.__name__}"
    if not isinstance(value, dict):
        return None, "invalid: JSON root must be an object"
    return value, ""


def _under(root: Path, raw: object) -> tuple[Path | None, str]:
    if not isinstance(raw, str) or not raw.strip():
        return None, "missing path"
    candidate = Path(raw)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None, "invalid traversal or absolute path"
    try:
        resolved = (root / candidate).resolve()
        resolved.relative_to(root.resolve())
    except (OSError, ValueError):
        return None, "invalid path escapes configured root"
    return resolved, ""


def _path_check(check_id: str, root: Path, raw: object, *, directory: bool) -> dict[str, Any]:
    path, error = _under(root, raw)
    if path is None:
        return _check(check_id, "invalid" if error.startswith("invalid") else "missing", None, error)
    try:
        exists = path.is_dir() if directory else path.is_file()
    except OSError as exc:
        return _check(check_id, "missing", path, f"unreadable: {exc.__class__.__name__}")
    if not exists:
        noun = "directory" if directory else "file"
        return _check(check_id, "missing", path, f"required {noun} is absent")
    try:
        stat = path.stat()
    except OSError as exc:
        return _check(check_id, "missing", path, f"unreadable: {exc.__class__.__name__}")
    return _check(check_id, "present", path, "metadata path exists", bytes=stat.st_size)


def _profile(project_root: Path, filename: str, checks: list[dict[str, Any]]) -> dict[str, Any]:
    path, error = _under(project_root, filename)
    if path is None:
        checks.append(_check(f"profile.{filename}", "invalid", None, error))
        return {}
    if not path.is_file():
        checks.append(_check(f"profile.{filename}", "missing", path, "required profile config is absent"))
        return {}
    payload, error = _read_small_json(path)
    if payload is None:
        checks.append(_check(f"profile.{filename}", "invalid", path, error))
        return {}
    checks.append(_check(f"profile.{filename}", "present", path, "small JSON metadata was read"))
    return payload


def _gui_actor_checks(artifact_root: Path, profile: dict[str, Any], checks: list[dict[str, Any]]) -> None:
    manifest_ref = profile.get("artifact_manifest")
    if not isinstance(manifest_ref, dict):
        checks.append(_check("gui_actor.deployment_manifest", "missing", None, "profile artifact_manifest is absent"))
        return
    deployment_path, error = _under(artifact_root, manifest_ref.get("relative_path"))
    if deployment_path is None:
        checks.append(_check("gui_actor.deployment_manifest", "invalid", None, error))
        return
    deployment, error = _read_small_json(deployment_path) if deployment_path.is_file() else (None, "required file is absent")
    if deployment is None:
        checks.append(_check("gui_actor.deployment_manifest", "missing" if error == "required file is absent" else "invalid", deployment_path, error))
        return
    checks.append(_check("gui_actor.deployment_manifest", "present", deployment_path, "small deployment metadata was read"))
    checkpoint_ref = deployment.get("checkpoint_parent")
    if not isinstance(checkpoint_ref, dict):
        checks.append(_check("gui_actor.checkpoint_manifest", "missing", None, "deployment checkpoint_parent is absent"))
        return
    checkpoint_path, error = _under(artifact_root, checkpoint_ref.get("relative_path"))
    if checkpoint_path is None:
        checks.append(_check("gui_actor.checkpoint_manifest", "invalid", None, error))
        return
    checkpoint, error = _read_small_json(checkpoint_path) if checkpoint_path.is_file() else (None, "required file is absent")
    if checkpoint is None:
        checks.append(_check("gui_actor.checkpoint_manifest", "missing" if error == "required file is absent" else "invalid", checkpoint_path, error))
        return
    checks.append(_check("gui_actor.checkpoint_manifest", "present", checkpoint_path, "small checkpoint manifest metadata was read"))
    files = checkpoint.get("files")
    if not isinstance(files, list):
        checks.append(_check("gui_actor.checkpoint_shards", "invalid", checkpoint_path, "checkpoint manifest files must be a list"))
        return
    shards: list[dict[str, Any]] = []
    invalid = False
    for entry in files:
        if not isinstance(entry, dict):
            invalid = True
            continue
        raw = entry.get("relative_path")
        if isinstance(raw, str) and raw.endswith(".safetensors"):
            shard_path, shard_error = _under(artifact_root, raw)
            if shard_path is None:
                invalid = True
                continue
            shards.append(_path_check("gui_actor.checkpoint_shard", artifact_root, raw, directory=False))
    missing = any(item["status"] != "present" for item in shards)
    if invalid or not shards:
        checks.append(_check("gui_actor.checkpoint_shards", "invalid", checkpoint_path, "manifest has no safe complete safetensors shard list", observed_count=len(shards)))
    elif missing:
        checks.append(_check("gui_actor.checkpoint_shards", "missing", checkpoint_path, "one or more manifest-listed safetensors shards are absent", observed_count=len(shards)))
    else:
        checks.append(_check("gui_actor.checkpoint_shards", "present", checkpoint_path, "all manifest-listed safetensors shards were statted; no weights were read or hashed", observed_count=len(shards)))
    checks.extend(shards)
    runtime = profile.get("runtime") if isinstance(profile.get("runtime"), dict) else {}
    checks.append(_path_check("gui_actor.runtime_python", artifact_root, runtime.get("isolated_runtime_path"), directory=False))


def _vista_constants(checks: list[dict[str, Any]]) -> dict[str, Path | str]:
    source_path = PROJECT_ROOT / "app" / "learn" / "hybrid" / "vista_current_source.py"
    source, error = _read_small_source(source_path)
    if source is None:
        checks.append(_check("vista.current_source_constants", "invalid", source_path, error))
        return {}
    try:
        tree = ast.parse(source, filename=str(source_path))
    except SyntaxError:
        checks.append(_check("vista.current_source_constants", "invalid", source_path, "invalid: source cannot be parsed"))
        return {}
    values: dict[str, Path | str] = {}
    required = {"VISTA_PROFILE_PATH", "VISTA_SERVER_PATH", "VISTA_RUNTIME", "DEFAULT_MODEL_PATH"}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        name = node.targets[0].id
        if name not in required:
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            values[name] = node.value.value
        elif (
            isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "Path"
            and len(node.value.args) == 1
            and isinstance(node.value.args[0], ast.Constant)
            and isinstance(node.value.args[0].value, str)
        ):
            values[name] = Path(node.value.args[0].value)
    if set(values) != required:
        checks.append(_check("vista.current_source_constants", "invalid", source_path, "invalid: required pinned VISTA constants were not found"))
        return {}
    checks.append(_check("vista.current_source_constants", "present", source_path, "bounded AST metadata read pinned VISTA paths"))
    return values


def _absolute_path_check(check_id: str, path: Path, *, directory: bool) -> dict[str, Any]:
    try:
        exists = path.is_dir() if directory else path.is_file()
    except OSError as exc:
        return _check(check_id, "missing", path, f"unreadable: {exc.__class__.__name__}")
    if not exists:
        return _check(check_id, "missing", path, f"required {'directory' if directory else 'file'} is absent")
    return _check(check_id, "present", path, "metadata path exists", bytes=path.stat().st_size)


def check_learning_environment(*, project_root: Path = PROJECT_ROOT, artifact_root: Path | None = None, omni_assets_root: Path | None = None) -> dict[str, Any]:
    project = Path(project_root).resolve()
    runner_root, runner_error = _runner_artifact_root()
    artifact = Path(artifact_root).resolve() if artifact_root is not None else (runner_root.resolve() if runner_root is not None else project)
    omni_root = Path(omni_assets_root).resolve() if omni_assets_root is not None else project
    checks: list[dict[str, Any]] = []
    runner_path = PROJECT_ROOT / "scripts" / "run_learning_gui_actor_once.py"
    checks.append(_check("gui_actor.runner_default", "present" if runner_root is not None else "invalid", runner_path, "bounded AST metadata read runner artifact root" if runner_root is not None else runner_error))
    hybrid_path = project / "configs" / "learn_hybrid_v1_2.json"
    hybrid, error = _read_small_json(hybrid_path) if hybrid_path.is_file() else (None, "required file is absent")
    hybrid_status = "present" if hybrid is not None else ("missing" if error == "required file is absent" else "invalid")
    checks.append(_check("hybrid_v1_2.config", hybrid_status, hybrid_path, "small JSON metadata was read" if hybrid is not None else error))
    omni = _profile(project, "configs/model_profiles/learn_mode_omniparser_v2.json", checks)
    gui = _profile(project, "configs/model_profiles/goal_binding_gui_actor_3b_bf16.json", checks)
    vista_constants = _vista_constants(checks)
    vista_profile = vista_constants.get("VISTA_PROFILE_PATH")
    vista = _profile(project, str(vista_profile), checks) if isinstance(vista_profile, str) else {}
    expected = omni.get("expected_paths") if isinstance(omni.get("expected_paths"), dict) else {}
    checks.append(_path_check("omni.code", omni_root, expected.get("code_path"), directory=True))
    checks.append(_path_check("omni.weights", omni_root, expected.get("weights_path") or omni.get("model_path"), directory=True))
    checks.append(_path_check("omni.runtime", omni_root, expected.get("runtime_path"), directory=True))
    runtime_path, runtime_error = _under(omni_root, expected.get("runtime_path"))
    if runtime_path is None:
        checks.append(_check("omni.runtime_python", "invalid" if runtime_error.startswith("invalid") else "missing", None, runtime_error))
    else:
        checks.append(_absolute_path_check("omni.runtime_python", runtime_path / "Scripts" / "python.exe", directory=False))
    _gui_actor_checks(artifact, gui, checks)
    model_path = vista_constants.get("DEFAULT_MODEL_PATH")
    runtime = vista_constants.get("VISTA_RUNTIME")
    server_path = vista_constants.get("VISTA_SERVER_PATH")
    if isinstance(model_path, Path):
        checks.append(_absolute_path_check("vista.model_directory", model_path, directory=True))
    if isinstance(runtime, Path):
        checks.append(_absolute_path_check("vista.runtime_python", runtime, directory=False))
    if isinstance(server_path, str):
        checks.append(_path_check("vista.server_script", project, server_path, directory=False))
    for name in ("pytest", "fastapi", "psutil"):
        available = importlib.util.find_spec(name) is not None
        checks.append(_check(f"dependency.{name}", "present" if available else "missing", None, "top-level module discoverable without import" if available else "top-level module is not discoverable"))
    has_failure = any(item["status"] in {"missing", "invalid"} for item in checks)
    return {
        "contract_version": "learning_environment_preflight_v1",
        "status": "missing_prerequisites" if has_failure else "metadata_present_runtime_not_run",
        "inspection_roots": {"project_root": str(project), "artifact_root": str(artifact), "omni_assets_root": str(omni_root), "artifact_root_source": "runner_source" if artifact_root is None and runner_root is not None else "inspection_override"},
        "runtime": {"model": "not_run", "gpu": "not_run", "ocr": "not_run", "gui": "not_run", "network": "not_run"},
        "managed_hybrid_v1_2": {"status": "blocked", "reason": "metadata preflight does not authorize managed hybrid_v1_2 runtime execution"},
        "checks": checks,
        "uncertainties": [
            "Metadata presence is not weight hashes, true model loading, VRAM capacity, inference, OCR, GUI, or network readiness.",
            "The VISTA model directory is only statted because this preflight does not read its shard manifest or weights; its pinned contents are not enumerated.",
            "Root overrides are inspection-only and do not modify or apply production runtime configuration.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    # 管道输出同样固定 UTF-8，不能随 Windows 控制台代码页损坏中文路径。
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Check bounded learn-model metadata without starting any runtime.")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--omni-assets-root", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = check_learning_environment(project_root=args.project_root, artifact_root=args.artifact_root, omni_assets_root=args.omni_assets_root)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"status={report['status']}")
        for check in report["checks"]:
            if check["status"] != "present":
                print(f"check={check['id']} status={check['status']} path={check.get('path', '<none>')} detail={check['detail']}")
    return 0 if report["status"] == "metadata_present_runtime_not_run" else 1


if __name__ == "__main__":
    raise SystemExit(main())
