"""Fail-closed composition verifier for the UI-Venus Windows SDPA deployment."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import json
import os
from pathlib import Path
import stat

from app.learn.hybrid import model_test_storage as storage


CONTRACT_VERSION = "goal_binding_ui_venus_deployment_manifest_v1"
UI_VENUS_PROVIDER = "ui_venus_1_5_2b_f16"
UI_VENUS_REPOSITORY = "inclusionAI/UI-Venus-1.5-2B"
WINDOWS_SDPA_RUNTIME_PROVIDER = "ui_venus_1_5_2b_f16_sdpa_runtime"
WINDOWS_SDPA_RUNTIME_REPOSITORY = "Desolate-Jix/agent-gui-runtime"
WINDOWS_SDPA_RUNTIME_REVISION = "5b84a19727de0e402503d214cc2f39ae60b07cce"
UI_VENUS_CHECKPOINT_REVISION = "bc4c6e62a1c545e043761439be95646d801853a4"
UI_VENUS_CHECKPOINT_FILES = frozenset({
    ".gitattributes", "README.md", "chat_template.json", "config.json",
    "generation_config.json", "model.safetensors", "preprocessor_config.json",
    "tokenizer.json", "tokenizer_config.json",
})
_SOURCE_DOCUMENT_VERSION = "goal_binding_ui_venus_source_identity_v1"
_PREPROCESSING_DOCUMENT_VERSION = "goal_binding_ui_venus_preprocessing_v1"
_RUNTIME_SMOKE_VERSION = "goal_binding_ui_venus_sdpa_runtime_smoke_v1"
_CODE_FILES = frozenset({
    "app/learn/hybrid/goal_binding_model_callers.py",
    "app/learn/hybrid/goal_binding_deployed_artifacts.py",
    "app/learn/hybrid/model_test_storage.py",
    "scripts/model_servers/goal_binding_transformers_worker.py",
    "scripts/model_servers/goal_binding_provider_runtimes.py",
})
_RUNTIME_PACKAGES = frozenset({"torch", "torchvision", "transformers", "accelerate", "qwen-vl-utils", "Pillow", "psutil", "pywin32"})
OFFICIAL_SOURCE_FILES = {
    "models/grounding/ui_venus1_5_gd.py": "8cc7640387be1f8ed9a3452560c3b11ae6487b373229355a45128b79d2c4707c",
    "requirements.txt": "99fdb61e4d2aeb9a56c5026894293b229f82546346d7bf232b432085faa75d9c",
}
OFFICIAL_SOURCE_REVISION = "inclusionAI/UI-Venus@192a9247ad1129279ba1d6c263d4c9e7ecef3644"
RUNTIME_PACKAGE_VERSIONS = {
    "torch": "2.12.0+cu130", "torchvision": "0.27.0+cu130",
    "transformers": "5.12.0", "accelerate": "1.14.0",
    "qwen-vl-utils": "0.0.14", "Pillow": "12.1.1", "psutil": "7.2.2",
    "pywin32": "311",
}
_ROLES = frozenset({"model", "runtime", "source", "preprocessing"})
_DEPLOYMENT_FIELDS = frozenset({"contract_version", "provider_id", "repo_id", "revision", "checkpoint_parent", "runtime_parent", "artifacts", "artifact_is_authorization"})


def _closed_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("deployment manifest has duplicate JSON keys")
        result[key] = value
    return result


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _relative(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value or Path(value).is_absolute() or ".." in Path(value).parts:
        raise ValueError(f"{field} is not a safe relative path")
    return value.replace("\\", "/")


def _reference(value: object, *, field: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != {"relative_path", "sha256"}:
        raise ValueError(f"{field} is invalid")
    path = _relative(value.get("relative_path"), field=field)
    digest = value.get("sha256")
    if not _is_sha256(digest):
        raise ValueError(f"{field} hash is invalid")
    return {"relative_path": path, "sha256": str(digest)}


def _safe_under(root: Path, relative: str) -> Path:
    try:
        _, resolved = storage._guard(root, root / relative)
    except ValueError as exc:
        if "unavailable" in str(exc):
            raise ValueError("deployment artifact is unavailable") from exc
        if "reparse" in str(exc):
            raise ValueError("deployment path contains a reparse point") from exc
        raise ValueError("deployment path escapes the artifact root") from exc
    return resolved


def _manifest_file_entries(payload: Mapping[str, object], *, root: Path, provider: str, revision: str) -> dict[str, dict[str, object]]:
    if set(payload) != {"contract_version", "provider_id", "repo_id", "revision", "files", "artifact_is_authorization"}:
        raise ValueError("registered parent manifest is not closed")
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("registered parent manifest files are invalid")
    namespace = Path("artifacts") / provider / revision
    result: dict[str, dict[str, object]] = {}
    for item in files:
        if not isinstance(item, Mapping) or set(item) != {"relative_path", "bytes", "sha256"}:
            raise ValueError("registered parent manifest file is invalid")
        relative = _relative(item.get("relative_path"), field="registered parent file")
        expected_bytes, expected_sha = item.get("bytes"), item.get("sha256")
        if isinstance(expected_bytes, bool) or not isinstance(expected_bytes, int) or expected_bytes < 0 or not _is_sha256(expected_sha):
            raise ValueError("registered parent manifest file is invalid")
        if not Path(relative).is_relative_to(namespace) or relative in result:
            raise ValueError("registered parent manifest file is outside its namespace or duplicated")
        local = _safe_under(root, relative)
        try:
            resolved, actual_relative = storage._validate_registered_file(root, local)
        except ValueError as exc:
            raise ValueError("registered parent manifest file is unavailable or ambiguous") from exc
        if actual_relative != relative or resolved.stat().st_size != expected_bytes or _sha256_file(resolved) != expected_sha:
            raise ValueError("registered parent manifest file changed locally")
        result[relative] = {"bytes": expected_bytes, "sha256": expected_sha, "path": resolved}
    return result


def _verify_exact_namespace(*, root: Path, provider: str, revision: str, files: Mapping[str, Mapping[str, object]]) -> None:
    namespace = _safe_under(root, (Path("artifacts") / provider / revision).as_posix())
    if not namespace.is_dir() or storage._is_reparse(namespace):
        raise ValueError("registered parent namespace is unavailable or a reparse point")
    discovered: set[str] = set()
    for directory, dirs, names in os.walk(namespace, followlinks=False):
        current = Path(directory)
        if storage._is_reparse(current):
            raise ValueError("registered parent namespace contains a reparse point")
        for name in [*dirs, *names]:
            candidate = current / name
            if storage._is_reparse(candidate):
                raise ValueError("registered parent namespace contains a reparse point")
        for name in names:
            candidate = current / name
            info = candidate.lstat()
            if not stat.S_ISREG(info.st_mode) or getattr(info, "st_nlink", 1) != 1:
                raise ValueError("registered parent namespace contains an ambiguous file")
            discovered.add(candidate.resolve().relative_to(root.resolve()).as_posix())
    if discovered != set(files):
        raise ValueError("registered parent namespace does not exactly match its manifest")


def _verified_parent(
    *, root: Path, reference: Mapping[str, str], provider: str, repo_id: str, revision: str
) -> dict[str, dict[str, object]]:
    manifest_path = _safe_under(root, reference["relative_path"])
    try:
        payload, resolved_root, resolved_manifest = storage._load_manifest(root, manifest_path)
    except ValueError as exc:
        raise ValueError("deployment parent is not durably registered") from exc
    if resolved_root != root.resolve() or _sha256_file(resolved_manifest) != reference["sha256"]:
        raise ValueError("deployment parent reference changed locally")
    if payload.get("provider_id") != provider or payload.get("repo_id") != repo_id or payload.get("revision") != revision or payload.get("artifact_is_authorization") is not False:
        raise ValueError("deployment parent identity mismatch")
    files = _manifest_file_entries(payload, root=root, provider=provider, revision=revision)
    _verify_exact_namespace(root=root, provider=provider, revision=revision, files=files)
    return files


def _artifact_projection(
    payload: Mapping[str, object], *, checkpoint_files: Mapping[str, Mapping[str, object]], runtime_files: Mapping[str, Mapping[str, object]]
) -> dict[str, Path]:
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != len(_ROLES):
        raise ValueError("deployment artifact projection is invalid")
    result: dict[str, Path] = {}
    paths: set[str] = set()
    expected_parent = {"model": "checkpoint", "runtime": "runtime", "source": "runtime", "preprocessing": "runtime"}
    for item in artifacts:
        if not isinstance(item, Mapping) or set(item) != {"role", "parent", "relative_path", "bytes", "sha256"}:
            raise ValueError("deployment artifact projection is invalid")
        role, parent = item.get("role"), item.get("parent")
        if not isinstance(role, str) or role not in _ROLES or role in result or parent != expected_parent.get(role):
            raise ValueError("deployment artifact role projection is invalid")
        relative = _relative(item.get("relative_path"), field="deployment artifact")
        expected_bytes, expected_sha = item.get("bytes"), item.get("sha256")
        if isinstance(expected_bytes, bool) or not isinstance(expected_bytes, int) or expected_bytes < 0 or not _is_sha256(expected_sha) or relative in paths:
            raise ValueError("deployment artifact projection is invalid")
        parent_files = checkpoint_files if parent == "checkpoint" else runtime_files
        source = parent_files.get(relative)
        if source is None or source["bytes"] != expected_bytes or source["sha256"] != expected_sha:
            raise ValueError("deployment artifact is not an exact parent-registered file")
        path = source["path"]
        if not isinstance(path, Path):
            raise ValueError("deployment artifact path is invalid")
        result[role] = path
        paths.add(relative)
    if set(result) != _ROLES:
        raise ValueError("deployment artifact roles are incomplete")
    return result


def _read_closed_json(path: Path, *, fields: frozenset[str], label: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_closed_object)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is unreadable") from exc
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(f"{label} is invalid")
    return dict(value)


def _current_code_hashes() -> dict[str, str]:
    repository = Path(__file__).resolve().parents[3]
    values: dict[str, str] = {}
    for relative in sorted(_CODE_FILES):
        path = repository / relative
        if not path.is_file():
            raise ValueError("current UI-Venus verifier code is unavailable")
        values[relative] = _sha256_file(path)
    return values


def _verify_source_document(
    *, path: Path, profile: Mapping[str, object], runtime_provider: str,
    runtime_revision: str, runtime_files: Mapping[str, Mapping[str, object]],
) -> str:
    document = _read_closed_json(
        path,
        fields=frozenset({"contract_version", "official_source_revision", "official_source_files", "project_revision", "code_files"}),
        label="UI-Venus source identity document",
    )
    preprocessing = profile.get("preprocessing")
    code_files = document.get("code_files")
    official_files = document.get("official_source_files")
    if (
        document.get("contract_version") != _SOURCE_DOCUMENT_VERSION
        or not isinstance(preprocessing, Mapping)
        or document.get("official_source_revision") != OFFICIAL_SOURCE_REVISION
        or preprocessing.get("source_revision") != OFFICIAL_SOURCE_REVISION
        or document.get("project_revision") != runtime_revision
        or not isinstance(code_files, Mapping)
        or set(code_files) != _CODE_FILES
        or any(not _is_sha256(value) for value in code_files.values())
        or dict(code_files) != _current_code_hashes()
    ):
        raise ValueError("UI-Venus source identity document does not bind current code")
    if not isinstance(official_files, Mapping) or dict(official_files) != OFFICIAL_SOURCE_FILES:
        raise ValueError("UI-Venus source identity document does not bind official source files")
    namespace = Path("artifacts") / runtime_provider / runtime_revision
    for relative, digest in OFFICIAL_SOURCE_FILES.items():
        if not isinstance(relative, str) or not _is_sha256(digest):
            raise ValueError("UI-Venus source identity document official file is invalid")
        candidate = _relative(relative, field="UI-Venus official source file")
        parent_relative = (namespace / "official" / candidate).as_posix()
        record = runtime_files.get(parent_relative)
        if record is None or record.get("sha256") != digest:
            raise ValueError("UI-Venus source identity document official file changed or escaped")
    return _sha256_file(path)


def _verify_preprocessing_document(*, path: Path, source_sha256: str, profile: Mapping[str, object]) -> None:
    from scripts.model_servers.goal_binding_provider_runtimes import UI_VENUS_CENTER_POINT_PROMPT

    document = _read_closed_json(
        path,
        fields=frozenset({"contract_version", "source_document_sha256", "official_attention_implementation", "tested_attention_implementation", "prompt", "dtype", "max_new_tokens", "native_output_kind", "coordinate_space"}),
        label="UI-Venus preprocessing document",
    )
    prompt = document.get("prompt")
    native = profile.get("native_output")
    if (
        document.get("contract_version") != _PREPROCESSING_DOCUMENT_VERSION
        or document.get("source_document_sha256") != source_sha256
        or document.get("official_attention_implementation") != "flash_attention_2"
        or document.get("tested_attention_implementation") != "sdpa"
        or not isinstance(prompt, Mapping)
        or set(prompt) != {"sha256", "utf8"}
        or prompt.get("utf8") != UI_VENUS_CENTER_POINT_PROMPT
        or prompt.get("sha256") != sha256(UI_VENUS_CENTER_POINT_PROMPT.encode("utf-8")).hexdigest()
        or document.get("dtype") != "bfloat16"
        or document.get("max_new_tokens") != 128
        or not isinstance(native, Mapping)
        or document.get("native_output_kind") != native.get("kind")
        or document.get("coordinate_space") != profile.get("coordinate_space")
    ):
        raise ValueError("UI-Venus preprocessing document does not bind the tested SDPA path")


def _verify_runtime_smoke(*, files: Mapping[str, Mapping[str, object]], runtime_provider: str, runtime_revision: str) -> None:
    candidate = (Path("artifacts") / runtime_provider / runtime_revision / "runtime-smoke.json").as_posix()
    record = files.get(candidate)
    if record is None or not isinstance(record.get("path"), Path):
        raise ValueError("UI-Venus runtime smoke document is missing")
    document = _read_closed_json(
        record["path"],
        fields=frozenset({"contract_version", "python", "packages", "python_executable_sha256", "smoke_script_sha256", "exit_code", "windows_process_scope_ready"}),
        label="UI-Venus runtime smoke document",
    )
    python = document.get("python")
    packages = document.get("packages")
    executable = (Path("artifacts") / runtime_provider / runtime_revision / "Scripts" / "python.exe").as_posix()
    pyvenv = (Path("artifacts") / runtime_provider / runtime_revision / "pyvenv.cfg").as_posix()
    base_python = (Path("artifacts") / runtime_provider / runtime_revision / "base" / "python.exe").as_posix()
    smoke_script = (Path("artifacts") / runtime_provider / runtime_revision / "runtime-smoke.py").as_posix()
    executable_record, script_record, pyvenv_record, base_python_record = files.get(executable), files.get(smoke_script), files.get(pyvenv), files.get(base_python)
    if (
        not isinstance(python, Mapping) or set(python) != {"implementation", "version"}
        or python.get("implementation") != "CPython" or not isinstance(python.get("version"), str)
        or pyvenv_record is None
        or base_python_record is None
        or document.get("python_executable_sha256") != (executable_record or {}).get("sha256")
        or document.get("smoke_script_sha256") != (script_record or {}).get("sha256")
        or document.get("exit_code") != 0
    ):
        raise ValueError("UI-Venus runtime smoke CPython identity is invalid")
    if document.get("windows_process_scope_ready") is not True:
        raise ValueError("UI-Venus Windows process scope readiness is invalid")
    if not isinstance(packages, list) or len(packages) != len(_RUNTIME_PACKAGES):
        raise ValueError("UI-Venus runtime smoke package set is invalid")
    observed: set[str] = set()
    namespace = (Path("artifacts") / runtime_provider / runtime_revision)
    for item in packages:
        if not isinstance(item, Mapping) or set(item) != {"distribution", "version", "module_origin"}:
            raise ValueError("UI-Venus runtime smoke package is invalid")
        distribution, version = item.get("distribution"), item.get("version")
        origin = _relative(item.get("module_origin"), field="UI-Venus runtime module origin")
        if not isinstance(distribution, str) or distribution not in _RUNTIME_PACKAGES or distribution in observed or version != RUNTIME_PACKAGE_VERSIONS.get(distribution) or not Path(origin).is_relative_to(namespace) or origin not in files:
            raise ValueError("UI-Venus runtime smoke package identity is invalid")
        observed.add(distribution)
    if observed != _RUNTIME_PACKAGES:
        raise ValueError("UI-Venus runtime smoke package set is incomplete")
    pyvenv_path = pyvenv_record.get("path")
    if not isinstance(pyvenv_path, Path):
        raise ValueError("UI-Venus runtime pyvenv.cfg path is invalid")
    try:
        config_lines = pyvenv_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError("UI-Venus runtime pyvenv.cfg is unreadable") from exc
    config: dict[str, str] = {}
    for line in config_lines:
        key, separator, value = line.partition("=")
        if not separator:
            continue
        normalized = key.strip().casefold()
        if normalized in config:
            raise ValueError("UI-Venus runtime pyvenv.cfg has duplicate fields")
        config[normalized] = value.strip()
    runtime_root = pyvenv_path.parent.resolve()
    expected_home = (runtime_root / "base").resolve()
    expected_executable = (expected_home / "python.exe").resolve()
    home = Path(config.get("home", ""))
    configured_executable = Path(config.get("executable", ""))
    if not home.is_absolute() or not configured_executable.is_absolute() or home.resolve() != expected_home or configured_executable.resolve() != expected_executable:
        raise ValueError("UI-Venus runtime Python home is not pinned to its registered artifact")


def verify_ui_venus_deployment(profile: Mapping[str, object], artifact_root: Path) -> dict[str, Path]:
    """Verify a non-authorizing UI-Venus profile against two immutable registered parents."""
    root = Path(artifact_root).resolve()
    if profile.get("provider_id") != UI_VENUS_PROVIDER or profile.get("repository_id") != UI_VENUS_REPOSITORY or profile.get("native_output", {}).get("kind") != "ui_venus_point_v1" or profile.get("runtime", {}).get("kind") != "transformers_sdpa_windows_v1":
        raise ValueError("profile is not the sealed UI-Venus Windows SDPA profile")
    ref = profile.get("artifact_manifest")
    if not isinstance(ref, Mapping) or ref.get("status") != "verified":
        raise ValueError("UI-Venus deployment is not acquired and verified")
    manifest_path = _safe_under(root, _relative(ref.get("relative_path"), field="profile deployment manifest"))
    try:
        raw = manifest_path.read_bytes()
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_closed_object)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("UI-Venus deployment manifest is unreadable") from exc
    if ref.get("sha256") != _sha256_file(manifest_path) or not isinstance(payload, Mapping) or set(payload) != _DEPLOYMENT_FIELDS:
        raise ValueError("UI-Venus deployment manifest is invalid")
    if payload.get("contract_version") != CONTRACT_VERSION or payload.get("artifact_is_authorization") is not False or payload.get("provider_id") != UI_VENUS_PROVIDER or payload.get("repo_id") != UI_VENUS_REPOSITORY or payload.get("revision") != UI_VENUS_CHECKPOINT_REVISION or profile.get("upstream_revision") != UI_VENUS_CHECKPOINT_REVISION:
        raise ValueError("UI-Venus deployment manifest identity mismatch")
    checkpoint_ref = _reference(payload.get("checkpoint_parent"), field="checkpoint parent")
    runtime_ref = _reference(payload.get("runtime_parent"), field="runtime parent")
    if checkpoint_ref == runtime_ref:
        raise ValueError("deployment parents must remain distinct")
    checkpoint_files = _verified_parent(root=root, reference=checkpoint_ref, provider=UI_VENUS_PROVIDER, repo_id=UI_VENUS_REPOSITORY, revision=UI_VENUS_CHECKPOINT_REVISION)
    checkpoint_namespace = Path("artifacts") / UI_VENUS_PROVIDER / UI_VENUS_CHECKPOINT_REVISION
    if {Path(relative).relative_to(checkpoint_namespace).as_posix() for relative in checkpoint_files} != UI_VENUS_CHECKPOINT_FILES:
        raise ValueError("UI-Venus checkpoint parent is not the exact expected nine-file snapshot")
    runtime_parent_path = _safe_under(root, runtime_ref["relative_path"])
    try:
        runtime_payload, _, _ = storage._load_manifest(root, runtime_parent_path)
    except ValueError as exc:
        raise ValueError("deployment parent is not durably registered") from exc
    runtime_revision = runtime_payload.get("revision")
    if runtime_revision != WINDOWS_SDPA_RUNTIME_REVISION:
        raise ValueError("UI-Venus runtime parent revision is invalid")
    runtime_files = _verified_parent(root=root, reference=runtime_ref, provider=WINDOWS_SDPA_RUNTIME_PROVIDER, repo_id=WINDOWS_SDPA_RUNTIME_REPOSITORY, revision=runtime_revision)
    _verify_runtime_smoke(files=runtime_files, runtime_provider=WINDOWS_SDPA_RUNTIME_PROVIDER, runtime_revision=runtime_revision)
    paths = _artifact_projection(payload, checkpoint_files=checkpoint_files, runtime_files=runtime_files)
    source_sha256 = _verify_source_document(
        path=paths["source"], profile=profile,
        runtime_provider=WINDOWS_SDPA_RUNTIME_PROVIDER,
        runtime_revision=runtime_revision, runtime_files=runtime_files,
    )
    _verify_preprocessing_document(path=paths["preprocessing"], source_sha256=source_sha256, profile=profile)
    artifacts = profile.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != len(_ROLES):
        raise ValueError("UI-Venus profile artifact projection is invalid")
    profile_artifacts = {item.get("role"): item for item in artifacts if isinstance(item, Mapping)}
    if set(profile_artifacts) != _ROLES:
        raise ValueError("UI-Venus profile artifact roles are invalid")
    for role, path in paths.items():
        item = profile_artifacts[role]
        if item.get("relative_path") != path.relative_to(root).as_posix() or item.get("bytes") != path.stat().st_size or item.get("sha256") != _sha256_file(path):
            raise ValueError("UI-Venus profile artifact does not match deployment projection")
    runtime = profile.get("runtime")
    preprocessing = profile.get("preprocessing")
    if not isinstance(runtime, Mapping) or not isinstance(preprocessing, Mapping) or runtime.get("isolated_runtime_path") != paths["runtime"].relative_to(root).as_posix() or runtime.get("sha256") != _sha256_file(paths["runtime"]) or preprocessing.get("sha256") != _sha256_file(paths["preprocessing"]):
        raise ValueError("UI-Venus runtime or preprocessing identity is not verified")
    return paths


__all__ = ["CONTRACT_VERSION", "WINDOWS_SDPA_RUNTIME_PROVIDER", "WINDOWS_SDPA_RUNTIME_REPOSITORY", "UI_VENUS_CHECKPOINT_REVISION", "verify_ui_venus_deployment"]
