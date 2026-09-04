"""Fail-closed composite verifier for the GUI-Actor Windows SDPA deployment."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import json
from pathlib import Path

from app.learn.hybrid import model_test_storage as storage
from app.learn.hybrid.goal_binding_deployed_artifacts import (
    _artifact_projection,
    _closed_object,
    _is_sha256,
    _read_closed_json,
    _reference,
    _relative,
    _safe_under,
    _sha256_file,
    _verified_parent,
)


CONTRACT_VERSION = "goal_binding_gui_actor_deployment_manifest_v1"
GUI_ACTOR_PROVIDER = "gui_actor_3b_bf16"
GUI_ACTOR_REPOSITORY = "microsoft/GUI-Actor-3B-Qwen2.5-VL"
GUI_ACTOR_CHECKPOINT_REVISION = "5fb97348752cb3d50be9709f47d9ae6c99725949"
WINDOWS_SDPA_RUNTIME_PROVIDER = "gui_actor_3b_bf16_sdpa_runtime"
WINDOWS_SDPA_RUNTIME_REPOSITORY = "Desolate-Jix/agent-gui-runtime"
WINDOWS_SDPA_RUNTIME_REVISION = "6ed93fbdc2487257a14123bde0acff74eebd2830"
OFFICIAL_SOURCE_REVISION = (
    "microsoft/GUI-Actor@d98d1bbd01862f9112114b83b032f492c365a173"
)
OFFICIAL_SOURCE_FILES = frozenset(
    {
        "gui_actor/__init__.py",
        "gui_actor/modeling_qwen25vl.py",
        "gui_actor/inference.py",
        "gui_actor/constants.py",
        "gui_actor/trainer.py",
    }
)
RUNTIME_PACKAGE_VERSIONS = {
    "torch": "2.5.1+cu124",
    "torchvision": "0.20.1+cu124",
    "transformers": "4.51.3",
    "accelerate": "1.1.1",
    "qwen-vl-utils": "0.0.8",
    "Pillow": "11.1.0",
    "psutil": "7.0.0",
}
_SOURCE_VERSION = "goal_binding_gui_actor_source_identity_v1"
_PREPROCESSING_VERSION = "goal_binding_gui_actor_preprocessing_v1"
_SMOKE_VERSION = "goal_binding_gui_actor_sdpa_runtime_smoke_v1"
_ROLES = frozenset({"model", "runtime", "source", "preprocessing"})
_DEPLOYMENT_FIELDS = frozenset(
    {
        "contract_version",
        "provider_id",
        "repo_id",
        "revision",
        "checkpoint_parent",
        "runtime_parent",
        "artifacts",
        "artifact_is_authorization",
    }
)
_CODE_FILES = frozenset(
    {
        "app/learn/hybrid/goal_binding_model_callers.py",
        "app/learn/hybrid/goal_binding_gui_actor_deployed_artifacts.py",
        "app/learn/hybrid/goal_binding_deployed_artifacts.py",
        "app/learn/hybrid/model_test_storage.py",
        "scripts/model_servers/goal_binding_transformers_worker.py",
        "scripts/model_servers/goal_binding_provider_runtimes.py",
    }
)


def _current_code_hashes() -> dict[str, str]:
    repository = Path(__file__).resolve().parents[3]
    result: dict[str, str] = {}
    for relative in sorted(_CODE_FILES):
        path = repository / relative
        if not path.is_file():
            raise ValueError("current GUI-Actor verifier code is unavailable")
        result[relative] = _sha256_file(path)
    return result


def _verify_source(
    *,
    path: Path,
    profile: Mapping[str, object],
    runtime_provider: str,
    runtime_revision: str,
    runtime_files: Mapping[str, Mapping[str, object]],
) -> str:
    document = _read_closed_json(
        path,
        fields=frozenset(
            {
                "contract_version",
                "official_source_revision",
                "official_source_files",
                "project_revision",
                "code_files",
            }
        ),
        label="GUI-Actor source identity document",
    )
    official = document.get("official_source_files")
    code = document.get("code_files")
    preprocessing = profile.get("preprocessing")
    if (
        document.get("contract_version") != _SOURCE_VERSION
        or document.get("official_source_revision") != OFFICIAL_SOURCE_REVISION
        or document.get("project_revision") != runtime_revision
        or not isinstance(preprocessing, Mapping)
        or preprocessing.get("source_revision") != OFFICIAL_SOURCE_REVISION
        or not isinstance(code, Mapping)
        or set(code) != _CODE_FILES
        or dict(code) != _current_code_hashes()
        or not isinstance(official, Mapping)
        or set(official) != OFFICIAL_SOURCE_FILES
        or any(not _is_sha256(value) for value in official.values())
    ):
        raise ValueError("GUI-Actor source identity document is invalid")
    namespace = Path("artifacts") / runtime_provider / runtime_revision / "official"
    installed_namespace = (
        Path("artifacts") / runtime_provider / runtime_revision / "Lib" / "site-packages"
    )
    for relative, digest in official.items():
        safe = _relative(relative, field="GUI-Actor official source file")
        record = runtime_files.get((namespace / safe).as_posix())
        if record is None or record.get("sha256") != digest:
            raise ValueError("GUI-Actor source identity document changed or escaped")
        installed_record = runtime_files.get((installed_namespace / safe).as_posix())
        if installed_record is None or installed_record.get("sha256") != digest:
            raise ValueError("GUI-Actor installed source is missing or changed")
    return _sha256_file(path)


def _verify_preprocessing(
    *, path: Path, source_sha256: str, profile: Mapping[str, object]
) -> None:
    document = _read_closed_json(
        path,
        fields=frozenset(
            {
                "contract_version",
                "source_document_sha256",
                "official_attention_implementation",
                "tested_attention_implementation",
                "dtype",
                "native_output_kind",
                "coordinate_space",
                "topk",
                "local_files_only",
                "device_map",
            }
        ),
        label="GUI-Actor preprocessing document",
    )
    native = profile.get("native_output")
    if (
        document.get("contract_version") != _PREPROCESSING_VERSION
        or document.get("source_document_sha256") != source_sha256
        or document.get("official_attention_implementation") != "flash_attention_2"
        or document.get("tested_attention_implementation") != "sdpa"
        or document.get("dtype") != "bfloat16"
        or not isinstance(native, Mapping)
        or document.get("native_output_kind") != native.get("kind")
        or document.get("coordinate_space") != profile.get("coordinate_space")
        or document.get("topk") != 3
        or document.get("local_files_only") is not True
        or document.get("device_map") != "cuda:0"
    ):
        raise ValueError("GUI-Actor preprocessing document is invalid")


def _verify_smoke(
    *,
    files: Mapping[str, Mapping[str, object]],
    runtime_provider: str,
    runtime_revision: str,
) -> None:
    namespace = Path("artifacts") / runtime_provider / runtime_revision
    smoke_record = files.get((namespace / "runtime-smoke.json").as_posix())
    if smoke_record is None or not isinstance(smoke_record.get("path"), Path):
        raise ValueError("GUI-Actor runtime smoke document is missing")
    document = _read_closed_json(
        smoke_record["path"],
        fields=frozenset(
            {
                "contract_version",
                "python",
                "packages",
                "python_executable_sha256",
                "smoke_script_sha256",
                "exit_code",
            }
        ),
        label="GUI-Actor runtime smoke document",
    )
    python = document.get("python")
    packages = document.get("packages")
    executable = files.get((namespace / "Scripts" / "python.exe").as_posix())
    base_python = files.get((namespace / "base" / "python.exe").as_posix())
    smoke_script = files.get((namespace / "runtime-smoke.py").as_posix())
    pyvenv = files.get((namespace / "pyvenv.cfg").as_posix())
    if (
        document.get("contract_version") != _SMOKE_VERSION
        or not isinstance(python, Mapping)
        or set(python) != {"implementation", "version"}
        or python.get("implementation") != "CPython"
        or not isinstance(python.get("version"), str)
        or executable is None
        or base_python is None
        or smoke_script is None
        or pyvenv is None
        or document.get("python_executable_sha256") != executable.get("sha256")
        or document.get("smoke_script_sha256") != smoke_script.get("sha256")
        or document.get("exit_code") != 0
        or not isinstance(packages, list)
        or len(packages) != len(RUNTIME_PACKAGE_VERSIONS)
    ):
        raise ValueError("GUI-Actor runtime smoke identity is invalid")
    observed: set[str] = set()
    for item in packages:
        if not isinstance(item, Mapping) or set(item) != {
            "distribution",
            "version",
            "module_origin",
        }:
            raise ValueError("GUI-Actor runtime smoke package is invalid")
        distribution = item.get("distribution")
        origin = _relative(
            item.get("module_origin"), field="GUI-Actor runtime module origin"
        )
        if (
            not isinstance(distribution, str)
            or distribution in observed
            or item.get("version") != RUNTIME_PACKAGE_VERSIONS.get(distribution)
            or not Path(origin).is_relative_to(namespace)
            or origin not in files
        ):
            raise ValueError("GUI-Actor runtime smoke package identity is invalid")
        observed.add(distribution)
    if observed != set(RUNTIME_PACKAGE_VERSIONS):
        raise ValueError("GUI-Actor runtime smoke package set is incomplete")
    pyvenv_path = pyvenv.get("path")
    if not isinstance(pyvenv_path, Path):
        raise ValueError("GUI-Actor runtime pyvenv.cfg path is invalid")
    config: dict[str, str] = {}
    for line in pyvenv_path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator:
            normalized = key.strip().casefold()
            if normalized in config:
                raise ValueError("GUI-Actor runtime pyvenv.cfg has duplicate fields")
            config[normalized] = value.strip()
    runtime_root = pyvenv_path.parent.resolve()
    expected_home = (runtime_root / "base").resolve()
    if (
        Path(config.get("home", "")).resolve() != expected_home
        or Path(config.get("executable", "")).resolve()
        != (expected_home / "python.exe").resolve()
    ):
        raise ValueError("GUI-Actor runtime Python home is not pinned")


def verify_gui_actor_deployment(
    profile: Mapping[str, object], artifact_root: Path
) -> dict[str, Path]:
    """Verify GUI-Actor against exact immutable checkpoint and runtime parents."""
    root = Path(artifact_root).resolve()
    if (
        profile.get("provider_id") != GUI_ACTOR_PROVIDER
        or profile.get("repository_id") != GUI_ACTOR_REPOSITORY
        or profile.get("native_output", {}).get("kind")
        != "gui_actor_topk_points_v1"
        or profile.get("coordinate_space") != "normalized_0_1"
        or profile.get("runtime", {}).get("kind")
        != "gui_actor_transformers_sdpa_windows_v1"
    ):
        raise ValueError("profile is not the sealed GUI-Actor Windows SDPA profile")
    ref = profile.get("artifact_manifest")
    if not isinstance(ref, Mapping) or ref.get("status") != "verified":
        raise ValueError("GUI-Actor deployment is not acquired and verified")
    manifest_path = _safe_under(
        root,
        _relative(ref.get("relative_path"), field="profile deployment manifest"),
    )
    try:
        payload = json.loads(
            manifest_path.read_text(encoding="utf-8"),
            object_pairs_hook=_closed_object,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("GUI-Actor deployment manifest is unreadable") from exc
    if (
        ref.get("sha256") != _sha256_file(manifest_path)
        or not isinstance(payload, Mapping)
        or set(payload) != _DEPLOYMENT_FIELDS
        or payload.get("contract_version") != CONTRACT_VERSION
        or payload.get("provider_id") != GUI_ACTOR_PROVIDER
        or payload.get("repo_id") != GUI_ACTOR_REPOSITORY
        or payload.get("revision") != GUI_ACTOR_CHECKPOINT_REVISION
        or profile.get("upstream_revision") != GUI_ACTOR_CHECKPOINT_REVISION
        or payload.get("artifact_is_authorization") is not False
    ):
        raise ValueError("GUI-Actor deployment manifest identity mismatch")
    checkpoint_ref = _reference(
        payload.get("checkpoint_parent"), field="checkpoint parent"
    )
    runtime_ref = _reference(payload.get("runtime_parent"), field="runtime parent")
    if checkpoint_ref == runtime_ref:
        raise ValueError("GUI-Actor deployment parents must remain distinct")
    checkpoint_files = _verified_parent(
        root=root,
        reference=checkpoint_ref,
        provider=GUI_ACTOR_PROVIDER,
        repo_id=GUI_ACTOR_REPOSITORY,
        revision=GUI_ACTOR_CHECKPOINT_REVISION,
    )
    runtime_manifest = _safe_under(root, runtime_ref["relative_path"])
    try:
        runtime_payload, _, _ = storage._load_manifest(root, runtime_manifest)
    except ValueError as exc:
        raise ValueError("GUI-Actor runtime parent is not durably registered") from exc
    runtime_revision = runtime_payload.get("revision")
    if runtime_revision != WINDOWS_SDPA_RUNTIME_REVISION:
        raise ValueError("GUI-Actor runtime parent revision is invalid")
    runtime_files = _verified_parent(
        root=root,
        reference=runtime_ref,
        provider=WINDOWS_SDPA_RUNTIME_PROVIDER,
        repo_id=WINDOWS_SDPA_RUNTIME_REPOSITORY,
        revision=runtime_revision,
    )
    _verify_smoke(
        files=runtime_files,
        runtime_provider=WINDOWS_SDPA_RUNTIME_PROVIDER,
        runtime_revision=runtime_revision,
    )
    paths = _artifact_projection(
        payload,
        checkpoint_files=checkpoint_files,
        runtime_files=runtime_files,
    )
    source_sha = _verify_source(
        path=paths["source"],
        profile=profile,
        runtime_provider=WINDOWS_SDPA_RUNTIME_PROVIDER,
        runtime_revision=runtime_revision,
        runtime_files=runtime_files,
    )
    _verify_preprocessing(
        path=paths["preprocessing"], source_sha256=source_sha, profile=profile
    )
    profile_artifacts = {
        item.get("role"): item
        for item in profile.get("artifacts", [])
        if isinstance(item, Mapping)
    }
    if set(profile_artifacts) != _ROLES:
        raise ValueError("GUI-Actor profile artifact roles are invalid")
    for role, path in paths.items():
        item = profile_artifacts[role]
        if (
            item.get("relative_path") != path.relative_to(root).as_posix()
            or item.get("bytes") != path.stat().st_size
            or item.get("sha256") != _sha256_file(path)
        ):
            raise ValueError("GUI-Actor profile artifact projection is invalid")
    runtime = profile.get("runtime")
    preprocessing = profile.get("preprocessing")
    if (
        not isinstance(runtime, Mapping)
        or not isinstance(preprocessing, Mapping)
        or runtime.get("isolated_runtime_path")
        != paths["runtime"].relative_to(root).as_posix()
        or runtime.get("sha256") != _sha256_file(paths["runtime"])
        or preprocessing.get("sha256") != _sha256_file(paths["preprocessing"])
    ):
        raise ValueError("GUI-Actor runtime or preprocessing identity is invalid")
    return paths


__all__ = [
    "CONTRACT_VERSION",
    "GUI_ACTOR_CHECKPOINT_REVISION",
    "GUI_ACTOR_PROVIDER",
    "GUI_ACTOR_REPOSITORY",
    "WINDOWS_SDPA_RUNTIME_PROVIDER",
    "WINDOWS_SDPA_RUNTIME_REPOSITORY",
    "WINDOWS_SDPA_RUNTIME_REVISION",
    "verify_gui_actor_deployment",
]
