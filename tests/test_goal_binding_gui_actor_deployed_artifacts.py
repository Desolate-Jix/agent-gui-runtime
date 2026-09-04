from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest


RUNTIME_REVISION = "b" * 40


def _write(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def _identity(path: Path, root: Path) -> dict[str, object]:
    return {
        "relative_path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256(path.read_bytes()).hexdigest(),
    }


def _build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    source_revision: str | None = None,
    attention: str = "sdpa",
    smoke_exit: int = 0,
) -> dict[str, object]:
    from app.learn.hybrid import goal_binding_gui_actor_deployed_artifacts as deployed
    from app.learn.hybrid import model_test_storage as storage

    monkeypatch.setattr(storage, "MODEL_TEST_ROOT", tmp_path)
    monkeypatch.setattr(deployed, "WINDOWS_SDPA_RUNTIME_REVISION", RUNTIME_REVISION)
    checkpoint_root = (
        tmp_path
        / "artifacts"
        / deployed.GUI_ACTOR_PROVIDER
        / deployed.GUI_ACTOR_CHECKPOINT_REVISION
    )
    checkpoint_paths = [
        _write(checkpoint_root / "model.safetensors", b"model"),
        _write(checkpoint_root / "config.json", b"config"),
    ]
    runtime_root = (
        tmp_path
        / "artifacts"
        / deployed.WINDOWS_SDPA_RUNTIME_PROVIDER
        / RUNTIME_REVISION
    )
    official = {
        "gui_actor/__init__.py": b"package",
        "gui_actor/modeling_qwen25vl.py": b"modeling",
        "gui_actor/inference.py": b"inference",
        "gui_actor/constants.py": b"constants",
        "gui_actor/trainer.py": b"trainer",
    }
    for relative, payload in official.items():
        _write(runtime_root / "official" / relative, payload)
    source = {
        "contract_version": "goal_binding_gui_actor_source_identity_v1",
        "official_source_revision": source_revision or deployed.OFFICIAL_SOURCE_REVISION,
        "official_source_files": {
            relative: sha256(payload).hexdigest()
            for relative, payload in official.items()
        },
        "project_revision": RUNTIME_REVISION,
        "code_files": deployed._current_code_hashes(),
    }
    source_path = _write(runtime_root / "official-source.json", _json_bytes(source))
    preprocessing = {
        "contract_version": "goal_binding_gui_actor_preprocessing_v1",
        "source_document_sha256": sha256(source_path.read_bytes()).hexdigest(),
        "official_attention_implementation": "flash_attention_2",
        "tested_attention_implementation": attention,
        "dtype": "bfloat16",
        "native_output_kind": "gui_actor_topk_points_v1",
        "coordinate_space": "normalized_0_1",
        "topk": 3,
        "local_files_only": True,
        "device_map": "cuda:0",
    }
    preprocessing_path = _write(
        runtime_root / "preprocessing.json", _json_bytes(preprocessing)
    )
    executable = _write(runtime_root / "Scripts" / "python.exe", b"runtime")
    base_python = _write(runtime_root / "base" / "python.exe", b"base")
    pyvenv = _write(
        runtime_root / "pyvenv.cfg",
        f"home = {runtime_root / 'base'}\nexecutable = {base_python}\n".encode(),
    )
    smoke_script = _write(runtime_root / "runtime-smoke.py", b"smoke")
    package_paths = []
    package_rows = []
    for distribution, version in deployed.RUNTIME_PACKAGE_VERSIONS.items():
        module = distribution.casefold().replace("-", "_")
        package = _write(
            runtime_root / "Lib" / "site-packages" / module / "__init__.py",
            distribution.encode(),
        )
        package_paths.append(package)
        package_rows.append(
            {
                "distribution": distribution,
                "version": version,
                "module_origin": package.relative_to(tmp_path).as_posix(),
            }
        )
    smoke = {
        "contract_version": "goal_binding_gui_actor_sdpa_runtime_smoke_v1",
        "python": {"implementation": "CPython", "version": "3.11.9"},
        "packages": package_rows,
        "python_executable_sha256": sha256(executable.read_bytes()).hexdigest(),
        "smoke_script_sha256": sha256(smoke_script.read_bytes()).hexdigest(),
        "exit_code": smoke_exit,
    }
    smoke_path = _write(runtime_root / "runtime-smoke.json", _json_bytes(smoke))
    runtime_paths = [
        executable,
        base_python,
        pyvenv,
        smoke_script,
        smoke_path,
        source_path,
        preprocessing_path,
        *package_paths,
        *[runtime_root / "official" / relative for relative in official],
    ]
    checkpoint_manifest = storage.register_downloaded_artifact(
        root=tmp_path,
        provider_id=deployed.GUI_ACTOR_PROVIDER,
        repo_id=deployed.GUI_ACTOR_REPOSITORY,
        revision=deployed.GUI_ACTOR_CHECKPOINT_REVISION,
        files=checkpoint_paths,
    )
    runtime_manifest = storage.register_downloaded_artifact(
        root=tmp_path,
        provider_id=deployed.WINDOWS_SDPA_RUNTIME_PROVIDER,
        repo_id=deployed.WINDOWS_SDPA_RUNTIME_REPOSITORY,
        revision=RUNTIME_REVISION,
        files=runtime_paths,
    )

    def reference(path: Path) -> dict[str, str]:
        return {
            "relative_path": path.relative_to(tmp_path).as_posix(),
            "sha256": sha256(path.read_bytes()).hexdigest(),
        }

    roles = {
        "model": checkpoint_paths[0],
        "runtime": executable,
        "source": source_path,
        "preprocessing": preprocessing_path,
    }
    deployment = {
        "contract_version": deployed.CONTRACT_VERSION,
        "provider_id": deployed.GUI_ACTOR_PROVIDER,
        "repo_id": deployed.GUI_ACTOR_REPOSITORY,
        "revision": deployed.GUI_ACTOR_CHECKPOINT_REVISION,
        "checkpoint_parent": reference(checkpoint_manifest),
        "runtime_parent": reference(runtime_manifest),
        "artifacts": [
            {
                "role": role,
                "parent": "checkpoint" if role == "model" else "runtime",
                **_identity(path, tmp_path),
            }
            for role, path in roles.items()
        ],
        "artifact_is_authorization": False,
    }
    deployment_path = tmp_path / "reports" / "gui-actor-deployment.json"
    deployment_path.parent.mkdir(exist_ok=True)
    deployment_path.write_bytes(_json_bytes(deployment))
    profile = {
        "provider_id": deployed.GUI_ACTOR_PROVIDER,
        "repository_id": deployed.GUI_ACTOR_REPOSITORY,
        "upstream_revision": deployed.GUI_ACTOR_CHECKPOINT_REVISION,
        "artifact_manifest": {"status": "verified", **reference(deployment_path)},
        "artifacts": [
            {"role": role, **_identity(path, tmp_path)}
            for role, path in roles.items()
        ],
        "runtime": {
            "kind": "gui_actor_transformers_sdpa_windows_v1",
            "isolated_runtime_path": executable.relative_to(tmp_path).as_posix(),
            "sha256": sha256(executable.read_bytes()).hexdigest(),
        },
        "preprocessing": {
            "source_revision": deployed.OFFICIAL_SOURCE_REVISION,
            "sha256": sha256(preprocessing_path.read_bytes()).hexdigest(),
        },
        "native_output": {"kind": "gui_actor_topk_points_v1"},
        "coordinate_space": "normalized_0_1",
        "artifact_is_authorization": False,
    }
    return {
        "root": tmp_path,
        "profile": profile,
        "roles": roles,
        "deployment": deployment,
        "deployment_path": deployment_path,
        "checkpoint_manifest": checkpoint_manifest,
        "runtime_manifest": runtime_manifest,
        "runtime_root": runtime_root,
    }


def _rewrite(fixture: dict[str, object], deployment: dict[str, object]) -> None:
    path = fixture["deployment_path"]
    profile = fixture["profile"]
    assert isinstance(path, Path) and isinstance(profile, dict)
    path.write_bytes(_json_bytes(deployment))
    profile["artifact_manifest"]["sha256"] = sha256(path.read_bytes()).hexdigest()


def test_gui_actor_composite_deployment_verifies_exact_registered_parents(
    tmp_path, monkeypatch
):
    from app.learn.hybrid import goal_binding_gui_actor_deployed_artifacts as deployed

    fixture = _build(tmp_path, monkeypatch)

    assert deployed.verify_gui_actor_deployment(
        fixture["profile"], fixture["root"]
    ) == fixture["roles"]


def test_gui_actor_runtime_identity_uses_its_compatible_packages_and_import_closure() -> None:
    from app.learn.hybrid import goal_binding_gui_actor_deployed_artifacts as deployed

    assert deployed.RUNTIME_PACKAGE_VERSIONS == {
        "torch": "2.5.1+cu124",
        "torchvision": "0.20.1+cu124",
        "transformers": "4.51.3",
        "accelerate": "1.1.1",
        "qwen-vl-utils": "0.0.8",
        "Pillow": "11.1.0",
        "psutil": "7.0.0",
    }
    assert deployed.OFFICIAL_SOURCE_FILES == frozenset(
        {
            "gui_actor/__init__.py",
            "gui_actor/modeling_qwen25vl.py",
            "gui_actor/inference.py",
            "gui_actor/constants.py",
            "gui_actor/trainer.py",
        }
    )


def test_gui_actor_deployment_rejects_cross_lineage_parent(tmp_path, monkeypatch):
    from app.learn.hybrid import goal_binding_gui_actor_deployed_artifacts as deployed

    fixture = _build(tmp_path, monkeypatch)
    value = deepcopy(fixture["deployment"])
    value["runtime_parent"] = deepcopy(value["checkpoint_parent"])
    _rewrite(fixture, value)

    with pytest.raises(ValueError, match="parent|identity|lineage"):
        deployed.verify_gui_actor_deployment(fixture["profile"], fixture["root"])


def test_gui_actor_deployment_rejects_duplicate_manifest_keys(tmp_path, monkeypatch):
    from app.learn.hybrid import goal_binding_gui_actor_deployed_artifacts as deployed

    fixture = _build(tmp_path, monkeypatch)
    path = fixture["deployment_path"]
    profile = fixture["profile"]
    assert isinstance(path, Path) and isinstance(profile, dict)
    raw = path.read_text(encoding="utf-8")
    raw = raw.replace(
        '"contract_version": "goal_binding_gui_actor_deployment_manifest_v1",',
        '"contract_version": "goal_binding_gui_actor_deployment_manifest_v1", '
        '"contract_version": "goal_binding_gui_actor_deployment_manifest_v1",',
        1,
    )
    path.write_text(raw, encoding="utf-8")
    profile["artifact_manifest"]["sha256"] = sha256(path.read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="deployment manifest"):
        deployed.verify_gui_actor_deployment(profile, fixture["root"])


def test_gui_actor_deployment_rejects_extra_or_mutated_parent_file(
    tmp_path, monkeypatch
):
    from app.learn.hybrid import goal_binding_gui_actor_deployed_artifacts as deployed

    extra_fixture = _build(tmp_path / "extra", monkeypatch)
    _write(extra_fixture["runtime_root"] / "unexpected.pyc", b"extra")
    with pytest.raises(ValueError, match="exactly match"):
        deployed.verify_gui_actor_deployment(
            extra_fixture["profile"], extra_fixture["root"]
        )

    mutated_fixture = _build(tmp_path / "mutated", monkeypatch)
    mutated_fixture["roles"]["runtime"].write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed locally"):
        deployed.verify_gui_actor_deployment(
            mutated_fixture["profile"], mutated_fixture["root"]
        )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"source_revision": "microsoft/GUI-Actor@wrong"}, "source identity"),
        ({"attention": "flash_attention_2"}, "preprocessing"),
        ({"smoke_exit": 1}, "runtime smoke"),
    ],
)
def test_gui_actor_deployment_rejects_bad_source_preprocessing_or_smoke(
    tmp_path, monkeypatch, kwargs, message
):
    from app.learn.hybrid import goal_binding_gui_actor_deployed_artifacts as deployed

    fixture = _build(tmp_path, monkeypatch, **kwargs)

    with pytest.raises(ValueError, match=message):
        deployed.verify_gui_actor_deployment(fixture["profile"], fixture["root"])


def test_model_caller_dispatches_gui_actor_composite_manifest_to_its_verifier(
    tmp_path, monkeypatch
):
    from app.learn.hybrid import goal_binding_gui_actor_deployed_artifacts as deployed
    from app.learn.hybrid import goal_binding_model_callers as callers

    manifest = tmp_path / "reports" / "gui-actor-deployment.json"
    manifest.parent.mkdir()
    manifest.write_bytes(_json_bytes({"contract_version": deployed.CONTRACT_VERSION}))
    profile = {
        "artifact_manifest": {
            "status": "verified",
            "relative_path": manifest.relative_to(tmp_path).as_posix(),
            "sha256": sha256(manifest.read_bytes()).hexdigest(),
        }
    }
    observed = []
    monkeypatch.setattr(callers, "_validate_profile", lambda value: value)
    monkeypatch.setattr(
        deployed,
        "verify_gui_actor_deployment",
        lambda value, root: observed.append((value, root)),
    )

    assert callers._verified(profile, tmp_path) == profile
    assert observed == [(profile, tmp_path)]


def test_caller_and_worker_code_identity_bind_gui_actor_verifier() -> None:
    from app.learn.hybrid import goal_binding_model_callers as callers
    from scripts.model_servers import goal_binding_transformers_worker as worker

    identity = callers._provider_code_identity(
        Path(worker.__file__).resolve(), Path(__import__("sys").executable)
    )

    assert identity["goal_binding_gui_actor_deployed_artifacts_sha256"] == sha256(
        (
            Path(callers.__file__).with_name(
                "goal_binding_gui_actor_deployed_artifacts.py"
            )
        ).read_bytes()
    ).hexdigest()
    assert worker._verify_code_identity(identity) == identity
