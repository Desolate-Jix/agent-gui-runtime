from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def _checkpoint(root: Path) -> Path:
    from app.learn.hybrid import goal_binding_deployed_artifacts as deployed
    from app.learn.hybrid import model_test_storage as storage

    namespace = root / "artifacts" / deployed.UI_VENUS_PROVIDER / deployed.UI_VENUS_CHECKPOINT_REVISION
    paths = []
    for name in deployed.UI_VENUS_CHECKPOINT_FILES:
        path = namespace / name
        _write(path, name)
        paths.append(path)
    return storage.register_downloaded_artifact(
        root=root, provider_id=deployed.UI_VENUS_PROVIDER, repo_id=deployed.UI_VENUS_REPOSITORY,
        revision=deployed.UI_VENUS_CHECKPOINT_REVISION, files=paths,
    )


def _source_checkout(path: Path) -> tuple[Path, str, dict[str, str]]:
    files = {
        "models/grounding/ui_venus1_5_gd.py": "model = 'fake'\n",
        "requirements.txt": "torch==fake\n",
    }
    for relative, content in files.items():
        _write(path / relative, content)
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-m", "source"], check=True, capture_output=True)
    revision = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    return path, revision, {relative: sha256(content.encode("utf-8")).hexdigest() for relative, content in files.items()}


def _fake_runtime(staging: Path, versions: dict[str, str]) -> None:
    staging.mkdir(parents=True)
    executable = Path(sys.executable)
    (staging / "Scripts").mkdir()
    shutil.copy2(executable, staging / "Scripts" / "python.exe")
    base_source = Path(sys.base_prefix)
    base = staging / "base"
    base.mkdir()
    shutil.copy2(base_source / "python.exe", base / "python.exe")
    for candidate in base_source.glob("*.dll"):
        shutil.copy2(candidate, base / candidate.name)
    shutil.copytree(base_source / "DLLs", base / "DLLs")
    shutil.copytree(base_source / "Lib", base / "Lib", ignore=shutil.ignore_patterns("site-packages", "__pycache__", "*.pyc"))
    _write(staging / "pyvenv.cfg", f"home = {base}\nexecutable = {base / 'python.exe'}\ninclude-system-site-packages = false\n")
    for extension in ("python311.dll", "python312.dll", "python313.dll"):
        candidate = executable.parent / extension
        if candidate.exists():
            shutil.copy2(candidate, staging / extension)
    module_names = {"torch": "torch", "torchvision": "torchvision", "transformers": "transformers", "accelerate": "accelerate", "qwen-vl-utils": "qwen_vl_utils", "Pillow": "PIL", "psutil": "psutil"}
    for distribution, module in module_names.items():
        _write(staging / "site-packages" / module / "__init__.py", "VALUE = 1\n")
        metadata_name = distribution.replace("-", "_")
        _write(staging / "site-packages" / f"{metadata_name}-{versions[distribution]}.dist-info" / "METADATA", f"Metadata-Version: 2.1\nName: {distribution}\nVersion: {versions[distribution]}\n")
    for module_name in ("win32api", "win32con", "win32event", "win32job", "win32process"):
        _write(staging / "site-packages" / "win32" / f"{module_name}.py", "VALUE = 1\n")
    _write(staging / "site-packages" / "pywin32.pth", "win32\nwin32/lib\nPythonwin\n")
    _write(staging / "site-packages" / f"pywin32-{versions['pywin32']}.dist-info" / "METADATA", f"Metadata-Version: 2.1\nName: pywin32\nVersion: {versions['pywin32']}\n")
    _write(staging / "Lib" / "site-packages" / "ui_venus_runtime.pth", "../../site-packages\n../../site-packages/win32\n../../site-packages/win32/lib\n../../site-packages/Pythonwin\n../../site-packages/pywin32_system32\n")


def test_ui_venus_production_source_and_sdpa_constants_are_frozen() -> None:
    from app.learn.hybrid import goal_binding_deployed_artifacts as deployed

    assert deployed.WINDOWS_SDPA_RUNTIME_REVISION == "5b84a19727de0e402503d214cc2f39ae60b07cce"
    assert deployed.OFFICIAL_SOURCE_FILES == {
        "models/grounding/ui_venus1_5_gd.py": "8cc7640387be1f8ed9a3452560c3b11ae6487b373229355a45128b79d2c4707c",
        "requirements.txt": "99fdb61e4d2aeb9a56c5026894293b229f82546346d7bf232b432085faa75d9c",
    }
    assert deployed.RUNTIME_PACKAGE_VERSIONS == {
        "torch": "2.12.0+cu130", "torchvision": "0.27.0+cu130", "transformers": "5.12.0",
        "accelerate": "1.14.0", "qwen-vl-utils": "0.0.14", "Pillow": "12.1.1",
        "psutil": "7.2.2", "pywin32": "311",
    }


def test_ui_venus_runtime_smoke_checks_real_windows_process_scope_startup() -> None:
    import scripts.prepare_ui_venus_sdpa_runtime as prepare

    smoke = prepare._smoke_script()
    assert '("pywin32", "win32api")' in smoke
    for module_name in ("win32api", "win32con", "win32event", "win32job", "win32process"):
        assert f'"{module_name}"' in smoke
    assert "windows_process_scope_available()" in smoke
    assert '"windows_process_scope_ready": True' in smoke


def test_ui_venus_runtime_smoke_rejects_missing_windows_process_scope_module(tmp_path: Path) -> None:
    from app.learn.hybrid import goal_binding_deployed_artifacts as deployed
    import scripts.prepare_ui_venus_sdpa_runtime as prepare

    staging = tmp_path / "runtime"
    _fake_runtime(staging, deployed.RUNTIME_PACKAGE_VERSIONS)
    (staging / "site-packages" / "win32" / "win32job.py").unlink()
    with pytest.raises(ValueError, match="Windows process scope startup smoke failed"):
        prepare._run_smoke(staging)


def test_prepare_ui_venus_runtime_materializes_smoked_specialized_artifact(tmp_path: Path, monkeypatch) -> None:
    from app.learn.hybrid import goal_binding_deployed_artifacts as deployed
    from app.learn.hybrid import model_test_storage as storage
    import scripts.prepare_ui_venus_sdpa_runtime as prepare

    monkeypatch.setattr(storage, "MODEL_TEST_ROOT", tmp_path)
    runtime_revision = "b" * 40
    monkeypatch.setattr(deployed, "WINDOWS_SDPA_RUNTIME_REVISION", runtime_revision)
    source, revision, source_hashes = _source_checkout(tmp_path / "source")
    monkeypatch.setattr(deployed, "OFFICIAL_SOURCE_FILES", source_hashes)
    monkeypatch.setattr(deployed, "OFFICIAL_SOURCE_REVISION", f"inclusionAI/UI-Venus@{revision}")
    monkeypatch.setattr(prepare, "OFFICIAL_SOURCE_GIT_REVISION", revision)
    staging = tmp_path / "staging" / deployed.WINDOWS_SDPA_RUNTIME_PROVIDER / runtime_revision
    _fake_runtime(staging, deployed.RUNTIME_PACKAGE_VERSIONS)
    checkpoint_manifest = _checkpoint(tmp_path)
    template = json.loads((Path(__file__).resolve().parents[1] / "configs" / "model_profiles" / "goal_binding_ui_venus_1_5_2b_f16.json").read_text(encoding="utf-8"))
    template["preprocessing"]["source_revision"] = f"inclusionAI/UI-Venus@{revision}"
    template_path = tmp_path / "template.json"
    template_path.write_text(json.dumps(template), encoding="utf-8")

    result = prepare.prepare_ui_venus_sdpa_runtime(root=tmp_path, checkpoint_manifest=checkpoint_manifest, runtime_staging=staging, source_checkout=source, profile_template=template_path)

    profile = json.loads(result["profile"].read_text(encoding="utf-8"))
    assert result["runtime_manifest"].is_file()
    runtime_root = tmp_path / "artifacts" / deployed.WINDOWS_SDPA_RUNTIME_PROVIDER / runtime_revision
    smoke = json.loads((runtime_root / "runtime-smoke.json").read_text(encoding="utf-8"))
    assert smoke["windows_process_scope_ready"] is True
    assert deployed.verify_ui_venus_deployment(profile, tmp_path)["runtime"].name == "python.exe"
    pyvenv = (runtime_root / "pyvenv.cfg").read_text(encoding="utf-8")
    assert f"home = {runtime_root / 'base'}" in pyvenv
    assert f"executable = {runtime_root / 'base' / 'python.exe'}" in pyvenv
    assert str(staging) not in pyvenv
    launched = subprocess.run(
        [str(runtime_root / "Scripts" / "python.exe"), "-I", "-c", "import json,sys; print(json.dumps({'prefix':sys.prefix,'base_prefix':sys.base_prefix}))"],
        check=False, capture_output=True, text=True, encoding="utf-8",
    )
    assert launched.returncode == 0, launched.stderr
    identity = json.loads(launched.stdout)
    assert Path(identity["prefix"]).resolve() == runtime_root.resolve()
    assert Path(identity["base_prefix"]).resolve() == (runtime_root / "base").resolve()
