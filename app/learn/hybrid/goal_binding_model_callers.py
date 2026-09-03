"""Lazy, fail-closed actual caller seam for replaceable goal-binding models."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from hashlib import sha256
import json
import math
from pathlib import Path
import socket
import sys
from typing import Any

from app.learn.hybrid.goal_binding_ab import GoalBindingArm, adapt_incumbent_candidate_index, make_native_point_adapter

_PROFILE_VERSION = "goal_binding_model_profile_v1"
_NOT_ACQUIRED = "not_acquired"
_HEX = frozenset("0123456789abcdef")
_FIELDS = frozenset({"contract_version", "profile_id", "arm_id", "provider_id", "model_id", "repository_id", "upstream_revision", "artifacts", "artifact_manifest", "runtime", "dtype_or_quantization", "native_output", "coordinate_space", "preprocessing", "max_output_bytes", "timeout_seconds", "license", "artifact_is_authorization", "execute_binding_enabled", "final_submit_forbidden"})
_CLEANUP_FIELDS = frozenset({"contract_version", "provider", "verified", "cleanup_status", "owned_processes", "provider_processes_after", "helper_processes_after", "orphan_descendant_pids", "active_listeners_after", "lease_files_after"})
_MODEL_TEST_ROOT = Path(r"E:\模型测试")
_MAX_REQUEST_BYTES = 1024 * 1024


def _closed_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("goal-binding profile has duplicate JSON keys")
        result[key] = value
    return result


def _sha256(value: bytes) -> str:
    return sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _HEX


def _text(value: object, field: str, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{field} is invalid")
    return value


def _relative(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or Path(value).is_absolute() or ".." in Path(value).parts:
        raise ValueError(f"{field} must be a safe relative path")
    return value.replace("\\", "/")


def _revision(value: object) -> str:
    if value == _NOT_ACQUIRED:
        return _NOT_ACQUIRED
    if not isinstance(value, str) or len(value) != 40 or set(value) > _HEX:
        raise ValueError("profile upstream_revision must be an immutable commit or not_acquired")
    return value


def _artifact(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != {"role", "relative_path", "sha256", "bytes"}:
        raise ValueError("profile artifact is not closed")
    role = _text(value.get("role"), "profile artifact role", 64)
    path = _relative(value.get("relative_path"), "profile artifact path")
    digest, size = value.get("sha256"), value.get("bytes")
    if not ((digest == _NOT_ACQUIRED and size == _NOT_ACQUIRED) or (_is_sha256(digest) and isinstance(size, int) and not isinstance(size, bool) and size >= 0)):
        raise ValueError("profile artifact hash and bytes must both be verified or not_acquired")
    return {"role": role, "relative_path": path, "sha256": digest, "bytes": size}


def _validate_profile(profile: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(profile, Mapping) or set(profile) != _FIELDS:
        raise ValueError("goal-binding profile is not closed")
    if profile.get("contract_version") != _PROFILE_VERSION:
        raise ValueError("goal-binding profile contract version is invalid")
    result: dict[str, object] = {"contract_version": _PROFILE_VERSION}
    for field in ("profile_id", "arm_id", "provider_id", "model_id", "repository_id", "dtype_or_quantization", "coordinate_space", "license"):
        result[field] = _text(profile.get(field), f"profile {field}")
    result["upstream_revision"] = _revision(profile.get("upstream_revision"))
    artifacts = profile.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("profile artifacts are invalid")
    result["artifacts"] = [_artifact(item) for item in artifacts]
    roles = [str(item["role"]) for item in result["artifacts"]]
    if len(roles) != len(set(roles)):
        raise ValueError("profile artifact roles are duplicated")
    manifest = profile.get("artifact_manifest")
    if not isinstance(manifest, Mapping) or set(manifest) != {"status", "relative_path", "sha256"}:
        raise ValueError("profile artifact manifest is not closed")
    status, digest = manifest.get("status"), manifest.get("sha256")
    if not ((status == _NOT_ACQUIRED and digest == _NOT_ACQUIRED) or (status == "verified" and _is_sha256(digest))):
        raise ValueError("profile artifact manifest is invalid")
    result["artifact_manifest"] = {"status": status, "relative_path": _relative(manifest.get("relative_path"), "profile artifact manifest path"), "sha256": digest}
    runtime = profile.get("runtime")
    if not isinstance(runtime, Mapping) or set(runtime) != {"kind", "isolated_runtime_path", "sha256", "worker", "entrypoint"}:
        raise ValueError("profile runtime is not closed")
    runtime_hash = runtime.get("sha256")
    if runtime_hash != _NOT_ACQUIRED and not _is_sha256(runtime_hash):
        raise ValueError("profile runtime hash is invalid")
    result["runtime"] = {"kind": _text(runtime.get("kind"), "profile runtime kind", 64), "isolated_runtime_path": _relative(runtime.get("isolated_runtime_path"), "profile isolated runtime path"), "sha256": runtime_hash, "worker": _relative(runtime.get("worker"), "profile worker"), "entrypoint": _text(runtime.get("entrypoint"), "profile runtime entrypoint", 160)}
    native = profile.get("native_output")
    if not isinstance(native, Mapping) or set(native) != {"kind", "raw_format"}:
        raise ValueError("profile native output is not closed")
    kind = _text(native.get("kind"), "profile native output kind", 96)
    if kind not in {"qwen_goal_binding_array_v1", "ui_venus_point_v1", "gui_actor_topk_points_v1", "phi_ground_any_v1", "gguf_bare_point_pair_v1"}:
        raise ValueError("profile native output kind is unsupported")
    result["native_output"] = {"kind": kind, "raw_format": _text(native.get("raw_format"), "profile native raw format", 64)}
    preprocessing = profile.get("preprocessing")
    if not isinstance(preprocessing, Mapping) or set(preprocessing) != {"identity", "source_revision", "sha256"}:
        raise ValueError("profile preprocessing is not closed")
    pre_hash = preprocessing.get("sha256")
    if pre_hash != _NOT_ACQUIRED and not _is_sha256(pre_hash):
        raise ValueError("profile preprocessing hash is invalid")
    result["preprocessing"] = {"identity": _text(preprocessing.get("identity"), "profile preprocessing identity", 160), "source_revision": _text(preprocessing.get("source_revision"), "profile preprocessing source revision", 160), "sha256": pre_hash}
    for field in ("max_output_bytes", "timeout_seconds"):
        value = profile.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"profile {field} is invalid")
        result[field] = value
    if profile.get("artifact_is_authorization") is not False or profile.get("execute_binding_enabled") is not False or profile.get("final_submit_forbidden") is not True:
        raise ValueError("goal-binding profile must be non-authorizing")
    result.update({"artifact_is_authorization": False, "execute_binding_enabled": False, "final_submit_forbidden": True})
    native_kind = result["native_output"]["kind"]  # type: ignore[index]
    expected_entrypoint = {
        "qwen_goal_binding_array_v1": "scripts.model_servers.goal_binding_provider_runtimes:run_llama_cpp",
        "ui_venus_point_v1": "scripts.model_servers.goal_binding_provider_runtimes:run_ui_venus",
        "gui_actor_topk_points_v1": "scripts.model_servers.goal_binding_provider_runtimes:run_gui_actor",
        "phi_ground_any_v1": "scripts.model_servers.goal_binding_provider_runtimes:run_phi_ground_any",
        "gguf_bare_point_pair_v1": "scripts.model_servers.goal_binding_provider_runtimes:run_llama_cpp",
    }[native_kind]
    expected_runtime_kind = {
        "qwen_goal_binding_array_v1": "llama_cpp",
        "ui_venus_point_v1": "transformers",
        "gui_actor_topk_points_v1": "gui_actor_official_runtime",
        "phi_ground_any_v1": "vllm",
        "gguf_bare_point_pair_v1": "llama_cpp",
    }[native_kind]
    if (
        result["runtime"]["worker"] != "scripts/model_servers/goal_binding_transformers_worker.py"  # type: ignore[index]
        or result["runtime"]["entrypoint"] != expected_entrypoint  # type: ignore[index]
        or result["runtime"]["kind"] != expected_runtime_kind  # type: ignore[index]
    ):
        raise ValueError("profile runtime worker or executable entrypoint is invalid")
    role_set = set(roles)
    if native_kind == "gguf_bare_point_pair_v1" and not {"model", "mmproj", "runtime", "source", "preprocessing"} <= role_set:
        raise ValueError("GGUF profiles require model, mmproj, runtime, source, and preprocessing artifacts")
    if result["runtime"]["kind"] == "llama_cpp" and "mmproj" not in role_set:  # type: ignore[index]
        raise ValueError("llama.cpp profiles require a verified mmproj artifact")
    if native_kind != "gguf_bare_point_pair_v1" and not {"model", "runtime", "source", "preprocessing"} <= role_set:
        raise ValueError("goal-binding profile requires model, runtime, source, and preprocessing artifacts")
    if native_kind == "gui_actor_topk_points_v1" and result["model_id"] != "microsoft/GUI-Actor-3B-Qwen2.5-VL":
        raise ValueError("GUI-Actor model identity is invalid")
    if native_kind == "phi_ground_any_v1" and result["coordinate_space"] != "padded_canvas_0_10000":
        raise ValueError("Phi-Ground-Any coordinate identity is invalid")
    return result


def load_goal_binding_profile(path: Path) -> dict[str, object]:
    """Load only JSON metadata; never resolve artifacts or import a model runtime."""
    if not isinstance(path, Path) or path.suffix.casefold() != ".json":
        raise ValueError("goal-binding profile path must be a JSON Path")
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_closed_object)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("goal-binding profile is unreadable") from exc
    if not isinstance(value, Mapping):
        raise ValueError("goal-binding profile must be an object")
    return deepcopy(_validate_profile(value))


def _safe_under(root: Path, relative: str) -> Path:
    root = root.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("profile artifact escapes the supplied artifact directory")
    return path


def _verified(profile: Mapping[str, object], artifact_dir: Path) -> dict[str, object]:
    sealed = _validate_profile(profile)
    ref = sealed["artifact_manifest"]
    assert isinstance(ref, Mapping)
    if ref["status"] != "verified":
        raise ValueError("goal-binding artifacts are not acquired and verified")
    manifest_path = _safe_under(artifact_dir, str(ref["relative_path"]))
    try:
        raw = manifest_path.read_bytes()
        manifest = json.loads(raw.decode("utf-8"), object_pairs_hook=_closed_object)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("verified goal-binding artifact manifest is unreadable") from exc
    if _sha256(raw) != ref["sha256"] or not isinstance(manifest, Mapping) or set(manifest) != {"contract_version", "provider_id", "repo_id", "revision", "files", "artifact_is_authorization"}:
        raise ValueError("verified goal-binding artifact manifest is invalid")
    if manifest["contract_version"] != "model_test_artifact_manifest_v1" or manifest["provider_id"] != sealed["provider_id"] or manifest["repo_id"] != sealed["repository_id"] or manifest["revision"] != sealed["upstream_revision"] or manifest["artifact_is_authorization"] is not False or not isinstance(manifest["files"], list):
        raise ValueError("verified goal-binding artifact manifest identity mismatch")
    files: dict[str, Mapping[str, object]] = {}
    for item in manifest["files"]:
        if not isinstance(item, Mapping) or set(item) != {"relative_path", "bytes", "sha256"}:
            raise ValueError("verified goal-binding artifact manifest file is invalid")
        path = _relative(item["relative_path"], "verified artifact path")
        if path in files or not _is_sha256(item["sha256"]) or isinstance(item["bytes"], bool) or not isinstance(item["bytes"], int) or item["bytes"] < 0:
            raise ValueError("verified goal-binding artifact manifest file is invalid")
        files[path] = item
        local = _safe_under(artifact_dir, path)
        if not local.is_file() or local.stat().st_size != item["bytes"] or _sha256_file(local) != item["sha256"]:
            raise ValueError("verified goal-binding manifest file changed locally")
    for expected in sealed["artifacts"]:
        assert isinstance(expected, Mapping)
        found = files.get(str(expected["relative_path"]))
        if found is None or found["sha256"] != expected["sha256"] or found["bytes"] != expected["bytes"]:
            raise ValueError("verified goal-binding artifact evidence does not match profile")
    runtime = sealed["runtime"]
    assert isinstance(runtime, Mapping)
    runtime_artifact = next((item for item in sealed["artifacts"] if isinstance(item, Mapping) and item["role"] == "runtime"), None)
    if runtime_artifact is None or runtime["sha256"] != runtime_artifact["sha256"]:
        raise ValueError("profile runtime artifact identity is not verified")
    preprocessing = sealed["preprocessing"]
    assert isinstance(preprocessing, Mapping)
    preprocessing_artifact = next((item for item in sealed["artifacts"] if isinstance(item, Mapping) and item["role"] == "preprocessing"), None)
    source_artifact = next((item for item in sealed["artifacts"] if isinstance(item, Mapping) and item["role"] == "source"), None)
    if (
        sealed["upstream_revision"] == _NOT_ACQUIRED
        or runtime["sha256"] == _NOT_ACQUIRED
        or preprocessing["sha256"] == _NOT_ACQUIRED
        or preprocessing["source_revision"] == _NOT_ACQUIRED
        or preprocessing_artifact is None
        or preprocessing_artifact["sha256"] != preprocessing["sha256"]
        or source_artifact is None
        or source_artifact["sha256"] == _NOT_ACQUIRED
    ):
        raise ValueError("profile runtime, source, and preprocessing identities are not sealed")
    return sealed


def exact_process_identity(value: Mapping[str, object]) -> dict[str, int]:
    if not isinstance(value, Mapping) or set(value) != {"pid", "create_time_ns"}:
        raise ValueError("process identity is not exact")
    pid, created = value.get("pid"), value.get("create_time_ns")
    if any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in (pid, created)):
        raise ValueError("process identity is not exact")
    return {"pid": int(pid), "create_time_ns": int(created)}


def verified_no_process_cleanup_receipt(provider: str) -> dict[str, object]:
    _text(provider, "cleanup provider", 96)
    return {"contract_version": "simple_native_provider_cleanup_v1", "provider": provider, "verified": True, "cleanup_status": "verified", "owned_processes": [], "provider_processes_after": [], "helper_processes_after": [], "orphan_descendant_pids": [], "active_listeners_after": [], "lease_files_after": []}


def cleanup_receipt_is_clean(receipt: Mapping[str, object]) -> bool:
    lists = ("owned_processes", "provider_processes_after", "helper_processes_after", "orphan_descendant_pids", "active_listeners_after", "lease_files_after")
    if not isinstance(receipt, Mapping) or set(receipt) not in (_CLEANUP_FIELDS, _CLEANUP_FIELDS | {"cleanup_observations"}):
        return False
    observations = receipt.get("cleanup_observations")
    evidence_valid = observations is None or (
        isinstance(observations, list)
        and bool(observations)
        and all(isinstance(item, Mapping) and item.get("verified") is True for item in observations)
    )
    return receipt.get("contract_version") == "simple_native_provider_cleanup_v1" and isinstance(receipt.get("provider"), str) and bool(receipt.get("provider")) and receipt.get("verified") is True and receipt.get("cleanup_status") == "verified" and evidence_valid and all(receipt.get(field) == [] for field in lists)


def _reserve_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _observe_gpu_cleanup(owned_pids: set[int]) -> dict[str, object]:
    from app.core.gpu_resources import _gpu_snapshot

    snapshot = _gpu_snapshot()
    processes = snapshot.get("compute_processes") if isinstance(snapshot, Mapping) else None
    if snapshot.get("available") is not True or not isinstance(processes, list):
        return {
            "status": "unavailable",
            "reason": snapshot.get("reason") if isinstance(snapshot, Mapping) else "invalid_gpu_observation",
            "owners_after": [],
        }
    owners = [deepcopy(item) for item in processes if isinstance(item, Mapping) and item.get("pid") in owned_pids]
    return {"status": "verified", "reason": None, "owners_after": owners}


class _ProviderWorkerFailure(RuntimeError):
    def __init__(self, message: str, *, cleanup_evidence: Mapping[str, object]) -> None:
        super().__init__(message)
        self.cleanup_evidence = deepcopy(dict(cleanup_evidence))


def _call_cleanup_evidence(
    *, identity: Mapping[str, object] | None, observation: Mapping[str, object],
    gpu: Mapping[str, object], scope_name: str, error: str | None,
    stdout_bytes: int, stderr_bytes: int,
) -> dict[str, object]:
    provider_after = list(observation.get("member_identities_after") or [])
    orphan_pids = list(observation.get("member_pids_after") or [])
    listeners = list(observation.get("active_listeners_after") or [])
    leases = [str(observation["pid_file_after"])] if observation.get("pid_file_after") else []
    gpu_owners = list(gpu.get("owners_after") or [])
    verified = (
        identity is not None
        and observation.get("cleanup_status") == "verified"
        and gpu.get("status") == "verified"
        and not provider_after
        and not orphan_pids
        and not listeners
        and not leases
        and not gpu_owners
    )
    return {
        "contract_version": "goal_binding_provider_call_cleanup_v1",
        "verified": verified,
        "worker_process_identity": deepcopy(dict(identity)) if identity is not None else None,
        "job_scope_name": scope_name,
        "process_scope_cleanup": deepcopy(dict(observation)),
        "provider_processes_after": provider_after,
        "helper_processes_after": [],
        "orphan_descendant_pids": orphan_pids,
        "active_listeners_after": listeners,
        "lease_files_after": leases,
        "gpu_observation": deepcopy(dict(gpu)),
        "gpu_owners_after": gpu_owners,
        "worker_stdout_bytes": stdout_bytes,
        "worker_stderr_bytes": stderr_bytes,
        "failure": error,
    }


def _resource_metrics_are_closed(value: object, *, request_bytes: int, timeout_seconds: int) -> bool:
    fields = {
        "latency_ms", "peak_vram_bytes", "peak_vram_status", "generation_tokens",
        "request_bytes", "provider_stdout_bytes", "provider_stderr_bytes", "timeout_seconds",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        return False
    latency, peak, tokens = value.get("latency_ms"), value.get("peak_vram_bytes"), value.get("generation_tokens")
    return (
        isinstance(latency, (int, float)) and not isinstance(latency, bool) and math.isfinite(float(latency)) and float(latency) >= 0
        and value.get("peak_vram_status") in {"measured", "unavailable"}
        and (peak is None or (isinstance(peak, int) and not isinstance(peak, bool) and peak >= 0))
        and ((value.get("peak_vram_status") == "measured") == (peak is not None))
        and (tokens is None or (isinstance(tokens, int) and not isinstance(tokens, bool) and tokens >= 0))
        and value.get("request_bytes") == request_bytes
        and value.get("timeout_seconds") == timeout_seconds
        and all(isinstance(value.get(field), int) and not isinstance(value.get(field), bool) and value[field] >= 0 for field in ("provider_stdout_bytes", "provider_stderr_bytes"))
    )


def native_adapter_for_profile(profile: Mapping[str, object]) -> Callable[..., object]:
    from app.learn.hybrid.goal_binding_native_adapters import parse_gguf_grounding, parse_gui_actor_top1, parse_phi_ground_any, parse_ui_venus_point
    native = profile.get("native_output")
    if not isinstance(native, Mapping):
        raise ValueError("profile native output is unavailable")
    result = {"ui_venus_point_v1": parse_ui_venus_point, "gui_actor_topk_points_v1": parse_gui_actor_top1, "phi_ground_any_v1": parse_phi_ground_any, "gguf_bare_point_pair_v1": parse_gguf_grounding}.get(native.get("kind"))
    if result is None:
        raise ValueError("profile has no native point adapter")
    return result


def _adapter_profile(profile: Mapping[str, object]) -> dict[str, object]:
    native = profile["native_output"]
    assert isinstance(native, Mapping)
    if native["kind"] == "phi_ground_any_v1":
        return {"contract_version": "goal_binding_native_profile_v1", "provider_id": profile["provider_id"], "native_shape": "phi_ground_any_v1", "coordinate_space": "capture_pixels", "image_size": [1680, 1008], "output_mode": "point"}
    return {"contract_version": "goal_binding_native_profile_v1", "provider_id": profile["provider_id"], "native_shape": native["kind"], "coordinate_space": profile["coordinate_space"]}


def _short_goal(request: Mapping[str, object]) -> str:
    goal = request.get("goal")
    if isinstance(goal, str):
        return _text(goal.strip(), "goal", 512)
    if not isinstance(goal, Mapping):
        raise ValueError("goal-binding caller requires one short goal")
    return f"{_text(goal.get('semantic_role'), 'goal role', 96)}: {_text(goal.get('semantic_label'), 'goal label', 384)}"


def _reject_provider_input(request: Mapping[str, object]) -> None:
    if any(key in request for key in {"gold", "holdout", "candidate_mapping", "authority", "execution", "execute_binding", "action_candidates"}):
        raise ValueError("goal-binding provider request contains forbidden authority or evaluation data")


def _invoke_provider_worker(
    *, profile: Mapping[str, object], artifact_dir: Path, image_path: Path, goal: str,
    incumbent_request: Mapping[str, object] | None = None,
    incumbent_projection: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Run one worker only after a verified profile selects its isolated runtime."""
    runtime = profile["runtime"]
    assert isinstance(runtime, Mapping)
    runtime_artifact = next(item for item in profile["artifacts"] if isinstance(item, Mapping) and item["role"] == "runtime")
    runtime_executable = _safe_under(artifact_dir, str(runtime_artifact["relative_path"]))
    worker = Path(__file__).resolve().parents[3] / str(runtime["worker"])
    provider_runtime = worker.with_name("goal_binding_provider_runtimes.py")
    if not runtime_executable.is_file() or not worker.is_file() or not provider_runtime.is_file():
        raise OSError("provider-isolated runtime is unavailable")
    runtime_kind = str(runtime.get("kind") or "")
    worker_python = Path(sys.executable).resolve() if runtime_kind == "llama_cpp" else runtime_executable
    if not worker_python.is_file():
        raise OSError("provider worker Python is unavailable")
    from app.learn.hybrid.windows_process_scope import WindowsProcessScope, benchmark_worker_scope_name_v1, observe_process_scope_cleanup, spawn_process_in_scope
    image_bytes = image_path.read_bytes()
    from PIL import Image
    with Image.open(image_path) as image: width, height = image.size
    seed = _sha256(image_bytes + goal.encode("utf-8"))
    work = artifact_dir / "goal-binding-native-traces" / seed
    work.mkdir(parents=True, exist_ok=False)
    screenshot = (work / "screenshot").with_suffix(image_path.suffix)
    screenshot.write_bytes(image_bytes)
    identity_path, request, stdout, stderr = work / "parent-identity.json", work / "request.json", work / "stdout.json", work / "stderr.txt"
    listener_port = _reserve_loopback_port() if runtime_kind == "llama_cpp" else None
    payload: dict[str, object] = {
        "image_path": str(screenshot), "goal": goal, "profile": deepcopy(dict(profile)),
        "screenshot": {"sha256": _sha256(image_bytes), "width": width, "height": height, "capture_id": f"capture/{_sha256(image_bytes)}"},
        "parent_identity_path": str(identity_path), "artifact_root": str(artifact_dir.resolve()),
        "code_identity": {
            "worker_sha256": _sha256_file(worker),
            "provider_runtime_sha256": _sha256_file(provider_runtime),
            "worker_python_sha256": _sha256_file(worker_python),
        },
    }
    if listener_port is not None:
        payload["listener_port"] = listener_port
    if incumbent_request is not None or incumbent_projection is not None:
        if runtime_kind != "llama_cpp" or incumbent_request is None or incumbent_projection is None:
            raise ValueError("incumbent request exception is invalid for this provider")
        payload["incumbent_request"] = deepcopy(dict(incumbent_request))
        payload["incumbent_projection"] = deepcopy(dict(incumbent_projection))
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(body) > _MAX_REQUEST_BYTES:
        raise ValueError("provider worker request exceeds the 1 MiB bound")
    request.write_bytes(body)
    scope_name = benchmark_worker_scope_name_v1(authority_kind="test_only", run_id=seed, stage="goal_binding", operation_id=str(profile["provider_id"]), worker_id=str(profile["profile_id"]), payload_sha256=_sha256(body), execution_nonce=_sha256((seed + goal).encode("utf-8"))[:32])
    scope = WindowsProcessScope(scope_name, create=True)
    observation: Mapping[str, object] | None = None
    identity: dict[str, int] | None = None
    failure: BaseException | None = None
    try:
        def before_resume(value: Mapping[str, object]) -> None:
            nonlocal identity
            identity = exact_process_identity(value)
            identity_path.write_text(json.dumps(identity, sort_keys=True), encoding="utf-8")
        with stdout.open("wb") as output_handle, stderr.open("wb") as error_handle:
            process = spawn_process_in_scope([str(worker_python), str(worker), "--execute", "--request-json", str(request)], scope_name=scope_name, cwd=artifact_dir, stdout=output_handle, stderr=error_handle, before_resume=before_resume)
            try:
                code = process.wait(timeout=float(profile["timeout_seconds"]))
            except BaseException as exc:
                process.kill()
                if type(exc).__name__ == "TimeoutExpired": raise TimeoutError("goal-binding provider worker timed out") from exc
                raise
            finally:
                process.close()
            if code != 0: raise OSError(stderr.read_text(encoding="utf-8", errors="strict")[:4096] or "provider worker exited nonzero")
    except BaseException as exc:
        failure = exc
    finally:
        scope.close()
        observation = observe_process_scope_cleanup(
            scope_name, terminate=True,
            listener_ports=([listener_port] if listener_port is not None else []),
            stable_zero_observations=3,
        )
    owned_pids = {identity["pid"]} if identity is not None else set()
    for item in observation.get("observed_member_pids_before") or []:
        if isinstance(item, int):
            owned_pids.add(item)
    if stdout.exists() and stdout.stat().st_size <= int(profile["max_output_bytes"]):
        try:
            preliminary = json.loads(stdout.read_text(encoding="utf-8"), object_pairs_hook=_closed_object)
            lineage = preliminary.get("request_lineage") if isinstance(preliminary, Mapping) else None
            child_cleanup = lineage.get("child_cleanup") if isinstance(lineage, Mapping) else None
            child_pid = child_cleanup.get("child_pid") if isinstance(child_cleanup, Mapping) else None
            if isinstance(child_pid, int) and not isinstance(child_pid, bool) and child_pid > 0:
                owned_pids.add(child_pid)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            pass
    gpu = _observe_gpu_cleanup(owned_pids)
    cleanup_evidence = _call_cleanup_evidence(
        identity=identity, observation=observation, gpu=gpu, scope_name=scope_name,
        error=str(failure) if failure is not None else None,
        stdout_bytes=stdout.stat().st_size if stdout.exists() else 0,
        stderr_bytes=stderr.stat().st_size if stderr.exists() else 0,
    )
    cleanup_path = work / "cleanup.json"
    cleanup_bytes = json.dumps(cleanup_evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    cleanup_path.write_bytes(cleanup_bytes)
    cleanup_ref = {"id": f"cleanup/{seed}", "sha256": _sha256(cleanup_bytes)}
    if failure is not None:
        raise _ProviderWorkerFailure(str(failure), cleanup_evidence=cleanup_evidence) from failure
    if cleanup_evidence["verified"] is not True:
        raise _ProviderWorkerFailure("provider worker cleanup has unresolved process, listener, lease, or GPU evidence", cleanup_evidence=cleanup_evidence)
    if (
        identity is None
        or not stdout.is_file()
        or stdout.stat().st_size > int(profile["max_output_bytes"])
        or stderr.stat().st_size > int(profile["max_output_bytes"])
    ):
        raise _ProviderWorkerFailure("provider worker output is unavailable or exceeds profile bound", cleanup_evidence=cleanup_evidence)
    try:
        envelope = json.loads(stdout.read_text(encoding="utf-8"), object_pairs_hook=_closed_object)
    except (OSError, json.JSONDecodeError) as exc:
        raise _ProviderWorkerFailure("provider worker output is invalid", cleanup_evidence=cleanup_evidence) from exc
    expected = {"contract_version", "profile_identity", "raw_native_output", "raw_native_output_sha256", "parsed_native", "resource_metrics", "worker_process_identity", "request_lineage"}
    runtime = profile["runtime"]
    preprocessing = profile["preprocessing"]
    native = profile["native_output"]
    assert isinstance(runtime, Mapping) and isinstance(preprocessing, Mapping) and isinstance(native, Mapping)
    identity_fields = {"profile_id": profile["profile_id"], "preprocessing_sha256": preprocessing["sha256"], "runtime_sha256": runtime["sha256"], "native_output_kind": native["kind"]}
    metrics = envelope.get("resource_metrics") if isinstance(envelope, Mapping) else None
    lineage = envelope.get("request_lineage") if isinstance(envelope, Mapping) else None
    child_cleanup = lineage.get("child_cleanup") if isinstance(lineage, Mapping) else None
    child_valid = child_cleanup is None
    if runtime_kind == "llama_cpp":
        child_valid = (
            isinstance(child_cleanup, Mapping)
            and child_cleanup.get("status") == "verified"
            and isinstance(child_cleanup.get("child_pid"), int)
            and child_cleanup.get("listener") == {"host": "127.0.0.1", "port": listener_port}
            and child_cleanup.get("termination") in {"terminated", "killed", "exited"}
        )
    if not isinstance(envelope, Mapping) or set(envelope) != expected or envelope.get("contract_version") != "goal_binding_native_trace_v1" or envelope.get("profile_identity") != identity_fields or not isinstance(envelope.get("raw_native_output"), str) or envelope.get("raw_native_output_sha256") != _sha256(envelope["raw_native_output"].encode("utf-8")) or exact_process_identity(envelope["worker_process_identity"]) != identity or not isinstance(lineage, Mapping) or lineage.get("screenshot_sha256") != payload["screenshot"]["sha256"] or lineage.get("capture_id") != payload["screenshot"]["capture_id"] or lineage.get("screenshot_dimensions") != [width, height] or lineage.get("code_identity") != payload["code_identity"] or not _resource_metrics_are_closed(metrics, request_bytes=len(body), timeout_seconds=int(profile["timeout_seconds"])) or not child_valid:
        raise _ProviderWorkerFailure("provider worker envelope is invalid", cleanup_evidence=cleanup_evidence)
    closed = deepcopy(dict(envelope))
    closed["cleanup_evidence"] = cleanup_evidence
    closed["cleanup_ref"] = cleanup_ref
    return closed


def make_goal_binding_arm(*, profile: Mapping[str, object], artifact_dir: Path) -> GoalBindingArm:
    sealed = _verified(profile, Path(artifact_dir))
    native = sealed["native_output"]
    assert isinstance(native, Mapping)
    adapt = adapt_incumbent_candidate_index if native["kind"] == "qwen_goal_binding_array_v1" else make_native_point_adapter(native_adapter_for_profile(sealed), _adapter_profile(sealed))
    state: dict[str, object] = {"blocked": False, "cleanup_observations": []}
    def call(image_path: Path, request: Mapping[str, object]) -> object:
        if state["blocked"]:
            raise RuntimeError("goal-binding provider is blocked by unresolved cleanup residue")
        if not isinstance(image_path, Path) or not image_path.is_file() or not isinstance(request, Mapping):
            raise ValueError("goal-binding request is invalid")
        _reject_provider_input(request)
        try:
            incumbent_request = request.get("incumbent_runtime_request")
            incumbent_projection = request.get("incumbent_projection")
            if sealed["provider_id"] == "qwen3_vl_8b_q4_k_m":
                if not isinstance(incumbent_request, Mapping) or not isinstance(incumbent_projection, Mapping):
                    raise ValueError("incumbent frozen request and projection are required")
            elif incumbent_request is not None or incumbent_projection is not None or "candidates" in request:
                raise ValueError("challenger provider input contains candidate data")
            envelope = _invoke_provider_worker(
                profile=sealed, artifact_dir=Path(artifact_dir), image_path=image_path,
                goal=_short_goal(request),
                incumbent_request=incumbent_request if isinstance(incumbent_request, Mapping) else None,
                incumbent_projection=incumbent_projection if isinstance(incumbent_projection, Mapping) else None,
            )
            observations = state["cleanup_observations"]
            assert isinstance(observations, list)
            cleanup_evidence = envelope.get("cleanup_evidence")
            if not isinstance(cleanup_evidence, Mapping):
                raise RuntimeError("provider call omitted actual cleanup evidence")
            observations.append(deepcopy(dict(cleanup_evidence)))
        except BaseException as exc:
            state["blocked"] = True
            evidence = getattr(exc, "cleanup_evidence", None)
            observations = state["cleanup_observations"]
            assert isinstance(observations, list)
            if isinstance(evidence, Mapping):
                observations.append(deepcopy(dict(evidence)))
            raise
        return deepcopy(envelope)
    def cleanup() -> Mapping[str, object]:
        observations = state["cleanup_observations"]
        assert isinstance(observations, list)
        provider_after = [item for evidence in observations if isinstance(evidence, Mapping) for item in evidence.get("provider_processes_after", [])]
        helper_after = [item for evidence in observations if isinstance(evidence, Mapping) for item in evidence.get("helper_processes_after", [])]
        orphan_pids = [item for evidence in observations if isinstance(evidence, Mapping) for item in evidence.get("orphan_descendant_pids", [])]
        listeners = [item for evidence in observations if isinstance(evidence, Mapping) for item in evidence.get("active_listeners_after", [])]
        leases = [item for evidence in observations if isinstance(evidence, Mapping) for item in evidence.get("lease_files_after", [])]
        gpu_owners = [item for evidence in observations if isinstance(evidence, Mapping) for item in evidence.get("gpu_owners_after", [])]
        verified = bool(observations) and state["blocked"] is False and all(
            isinstance(item, Mapping) and item.get("verified") is True for item in observations
        ) and not any((provider_after, helper_after, orphan_pids, listeners, leases, gpu_owners))
        return {
            "contract_version": "simple_native_provider_cleanup_v1",
            "provider": str(sealed["provider_id"]),
            "verified": verified,
            "cleanup_status": "verified" if verified else "failed",
            "owned_processes": [*provider_after, *helper_after, *gpu_owners],
            "provider_processes_after": provider_after,
            "helper_processes_after": helper_after,
            "orphan_descendant_pids": orphan_pids,
            "active_listeners_after": listeners,
            "lease_files_after": leases,
            "cleanup_observations": deepcopy(observations),
        }
    return GoalBindingArm(arm_id=str(sealed["arm_id"]), provider_id=str(sealed["provider_id"]), call=call, adapt=adapt, cleanup=cleanup)


def probe_goal_binding_profile(
    *, profile: Mapping[str, object], image_path: Path,
    artifact_dir: Path | None = None,
) -> dict[str, object]:
    arm = make_goal_binding_arm(profile=profile, artifact_dir=artifact_dir or _MODEL_TEST_ROOT)
    raw = arm.call(image_path, {"goal": "button: Open"})
    return {"contract_version": "goal_binding_profile_probe_v1", "provider_id": arm.provider_id, "raw_native_output": raw, "artifact_is_authorization": False, "contains_holdout": False, "candidate_mapping": None, "cleanup": arm.cleanup()}
