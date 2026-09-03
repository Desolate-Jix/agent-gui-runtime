"""One-profile worker with lazy provider dispatch and a closed native trace envelope."""
from __future__ import annotations
import argparse
from collections.abc import Callable, Mapping
from hashlib import sha256
import importlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time
from typing import Any

_DISPATCHERS: dict[str, Callable[..., object]] = {}


def _closed_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("worker JSON has duplicate keys")
        result[key] = value
    return result


def register_provider_dispatcher(provider_id: str, dispatcher: Callable[..., object]) -> None:
    if not isinstance(provider_id, str) or not provider_id or not callable(dispatcher):
        raise ValueError("provider dispatcher is invalid")
    _DISPATCHERS[provider_id] = dispatcher


def _sha(value: bytes) -> str:
    return sha256(value).hexdigest()


def _sha_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _identity(profile: Mapping[str, object]) -> dict[str, object]:
    runtime = profile.get("runtime")
    preprocessing = profile.get("preprocessing")
    native = profile.get("native_output")
    if not isinstance(runtime, Mapping) or not isinstance(preprocessing, Mapping) or not isinstance(native, Mapping):
        raise ValueError("worker profile identity is invalid")
    return {"profile_id": profile.get("profile_id", profile.get("provider_id")), "preprocessing_sha256": preprocessing.get("sha256", "not_acquired"), "runtime_sha256": runtime.get("sha256", "not_acquired"), "native_output_kind": native.get("kind", _native_kind_for_provider(str(profile.get("provider_id") or "")))}


def native_trace_envelope(*, profile_identity: Mapping[str, object], raw_native_output: str, resource_metrics: Mapping[str, object], parsed_native: object = None, worker_process_identity: Mapping[str, object] | None = None, request_lineage: Mapping[str, object] | None = None) -> dict[str, object]:
    needed = {"profile_id", "preprocessing_sha256", "runtime_sha256", "native_output_kind"}
    if not isinstance(profile_identity, Mapping) or set(profile_identity) != needed or not isinstance(raw_native_output, str) or not isinstance(resource_metrics, Mapping):
        raise ValueError("worker native trace is invalid")
    metrics = dict(resource_metrics)
    expected_metrics = {
        "latency_ms", "peak_vram_bytes", "peak_vram_status", "generation_tokens",
        "request_bytes", "provider_stdout_bytes", "provider_stderr_bytes", "timeout_seconds",
    }
    peak = metrics.get("peak_vram_bytes")
    generation_tokens = metrics.get("generation_tokens")
    if (
        set(metrics) != expected_metrics
        or isinstance(metrics["latency_ms"], bool)
        or not isinstance(metrics["latency_ms"], (int, float))
        or not math.isfinite(float(metrics["latency_ms"]))
        or float(metrics["latency_ms"]) < 0
        or metrics["peak_vram_status"] not in {"measured", "unavailable"}
        or (peak is not None and (isinstance(peak, bool) or not isinstance(peak, int) or peak < 0))
        or (metrics["peak_vram_status"] == "measured") != (peak is not None)
        or (generation_tokens is not None and (isinstance(generation_tokens, bool) or not isinstance(generation_tokens, int) or generation_tokens < 0))
        or any(isinstance(metrics[field], bool) or not isinstance(metrics[field], int) or metrics[field] < 0 for field in ("request_bytes", "provider_stdout_bytes", "provider_stderr_bytes", "timeout_seconds"))
    ):
        raise ValueError("worker resource metrics are invalid")
    identity = dict(worker_process_identity or {"pid": os.getpid(), "create_time_ns": time.time_ns()})
    if set(identity) != {"pid", "create_time_ns"} or any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in identity.values()):
        raise ValueError("worker process identity is invalid")
    lineage = dict(request_lineage or {})
    return {"contract_version": "goal_binding_native_trace_v1", "profile_identity": dict(profile_identity), "raw_native_output": raw_native_output, "raw_native_output_sha256": _sha(raw_native_output.encode("utf-8")), "parsed_native": parsed_native, "resource_metrics": metrics, "worker_process_identity": identity, "request_lineage": lineage}


def _native_kind_for_provider(provider_id: str) -> str:
    if provider_id == "ui_venus_1_5_2b_f16": return "ui_venus_point_v1"
    if provider_id == "gui_actor_3b_bf16": return "gui_actor_topk_points_v1"
    if provider_id == "phi_ground_any_bf16": return "phi_ground_any_v1"
    if provider_id == "qwen3_vl_8b_q4_k_m": return "qwen_goal_binding_array_v1"
    return "gguf_bare_point_pair_v1"


def _parse_ui_venus(raw: object) -> str:
    if not isinstance(raw, str): raise ValueError("UI-Venus native output must be UTF-8 text")
    try: value = json.loads(raw)
    except json.JSONDecodeError as exc: raise ValueError("UI-Venus native output is invalid") from exc
    if not isinstance(value, list) or len(value) != 2 or any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in value): raise ValueError("UI-Venus must return one bare point")
    if value == [-1, -1]: return raw
    if not all(math.isfinite(float(x)) and 0 <= float(x) <= 1000 for x in value): raise ValueError("UI-Venus point is out of range")
    return raw


def _parse_phi(raw: object, *, width: int, height: int) -> dict[str, object]:
    if not isinstance(raw, str): raise ValueError("Phi-Ground-Any native output must be UTF-8 text")
    match = re.fullmatch(r"\s*<x>([^<]+)</x><y>([^<]+)</y>\s*", raw)
    if match is None: raise ValueError("Phi-Ground-Any must return exactly one x/y pair")
    try: x, y = float(match.group(1)), float(match.group(2))
    except ValueError as exc: raise ValueError("Phi-Ground-Any point is invalid") from exc
    if not all(math.isfinite(v) and 0 <= v <= 10000 for v in (x,y)): raise ValueError("Phi-Ground-Any point is out of range")
    from scripts.model_servers.goal_binding_provider_runtimes import phi_image_geometry
    geometry = phi_image_geometry(width, height)
    ratio = geometry["reshape_ratio"]
    if x / 10000 * 1680 >= geometry["resized_dimensions"][0] or y / 10000 * 1008 >= geometry["resized_dimensions"][1]:
        raise ValueError("Phi-Ground-Any point falls in padding or outside capture")
    px, py = x / 10000 * 1680 / ratio, y / 10000 * 1008 / ratio
    if not all(math.isfinite(v) for v in (px,py)) or not (0 <= px < width and 0 <= py < height): raise ValueError("Phi-Ground-Any point falls in padding or outside capture")
    return {"point": [px, py]}


def _load_entrypoint(profile: Mapping[str, object]) -> Callable[..., object]:
    runtime = profile.get("runtime")
    if not isinstance(runtime, Mapping): raise ValueError("worker runtime is invalid")
    entrypoint = runtime.get("entrypoint")
    if not isinstance(entrypoint, str) or ":" not in entrypoint: raise ValueError("provider runtime entrypoint is not pinned")
    module_name, attribute = entrypoint.split(":", 1)
    repository_root = Path(__file__).resolve().parents[2]
    if str(repository_root) not in sys.path:
        sys.path.insert(0, str(repository_root))
    module = importlib.import_module(module_name)
    target = getattr(module, attribute, None)
    if not callable(target): raise ValueError("provider runtime entrypoint is unavailable")
    return target


def _dispatch_provider(
    *, profile: Mapping[str, object], image_path: Path, goal: str,
    artifact_root: Path, incumbent_projection: object = None,
    incumbent_request: object = None, listener_port: int | None = None,
) -> object:
    provider_id = profile.get("provider_id")
    if not isinstance(provider_id, str) or not provider_id: raise ValueError("worker provider is invalid")
    dispatcher = _DISPATCHERS.get(provider_id) or _load_entrypoint(profile)
    return dispatcher(
        image_path=image_path, goal=goal, profile=profile, artifact_root=artifact_root,
        incumbent_projection=incumbent_projection, incumbent_request=incumbent_request,
        listener_port=listener_port,
    )


def _verify_code_identity(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != {"worker_sha256", "provider_runtime_sha256", "worker_python_sha256"}:
        raise ValueError("worker code identity is unavailable")
    runtime_path = Path(__file__).with_name("goal_binding_provider_runtimes.py")
    observed = {
        "worker_sha256": _sha_file(Path(__file__)),
        "provider_runtime_sha256": _sha_file(runtime_path),
        "worker_python_sha256": _sha_file(Path(sys.executable)),
    }
    if dict(value) != observed:
        raise ValueError("worker code identity changed after request sealing")
    return observed


def _run_provider_once(payload: Mapping[str, object], *, request_bytes: int | None = None, dispatcher: Callable[..., object] | None = None) -> dict[str, object]:
    allowed = {
        "image_path", "goal", "profile", "screenshot", "parent_identity_path",
        "incumbent_projection", "incumbent_request", "artifact_root", "listener_port",
        "code_identity",
    }
    if not set(payload) <= allowed or not {"image_path", "goal", "profile", "screenshot", "parent_identity_path"} <= set(payload): raise ValueError("worker request must contain exactly one screenshot and one short goal")
    image_path, goal, profile, screenshot = payload["image_path"], payload["goal"], payload["profile"], payload["screenshot"]
    if not isinstance(image_path, str) or not isinstance(goal, str) or not goal.strip() or len(goal) > 512 or not isinstance(profile, Mapping) or not isinstance(screenshot, Mapping): raise ValueError("worker request is invalid")
    path = Path(image_path)
    if not path.is_file() or path.stat().st_size > 32 * 1024 * 1024 or _sha(path.read_bytes()) != screenshot.get("sha256"): raise ValueError("worker screenshot copy/hash changed or exceeds byte bound")
    from PIL import Image
    try:
        with Image.open(path) as image:
            dimensions = (image.width, image.height)
    except (OSError, SyntaxError) as exc:
        raise ValueError("worker screenshot copy is not a readable image") from exc
    if dimensions != (screenshot.get("width"), screenshot.get("height")) or dimensions[0] * dimensions[1] > 32 * 1024 * 1024:
        raise ValueError("worker screenshot dimensions changed")
    identity_path = payload["parent_identity_path"]
    if not isinstance(identity_path, str): raise ValueError("worker identity path is invalid")
    identity = json.loads(Path(identity_path).read_text(encoding="utf-8"), object_pairs_hook=_closed_object)
    if not isinstance(identity, Mapping): raise ValueError("worker parent identity is invalid")
    artifact_root_value = payload.get("artifact_root", str(path.parent))
    if not isinstance(artifact_root_value, str):
        raise ValueError("worker artifact root is invalid")
    artifact_root = Path(artifact_root_value).resolve()
    if not path.resolve().is_relative_to(artifact_root) or not Path(identity_path).resolve().is_relative_to(artifact_root):
        raise ValueError("worker request artifacts escape the supplied artifact root")
    provider_id = profile.get("provider_id")
    has_incumbent = payload.get("incumbent_projection") is not None or payload.get("incumbent_request") is not None
    if provider_id == "qwen3_vl_8b_q4_k_m":
        if not isinstance(payload.get("incumbent_projection"), Mapping) or not isinstance(payload.get("incumbent_request"), Mapping):
            raise ValueError("incumbent worker request exception is incomplete")
    elif has_incumbent:
        raise ValueError("challenger worker request contains incumbent candidate data")
    code_identity = payload.get("code_identity")
    verified_code = _verify_code_identity(code_identity) if code_identity is not None else {
        "worker_sha256": _sha_file(Path(__file__)),
        "provider_runtime_sha256": _sha_file(Path(__file__).with_name("goal_binding_provider_runtimes.py")),
        "worker_python_sha256": _sha_file(Path(sys.executable)),
    }
    started = time.perf_counter()
    dispatched = (dispatcher or _dispatch_provider)(
        profile=profile, image_path=path, goal=goal, artifact_root=artifact_root,
        incumbent_projection=payload.get("incumbent_projection"),
        incumbent_request=payload.get("incumbent_request"),
        listener_port=payload.get("listener_port") if isinstance(payload.get("listener_port"), int) else None,
    )
    if _sha_file(path) != screenshot.get("sha256"):
        raise ValueError("worker screenshot changed during inference")
    runtime_telemetry: dict[str, object] = {
        "generation_tokens": None, "peak_vram_bytes": None,
        "peak_vram_status": "unavailable", "provider_stdout_bytes": 0,
        "provider_stderr_bytes": 0,
    }
    child_cleanup = None
    if isinstance(dispatched, Mapping) and set(dispatched) in (
        {"raw_native_output", "parsed_native", "telemetry"},
        {"raw_native_output", "parsed_native", "telemetry", "child_cleanup"},
    ):
        raw = dispatched["raw_native_output"]
        dispatcher_parsed = dispatched["parsed_native"]
        telemetry = dispatched["telemetry"]
        if not isinstance(telemetry, Mapping):
            raise ValueError("provider runtime telemetry is invalid")
        runtime_telemetry.update(dict(telemetry))
        child_cleanup = dispatched.get("child_cleanup")
    else:
        raw, dispatcher_parsed = dispatched, None
    kind = _native_kind_for_provider(str(profile.get("provider_id") or ""))
    raw_text = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False, separators=(",", ":"))
    failure = None
    try:
        parsed = _project_native(kind, raw_text, screenshot=screenshot)
    except (ValueError, TypeError) as exc:
        parsed = None
        failure = {"kind": "malformed_native_output", "message": str(exc), "attempted": True, "terminal": False}
    timeout = profile.get("timeout_seconds", 0)
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 0:
        raise ValueError("worker timeout identity is invalid")
    metrics = {
        "latency_ms": round((time.perf_counter()-started)*1000, 3),
        "peak_vram_bytes": runtime_telemetry.get("peak_vram_bytes"),
        "peak_vram_status": runtime_telemetry.get("peak_vram_status", "unavailable"),
        "generation_tokens": runtime_telemetry.get("generation_tokens"),
        "request_bytes": request_bytes if isinstance(request_bytes, int) and request_bytes >= 0 else len(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")),
        "provider_stdout_bytes": runtime_telemetry.get("provider_stdout_bytes", 0),
        "provider_stderr_bytes": runtime_telemetry.get("provider_stderr_bytes", 0),
        "timeout_seconds": timeout,
    }
    lineage = {
        "screenshot_sha256": screenshot.get("sha256"),
        "capture_id": screenshot.get("capture_id"),
        "screenshot_dimensions": [screenshot.get("width"), screenshot.get("height")],
        "code_identity": verified_code,
        "child_cleanup": child_cleanup,
    }
    if kind == "phi_ground_any_v1":
        from scripts.model_servers.goal_binding_provider_runtimes import phi_image_geometry
        lineage["preprocessing_geometry"] = phi_image_geometry(screenshot["width"], screenshot["height"])
    envelope = native_trace_envelope(
        profile_identity=_identity(profile), raw_native_output=raw_text,
        parsed_native=parsed, resource_metrics=metrics,
        worker_process_identity=identity, request_lineage=lineage,
    )
    envelope.update(contract_version="goal_binding_native_trace_v2", outcome="provider_failure" if failure else "native_output", failure=failure)
    return envelope


def _reject_constant(value: str) -> None:
    raise ValueError("native JSON contains a non-finite number")


def _project_native(kind: str, raw: str, *, screenshot: Mapping[str, object]) -> object:
    if kind == "ui_venus_point_v1":
        return _parse_ui_venus(raw)
    if kind == "phi_ground_any_v1":
        return _parse_phi(raw, width=int(screenshot["width"]), height=int(screenshot["height"]))
    if kind in {"gui_actor_topk_points_v1", "qwen_goal_binding_array_v1"}:
        value = json.loads(raw, object_pairs_hook=_closed_object, parse_constant=_reject_constant)
        if kind == "qwen_goal_binding_array_v1":
            if not isinstance(value, list):
                raise ValueError("incumbent native output must be a bare JSON array")
            return value
        if not isinstance(value, Mapping) or not isinstance(value.get("topk_points"), list):
            raise ValueError("GUI-Actor native output must contain topk_points")
        return {"topk_points": value["topk_points"]}
    return raw


def atomic_write(path: Path, body: bytes) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    if path.exists() or temporary.exists():
        raise ValueError("mailbox path already exists")
    with temporary.open("xb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def write_json(path: Path, value: object) -> None:
    atomic_write(path, json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8"))


def read_json(path: Path, maximum: int = 1024 * 1024) -> object:
    if path.stat().st_size > maximum:
        raise ValueError("mailbox JSON exceeds byte bound")
    return json.loads(path.read_bytes().decode("utf-8"), object_pairs_hook=_closed_object, parse_constant=_reject_constant)


def provider_failure(exc: Exception, *, attempted: bool) -> dict[str, object]:
    if isinstance(exc, TimeoutError):
        kind = "provider_timeout"
    elif "provider_platform_incompatible" in str(exc):
        kind = "provider_platform_incompatible"
    elif isinstance(exc, ImportError):
        kind = "provider_dependency_failure"
    elif "out of memory" in str(exc).casefold() or isinstance(exc, MemoryError):
        kind = "provider_oom"
    else:
        kind = "provider_runtime_failure"
    return {"kind": kind, "message": str(exc)[:4096], "attempted": attempted, "terminal": True}


def failure_envelope(payload: Mapping[str, object], failure: Mapping[str, object], *, identity: Mapping[str, object], request_bytes: int) -> dict[str, object]:
    screenshot, profile = payload["screenshot"], payload["profile"]
    envelope = native_trace_envelope(
        profile_identity=_identity(profile), raw_native_output="", parsed_native=None,
        worker_process_identity=identity,
        resource_metrics={"latency_ms": 0, "peak_vram_bytes": None, "peak_vram_status": "unavailable", "generation_tokens": None, "request_bytes": request_bytes, "provider_stdout_bytes": 0, "provider_stderr_bytes": 0, "timeout_seconds": profile["timeout_seconds"]},
        request_lineage={"screenshot_sha256": screenshot["sha256"], "screenshot_dimensions": [screenshot["width"], screenshot["height"]], "capture_id": screenshot["capture_id"], "code_identity": payload["code_identity"], "child_cleanup": None},
    )
    envelope.update(contract_version="goal_binding_native_trace_v2", outcome="provider_failure", failure=dict(failure))
    return envelope


def _open_session(config: Mapping[str, object]) -> object:
    profile = config["profile"]
    module_name, _ = profile["runtime"]["entrypoint"].split(":", 1)
    module = importlib.import_module(module_name)
    return module.open_session(profile=profile, artifact_root=Path(config["artifact_root"]), session_root=Path(config["session_root"]), scope_name=config["scope_name"], listener_port=config["listener_port"])


def serve_session(config_path: Path) -> None:
    root = config_path.resolve().parent
    config = read_json(config_path)
    required = {"contract_version", "session_id", "run_id", "arm_id", "session_root", "scope_name", "profile", "artifact_root", "code_identity", "listener_port"}
    if not isinstance(config, Mapping) or set(config) != required or config["contract_version"] != "goal_binding_provider_session_v1" or Path(config["session_root"]).resolve() != root:
        raise ValueError("worker session identity is invalid")
    identity = read_json(root / "parent-identity.json")
    from app.learn.hybrid.windows_process_scope import _identity_for_pid, WindowsProcessScope
    observed_identity = _identity_for_pid(os.getpid())
    import psutil
    ancestors = {process.pid for process in psutil.Process().parents()}
    if identity != _identity_for_pid(identity["pid"]) or (identity != observed_identity and identity["pid"] not in ancestors):
        raise ValueError("worker launcher identity/ancestry mismatch")
    launcher_identity, identity = identity, observed_identity
    scope = WindowsProcessScope(config["scope_name"], create=False)
    try:
        if not {os.getpid(), launcher_identity["pid"]} <= set(scope.pids()):
            raise ValueError("worker is outside its exact Job")
    finally:
        scope.close()
    _verify_code_identity(config["code_identity"])
    write_json(root / "worker-identity.json", identity)
    digest = _sha_file(config_path)
    runtime = None
    failure = None
    try:
        try:
            runtime = _open_session(config)
        except (ImportError, OSError, RuntimeError, ValueError, TypeError, AttributeError, MemoryError) as exc:
            from scripts.model_servers.goal_binding_provider_runtimes import ProviderIntegrityError
            if isinstance(exc, ProviderIntegrityError):
                raise
            failure = provider_failure(exc, attempted=False)
        runtime_state = {"server_process_identity": getattr(runtime, "identity", None), "listener_port": getattr(runtime, "port", None)}
        write_json(root / "ready.json", {"session_sha256": digest, "worker_process_identity": identity, "launcher_process_identity": launcher_identity, "runtime_state": runtime_state, "failure": failure})
        while failure is not None and not (root / "stop.json").exists():
            time.sleep(0.01)
        sequence = 1
        while sequence <= 25 and not (root / "stop.json").exists() and failure is None:
            path = root / "requests" / f"{sequence:06d}.json"
            if not path.exists():
                time.sleep(0.01)
                continue
            request = read_json(path)
            request_sha256 = _sha_file(path)
            if not isinstance(request, Mapping) or set(request) != {"session_sha256", "sequence", "payload"} or request["session_sha256"] != digest or request["sequence"] != sequence:
                raise ValueError("worker mailbox request identity mismatch")
            payload = request["payload"]
            if not isinstance(payload, Mapping) or payload.get("profile") != config["profile"] or payload.get("code_identity") != config["code_identity"] or payload.get("artifact_root") != config["artifact_root"] or Path(payload.get("parent_identity_path", "")).resolve() != root / "worker-identity.json" or Path(payload.get("image_path", "")).resolve() != root / "requests" / f"{sequence:06d}.png":
                raise ValueError("worker mailbox payload identity mismatch")
            def invoke(**kwargs):
                nonlocal failure
                try:
                    return runtime(**kwargs)
                except (ImportError, OSError, RuntimeError, ValueError, TypeError, AttributeError, MemoryError) as exc:
                    from scripts.model_servers.goal_binding_provider_runtimes import ProviderIntegrityError
                    if isinstance(exc, ProviderIntegrityError):
                        raise
                    failure = provider_failure(exc, attempted=True)
                    return ""
            envelope = _run_provider_once(payload, request_bytes=path.stat().st_size, dispatcher=invoke)
            if failure:
                envelope = failure_envelope(payload, failure, identity=identity, request_bytes=path.stat().st_size)
            envelope["request_lineage"].update(session_id=config["session_id"], sequence=sequence, session_sha256=digest, request_sha256=request_sha256)
            atomic_write(root / "raw" / f"{sequence:06d}.utf8", envelope["raw_native_output"].encode("utf-8"))
            write_json(root / "responses" / f"{sequence:06d}.json", envelope)
            sequence += 1
    except (OSError, ValueError, RuntimeError) as exc:
        write_json(root / "fatal.json", {"session_sha256": digest, "error": str(exc)[:4096]})
        raise
    finally:
        cleanup = runtime.close() if runtime is not None else {"status": "not_loaded"}
        write_json(root / "stopped.json", {"session_sha256": digest, "worker_process_identity": identity, "runtime_cleanup": cleanup})


def main(argv: list[str] | None = None) -> int:
    parser=argparse.ArgumentParser(description="Run one bounded goal-binding provider request.")
    parser.add_argument("--execute", action="store_true"); parser.add_argument("--request-json", type=Path)
    parser.add_argument("--session-json", type=Path)
    args=parser.parse_args(argv)
    if args.execute and args.session_json is not None:
        repository_root = str(Path(__file__).resolve().parents[2])
        if repository_root not in sys.path:
            sys.path.insert(0, repository_root)
        serve_session(args.session_json)
        return 0
    if not args.execute or args.request_json is None: parser.error("--execute and --request-json are required")
    try:
        request_raw = args.request_json.read_bytes()
        payload=json.loads(request_raw.decode("utf-8"), object_pairs_hook=_closed_object)
        if not isinstance(payload, Mapping): raise ValueError("worker request must be an object")
        print(json.dumps(_run_provider_once(payload, request_bytes=len(request_raw)), ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0
    except (OSError, ValueError, RuntimeError, ImportError) as exc:
        parser.error(str(exc))

if __name__ == "__main__": raise SystemExit(main())
