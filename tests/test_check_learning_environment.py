from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import builtins


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_learning_environment.py"


def _load_module(tmp_path: Path):
    spec = importlib.util.spec_from_file_location("check_learning_environment", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # 测试源码与固定资产都放临时目录，不能依赖开发机的 D/E 盘模型。
    module.PROJECT_ROOT = tmp_path / "doctor-source"
    source = module.PROJECT_ROOT / "app/learn/hybrid/vista_current_source.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    pinned = module.PROJECT_ROOT / "pinned-vista"
    pinned.mkdir()
    runtime = module.PROJECT_ROOT / "python.exe"
    runtime.write_bytes(b"metadata-only runtime")
    source.write_text(
        'VISTA_PROFILE_PATH = "configs/model_profiles/vista_4b_transformers.json"\n'
        'VISTA_SERVER_PATH = "app/vision/model_workers/vista_openai_server.py"\n'
        f"VISTA_RUNTIME = Path({str(runtime)!r})\n"
        f"DEFAULT_MODEL_PATH = Path({str(pinned)!r})\n",
        encoding="utf-8",
    )
    runner = module.PROJECT_ROOT / "scripts/run_learning_gui_actor_once.py"
    runner.parent.mkdir(parents=True, exist_ok=True)
    runner.write_text(
        f"parser.add_argument('--artifact-root', default=Path({str(tmp_path)!r}) / 'assets')\n",
        encoding="utf-8",
    )
    return module


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _profiles(project_root: Path) -> None:
    profiles = project_root / "configs" / "model_profiles"
    _write_json(
        profiles / "learn_mode_omniparser_v2.json",
        {
            "model_path": "models/omni/weights",
            "expected_paths": {
                "code_path": "tools/omni",
                "weights_path": "models/omni/weights",
                "runtime_path": "tools/omni/.venv",
            },
        },
    )
    _write_json(
        profiles / "vista_4b_transformers.json",
        {
            "model_path": "models/vista-4b-safetensors-sharded",
        },
    )
    _write_json(
        profiles / "goal_binding_gui_actor_3b_bf16.json",
        {
            "artifact_manifest": {
                "relative_path": "reports/deploy/deployment.json",
                "status": "verified",
            },
            "runtime": {"isolated_runtime_path": "artifacts/runtime/Scripts/python.exe"},
        },
    )
    _write_json(project_root / "configs" / "learn_hybrid_v1_2.json", {"config_id": "learn_hybrid_v1_2"})


def _complete_tree(project_root: Path, artifact_root: Path) -> None:
    _profiles(project_root)
    for path in [
        project_root / "models" / "omni" / "weights",
        project_root / "tools" / "omni",
        project_root / "tools" / "omni" / ".venv",
        project_root / "tools" / "omni" / ".venv" / "Scripts",
        project_root / "app" / "vision" / "model_workers",
        artifact_root / "artifacts" / "gui" / "model",
        artifact_root / "artifacts" / "gui" / "model2",
        artifact_root / "artifacts" / "runtime" / "Scripts",
    ]:
        path.mkdir(parents=True, exist_ok=True)
    (project_root / "tools" / "omni" / ".venv" / "Scripts" / "python.exe").write_bytes(b"omni")
    (project_root / "app" / "vision" / "model_workers" / "vista_openai_server.py").write_text("", encoding="utf-8")
    (artifact_root / "artifacts" / "gui" / "model" / "model-00001-of-00002.safetensors").write_bytes(b"one")
    (artifact_root / "artifacts" / "gui" / "model2" / "model-00002-of-00002.safetensors").write_bytes(b"two")
    (artifact_root / "artifacts" / "runtime" / "Scripts" / "python.exe").write_bytes(b"runtime")
    _write_json(
        artifact_root / "reports" / "deploy" / "deployment.json",
        {"checkpoint_parent": {"relative_path": "manifests/checkpoint.json"}},
    )
    _write_json(
        artifact_root / "manifests" / "checkpoint.json",
        {
            "files": [
                {"relative_path": "artifacts/gui/model/model-00001-of-00002.safetensors"},
                {"relative_path": "artifacts/gui/model2/model-00002-of-00002.safetensors"},
            ]
        },
    )


def test_reports_metadata_only_readiness_and_all_gui_actor_shards(tmp_path: Path) -> None:
    module = _load_module(tmp_path)
    project_root = tmp_path / "project"
    artifact_root = tmp_path / "assets"
    _complete_tree(project_root, artifact_root)

    report = module.check_learning_environment(project_root=project_root, artifact_root=artifact_root)

    assert report["status"] == "metadata_present_runtime_not_run"
    assert report["runtime"]["model"] == "not_run"
    assert report["runtime"]["gpu"] == "not_run"
    shard_check = next(item for item in report["checks"] if item["id"] == "gui_actor.checkpoint_shards")
    assert shard_check["status"] == "present"
    assert shard_check["observed_count"] == 2
    assert report["managed_hybrid_v1_2"]["status"] == "blocked"
    assert "weight hashes" in " ".join(report["uncertainties"]).lower()


def test_missing_and_traversal_paths_are_actionable_without_store_mutation(tmp_path: Path) -> None:
    module = _load_module(tmp_path)
    project_root = tmp_path / "project"
    artifact_root = tmp_path / "assets"
    _complete_tree(project_root, artifact_root)
    profile = project_root / "configs" / "model_profiles" / "learn_mode_omniparser_v2.json"
    _write_json(profile, {"model_path": "../escape", "expected_paths": {"code_path": "tools/missing"}})
    before = sorted((str(path.relative_to(tmp_path)), path.stat().st_mtime_ns) for path in tmp_path.rglob("*"))

    report = module.check_learning_environment(project_root=project_root, artifact_root=artifact_root)
    after = sorted((str(path.relative_to(tmp_path)), path.stat().st_mtime_ns) for path in tmp_path.rglob("*"))

    assert report["status"] == "missing_prerequisites"
    assert any(item["status"] == "invalid" and "traversal" in item["detail"] for item in report["checks"])
    assert any(item["status"] == "missing" for item in report["checks"])
    assert before == after


def test_bounded_checker_uses_no_model_import_or_subprocess(tmp_path: Path) -> None:
    module = _load_module(tmp_path)
    _complete_tree(tmp_path / "project", tmp_path / "assets")
    original_open = Path.open
    original_import = builtins.__import__

    def guarded_open(path: Path, *args, **kwargs):
        if path.suffix in {".safetensors", ".exe"}:
            raise AssertionError(f"asset content was opened: {path}")
        return original_open(path, *args, **kwargs)

    def guarded_import(name, *args, **kwargs):
        if name.split(".")[0] in {"torch", "transformers", "PIL", "psutil", "subprocess"}:
            raise AssertionError(f"forbidden runtime import: {name}")
        return original_import(name, *args, **kwargs)

    Path.open = guarded_open
    builtins.__import__ = guarded_import
    try:
        report = module.check_learning_environment(project_root=tmp_path / "project", artifact_root=tmp_path / "assets")
    finally:
        Path.open = original_open
        builtins.__import__ = original_import

    assert report["runtime"] == {"model": "not_run", "gpu": "not_run", "ocr": "not_run", "gui": "not_run", "network": "not_run"}


def test_malformed_hybrid_config_is_reported_as_invalid(tmp_path: Path) -> None:
    module = _load_module(tmp_path)
    project_root = tmp_path / "project"
    artifact_root = tmp_path / "assets"
    _complete_tree(project_root, artifact_root)
    (project_root / "configs" / "learn_hybrid_v1_2.json").write_text("{not json", encoding="utf-8")

    report = module.check_learning_environment(project_root=project_root, artifact_root=artifact_root)

    hybrid = next(item for item in report["checks"] if item["id"] == "hybrid_v1_2.config")
    assert hybrid["status"] == "invalid"
    assert "invalid JSON" in hybrid["detail"]


def test_missing_second_shard_and_omni_interpreter_are_actionable(tmp_path: Path) -> None:
    module = _load_module(tmp_path)
    project_root = tmp_path / "project"
    artifact_root = tmp_path / "assets"
    _complete_tree(project_root, artifact_root)
    (artifact_root / "artifacts" / "gui" / "model2" / "model-00002-of-00002.safetensors").unlink()
    (project_root / "tools" / "omni" / ".venv" / "Scripts" / "python.exe").unlink()

    report = module.check_learning_environment(project_root=project_root, artifact_root=artifact_root)

    assert report["status"] == "missing_prerequisites"
    assert next(item for item in report["checks"] if item["id"] == "omni.runtime_python")["status"] == "missing"
    assert next(item for item in report["checks"] if item["id"] == "gui_actor.checkpoint_shards")["status"] == "missing"


def test_vista_pinned_constants_ignore_project_root_override_and_cli_is_actionable(tmp_path: Path, capsys) -> None:
    module = _load_module(tmp_path)
    project_root = tmp_path / "alternate-project"
    artifact_root = tmp_path / "assets"
    _complete_tree(project_root, artifact_root)

    report = module.check_learning_environment(project_root=project_root, artifact_root=artifact_root)
    (project_root / "tools" / "omni" / ".venv" / "Scripts" / "python.exe").unlink()
    exit_code = module.main(["--project-root", str(project_root), "--artifact-root", str(artifact_root)])
    stdout = capsys.readouterr().out

    vista = next(item for item in report["checks"] if item["id"] == "vista.model_directory")
    assert Path(vista["path"]) == module.PROJECT_ROOT / "pinned-vista"
    assert not Path(vista["path"]).is_relative_to(project_root)
    assert exit_code == 1
    assert "check=" in stdout and "path=" in stdout and "detail=" in stdout


def test_oversized_json_is_rejected_by_bounded_reader(tmp_path: Path) -> None:
    module = _load_module(tmp_path)
    path = tmp_path / "large.json"
    path.write_bytes(b"{" + b" " * module.MAX_JSON_BYTES + b"}")

    payload, error = module._read_small_json(path)

    assert payload is None
    assert "safety cap" in error


def test_cli_preserves_chinese_json_even_when_shell_encoding_is_ascii(tmp_path: Path):
    import os
    import subprocess
    import sys

    project = tmp_path / "中文配置"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--json", "--project-root", str(project),
         "--artifact-root", str(tmp_path / "assets")],
        env={**os.environ, "PYTHONIOENCODING": "ascii"},
        capture_output=True, timeout=15,
    )
    assert result.returncode == 1
    assert result.stderr == b""
    payload = json.loads(result.stdout.decode("utf-8"))
    assert payload["inspection_roots"]["project_root"] == str(project.resolve())
