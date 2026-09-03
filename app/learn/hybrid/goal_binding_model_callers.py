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
import os
import time
import subprocess
import csv
from uuid import uuid4
from typing import Any

from app.learn.hybrid.goal_binding_ab import GoalBindingArm, adapt_incumbent_candidate_index, make_native_point_adapter
from app.learn.hybrid.model_test_storage import MODEL_TEST_ROOT

_PROFILE_VERSION = "goal_binding_model_profile_v1"
_NOT_ACQUIRED = "not_acquired"
_HEX = frozenset("0123456789abcdef")
_FIELDS = frozenset({"contract_version", "profile_id", "arm_id", "provider_id", "model_id", "repository_id", "upstream_revision", "artifacts", "artifact_manifest", "runtime", "dtype_or_quantization", "native_output", "coordinate_space", "preprocessing", "max_output_bytes", "timeout_seconds", "license", "artifact_is_authorization", "execute_binding_enabled", "final_submit_forbidden"})
_CLEANUP_FIELDS = frozenset({"contract_version", "provider", "verified", "cleanup_status", "owned_processes", "provider_processes_after", "helper_processes_after", "orphan_descendant_pids", "active_listeners_after", "lease_files_after"})
_MODEL_TEST_ROOT = MODEL_TEST_ROOT
_MAX_REQUEST_BYTES = 1024 * 1024
_MAX_SCREENSHOT_BYTES = 32 * 1024 * 1024
_MAX_SCREENSHOT_PIXELS = 32 * 1024 * 1024
_CLEANUP_TIMEOUT_SECONDS = 120.0


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


def _adapter_profile(profile: Mapping[str, object], *, image_size: tuple[int, int] | None = None) -> dict[str, object]:
    native = profile["native_output"]
    assert isinstance(native, Mapping)
    if native["kind"] == "phi_ground_any_v1":
        if image_size is None:
            raise ValueError("Phi adapter requires actual capture dimensions")
        return {"contract_version": "goal_binding_native_profile_v1", "provider_id": profile["provider_id"], "native_shape": "phi_ground_any_v1", "coordinate_space": "capture_pixels", "image_size": list(image_size), "output_mode": "point"}
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




def _worker_python(profile: Mapping[str, object], artifact_dir: Path) -> Path:
    if profile["runtime"]["kind"] == "llama_cpp":
        return Path(sys.executable).resolve()
    artifact = next(item for item in profile["artifacts"] if item["role"] == "runtime")
    return _safe_under(artifact_dir, artifact["relative_path"])


def _gpu_ownership_snapshot() -> dict[str, object]:
    from app.learn.hybrid.windows_process_scope import _identity_for_pid
    try:
        result = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,used_gpu_memory", "--format=csv,noheader,nounits"], capture_output=True, timeout=10, check=True)
        raw = result.stdout.decode("utf-8", errors="strict")
        owners = []
        for row in csv.reader(raw.splitlines()):
            if len(row) != 2:
                raise ValueError("GPU ownership observation shape is invalid")
            identity = _identity_for_pid(int(row[0].strip()))
            memory = row[1].strip()
            owners.append({**identity, "used_memory_mib": int(memory) if memory.isdigit() else None})
        return {"status": "verified", "owners": owners, "raw": raw}
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        return {"status": "unavailable", "owners": [], "reason": str(exc)}


def _resource_preflight(profile: Mapping[str, object]) -> Mapping[str, object]:
    from app.core.gpu_resources import build_model_resource_preflight, _known_model_pids
    if _known_model_pids():
        raise RuntimeError("benchmark/model GPU residue exists before provider arm")
    return build_model_resource_preflight(dict(profile))


class GoalBindingProviderSession:
    """每个 arm 延迟创建一个有界邮箱与精确进程域。"""

    def __init__(self, profile: Mapping[str, object], artifact_dir: Path, run_root: Path | None = None):
        self.profile, self.artifact_dir = deepcopy(dict(profile)), artifact_dir.resolve()
        self.session_id = uuid4().hex
        self.run_root = (run_root or (self.artifact_dir / "goal-binding-native-traces" / uuid4().hex)).resolve()
        arm_component = _sha256(str(profile["arm_id"]).encode("utf-8"))[:24]
        self.root = self.run_root / "arms" / arm_component / "native-session" / self.session_id
        self.lease_path = self.artifact_dir / "goal-binding-leases" / "gpu_vision.lock"
        self.scope = self.process = self.lease = None
        self.identity = None
        self.launcher_identity = None
        self.sequence = 0
        self.failure = None
        self.blocked = False
        self.receipt = None
        self.config = None
        self.baseline = None
        self.port = None
        self.runtime_state = None
        self.started_ns = time.time_ns()

    def _open(self):
        from app.learn.hybrid.windows_process_scope import WindowsProcessScope, benchmark_worker_scope_name_v1, spawn_process_in_scope
        from app.learn.recognition.uei.omniparser_shadow_adapter import ProcessResourceLeaseManager
        from scripts.model_servers.goal_binding_transformers_worker import write_json
        _verified(self.profile, self.artifact_dir)
        self.baseline = _gpu_ownership_snapshot()
        preflight = _resource_preflight(self.profile)
        if self.baseline.get("status") != "verified" or preflight.get("status") != "ready" or preflight.get("model_launch_allowed") is not True:
            raise RuntimeError("provider GPU/resource preflight is unavailable or contended")
        self.lease = ProcessResourceLeaseManager(root=self.lease_path.parent)("gpu_vision")
        if self.lease is None:
            raise RuntimeError("provider GPU lease unavailable or stale")
        self.root.mkdir(parents=True, exist_ok=False)
        for name in ("requests", "responses", "raw"):
            (self.root / name).mkdir()
        worker = Path(__file__).resolve().parents[3] / self.profile["runtime"]["worker"]
        python = _worker_python(self.profile, self.artifact_dir)
        code = {"worker_sha256": _sha256_file(worker), "provider_runtime_sha256": _sha256_file(worker.with_name("goal_binding_provider_runtimes.py")), "worker_python_sha256": _sha256_file(python)}
        self.port = _reserve_loopback_port() if self.profile["runtime"]["kind"] == "llama_cpp" else None
        profile_hash = _sha256(json.dumps(self.profile, sort_keys=True).encode("utf-8"))
        name = benchmark_worker_scope_name_v1(authority_kind="test_only", run_id=self.run_root.name, stage="goal_binding", operation_id=str(self.profile["arm_id"]), worker_id=str(self.profile["profile_id"]), payload_sha256=profile_hash, execution_nonce=self.session_id)
        self.config = {"contract_version": "goal_binding_provider_session_v1", "session_id": self.session_id, "run_id": self.run_root.name, "arm_id": self.profile["arm_id"], "session_root": str(self.root), "scope_name": name, "profile": self.profile, "artifact_root": str(self.artifact_dir), "code_identity": code, "listener_port": self.port}
        write_json(self.root / "session.json", self.config)
        self.config_sha = _sha256_file(self.root / "session.json")
        self.scope = WindowsProcessScope(name, create=True)
        def before_resume(identity):
            self.launcher_identity = exact_process_identity(identity)
            self.identity = self.launcher_identity
            write_json(self.root / "parent-identity.json", self.launcher_identity)
        env = dict(os.environ, PYTHONIOENCODING="utf-8", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME=name)
        with (self.root / "worker.stdout.bin").open("xb") as stdout, (self.root / "worker.stderr.bin").open("xb") as stderr:
            self.process = spawn_process_in_scope([str(python), str(worker), "--execute", "--session-json", str(self.root / "session.json")], scope_name=name, cwd=self.artifact_dir, stdout=stdout, stderr=stderr, env=env, before_resume=before_resume)
        ready = self._wait(self.root / "ready.json")
        from app.learn.hybrid.windows_process_scope import _identity_for_pid
        import psutil
        worker_identity = exact_process_identity(ready["worker_process_identity"])
        if set(ready) != {"session_sha256", "worker_process_identity", "launcher_process_identity", "runtime_state", "failure"} or ready["session_sha256"] != self.config_sha or ready["launcher_process_identity"] != self.launcher_identity or _identity_for_pid(worker_identity["pid"]) != worker_identity or worker_identity["pid"] not in self.scope.pids() or (worker_identity != self.launcher_identity and self.launcher_identity["pid"] not in {process.pid for process in psutil.Process(worker_identity["pid"]).parents()}):
            raise RuntimeError("provider readiness identity mismatch")
        self.identity = worker_identity
        self.runtime_state = ready["runtime_state"]
        if not isinstance(self.runtime_state, Mapping) or set(self.runtime_state) != {"server_process_identity", "listener_port"}:
            raise RuntimeError("provider runtime readiness is not closed")
        runtime_identity = self.runtime_state["server_process_identity"]
        if runtime_identity is not None:
            from scripts.model_servers.goal_binding_provider_runtimes import _verify_listener
            actual_port = self.runtime_state["listener_port"]
            if self.profile["provider_id"] != "qwen3_vl_8b_q4_k_m" and actual_port != self.port:
                raise RuntimeError("provider runtime listener port mismatch")
            self.port = actual_port
            if not _verify_listener(port=self.port, identity=exact_process_identity(runtime_identity), scope_name=self.config["scope_name"]):
                raise RuntimeError("provider runtime listener is not ready")
        self.failure = ready["failure"]

    def _wait(self, path: Path):
        from scripts.model_servers.goal_binding_transformers_worker import read_json
        deadline = time.monotonic() + self.profile["timeout_seconds"]
        while True:
            if _sha256_file(self.root / "session.json") != self.config_sha:
                raise RuntimeError("provider session mailbox identity changed")
            for folder in (self.root, self.root / "responses", self.root / "raw"):
                for log in folder.iterdir():
                    if not log.is_file() or not (log.suffix in {".bin", ".utf8"} or folder.name == "responses"):
                        continue
                    try:
                        size = log.stat().st_size
                    except FileNotFoundError:
                        if folder.name == "responses" and log.name.endswith(".json.tmp"):
                            continue
                        raise
                    if size > self.profile["max_output_bytes"]:
                        raise RuntimeError("provider live output exceeds byte bound")
            if (self.root / "fatal.json").exists():
                raise RuntimeError("provider mailbox integrity failure: " + str(read_json(self.root / "fatal.json")))
            if path.exists():
                return read_json(path, self.profile["max_output_bytes"])
            if self.process.poll() is not None:
                raise RuntimeError("provider worker exited without a bound response")
            if time.monotonic() >= deadline:
                raise TimeoutError("provider session call timed out")
            time.sleep(0.01)

    def call(self, image_path: Path, request: Mapping[str, object]) -> object:
        from scripts.model_servers.goal_binding_transformers_worker import atomic_write, write_json, provider_failure, failure_envelope
        from app.learn.hybrid.goal_binding_ab import _native_envelope
        if self.blocked:
            raise RuntimeError("provider session is blocked by infrastructure integrity")
        if self.receipt is not None and self.failure is None:
            raise RuntimeError("provider session is already closed")
        if self.sequence >= 25:
            raise ValueError("provider arm exceeds 25 bounded requests")
        _reject_provider_input(request)
        if set(request) - {"contract_version", "goal", "incumbent_runtime_request", "incumbent_projection"}:
            raise ValueError("provider arm request is not closed")
        incumbent = self.profile["provider_id"] == "qwen3_vl_8b_q4_k_m"
        if not incumbent and any(key in request for key in ("incumbent_runtime_request", "incumbent_projection")):
            raise ValueError("challenger provider input contains candidate data")
        goal = _short_goal(request)
        if image_path.stat().st_size > _MAX_SCREENSHOT_BYTES:
            raise ValueError("provider screenshot byte bound exceeded")
        image_bytes = image_path.read_bytes()
        from PIL import Image
        with Image.open(image_path) as image:
            width, height = image.size
            if width * height > _MAX_SCREENSHOT_PIXELS:
                raise ValueError("provider screenshot pixel bound exceeded")
            image.verify()
        self.sequence += 1
        attempted = False
        try:
            if self.config is None:
                self._open()
            payload = {"image_path": str(self.root / "requests" / f"{self.sequence:06d}.png"), "goal": goal, "profile": self.profile, "screenshot": {"sha256": _sha256(image_bytes), "width": width, "height": height, "capture_id": "capture/" + _sha256(image_bytes)}, "parent_identity_path": str(self.root / "worker-identity.json"), "artifact_root": str(self.artifact_dir), "code_identity": self.config["code_identity"], "listener_port": self.port}
            if incumbent:
                payload.update(incumbent_request=request["incumbent_runtime_request"], incumbent_projection=request["incumbent_projection"])
            if self.failure:
                failure = dict(self.failure)
                failure.update(kind=("provider_unavailable_after_" if self.sequence > 1 else "") + failure["kind"], attempted=False)
                envelope = failure_envelope(payload, failure, identity=self.identity, request_bytes=0)
            else:
                atomic_write(Path(payload["image_path"]), image_bytes)
                body = json.dumps({"session_sha256": self.config_sha, "sequence": self.sequence, "payload": payload}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                if len(body) > _MAX_REQUEST_BYTES:
                    raise ValueError("provider request byte bound exceeded")
                atomic_write(self.root / "requests" / f"{self.sequence:06d}.json", body)
                attempted = True
                envelope = self._wait(self.root / "responses" / f"{self.sequence:06d}.json")
                from scripts.model_servers.goal_binding_transformers_worker import _identity
                if _native_envelope(envelope) is None or envelope["worker_process_identity"] != self.identity or envelope["profile_identity"] != _identity(self.profile) or not _resource_metrics_are_closed(envelope["resource_metrics"], request_bytes=len(body), timeout_seconds=self.profile["timeout_seconds"]):
                    raise RuntimeError("provider envelope process/profile mismatch")
                lineage = envelope["request_lineage"]
                if lineage.get("session_id") != self.session_id or lineage.get("sequence") != self.sequence or lineage.get("session_sha256") != self.config_sha or lineage.get("request_sha256") != _sha256(body) or lineage.get("screenshot_sha256") != payload["screenshot"]["sha256"] or lineage.get("screenshot_dimensions") != [width, height] or lineage.get("code_identity") != self.config["code_identity"]:
                    raise RuntimeError("provider envelope capture/session mismatch")
                raw = self.root / "raw" / f"{self.sequence:06d}.utf8"
                if raw.read_bytes() != envelope["raw_native_output"].encode("utf-8"):
                    raise RuntimeError("provider raw mailbox mismatch")
                if envelope.get("failure") and envelope["failure"]["terminal"]:
                    self.failure = envelope["failure"]
            if self.failure:
                if not self.cleanup()["verified"]:
                    raise RuntimeError("provider failure cleanup could not be verified")
            envelope["request_lineage"].update(session_id=self.session_id, sequence=self.sequence, session_sha256=self.config_sha)
            self._persist_outcome(envelope)
            return envelope
        except TimeoutError as exc:
            self.failure = provider_failure(exc, attempted=attempted)
            if not self.cleanup()["verified"]:
                self.blocked = True
                raise RuntimeError("provider timeout cleanup could not be verified") from exc
            payload = {"profile": self.profile, "screenshot": {"sha256": _sha256(image_bytes), "width": width, "height": height, "capture_id": "capture/" + _sha256(image_bytes)}, "code_identity": self.config["code_identity"]}
            envelope = failure_envelope(payload, self.failure, identity=self.identity, request_bytes=0)
            envelope["request_lineage"].update(session_id=self.session_id, sequence=self.sequence, session_sha256=self.config_sha)
            self._persist_outcome(envelope)
            return envelope
        except BaseException:
            self.blocked = True
            self.cleanup()
            raise

    def _persist_outcome(self, envelope):
        from scripts.model_servers.goal_binding_transformers_worker import atomic_write, write_json
        raw = self.root / "raw" / f"{self.sequence:06d}.utf8"
        response = self.root / "responses" / f"{self.sequence:06d}.json"
        if not raw.exists():
            atomic_write(raw, envelope["raw_native_output"].encode("utf-8"))
        if not response.exists():
            write_json(response, envelope)

    def cleanup(self) -> Mapping[str, object]:
        from app.learn.hybrid.windows_process_scope import observe_process_scope_cleanup
        from scripts.model_servers.goal_binding_transformers_worker import write_json, read_json
        if self.receipt is not None:
            return deepcopy(self.receipt)
        observation = {"cleanup_status": "not_started"}
        cleanup_errors = []
        if self.process is not None:
            cleanup_deadline = time.monotonic() + _CLEANUP_TIMEOUT_SECONDS
            if not (self.root / "stop.json").exists():
                write_json(self.root / "stop.json", {"session_sha256": self.config_sha})
            try:
                self.process.wait(timeout=max(0.0, cleanup_deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                cleanup_errors.append("provider cleanup deadline exceeded")
        if self.scope is not None:
            self.scope.close()
            observation = observe_process_scope_cleanup(self.config["scope_name"], terminate=True, listener_ports=[self.port] if self.port else [], stable_zero_observations=3)
        exit_code = None
        if self.process is not None:
            exit_code = self.process.poll()
            self.process.close()
        if self.lease is not None:
            try:
                self.lease.release()
            except RuntimeError as exc:
                cleanup_errors.append(str(exc))
        runtime_cleanup = None
        stopped = self.root / "stopped.json"
        if stopped.exists():
            try:
                stop = read_json(stopped)
                if not isinstance(stop, Mapping) or set(stop) != {"session_sha256", "worker_process_identity", "runtime_cleanup"} or stop["session_sha256"] != self.config_sha or stop["worker_process_identity"] != self.identity:
                    raise ValueError("worker stop identity mismatch")
                runtime_cleanup = stop["runtime_cleanup"]
                if not isinstance(runtime_cleanup, Mapping) or runtime_cleanup.get("status") not in {"released", "not_loaded"}:
                    raise ValueError("provider runtime cleanup is unresolved")
                if self.profile["provider_id"] == "qwen3_vl_8b_q4_k_m" and runtime_cleanup.get("status") == "released":
                    from app.core.model_server import _validate_exact_qwen_cleanup_evidence
                    release = runtime_cleanup["managed_release"]
                    _validate_exact_qwen_cleanup_evidence(release, release["lease"])
            except (OSError, ValueError, KeyError, TypeError) as exc:
                cleanup_errors.append(str(exc))
        elif self.profile["provider_id"] == "qwen3_vl_8b_q4_k_m":
            cleanup_errors.append("managed incumbent release evidence is unavailable")
        samples = []
        baseline_ids = {(owner["pid"], owner["create_time_ns"]) for owner in (self.baseline or {}).get("owners", [])}
        for _ in range(3):
            sample = _gpu_ownership_snapshot()
            sample = deepcopy(sample)
            sample["new_owners"] = [owner for owner in sample.get("owners", []) if (owner["pid"], owner["create_time_ns"]) not in baseline_ids]
            samples.append(sample)
            time.sleep(0.02)
        gpu_owners = [owner for sample in samples for owner in sample["new_owners"]]
        leases = [str(self.lease_path)] if self.lease_path.exists() else []
        verified = self.identity is not None and not self.blocked and observation.get("cleanup_status") == "verified" and all(sample.get("status") == "verified" for sample in samples) and not gpu_owners and not leases and not cleanup_errors and exit_code is not None
        evidence = {"verified": verified, "scope": observation, "baseline": self.baseline, "gpu_samples": samples, "worker_process_identity": self.identity, "exit_code": exit_code, "request_count": self.sequence, "errors": cleanup_errors, "session_id": self.session_id, "logs": {name: {"sha256": _sha256_file(self.root / name), "bytes": (self.root / name).stat().st_size} for name in ("worker.stdout.bin", "worker.stderr.bin") if (self.root / name).exists()}}
        evidence.update(launcher_process_identity=self.launcher_identity, runtime_state=self.runtime_state, runtime_cleanup=runtime_cleanup, started_ns=self.started_ns, stopped_ns=time.time_ns(), profile=self.profile, code_identity=self.config.get("code_identity") if self.config else None)
        evidence.update(contract_version="goal_binding_provider_call_cleanup_v1", cleanup_path=str(self.root / "cleanup.json"))
        self.receipt = {"contract_version": "simple_native_provider_cleanup_v1", "provider": self.profile["provider_id"], "verified": verified, "cleanup_status": "verified" if verified else "failed", "owned_processes": gpu_owners, "provider_processes_after": observation.get("member_identities_after", []), "helper_processes_after": [], "orphan_descendant_pids": observation.get("member_pids_after", []), "active_listeners_after": observation.get("active_listeners_after", []), "lease_files_after": leases, "cleanup_observations": [evidence]}
        if self.root.exists():
            write_json(self.root / "cleanup.json", self.receipt)
        return deepcopy(self.receipt)


def make_goal_binding_arm(*, profile: Mapping[str, object], artifact_dir: Path, run_root: Path | None = None) -> GoalBindingArm:
    sealed = _verified(profile, Path(artifact_dir))
    native = sealed["native_output"]
    assert isinstance(native, Mapping)
    def adapt(raw: object, goal_index: int, context: Mapping[str, object]) -> Mapping[str, object]:
        if native["kind"] == "qwen_goal_binding_array_v1":
            return adapt_incumbent_candidate_index(raw, goal_index, context)
        adapter = make_native_point_adapter(native_adapter_for_profile(sealed), _adapter_profile(sealed, image_size=context["image_size"]))
        return adapter(raw, goal_index, context)
    session = GoalBindingProviderSession(sealed, Path(artifact_dir), run_root)
    return GoalBindingArm(arm_id=str(sealed["arm_id"]), provider_id=str(sealed["provider_id"]), call=session.call, adapt=adapt, cleanup=session.cleanup)

def probe_goal_binding_profile(
    *, profile: Mapping[str, object], image_path: Path,
    artifact_dir: Path | None = None,
) -> dict[str, object]:
    arm = make_goal_binding_arm(profile=profile, artifact_dir=artifact_dir or _MODEL_TEST_ROOT)
    try:
        raw = arm.call(image_path, {"goal": "button: Open"})
    finally:
        cleanup = arm.cleanup()
    return {"contract_version": "goal_binding_profile_probe_v1", "provider_id": arm.provider_id, "raw_native_output": raw, "artifact_is_authorization": False, "contains_holdout": False, "candidate_mapping": None, "cleanup": cleanup}
