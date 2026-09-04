from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_REVISION = "b" * 40
OFFICIAL_SOURCE = {
    "gui_actor/__init__.py": "",
    "gui_actor/trainer.py": "def rank0_print(*args):\n    return None\n",
    "gui_actor/modeling_qwen25vl.py": (
        "from .trainer import rank0_print\n"
        "class Qwen2_5_VLForConditionalGenerationWithPointer:\n    pass\n"
    ),
    "gui_actor/inference.py": "def inference(*args, **kwargs):\n    return None\n",
    "gui_actor/constants.py": "grounding_system_message = 'system'\n",
}
OFFICIAL_SOURCE_REPOSITORY_PATHS = {
    relative: f"src/{relative}" for relative in OFFICIAL_SOURCE
}


def test_gui_actor_windows_sdpa_runtime_revision_is_frozen() -> None:
    from app.learn.hybrid import goal_binding_gui_actor_deployed_artifacts as deployed

    assert deployed.WINDOWS_SDPA_RUNTIME_REVISION == "4c44a66451e817a4d6df1d2977019b483924ad84"


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    return path


def _checkpoint(root: Path, *, revision: str | None = None) -> Path:
    from app.learn.hybrid import goal_binding_gui_actor_deployed_artifacts as deployed
    from app.learn.hybrid import model_test_storage as storage

    value = revision or deployed.GUI_ACTOR_CHECKPOINT_REVISION
    namespace = root / "artifacts" / deployed.GUI_ACTOR_PROVIDER / value
    files = [
        _write(namespace / "model.safetensors", "model"),
        _write(namespace / "config.json", "config"),
    ]
    return storage.register_downloaded_artifact(
        root=root,
        provider_id=deployed.GUI_ACTOR_PROVIDER,
        repo_id=deployed.GUI_ACTOR_REPOSITORY,
        revision=value,
        files=files,
    )


def _source_checkout(path: Path) -> tuple[Path, str]:
    for relative, content in OFFICIAL_SOURCE.items():
        _write(path / OFFICIAL_SOURCE_REPOSITORY_PATHS[relative], content)
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test"], check=True
    )
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", "source"],
        check=True,
        capture_output=True,
    )
    revision = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return path, revision


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
    shutil.copytree(
        base_source / "Lib",
        base / "Lib",
        ignore=shutil.ignore_patterns("site-packages", "__pycache__", "*.pyc"),
    )
    _write(
        staging / "pyvenv.cfg",
        f"home = {executable.parent}\ninclude-system-site-packages = false\n",
    )
    for extension in ("python311.dll", "python312.dll", "python313.dll"):
        candidate = executable.parent / extension
        if candidate.exists():
            shutil.copy2(candidate, staging / extension)
    modules = {
        "torch": "torch",
        "torchvision": "torchvision",
        "transformers": "transformers",
        "accelerate": "accelerate",
        "qwen-vl-utils": "qwen_vl_utils",
        "Pillow": "PIL",
        "psutil": "psutil",
    }
    for distribution, module in modules.items():
        _write(
            staging / "Lib" / "site-packages" / module / "__init__.py",
            "VALUE = 1\n",
        )
        metadata = distribution.replace("-", "_")
        _write(
            staging
            / "Lib"
            / "site-packages"
            / f"{metadata}-{versions[distribution]}.dist-info"
            / "METADATA",
            f"Metadata-Version: 2.1\nName: {distribution}\nVersion: {versions[distribution]}\n",
        )
    for relative, content in OFFICIAL_SOURCE.items():
        _write(staging / "Lib" / "site-packages" / relative, content)


def _template(path: Path, source_revision: str) -> Path:
    profile = json.loads(
        (
            ROOT
            / "configs"
            / "model_profiles"
            / "goal_binding_gui_actor_3b_bf16.json"
        ).read_text(encoding="utf-8")
    )
    profile["preprocessing"]["source_revision"] = source_revision
    path.write_text(json.dumps(profile), encoding="utf-8")
    return path


def test_prepare_gui_actor_cli_bootstraps_project_root_in_clean_environment() -> None:
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "prepare_gui_actor_sdpa_runtime.py"),
            "--help",
        ],
        cwd=ROOT.parent,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr


def test_prepare_gui_actor_materializes_composite_runtime(tmp_path, monkeypatch):
    from app.learn.hybrid import goal_binding_gui_actor_deployed_artifacts as deployed
    from app.learn.hybrid import model_test_storage as storage
    import scripts.prepare_gui_actor_sdpa_runtime as prepare

    monkeypatch.setattr(storage, "MODEL_TEST_ROOT", tmp_path)
    monkeypatch.setattr(deployed, "WINDOWS_SDPA_RUNTIME_REVISION", RUNTIME_REVISION)
    source, source_git_revision = _source_checkout(tmp_path / "source")
    source_revision = f"microsoft/GUI-Actor@{source_git_revision}"
    monkeypatch.setattr(deployed, "OFFICIAL_SOURCE_REVISION", source_revision)
    monkeypatch.setattr(prepare, "OFFICIAL_SOURCE_GIT_REVISION", source_git_revision)
    staging = (
        tmp_path
        / "staging"
        / deployed.WINDOWS_SDPA_RUNTIME_PROVIDER
        / RUNTIME_REVISION
    )
    _fake_runtime(staging, deployed.RUNTIME_PACKAGE_VERSIONS)

    result = prepare.prepare_gui_actor_sdpa_runtime(
        root=tmp_path,
        checkpoint_manifest=_checkpoint(tmp_path),
        runtime_staging=staging,
        source_checkout=source,
        profile_template=_template(tmp_path / "template.json", source_revision),
    )

    profile = json.loads(result["profile"].read_text(encoding="utf-8"))
    paths = deployed.verify_gui_actor_deployment(profile, tmp_path)
    assert result["runtime_manifest"].is_file()
    assert paths["runtime"].name == "python.exe"
    runtime_root = (
        tmp_path
        / "artifacts"
        / deployed.WINDOWS_SDPA_RUNTIME_PROVIDER
        / RUNTIME_REVISION
    )
    for relative in deployed.OFFICIAL_SOURCE_FILES:
        assert (runtime_root / "official" / relative).is_file()
    smoke = json.loads((runtime_root / "runtime-smoke.json").read_text("utf-8"))
    assert smoke["exit_code"] == 0


def test_prepare_gui_actor_rejects_wrong_staging_or_checkpoint_revision(
    tmp_path, monkeypatch
):
    from app.learn.hybrid import goal_binding_gui_actor_deployed_artifacts as deployed
    from app.learn.hybrid import model_test_storage as storage
    import scripts.prepare_gui_actor_sdpa_runtime as prepare

    monkeypatch.setattr(storage, "MODEL_TEST_ROOT", tmp_path)
    monkeypatch.setattr(deployed, "WINDOWS_SDPA_RUNTIME_REVISION", RUNTIME_REVISION)
    wrong = tmp_path / "staging" / "wrong" / RUNTIME_REVISION
    wrong.mkdir(parents=True)
    with pytest.raises(ValueError, match="staging path"):
        prepare.prepare_gui_actor_sdpa_runtime(
            root=tmp_path,
            checkpoint_manifest=tmp_path / "missing.json",
            runtime_staging=wrong,
            source_checkout=tmp_path / "source",
            profile_template=tmp_path / "template.json",
        )

    expected = (
        tmp_path
        / "staging"
        / deployed.WINDOWS_SDPA_RUNTIME_PROVIDER
        / RUNTIME_REVISION
    )
    expected.mkdir(parents=True)
    wrong_manifest = _checkpoint(tmp_path, revision="a" * 40)
    with pytest.raises(ValueError, match="checkpoint parent identity"):
        prepare.prepare_gui_actor_sdpa_runtime(
            root=tmp_path,
            checkpoint_manifest=wrong_manifest,
            runtime_staging=expected,
            source_checkout=tmp_path / "source",
            profile_template=tmp_path / "template.json",
        )


def test_gui_actor_source_checkout_and_smoke_fail_closed(tmp_path, monkeypatch):
    import scripts.prepare_gui_actor_sdpa_runtime as prepare

    source, revision = _source_checkout(tmp_path / "source")
    monkeypatch.setattr(prepare, "OFFICIAL_SOURCE_GIT_REVISION", revision)
    _write(source / "gui_actor" / "trainer.py", "changed\n")
    with pytest.raises(ValueError, match="source checkout is dirty"):
        prepare._verified_official_source(source)

    staging = tmp_path / "runtime"
    executable = _write(staging / "Scripts" / "python.exe", "fake")
    _write(staging / "runtime-smoke.py", prepare._smoke_script())
    monkeypatch.setattr(
        prepare.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1, stdout="", stderr="import failed"
        ),
    )
    with pytest.raises(ValueError, match="runtime smoke failed"):
        prepare._run_smoke(staging)
    assert executable.is_file()


def test_gui_actor_smoke_rejects_wrong_package_identity():
    from app.learn.hybrid import goal_binding_gui_actor_deployed_artifacts as deployed
    import scripts.prepare_gui_actor_sdpa_runtime as prepare

    packages = [
        {
            "distribution": distribution,
            "version": version,
            "module_origin": f"site-packages/{distribution}/__init__.py",
        }
        for distribution, version in deployed.RUNTIME_PACKAGE_VERSIONS.items()
    ]
    packages[0]["version"] = "wrong"
    with pytest.raises(ValueError, match="package version"):
        prepare._validated_smoke_output(
            {"python": {"implementation": "CPython", "version": "3.11.9"}, "packages": packages},
            Path("C:/runtime"),
        )
