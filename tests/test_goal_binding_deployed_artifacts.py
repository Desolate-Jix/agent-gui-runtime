from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT_REVISION = "bc4c6e62a1c545e043761439be95646d801853a4"
RUNTIME_REVISION = "b" * 40
CHECKPOINT_FILES = (
    ".gitattributes",
    "README.md",
    "chat_template.json",
    "config.json",
    "generation_config.json",
    "model.safetensors",
    "preprocessor_config.json",
    "tokenizer.json",
    "tokenizer_config.json",
)
CODE_FILES = (
    "app/learn/hybrid/goal_binding_model_callers.py",
    "app/learn/hybrid/goal_binding_deployed_artifacts.py",
    "app/learn/hybrid/model_test_storage.py",
    "scripts/model_servers/goal_binding_transformers_worker.py",
    "scripts/model_servers/goal_binding_provider_runtimes.py",
)


def _write(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _identity(path: Path, root: Path) -> dict[str, object]:
    return {"relative_path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path.read_bytes()).hexdigest()}


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


@pytest.fixture
def deployed_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    from app.learn.hybrid import goal_binding_deployed_artifacts as deployed
    from app.learn.hybrid import model_test_storage as storage
    from scripts.model_servers.goal_binding_provider_runtimes import UI_VENUS_CENTER_POINT_PROMPT

    monkeypatch.setattr(storage, "MODEL_TEST_ROOT", tmp_path)
    monkeypatch.setattr(deployed, "WINDOWS_SDPA_RUNTIME_REVISION", RUNTIME_REVISION)
    checkpoint_paths = [
        _write(tmp_path / "artifacts" / "ui_venus_1_5_2b_f16" / CHECKPOINT_REVISION / name, name.encode("utf-8"))
        for name in CHECKPOINT_FILES
    ]
    runtime_root = tmp_path / "artifacts" / "ui_venus_1_5_2b_f16_sdpa_runtime" / RUNTIME_REVISION
    official_sources = {
        "models/grounding/ui_venus1_5_gd.py": b"official-model-source",
        "requirements.txt": b"official-requirements",
    }
    monkeypatch.setattr(deployed, "OFFICIAL_SOURCE_FILES", {name: sha256(payload).hexdigest() for name, payload in official_sources.items()})
    monkeypatch.setattr(deployed, "OFFICIAL_SOURCE_REVISION", "inclusionAI/UI-Venus@" + "a" * 40)
    monkeypatch.setattr(deployed, "RUNTIME_PACKAGE_VERSIONS", {name: "1.0.0" for name in deployed.RUNTIME_PACKAGE_VERSIONS})
    for relative, payload in official_sources.items():
        _write(runtime_root / "official" / relative, payload)
    code_hashes = {name: sha256((ROOT / name).read_bytes()).hexdigest() for name in CODE_FILES}
    source_payload = {
        "contract_version": "goal_binding_ui_venus_source_identity_v1",
        "official_source_revision": deployed.OFFICIAL_SOURCE_REVISION,
        "official_source_files": dict(deployed.OFFICIAL_SOURCE_FILES),
        "project_revision": RUNTIME_REVISION,
        "code_files": code_hashes,
    }
    source_bytes = _json_bytes(source_payload)
    source_path = _write(runtime_root / "official-source.json", source_bytes)
    preprocessing_payload = {
        "contract_version": "goal_binding_ui_venus_preprocessing_v1",
        "source_document_sha256": sha256(source_bytes).hexdigest(),
        "official_attention_implementation": "flash_attention_2",
        "tested_attention_implementation": "sdpa",
        "prompt": {"sha256": sha256(UI_VENUS_CENTER_POINT_PROMPT.encode("utf-8")).hexdigest(), "utf8": UI_VENUS_CENTER_POINT_PROMPT},
        "dtype": "bfloat16",
        "max_new_tokens": 128,
        "native_output_kind": "ui_venus_point_v1",
        "coordinate_space": "normalized_0_1000",
    }
    preprocessing_path = _write(runtime_root / "preprocessing.json", _json_bytes(preprocessing_payload))
    packages = {
        "torch": "site-packages/torch/__init__.py",
        "torchvision": "site-packages/torchvision/__init__.py",
        "transformers": "site-packages/transformers/__init__.py",
        "accelerate": "site-packages/accelerate/__init__.py",
        "qwen-vl-utils": "site-packages/qwen_vl_utils/__init__.py",
        "Pillow": "site-packages/PIL/__init__.py",
        "psutil": "site-packages/psutil/__init__.py",
        "pywin32": "site-packages/win32/win32api.pyd",
    }
    module_paths = [_write(runtime_root / path, name.encode("utf-8")) for name, path in packages.items()]
    executable = _write(runtime_root / "Scripts" / "python.exe", b"runtime")
    base_python = _write(runtime_root / "base" / "python.exe", b"base-runtime")
    smoke_script = _write(runtime_root / "runtime-smoke.py", b"smoke")
    smoke_payload = {
        "contract_version": "goal_binding_ui_venus_sdpa_runtime_smoke_v1",
        "python": {"implementation": "CPython", "version": "3.11.9"},
        "packages": [{"distribution": name, "version": "1.0.0", "module_origin": (runtime_root / path).relative_to(tmp_path).as_posix()} for name, path in packages.items()],
        "python_executable_sha256": sha256(executable.read_bytes()).hexdigest(),
        "smoke_script_sha256": sha256(smoke_script.read_bytes()).hexdigest(),
        "exit_code": 0,
        "windows_process_scope_ready": True,
    }
    smoke_path = _write(runtime_root / "runtime-smoke.json", _json_bytes(smoke_payload))
    pyvenv = _write(runtime_root / "pyvenv.cfg", f"home = {runtime_root / 'base'}\nexecutable = {base_python}\n".encode("utf-8"))
    runtime_paths = [pyvenv, executable, base_python, smoke_script, *[runtime_root / "official" / name for name in official_sources], source_path, preprocessing_path, smoke_path, *module_paths]
    checkpoint_manifest = storage.register_downloaded_artifact(
        root=tmp_path,
        provider_id="ui_venus_1_5_2b_f16",
        repo_id="inclusionAI/UI-Venus-1.5-2B",
        revision=CHECKPOINT_REVISION,
        files=checkpoint_paths,
    )
    runtime_manifest = storage.register_downloaded_artifact(
        root=tmp_path,
        provider_id="ui_venus_1_5_2b_f16_sdpa_runtime",
        repo_id="Desolate-Jix/agent-gui-runtime",
        revision=RUNTIME_REVISION,
        files=runtime_paths,
    )
    def reference(path: Path) -> dict[str, str]:
        return {"relative_path": path.relative_to(tmp_path).as_posix(), "sha256": sha256(path.read_bytes()).hexdigest()}
    roles = {
        "model": next(path for path in checkpoint_paths if path.name == "model.safetensors"),
        "runtime": next(path for path in runtime_paths if path.name == "python.exe"),
        "source": source_path,
        "preprocessing": preprocessing_path,
    }
    deployment = {
        "contract_version": "goal_binding_ui_venus_deployment_manifest_v1",
        "provider_id": "ui_venus_1_5_2b_f16",
        "repo_id": "inclusionAI/UI-Venus-1.5-2B",
        "revision": CHECKPOINT_REVISION,
        "checkpoint_parent": reference(checkpoint_manifest),
        "runtime_parent": reference(runtime_manifest),
        "artifacts": [
            {"role": role, "parent": "checkpoint" if role == "model" else "runtime", **_identity(path, tmp_path)}
            for role, path in roles.items()
        ],
        "artifact_is_authorization": False,
    }
    deployment_path = tmp_path / "reports" / "ui-venus-deployment.json"
    deployment_path.write_text(json.dumps(deployment, sort_keys=True), encoding="utf-8")
    profile = json.loads((ROOT / "configs" / "model_profiles" / "goal_binding_ui_venus_1_5_2b_f16.json").read_text(encoding="utf-8"))
    profile["upstream_revision"] = CHECKPOINT_REVISION
    profile["artifact_manifest"] = {"status": "verified", "relative_path": deployment_path.relative_to(tmp_path).as_posix(), "sha256": sha256(deployment_path.read_bytes()).hexdigest()}
    profile["artifacts"] = [
        {"role": role, **_identity(path, tmp_path)} for role, path in roles.items()
    ]
    profile["runtime"]["isolated_runtime_path"] = roles["runtime"].relative_to(tmp_path).as_posix()
    profile["runtime"]["sha256"] = sha256(roles["runtime"].read_bytes()).hexdigest()
    profile["preprocessing"]["sha256"] = sha256(roles["preprocessing"].read_bytes()).hexdigest()
    profile["preprocessing"]["source_revision"] = deployed.OFFICIAL_SOURCE_REVISION
    return {"root": tmp_path, "profile": profile, "deployment_path": deployment_path, "deployment": deployment, "roles": roles, "checkpoint_manifest": checkpoint_manifest, "runtime_manifest": runtime_manifest}


def test_registered_checkpoint_and_sdpa_runtime_compose_into_verified_ui_venus_deployment(deployed_fixture: dict[str, object]) -> None:
    from app.learn.hybrid import goal_binding_deployed_artifacts as deployed

    profile = deployed_fixture["profile"]
    root = deployed_fixture["root"]
    assert isinstance(profile, dict) and isinstance(root, Path)
    paths = deployed.verify_ui_venus_deployment(profile, root)
    assert paths == deployed_fixture["roles"]


def test_profile_and_runtime_reverify_the_composite_deployment_before_use(deployed_fixture: dict[str, object]) -> None:
    from app.learn.hybrid import goal_binding_model_callers as callers
    from scripts.model_servers import goal_binding_provider_runtimes as runtimes

    profile = deployed_fixture["profile"]
    root = deployed_fixture["root"]
    assert isinstance(profile, dict) and isinstance(root, Path)
    assert callers._verified(profile, root) == profile
    assert runtimes.verified_artifact_paths(profile, root) == deployed_fixture["roles"]


def _rewrite_deployment(fixture: dict[str, object], value: dict[str, object]) -> None:
    path = fixture["deployment_path"]
    profile = fixture["profile"]
    assert isinstance(path, Path) and isinstance(profile, dict)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    profile["artifact_manifest"]["sha256"] = sha256(path.read_bytes()).hexdigest()


def _refresh_runtime_parent(fixture: dict[str, object]) -> None:
    root = fixture["root"]
    manifest_path = fixture["runtime_manifest"]
    deployment = deepcopy(fixture["deployment"])
    profile = fixture["profile"]
    assert isinstance(root, Path) and isinstance(manifest_path, Path) and isinstance(profile, dict)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        path = root / entry["relative_path"]
        entry["bytes"] = path.stat().st_size
        entry["sha256"] = sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    registry_path = root / "reports" / "artifact-registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["manifests"][manifest_path.relative_to(root).as_posix()] = sha256(manifest_path.read_bytes()).hexdigest()
    registry_path.write_text(json.dumps(registry, sort_keys=True), encoding="utf-8")
    deployment["runtime_parent"]["sha256"] = sha256(manifest_path.read_bytes()).hexdigest()
    for entry in deployment["artifacts"]:
        if entry["parent"] == "runtime":
            path = root / entry["relative_path"]
            entry["bytes"] = path.stat().st_size
            entry["sha256"] = sha256(path.read_bytes()).hexdigest()
    _rewrite_deployment(fixture, deployment)
    for entry in profile["artifacts"]:
        path = root / entry["relative_path"]
        entry["bytes"] = path.stat().st_size
        entry["sha256"] = sha256(path.read_bytes()).hexdigest()
    profile["runtime"]["sha256"] = next(entry["sha256"] for entry in profile["artifacts"] if entry["role"] == "runtime")
    profile["preprocessing"]["sha256"] = next(entry["sha256"] for entry in profile["artifacts"] if entry["role"] == "preprocessing")


def test_deployment_rejects_extra_file_in_registered_parent_namespace(deployed_fixture: dict[str, object]) -> None:
    from app.learn.hybrid import goal_binding_deployed_artifacts as deployed

    root = deployed_fixture["root"]
    assert isinstance(root, Path)
    _write(root / "artifacts" / "ui_venus_1_5_2b_f16" / CHECKPOINT_REVISION / "extra.bin", b"extra")
    with pytest.raises(ValueError, match="exactly match"):
        deployed.verify_ui_venus_deployment(deployed_fixture["profile"], root)


def test_deployment_rejects_unregistered_forged_runtime_parent(deployed_fixture: dict[str, object]) -> None:
    from app.learn.hybrid import goal_binding_deployed_artifacts as deployed

    path = deployed_fixture["runtime_manifest"]
    root = deployed_fixture["root"]
    assert isinstance(path, Path) and isinstance(root, Path)
    value = json.loads(path.read_text(encoding="utf-8"))
    value["repo_id"] = "forged/runtime"
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    deployment = deepcopy(deployed_fixture["deployment"])
    deployment["runtime_parent"]["sha256"] = sha256(path.read_bytes()).hexdigest()
    _rewrite_deployment(deployed_fixture, deployment)
    with pytest.raises(ValueError, match="durably registered"):
        deployed.verify_ui_venus_deployment(deployed_fixture["profile"], root)


def test_deployment_rejects_cross_lineage_parent_and_duplicate_role(deployed_fixture: dict[str, object]) -> None:
    from app.learn.hybrid import goal_binding_deployed_artifacts as deployed
    from app.learn.hybrid import model_test_storage as storage

    root = deployed_fixture["root"]
    assert isinstance(root, Path)
    cross_lineage = deepcopy(deployed_fixture["deployment"])
    cross_lineage["runtime_parent"] = deepcopy(cross_lineage["checkpoint_parent"])
    _rewrite_deployment(deployed_fixture, cross_lineage)
    with pytest.raises(ValueError, match="distinct"):
        deployed.verify_ui_venus_deployment(deployed_fixture["profile"], root)
    foreign_revision = "c" * 40
    foreign_file = _write(root / "artifacts" / "foreign_runtime" / foreign_revision / "python.exe", b"foreign")
    foreign_manifest = storage.register_downloaded_artifact(
        root=root,
        provider_id="foreign_runtime",
        repo_id="foreign/runtime",
        revision=foreign_revision,
        files=[foreign_file],
    )
    foreign_parent = deepcopy(deployed_fixture["deployment"])
    foreign_parent["runtime_parent"] = {
        "relative_path": foreign_manifest.relative_to(root).as_posix(),
        "sha256": sha256(foreign_manifest.read_bytes()).hexdigest(),
    }
    _rewrite_deployment(deployed_fixture, foreign_parent)
    with pytest.raises(ValueError, match="identity mismatch|revision is invalid"):
        deployed.verify_ui_venus_deployment(deployed_fixture["profile"], root)
    duplicate_role = deepcopy(deployed_fixture["deployment"])
    duplicate_role["artifacts"][1]["role"] = "model"
    _rewrite_deployment(deployed_fixture, duplicate_role)
    with pytest.raises(ValueError, match="role projection"):
        deployed.verify_ui_venus_deployment(deployed_fixture["profile"], root)


def test_deployment_rejects_artifact_traversal_and_hardlink_ambiguity(deployed_fixture: dict[str, object]) -> None:
    from app.learn.hybrid import goal_binding_deployed_artifacts as deployed

    root = deployed_fixture["root"]
    roles = deployed_fixture["roles"]
    assert isinstance(root, Path) and isinstance(roles, dict)
    traversal = deepcopy(deployed_fixture["deployment"])
    traversal["artifacts"][0]["relative_path"] = "../model.safetensors"
    _rewrite_deployment(deployed_fixture, traversal)
    with pytest.raises(ValueError, match="safe relative"):
        deployed.verify_ui_venus_deployment(deployed_fixture["profile"], root)
    runtime = roles["runtime"]
    assert isinstance(runtime, Path)
    alias = runtime.with_name("python-alias.exe")
    try:
        os.link(runtime, alias)
    except OSError:
        pytest.skip("hard links unavailable")
    original = deepcopy(deployed_fixture["deployment"])
    _rewrite_deployment(deployed_fixture, original)
    with pytest.raises(ValueError, match="ambiguous|exactly match"):
        deployed.verify_ui_venus_deployment(deployed_fixture["profile"], root)


def test_deployment_rejects_missing_parent_file_and_reparse_alias(deployed_fixture: dict[str, object]) -> None:
    from app.learn.hybrid import goal_binding_deployed_artifacts as deployed

    root = deployed_fixture["root"]
    roles = deployed_fixture["roles"]
    assert isinstance(root, Path) and isinstance(roles, dict)
    model = roles["model"]
    assert isinstance(model, Path)
    model.unlink()
    with pytest.raises(ValueError, match="unavailable|changed"):
        deployed.verify_ui_venus_deployment(deployed_fixture["profile"], root)

    _write(model, b"checkpoint")
    alias = model.with_name("model-alias.safetensors")
    try:
        alias.symlink_to(model)
    except OSError:
        pytest.skip("symbolic links unavailable")
    with pytest.raises(ValueError, match="reparse"):
        deployed.verify_ui_venus_deployment(deployed_fixture["profile"], root)


def test_deployment_rejects_opaque_source_and_preprocessing_bytes(deployed_fixture: dict[str, object]) -> None:
    from app.learn.hybrid import goal_binding_deployed_artifacts as deployed

    root = deployed_fixture["root"]
    manifest_path = deployed_fixture["runtime_manifest"]
    roles = deployed_fixture["roles"]
    deployment = deepcopy(deployed_fixture["deployment"])
    assert isinstance(root, Path) and isinstance(manifest_path, Path) and isinstance(roles, dict)
    source = roles["source"]
    assert isinstance(source, Path)
    source.write_bytes(b"opaque")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_relative = source.relative_to(root).as_posix()
    for entry in manifest["files"]:
        if entry["relative_path"] == source_relative:
            entry["bytes"] = source.stat().st_size
            entry["sha256"] = sha256(source.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    registry_path = root / "reports" / "artifact-registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["manifests"][manifest_path.relative_to(root).as_posix()] = sha256(manifest_path.read_bytes()).hexdigest()
    registry_path.write_text(json.dumps(registry, sort_keys=True), encoding="utf-8")
    deployment["runtime_parent"]["sha256"] = sha256(manifest_path.read_bytes()).hexdigest()
    for item in deployment["artifacts"]:
        if item["role"] == "source":
            item["bytes"] = source.stat().st_size
            item["sha256"] = sha256(source.read_bytes()).hexdigest()
    _rewrite_deployment(deployed_fixture, deployment)
    profile = deployed_fixture["profile"]
    assert isinstance(profile, dict)
    for item in profile["artifacts"]:
        if item["role"] == "source":
            item["bytes"] = source.stat().st_size
            item["sha256"] = sha256(source.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="source identity document|preprocessing document"):
        deployed.verify_ui_venus_deployment(deployed_fixture["profile"], root)


def test_deployment_rejects_opaque_preprocessing_bytes(deployed_fixture: dict[str, object]) -> None:
    from app.learn.hybrid import goal_binding_deployed_artifacts as deployed

    root = deployed_fixture["root"]
    assert isinstance(root, Path)
    preprocessing = root / "artifacts" / "ui_venus_1_5_2b_f16_sdpa_runtime" / RUNTIME_REVISION / "preprocessing.json"
    preprocessing.write_bytes(b"opaque")
    _refresh_runtime_parent(deployed_fixture)
    with pytest.raises(ValueError, match="preprocessing document"):
        deployed.verify_ui_venus_deployment(deployed_fixture["profile"], root)


def test_deployment_rejects_registered_incomplete_checkpoint_snapshot(deployed_fixture: dict[str, object]) -> None:
    from app.learn.hybrid import goal_binding_deployed_artifacts as deployed

    root = deployed_fixture["root"]
    manifest_path = deployed_fixture["checkpoint_manifest"]
    deployment = deepcopy(deployed_fixture["deployment"])
    assert isinstance(root, Path) and isinstance(manifest_path, Path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    removed = next(entry for entry in manifest["files"] if entry["relative_path"].endswith("tokenizer_config.json"))
    (root / removed["relative_path"]).unlink()
    manifest["files"].remove(removed)
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    registry_path = root / "reports" / "artifact-registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["manifests"][manifest_path.relative_to(root).as_posix()] = sha256(manifest_path.read_bytes()).hexdigest()
    registry_path.write_text(json.dumps(registry, sort_keys=True), encoding="utf-8")
    deployment["checkpoint_parent"]["sha256"] = sha256(manifest_path.read_bytes()).hexdigest()
    _rewrite_deployment(deployed_fixture, deployment)
    with pytest.raises(ValueError, match="exact expected nine-file"):
        deployed.verify_ui_venus_deployment(deployed_fixture["profile"], root)


def test_deployment_rejects_missing_runtime_smoke_document(deployed_fixture: dict[str, object]) -> None:
    from app.learn.hybrid import goal_binding_deployed_artifacts as deployed

    root = deployed_fixture["root"]
    manifest_path = deployed_fixture["runtime_manifest"]
    deployment = deepcopy(deployed_fixture["deployment"])
    assert isinstance(root, Path) and isinstance(manifest_path, Path)
    smoke_relative = (Path("artifacts") / "ui_venus_1_5_2b_f16_sdpa_runtime" / RUNTIME_REVISION / "runtime-smoke.json").as_posix()
    (root / smoke_relative).unlink()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"] = [entry for entry in manifest["files"] if entry["relative_path"] != smoke_relative]
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    registry_path = root / "reports" / "artifact-registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["manifests"][manifest_path.relative_to(root).as_posix()] = sha256(manifest_path.read_bytes()).hexdigest()
    registry_path.write_text(json.dumps(registry, sort_keys=True), encoding="utf-8")
    deployment["runtime_parent"]["sha256"] = sha256(manifest_path.read_bytes()).hexdigest()
    _rewrite_deployment(deployed_fixture, deployment)
    with pytest.raises(ValueError, match="runtime smoke document is missing"):
        deployed.verify_ui_venus_deployment(deployed_fixture["profile"], root)


def test_deployment_rejects_runtime_python_home_outside_registered_artifact(deployed_fixture: dict[str, object]) -> None:
    from app.learn.hybrid import goal_binding_deployed_artifacts as deployed

    root = deployed_fixture["root"]
    assert isinstance(root, Path)
    pyvenv = root / "artifacts" / "ui_venus_1_5_2b_f16_sdpa_runtime" / RUNTIME_REVISION / "pyvenv.cfg"
    pyvenv.write_text("home = E:\\staging\\old-runtime\\base\nexecutable = E:\\staging\\old-runtime\\base\\python.exe\n", encoding="utf-8")
    _refresh_runtime_parent(deployed_fixture)
    with pytest.raises(ValueError, match="Python home"):
        deployed.verify_ui_venus_deployment(deployed_fixture["profile"], root)


@pytest.mark.parametrize("mutation, message", [
    (lambda value: value.clear(), "runtime smoke document is invalid"),
    (lambda value: value["packages"].pop(), "package set is invalid"),
    (lambda value: value.__setitem__("windows_process_scope_ready", False), "Windows process scope readiness is invalid"),
    (lambda value: value["packages"].__setitem__(0, {**value["packages"][0], "module_origin": "../escape.py"}), "module origin"),
])
def test_deployment_rejects_missing_malformed_or_escape_runtime_smoke(deployed_fixture: dict[str, object], mutation, message: str) -> None:
    from app.learn.hybrid import goal_binding_deployed_artifacts as deployed

    root = deployed_fixture["root"]
    assert isinstance(root, Path)
    smoke = root / "artifacts" / "ui_venus_1_5_2b_f16_sdpa_runtime" / RUNTIME_REVISION / "runtime-smoke.json"
    value = json.loads(smoke.read_text(encoding="utf-8"))
    mutation(value)
    smoke.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    _refresh_runtime_parent(deployed_fixture)
    with pytest.raises(ValueError, match=message):
        deployed.verify_ui_venus_deployment(deployed_fixture["profile"], root)


def test_deployment_rejects_source_document_with_changed_current_code_hash(deployed_fixture: dict[str, object]) -> None:
    from app.learn.hybrid import goal_binding_deployed_artifacts as deployed

    root = deployed_fixture["root"]
    assert isinstance(root, Path)
    source = root / "artifacts" / "ui_venus_1_5_2b_f16_sdpa_runtime" / RUNTIME_REVISION / "official-source.json"
    value = json.loads(source.read_text(encoding="utf-8"))
    value["code_files"]["app/learn/hybrid/model_test_storage.py"] = "0" * 64
    source.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    _refresh_runtime_parent(deployed_fixture)
    with pytest.raises(ValueError, match="does not bind current code"):
        deployed.verify_ui_venus_deployment(deployed_fixture["profile"], root)


def test_worker_environment_scrubs_ambient_python_injection(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.learn.hybrid import goal_binding_model_callers as callers

    monkeypatch.setenv("PYTHONPATH", "C:/ambient/injection")
    monkeypatch.setenv("PYTHONHOME", "C:/ambient/python-home")
    environment = callers._isolated_worker_environment("scope-test")
    assert "PYTHONPATH" not in environment and "PYTHONHOME" not in environment
    assert environment["PYTHONNOUSERSITE"] == "1"
    assert environment["AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME"] == "scope-test"


def test_worker_identity_rejects_legacy_identity_without_deployment_and_storage_hashes() -> None:
    from scripts.model_servers import goal_binding_transformers_worker as worker

    with pytest.raises(ValueError, match="code identity"):
        worker._verify_code_identity({
            "worker_sha256": "a" * 64,
            "provider_runtime_sha256": "b" * 64,
            "worker_python_sha256": "c" * 64,
        })


def test_deployment_rejects_source_document_without_official_file_hashes(deployed_fixture: dict[str, object]) -> None:
    from app.learn.hybrid import goal_binding_deployed_artifacts as deployed

    root = deployed_fixture["root"]
    assert isinstance(root, Path)
    source = root / "artifacts" / "ui_venus_1_5_2b_f16_sdpa_runtime" / RUNTIME_REVISION / "official-source.json"
    value = json.loads(source.read_text(encoding="utf-8"))
    value.pop("official_source_files")
    source.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    _refresh_runtime_parent(deployed_fixture)
    with pytest.raises(ValueError, match="source identity document"):
        deployed.verify_ui_venus_deployment(deployed_fixture["profile"], root)
