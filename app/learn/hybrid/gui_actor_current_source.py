"""GUIActor 当前源码单次加载器；历史部署封印保持不变。"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
from typing import Any
from uuid import uuid4

from app.learn.hybrid.goal_binding_model_callers import load_goal_binding_profile
from app.learn.hybrid import model_test_storage as storage


GUI_ACTOR_PROVIDER = "gui_actor_3b_bf16"
GUI_ACTOR_REPOSITORY = "microsoft/GUI-Actor-3B-Qwen2.5-VL"
GUI_ACTOR_REVISION = "5fb97348752cb3d50be9709f47d9ae6c99725949"
RUNTIME_PROVIDER = "gui_actor_3b_bf16_sdpa_runtime"
RUNTIME_REPOSITORY = "Desolate-Jix/agent-gui-runtime"
RUNTIME_REVISION = "ca138459132fe1b88d5923af2842f11711efbce9"
OFFICIAL_SOURCE_REVISION = "microsoft/GUI-Actor@d98d1bbd01862f9112114b83b032f492c365a173"
DEPLOYMENT_CONTRACT = "goal_binding_gui_actor_deployment_manifest_v1"
SOURCE_CONTRACT = "goal_binding_gui_actor_source_identity_v1"
CURRENT_SOURCE_CONTRACT = "gui_actor_current_source_receipt_v1"
DEFAULT_STORAGE_LIMIT_BYTES = 32_212_254_720
_CODE_FILES = (
    "app/learn/hybrid/goal_binding_model_callers.py",
    "app/learn/hybrid/goal_binding_gui_actor_deployed_artifacts.py",
    "app/learn/hybrid/goal_binding_deployed_artifacts.py",
    "app/learn/hybrid/model_test_storage.py",
    "scripts/model_servers/goal_binding_transformers_worker.py",
    "scripts/model_servers/goal_binding_provider_runtimes.py",
    "app/learn/hybrid/gui_actor_current_source.py",
    "scripts/run_learning_gui_actor_once.py",
)


class GuiActorCurrentSourceError(ValueError):
    """可操作的 GUIActor 当前源码失败。"""


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _closed_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise GuiActorCurrentSourceError("identity JSON has duplicate keys")
        result[key] = value
    return result


def _read_json(path: Path, *, label: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_closed_object)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GuiActorCurrentSourceError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise GuiActorCurrentSourceError(f"{label} must be an object")
    return value


def _digest(value: object) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise GuiActorCurrentSourceError("identity SHA-256 is invalid")
    return value


def _under(root: Path, value: object, *, label: str) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute() or ".." in Path(value).parts:
        raise GuiActorCurrentSourceError(f"{label} is not root-relative")
    resolved_root = root.resolve()
    candidate = (resolved_root / value).resolve()
    if not candidate.is_relative_to(resolved_root):
        raise GuiActorCurrentSourceError(f"{label} escapes artifact root")
    return candidate


def _reference(root: Path, value: object, *, label: str) -> tuple[Path, str]:
    if not isinstance(value, Mapping) or set(value) not in ({"relative_path", "sha256"}, {"relative_path", "sha256", "status"}):
        raise GuiActorCurrentSourceError(f"{label} reference is invalid")
    if value.get("status", "verified") != "verified":
        raise GuiActorCurrentSourceError(f"{label} is not verified")
    path = _under(root, value.get("relative_path"), label=label)
    digest = _digest(value.get("sha256"))
    if not path.is_file() or _sha256_file(path) != digest:
        raise GuiActorCurrentSourceError(f"{label} hash differs")
    return path, digest


def _parent_files(root: Path, reference: object, *, provider: str, repository: str, revision: str, label: str) -> tuple[Path, str, dict[str, dict[str, object]]]:
    path, digest = _reference(root, reference, label=label)
    try:
        payload, _, _ = storage._load_manifest(root, path)
    except ValueError as exc:
        raise GuiActorCurrentSourceError(f"{label} is not durably registered") from exc
    if payload.get("provider_id") != provider or payload.get("repo_id") != repository or payload.get("revision") != revision or payload.get("artifact_is_authorization") is not False:
        raise GuiActorCurrentSourceError(f"{label} metadata differs")
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        raise GuiActorCurrentSourceError(f"{label} files are invalid")
    verified: dict[str, dict[str, object]] = {}
    for item in files:
        if not isinstance(item, Mapping) or set(item) != {"relative_path", "bytes", "sha256"}:
            raise GuiActorCurrentSourceError(f"{label} file entry is invalid")
        relative = item.get("relative_path")
        size = item.get("bytes")
        if not isinstance(relative, str) or isinstance(size, bool) or not isinstance(size, int) or size < 0 or relative in verified:
            raise GuiActorCurrentSourceError(f"{label} file identity is invalid")
        file_path = _under(root, relative, label=f"{label} file")
        digest_item = _digest(item.get("sha256"))
        if not file_path.is_file() or file_path.stat().st_size != size or _sha256_file(file_path) != digest_item:
            raise GuiActorCurrentSourceError(f"{label} file hash differs")
        verified[relative] = {"relative_path": relative, "bytes": size, "sha256": digest_item}
    return path, digest, verified


def _profile_roles(root: Path, profile: Mapping[str, object]) -> dict[str, dict[str, object]]:
    items = profile.get("artifacts")
    if not isinstance(items, list):
        raise GuiActorCurrentSourceError("profile artifacts are invalid")
    roles: dict[str, dict[str, object]] = {}
    for item in items:
        if not isinstance(item, Mapping):
            raise GuiActorCurrentSourceError("profile artifact is invalid")
        role, relative, size = item.get("role"), item.get("relative_path"), item.get("bytes")
        if not isinstance(role, str) or role in roles or not isinstance(relative, str) or isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise GuiActorCurrentSourceError("profile artifact identity is invalid")
        path = _under(root, relative, label=f"profile {role}")
        digest = _digest(item.get("sha256"))
        if not path.is_file() or path.stat().st_size != size or _sha256_file(path) != digest:
            raise GuiActorCurrentSourceError(f"profile {role} hash differs")
        roles[role] = {"relative_path": relative, "bytes": size, "sha256": digest}
    if set(roles) != {"model", "runtime", "source", "preprocessing"}:
        raise GuiActorCurrentSourceError("profile artifact roles are incomplete")
    return roles


def _current_code_identity(project_root: Path) -> dict[str, str]:
    identity: dict[str, str] = {}
    for relative in _CODE_FILES:
        path = project_root / relative
        if not path.is_file():
            raise GuiActorCurrentSourceError("current GUIActor source is unavailable")
        identity[relative] = _sha256_file(path)
    return identity


def verify_current_source_identity(profile: Mapping[str, object], artifact_root: Path, *, project_root: Path | None = None) -> dict[str, object]:
    """验证不可变资产，并单独记录当前源码身份。"""
    root = Path(artifact_root).resolve()
    project = (project_root or Path(__file__).resolve().parents[3]).resolve()
    runtime = profile.get("runtime")
    preprocessing = profile.get("preprocessing")
    native = profile.get("native_output")
    if (
        profile.get("provider_id") != GUI_ACTOR_PROVIDER
        or profile.get("repository_id") != GUI_ACTOR_REPOSITORY
        or profile.get("upstream_revision") != GUI_ACTOR_REVISION
        or not isinstance(runtime, Mapping)
        or runtime.get("kind") != "gui_actor_transformers_sdpa_windows_v1"
        or not isinstance(native, Mapping)
        or native.get("kind") != "gui_actor_topk_points_v1"
        or profile.get("coordinate_space") != "normalized_0_1"
        or not isinstance(preprocessing, Mapping)
        or preprocessing.get("source_revision") != OFFICIAL_SOURCE_REVISION
    ):
        raise GuiActorCurrentSourceError("profile is not the GUIActor current-source contract")
    deployment_path, deployment_digest = _reference(root, profile.get("artifact_manifest"), label="deployment")
    deployment = _read_json(deployment_path, label="deployment")
    expected_deployment_fields = {"contract_version", "provider_id", "repo_id", "revision", "checkpoint_parent", "runtime_parent", "artifacts", "artifact_is_authorization"}
    if set(deployment) != expected_deployment_fields or deployment.get("contract_version") != DEPLOYMENT_CONTRACT or deployment.get("provider_id") != GUI_ACTOR_PROVIDER or deployment.get("repo_id") != GUI_ACTOR_REPOSITORY or deployment.get("revision") != GUI_ACTOR_REVISION or deployment.get("artifact_is_authorization") is not False:
        raise GuiActorCurrentSourceError("deployment metadata differs")
    checkpoint_path, checkpoint_digest, checkpoint_files = _parent_files(root, deployment.get("checkpoint_parent"), provider=GUI_ACTOR_PROVIDER, repository=GUI_ACTOR_REPOSITORY, revision=GUI_ACTOR_REVISION, label="checkpoint parent")
    runtime_path, runtime_digest, runtime_files = _parent_files(root, deployment.get("runtime_parent"), provider=RUNTIME_PROVIDER, repository=RUNTIME_REPOSITORY, revision=RUNTIME_REVISION, label="runtime parent")
    roles = _profile_roles(root, profile)
    items = deployment.get("artifacts")
    if not isinstance(items, list):
        raise GuiActorCurrentSourceError("deployment artifacts are invalid")
    deployed: dict[str, dict[str, object]] = {}
    for item in items:
        if not isinstance(item, Mapping) or not isinstance(item.get("role"), str) or item["role"] in deployed:
            raise GuiActorCurrentSourceError("deployment artifact roles are invalid")
        role = str(item["role"])
        candidate = {key: item.get(key) for key in ("relative_path", "bytes", "sha256")}
        if role not in {"model", "runtime", "source", "preprocessing"} or not isinstance(candidate["relative_path"], str) or isinstance(candidate["bytes"], bool) or not isinstance(candidate["bytes"], int):
            raise GuiActorCurrentSourceError("deployment artifact identity is invalid")
        candidate["sha256"] = _digest(candidate["sha256"])
        deployed[role] = candidate  # type: ignore[assignment]
    if set(deployed) != set(roles):
        raise GuiActorCurrentSourceError("deployment artifact roles are incomplete")
    for role, entry in roles.items():
        if deployed[role] != entry:
            raise GuiActorCurrentSourceError(f"profile {role} differs from deployment")
        parent = checkpoint_files if role == "model" else runtime_files
        if parent.get(str(entry["relative_path"])) != entry:
            raise GuiActorCurrentSourceError(f"{role} differs from parent manifest")
    source_path = _under(root, roles["source"]["relative_path"], label="official source")
    source = _read_json(source_path, label="official source")
    official = source.get("official_source_files")
    if source.get("contract_version") != SOURCE_CONTRACT or source.get("official_source_revision") != OFFICIAL_SOURCE_REVISION or source.get("project_revision") != RUNTIME_REVISION or not isinstance(official, Mapping) or not official:
        raise GuiActorCurrentSourceError("official source files are invalid")
    runtime_root = source_path.parent
    official_verified: dict[str, str] = {}
    for relative, digest in official.items():
        if not isinstance(relative, str):
            raise GuiActorCurrentSourceError("official source file name is invalid")
        expected = _digest(digest)
        original = _under(runtime_root, str(Path("official") / relative), label="official source file")
        installed = _under(runtime_root, str(Path("Lib/site-packages") / relative), label="installed source file")
        if (runtime_files.get(original.relative_to(root).as_posix()) is None or runtime_files.get(installed.relative_to(root).as_posix()) is None or not original.is_file() or not installed.is_file() or _sha256_file(original) != expected or _sha256_file(installed) != expected):
            raise GuiActorCurrentSourceError("official source file hash differs")
        official_verified[relative] = expected
    expected_python = _under(root, runtime.get("isolated_runtime_path"), label="runtime Python")
    if roles["runtime"]["relative_path"] != expected_python.relative_to(root).as_posix() or roles["runtime"]["sha256"] != _sha256_file(expected_python):
        raise GuiActorCurrentSourceError("runtime Python differs from verified role")
    return {
        "contract_version": CURRENT_SOURCE_CONTRACT,
        "source_binding": "current_source_external_v1",
        "frozen_deployment_seal": "not_invoked",
        "artifact_is_authorization": False,
        "provider_id": GUI_ACTOR_PROVIDER,
        "deployment": {"path": str(deployment_path), "sha256": deployment_digest},
        "checkpoint_parent": {"path": str(checkpoint_path), "sha256": checkpoint_digest},
        "runtime_parent": {"path": str(runtime_path), "sha256": runtime_digest},
        "verified_roles": roles,
        "official_source_revision": OFFICIAL_SOURCE_REVISION,
        "official_source_files": official_verified,
        "runtime_python": str(expected_python),
        "code_identity": _current_code_identity(project),
    }


def inventory_storage_bytes(root: Path) -> int:
    total = 0
    for directory, _, names in os.walk(root, followlinks=False):
        for name in names:
            path = Path(directory) / name
            try:
                info = path.lstat()
            except OSError as exc:
                raise GuiActorCurrentSourceError("storage inventory changed") from exc
            if stat.S_ISREG(info.st_mode):
                total += info.st_size
    return total



def _gpu_preflight() -> dict[str, object]:
    """要求空闲 CUDA:0 且满足已测得的 GUIActor BF16 下限。"""
    try:
        completed = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free,utilization.gpu", "--format=csv,noheader,nounits"],
            capture_output=True,
            timeout=10,
            check=True,
        )
        raw = completed.stdout.decode("utf-8", errors="strict").strip()
    except (OSError, UnicodeDecodeError, subprocess.SubprocessError) as exc:
        raise GuiActorCurrentSourceError("GPU preflight is unavailable") from exc
    rows = [line.strip() for line in raw.splitlines() if line.strip()]
    if not rows:
        raise GuiActorCurrentSourceError("GPU preflight returned no CUDA devices")
    fields = [field.strip() for field in rows[0].split(",")]
    if len(fields) != 2 or not all(field.isdecimal() for field in fields):
        raise GuiActorCurrentSourceError("GPU preflight output is invalid")
    available, utilization = (int(field) for field in fields)
    required = 10_240
    if available < required:
        raise GuiActorCurrentSourceError("GPU preflight has insufficient free GPU memory")
    if utilization > 20:
        raise GuiActorCurrentSourceError("GPU preflight utilization is contended")
    return {"status": "ready", "required_free_mib": required, "available_free_mib": available, "utilization_percent": utilization}


def _write_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def _read_child_result(path: Path) -> dict[str, object]:
    return _read_json(path, label="GUIActor child result")


def _create_time_ns_text(value: int) -> str:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise GuiActorCurrentSourceError("GUIActor child create time is invalid")
    return str(value)


def _run_exact_child(*, command: list[str], cwd: Path, stdout_path: Path, stderr_path: Path, timeout_seconds: int) -> dict[str, object]:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        child = subprocess.Popen(command, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, creationflags=creationflags)
        try:
            import psutil
        except ImportError:
            created_ns = 0
        else:
            try:
                created_ns = int(psutil.Process(child.pid).create_time() * 1_000_000_000)
            except (OSError, psutil.Error):
                created_ns = 0
        try:
            exit_code = child.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            child_state = _kill_exact_child(child, created_ns=created_ns, status="timed_out")
            error = GuiActorCurrentSourceError("GUIActor child timed out and was killed")
            error.child = child_state
            raise error from exc
        except KeyboardInterrupt as exc:
            exc.child = _kill_exact_child(child, created_ns=created_ns, status="interrupted")
            raise
    return {
        "status": "exited",
        "pid": int(child.pid),
        "create_time_ns": _create_time_ns_text(created_ns),
        "exit_code": int(exit_code),
        "cleanup": {
            "status": "verified_exact_child_exited",
            "pid": int(child.pid),
            "create_time_ns": _create_time_ns_text(created_ns),
            "exit_code": int(exit_code),
        },
    }


def _kill_exact_child(child: subprocess.Popen[bytes], *, created_ns: int, status: str) -> dict[str, object]:
    cleanup: dict[str, object] = {
        "status": "failed_exact_child_cleanup",
        "pid": int(child.pid),
        "create_time_ns": _create_time_ns_text(created_ns),
        "exit_code": child.returncode,
    }
    try:
        child.kill()
        exit_code = child.wait(timeout=30)
    except (OSError, subprocess.TimeoutExpired) as error:
        cleanup["error_type"] = type(error).__name__
    else:
        cleanup["status"] = "verified_exact_child_killed"
        cleanup["exit_code"] = int(exit_code)
    return {
        "status": status,
        "pid": int(child.pid),
        "create_time_ns": _create_time_ns_text(created_ns),
        "exit_code": cleanup["exit_code"],
        "cleanup": cleanup,
    }


def _trace(path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    try:
        raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise GuiActorCurrentSourceError("GUIActor child trace is not UTF-8") from exc
    return {"path": str(path), "sha256": sha256(raw).hexdigest(), "bytes": len(raw), "encoding": "utf-8"}


def _failure_trace(path: Path | None) -> dict[str, object] | None:
    if path is None or not path.is_file():
        return None
    raw = path.read_bytes()
    try:
        raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        encoding = "invalid-utf8"
    else:
        encoding = "utf-8"
    return {"path": str(path), "sha256": sha256(raw).hexdigest(), "bytes": len(raw), "encoding": encoding}


def _not_started_child() -> dict[str, object]:
    return {
        "status": "not_started",
        "pid": None,
        "create_time_ns": None,
        "exit_code": None,
        "cleanup": {"status": "not_started"},
    }


def _write_failure_result(
    *,
    output: Path,
    stage: str,
    error: BaseException,
    child: Mapping[str, object],
    stdout_path: Path | None,
    stderr_path: Path | None,
    image_sha256: str | None,
    target_sha256: str | None,
    storage_preflight: Mapping[str, object] | None,
    gpu_preflight: Mapping[str, object] | None,
) -> None:
    _write_json(output / "failure-result.json", {
        "contract_version": "gui_actor_current_source_failure_v1",
        "outcome": "failed",
        "failure_stage": stage,
        "error": {"type": type(error).__name__, "message": str(error)},
        "child": deepcopy(dict(child)),
        "stdout_trace": _failure_trace(stdout_path),
        "stderr_trace": _failure_trace(stderr_path),
        "image_sha256": image_sha256,
        "target_sha256": target_sha256,
        "storage_preflight": deepcopy(dict(storage_preflight)) if storage_preflight is not None else None,
        "gpu_preflight": deepcopy(dict(gpu_preflight)) if gpu_preflight is not None else None,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    })


def _profile_path(project_root: Path) -> Path:
    return project_root / "configs/model_profiles/goal_binding_gui_actor_3b_bf16.json"


def load_gui_actor_profile(path: Path) -> dict[str, object]:
    return load_goal_binding_profile(path)


def run_gui_actor_once(*, project_root: Path, image_path: Path, target_text: str, artifact_root: Path, out_dir: Path, storage_limit_bytes: int = DEFAULT_STORAGE_LIMIT_BYTES) -> dict[str, object]:
    """运行一次父进程托管的 GUIActor 推理，不接受历史报告。"""
    project = Path(project_root).resolve()
    image = Path(image_path).resolve()
    root = Path(artifact_root).resolve()
    output = Path(out_dir).resolve()
    if not project.is_dir():
        raise GuiActorCurrentSourceError("project root is unavailable")
    if not output.is_relative_to(project):
        raise GuiActorCurrentSourceError("output must remain under project root")
    if not image.is_file() or not isinstance(target_text, str) or not target_text.strip():
        raise GuiActorCurrentSourceError("image and target text are required")
    if isinstance(storage_limit_bytes, bool) or not isinstance(storage_limit_bytes, int) or storage_limit_bytes <= 0:
        raise GuiActorCurrentSourceError("storage limit is invalid")

    output.mkdir(parents=True, exist_ok=False)
    stage = "storage_preflight"
    child: Mapping[str, object] = _not_started_child()
    stdout_path: Path | None = None
    stderr_path: Path | None = None
    image_digest: str | None = _sha256_file(image)
    target_digest: str | None = sha256(target_text.encode("utf-8")).hexdigest()
    storage_preflight: dict[str, object] | None = None
    gpu_preflight: dict[str, object] | None = None
    try:
        used = inventory_storage_bytes(root)
        storage_preflight = {"limit_bytes": storage_limit_bytes, "used_bytes": used}
        if used > storage_limit_bytes:
            raise GuiActorCurrentSourceError("storage inventory exceeds the configured cap")

        stage = "profile"
        profile = load_gui_actor_profile(_profile_path(project))
        stage = "gpu_preflight"
        gpu_preflight = _gpu_preflight()
        stage = "current_source_identity"
        receipt = verify_current_source_identity(profile, root, project_root=project)
        stage = "runtime"
        runtime_python = Path(str(receipt["runtime_python"]))
        if not runtime_python.is_file():
            raise GuiActorCurrentSourceError("verified runtime Python is unavailable")

        stage = "invocation"
        invocation_nonce = uuid4().hex
        invocation = {
            "contract_version": "gui_actor_current_source_invocation_v1",
            "invocation_nonce": invocation_nonce,
            "image_path": str(image),
            "image_sha256": image_digest,
            "target_text": target_text,
            "target_sha256": target_digest,
            "artifact_root": str(root),
            "profile": profile,
            "native_profile": {
                "contract_version": "goal_binding_native_profile_v1",
                "provider_id": GUI_ACTOR_PROVIDER,
                "native_shape": "gui_actor_topk_points_v1",
                "coordinate_space": "normalized_0_1",
            },
            "current_source_receipt": receipt,
        }
        invocation_path = output / "invocation.json"
        child_result_path = output / "child-result.json"
        stdout_path = output / "child.stdout.utf8"
        stderr_path = output / "child.stderr.utf8"
        _write_json(invocation_path, invocation)
        command = [
            str(runtime_python),
            "-B",
            str(project / "scripts/run_learning_gui_actor_once.py"),
            "--child",
            "--invocation",
            str(invocation_path),
            "--child-result",
            str(child_result_path),
        ]
        stage = "child_start"
        child = _run_exact_child(
            command=command,
            cwd=project,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            timeout_seconds=int(profile["timeout_seconds"]),
        )
        if child.get("exit_code") != 0:
            stage = "child_exit"
            raise GuiActorCurrentSourceError("GUIActor child exited unsuccessfully")

        stage = "child_response"
        response = _read_child_result(child_result_path)
        expected_fields = {
            "contract_version",
            "invocation_nonce",
            "image_sha256",
            "target_sha256",
            "raw_output_utf8",
            "provider_id",
            "native_profile",
            "current_source_receipt",
        }
        if (
            set(response) != expected_fields
            or response.get("contract_version") != "gui_actor_current_source_child_result_v1"
            or response.get("invocation_nonce") != invocation_nonce
            or response.get("image_sha256") != image_digest
            or response.get("target_sha256") != target_digest
        ):
            raise GuiActorCurrentSourceError("GUIActor child nonce or input provenance differs")
        raw = response.get("raw_output_utf8")
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > int(profile["max_output_bytes"]):
            raise GuiActorCurrentSourceError("GUIActor child raw output is invalid")
        if (
            response.get("provider_id") != GUI_ACTOR_PROVIDER
            or response.get("native_profile") != invocation["native_profile"]
            or response.get("current_source_receipt") != receipt
        ):
            raise GuiActorCurrentSourceError("GUIActor child source provenance differs")

        stage = "trace_verification"
        result = {
            "contract_version": "gui_actor_current_source_result_v1",
            "raw_output_utf8": raw,
            "native_output_ref": {
                "id": f"gui-actor-current-source/{invocation_nonce}",
                "sha256": sha256(raw.encode("utf-8")).hexdigest(),
            },
            "source_score": None,
            "provider_id": GUI_ACTOR_PROVIDER,
            "native_profile": invocation["native_profile"],
            "current_source_receipt": receipt,
            "image_sha256": image_digest,
            "target_sha256": target_digest,
            "storage_preflight": storage_preflight,
            "gpu_preflight": gpu_preflight,
            "child_exit_code": child["exit_code"],
            "cleanup": child["cleanup"],
            "stdout_trace": _trace(stdout_path),
            "stderr_trace": _trace(stderr_path),
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        }
        _write_json(output / "result.json", result)
        return result
    except GuiActorCurrentSourceError as error:
        timeout_child = getattr(error, "child", None)
        if isinstance(timeout_child, Mapping):
            child = timeout_child
            if stage == "child_start":
                stage = "child_timeout"
        _write_failure_result(
            output=output,
            stage=stage,
            error=error,
            child=child,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            image_sha256=image_digest,
            target_sha256=target_digest,
            storage_preflight=storage_preflight,
            gpu_preflight=gpu_preflight,
        )
        raise
    except KeyboardInterrupt as error:
        interrupted_child = getattr(error, "child", None)
        if isinstance(interrupted_child, Mapping):
            child = interrupted_child
        _write_failure_result(
            output=output,
            stage="interrupted",
            error=error,
            child=child,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            image_sha256=image_digest,
            target_sha256=target_digest,
            storage_preflight=storage_preflight,
            gpu_preflight=gpu_preflight,
        )
        raise


def _checkpoint_directory(artifact_root: Path, receipt: Mapping[str, object]) -> Path:
    """模型角色指向已校验分片，Transformers 则读取其配置所在目录。"""
    shard = _under(artifact_root, receipt["verified_roles"]["model"]["relative_path"], label="checkpoint shard")
    checkpoint = shard.parent
    if not shard.is_file() or not (checkpoint / "config.json").is_file():
        raise GuiActorCurrentSourceError("verified checkpoint directory is unavailable")
    return checkpoint


def run_gui_actor_child(*, invocation_path: Path, child_result_path: Path) -> None:
    """仅允许受管当前父进程调用的子进程入口。"""
    invocation = _read_json(Path(invocation_path), label="GUIActor invocation")
    required = {"contract_version", "invocation_nonce", "image_path", "image_sha256", "target_text", "target_sha256", "artifact_root", "profile", "native_profile", "current_source_receipt"}
    if set(invocation) != required or invocation.get("contract_version") != "gui_actor_current_source_invocation_v1" or not isinstance(invocation.get("profile"), Mapping):
        raise GuiActorCurrentSourceError("GUIActor child invocation is invalid")
    profile = dict(invocation["profile"])
    receipt = invocation["current_source_receipt"]
    if not isinstance(receipt, Mapping) or receipt.get("contract_version") != CURRENT_SOURCE_CONTRACT or receipt.get("source_binding") != "current_source_external_v1":
        raise GuiActorCurrentSourceError("GUIActor child current-source receipt is invalid")
    image = Path(str(invocation["image_path"])).resolve()
    target = invocation.get("target_text")
    if not image.is_file() or not isinstance(target, str) or _sha256_file(image) != invocation.get("image_sha256") or sha256(target.encode("utf-8")).hexdigest() != invocation.get("target_sha256"):
        raise GuiActorCurrentSourceError("GUIActor child input changed")
    from scripts.model_servers.goal_binding_provider_runtimes import run_gui_actor
    try:
        import torch
        import transformers
        from gui_actor import constants, inference, modeling_qwen25vl
    except ImportError as exc:
        raise GuiActorCurrentSourceError("GUIActor runtime dependencies are unavailable") from exc
    checkpoint = _checkpoint_directory(Path(str(invocation["artifact_root"])), receipt)
    processor = transformers.AutoProcessor.from_pretrained(checkpoint, local_files_only=True)
    model = modeling_qwen25vl.Qwen2_5_VLForConditionalGenerationWithPointer.from_pretrained(checkpoint, local_files_only=True, torch_dtype=torch.bfloat16, device_map="cuda:0", attn_implementation="sdpa").eval()
    dependencies = {"model": model, "processor": processor, "tokenizer": processor.tokenizer, "torch": torch, "inference": inference.inference, "grounding_system_message": constants.grounding_system_message}
    canonical = run_gui_actor(image_path=image, goal=target, profile=profile, artifact_root=Path(str(invocation["artifact_root"])), dependencies=dependencies)
    raw = canonical.get("raw_native_output") if isinstance(canonical, Mapping) else None
    if not isinstance(raw, str):
        raise GuiActorCurrentSourceError("canonical GUIActor runner returned invalid raw output")
    _write_json(Path(child_result_path), {"contract_version": "gui_actor_current_source_child_result_v1", "invocation_nonce": invocation["invocation_nonce"], "image_sha256": invocation["image_sha256"], "target_sha256": invocation["target_sha256"], "raw_output_utf8": raw, "provider_id": GUI_ACTOR_PROVIDER, "native_profile": invocation["native_profile"], "current_source_receipt": receipt})


__all__ = ["DEFAULT_STORAGE_LIMIT_BYTES", "GuiActorCurrentSourceError", "inventory_storage_bytes", "load_gui_actor_profile", "run_gui_actor_child", "run_gui_actor_once", "verify_current_source_identity"]
