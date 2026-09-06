"""VISTA 当前源码单次 ROI 定位器；只管理自身启动的本地子进程。"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from hashlib import sha256
import base64
import json
from math import isfinite
from pathlib import Path
import socket
import subprocess
import time
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest
from uuid import uuid4

import psutil

VISTA_PROVIDER = "vista_4b"
VISTA_MODEL_NAME = "inclusionAI/VISTA-4B"
VISTA_PROFILE_PATH = "configs/model_profiles/vista_4b_transformers.json"
VISTA_SERVER_PATH = "scripts/model_servers/vista_openai_server.py"
VISTA_RUNTIME = Path("D:/agent-gui-runtime/.venv/Scripts/python.exe")
DEFAULT_MODEL_PATH = Path("D:/agent-gui-runtime/models/vista-4b-safetensors-sharded")
DEFAULT_TIMEOUT_SECONDS = 180
MAX_RESPONSE_BYTES = 1024 * 1024
_MODEL_INDEX_SHA256 = "19d0db312ba3dc18eb7ba8a07f15a2fe8eb99ae20bc0cccc24dfb4d872b08dab"
_PROFILE_SHA256 = "c21e630a19cdbfa3d7cf6a3f48d323324cd6e5a2bdc06b2d789466a4bff6f7d8"
_SERVER_SHA256 = "678ec58bb3f4019071ab9ba42e2aa430edad9b72d882abf77740a39a52ec3790"
_MODEL_SHARDS = {
    "model-00001-of-00006.safetensors": (1581534168, "5dd8b455d68804eb01a310acdf7f1b367c7e350194505a4dae6b421f3d0d5860"),
    "model-00002-of-00006.safetensors": (1606375136, "edbcff82db324de7884fd91e62c815e80384d634a79a4af5268f643af1f1e9ad"),
    "model-00003-of-00006.safetensors": (1570067784, "a7ac08f711b69ca17c948fbac35a780d9b0c0315c6996b11f7752b32276808b3"),
    "model-00004-of-00006.safetensors": (1606375128, "954d65dc3d831796c82403addffb03cbcb40287f7fd3c8817fa020f858ca27a6"),
    "model-00005-of-00006.safetensors": (1595900808, "bf9a5c71ac43e6609202de7b2a2143232f11cd133dbc7eab0656ada09505b913"),
    "model-00006-of-00006.safetensors": (1118366608, "647f7871bcff8c42e7ec9e760166c9144587c6006114f18b34156a8443963e94"),
}
_AUXILIARY_MODEL_FILES = (
    "config.json",
    "processor_config.json",
    "tokenizer_config.json",
    "tokenizer.json",
    "chat_template.jinja",
    "generation_config.json",
)


class VistaCurrentSourceError(ValueError):
    """可操作的 VISTA 当前源码失败。"""


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def _trace(path: Path | None) -> dict[str, object] | None:
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


def _create_time_ns_text(value: int) -> str:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise VistaCurrentSourceError("VISTA child create time is invalid")
    return str(value)


def _child_state(child: subprocess.Popen[bytes], *, created_ns: int, status: str, exit_code: int | None, cleanup_status: str) -> dict[str, object]:
    return {
        "status": status,
        "pid": int(child.pid),
        "create_time_ns": _create_time_ns_text(created_ns),
        "exit_code": exit_code,
        "cleanup": {
            "status": cleanup_status,
            "pid": int(child.pid),
            "create_time_ns": _create_time_ns_text(created_ns),
            "exit_code": exit_code,
        },
    }


def _process_identity(process: psutil.Process) -> dict[str, object]:
    return {
        "pid": int(process.pid),
        "create_time_ns": _create_time_ns_text(
            int(process.create_time() * 1_000_000_000),
        ),
    }


def _snapshot_owned_tree(child: subprocess.Popen[bytes], *, created_ns: int) -> list[dict[str, object]]:
    """只将同一 PID+创建时间的根及其递归后代视为可终止对象。"""
    try:
        root = psutil.Process(child.pid)
        root_identity = _process_identity(root)
        if root_identity["create_time_ns"] != _create_time_ns_text(created_ns):
            raise VistaCurrentSourceError("VISTA owned root process incarnation changed")
        processes = [root, *root.children(recursive=True)]
        identities = {_process_identity(process)["pid"]: _process_identity(process) for process in processes}
    except (psutil.Error, OSError) as exc:
        raise VistaCurrentSourceError("VISTA owned process tree is unobservable") from exc
    return [identities[pid] for pid in sorted(identities)]


def _listener_pids(port: int) -> list[int]:
    try:
        return sorted({
            int(connection.pid)
            for connection in psutil.net_connections(kind="tcp")
            if connection.status == psutil.CONN_LISTEN
            and connection.pid is not None
            and int(getattr(connection.laddr, "port", connection.laddr[1])) == port
        })
    except (psutil.Error, OSError) as exc:
        raise VistaCurrentSourceError("VISTA listener ownership is unobservable") from exc


def _verify_owned_listener(*, port: int, owned_members: list[dict[str, object]]) -> bool:
    listeners = _listener_pids(port)
    owned_pids = {int(member["pid"]) for member in owned_members}
    if not listeners:
        return False
    if not set(listeners).issubset(owned_pids):
        raise VistaCurrentSourceError("VISTA listener is not owned by this invocation")
    return True


def _current_owned_processes(members: list[dict[str, object]]) -> list[psutil.Process]:
    current: list[psutil.Process] = []
    for member in members:
        try:
            process = psutil.Process(int(member["pid"]))
            if _process_identity(process) == member:
                current.append(process)
        except (psutil.Error, OSError):
            continue
    return current


def _cleanup_owned_tree(child: subprocess.Popen[bytes], *, created_ns: int, members: list[dict[str, object]], port: int, status: str) -> dict[str, object]:
    """仅结束记录过且创建时间匹配的树成员，随后验证端口和成员均消失。"""
    cleanup: dict[str, object] = {
        "status": "failed_exact_child_cleanup",
        "pid": int(child.pid),
        "create_time_ns": _create_time_ns_text(created_ns),
        "exit_code": child.poll(),
        "owned_members": deepcopy(members),
        "active_listeners_after": None,
        "owned_members_after": None,
        "owned_tree_exited": False,
        "listener_absent": False,
    }
    if not members:
        cleanup["error_type"] = "OwnershipProofMissing"
        return {
            "status": status, "pid": int(child.pid),
            "create_time_ns": _create_time_ns_text(created_ns),
            "exit_code": child.poll(), "cleanup": cleanup,
        }
    try:
        processes = _current_owned_processes(members)
        for process in reversed(processes):
            process.terminate()
        _, alive = psutil.wait_procs(processes, timeout=10)
        for process in alive:
            process.kill()
        if alive:
            psutil.wait_procs(alive, timeout=10)
        members_after = [_process_identity(process) for process in _current_owned_processes(members)]
        listeners_after = _listener_pids(port)
    except (psutil.Error, OSError, VistaCurrentSourceError) as error:
        cleanup["error_type"] = type(error).__name__
        cleanup["error"] = str(error)
        return {
            "status": status, "pid": int(child.pid),
            "create_time_ns": _create_time_ns_text(created_ns),
            "exit_code": child.poll(), "cleanup": cleanup,
        }
    cleanup["exit_code"] = child.poll()
    cleanup["owned_members_after"] = members_after
    cleanup["active_listeners_after"] = listeners_after
    if not members_after and not listeners_after:
        cleanup["status"] = "verified_exact_child_killed"
        cleanup["owned_tree_status"] = "verified_owned_tree_reaped"
        cleanup["owned_tree_exited"] = True
        cleanup["listener_absent"] = True
    return {
        "status": status, "pid": int(child.pid),
        "create_time_ns": _create_time_ns_text(created_ns),
        "exit_code": child.poll(), "cleanup": cleanup,
    }


def _read_profile(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VistaCurrentSourceError("VISTA profile is unreadable") from exc
    required = {
        "profile_id", "exclusive_resource_group", "label", "role", "provider_mode",
        "input_format", "runtime", "output_contract", "model_name", "model_path",
        "endpoint", "request_cancel_supported", "request_cancel_endpoint",
        "start_script", "stop_script", "pid_file", "host", "port", "device",
        "dtype", "max_new_tokens", "gpu_memory_gib", "cpu_memory_gib",
        "supports_ocr_anchors", "launchable", "best_for", "limitations",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise VistaCurrentSourceError("VISTA profile is not closed")
    if (
        value.get("profile_id") != "vista_4b_transformers"
        or value.get("model_name") != VISTA_MODEL_NAME
        or value.get("runtime") != "transformers"
        or value.get("dtype") != "bfloat16"
        or value.get("output_contract") != "vista_point_v1"
        or value.get("launchable") is not True
        or value.get("max_new_tokens") != 32
        or value.get("gpu_memory_gib") != 10
    ):
        raise VistaCurrentSourceError("VISTA profile differs from the BF16 contract")
    return value


def _auxiliary_model_identity(model_root: Path) -> list[dict[str, object]]:
    identity: list[dict[str, object]] = []
    for name in _AUXILIARY_MODEL_FILES:
        path = model_root / name
        if not path.is_file():
            raise VistaCurrentSourceError("VISTA model config or tokenizer is unavailable")
        identity.append({
            "name": name,
            "bytes": path.stat().st_size,
            "sha256": _sha256_file(path),
        })
    return identity


def verify_vista_current_source(*, project_root: Path, model_path: Path) -> dict[str, object]:
    """验证当前代码、固定配置和既有主库权重，不复制模型。"""
    project = Path(project_root).resolve()
    expected_model = DEFAULT_MODEL_PATH.resolve()
    actual_model = Path(model_path).resolve()
    if actual_model != expected_model:
        raise VistaCurrentSourceError("VISTA model path is not the trusted local asset")
    profile_path = project / VISTA_PROFILE_PATH
    server_path = project / VISTA_SERVER_PATH
    current_path = project / "app/learn/hybrid/vista_current_source.py"
    if not VISTA_RUNTIME.is_file() or not profile_path.is_file() or not server_path.is_file() or not current_path.is_file():
        raise VistaCurrentSourceError("VISTA current source runtime is unavailable")
    if _sha256_file(profile_path) != _PROFILE_SHA256:
        raise VistaCurrentSourceError("VISTA profile hash differs")
    if _sha256_file(server_path) != _SERVER_SHA256:
        raise VistaCurrentSourceError("VISTA server hash differs")
    profile = _read_profile(profile_path)
    if not actual_model.is_dir():
        raise VistaCurrentSourceError("VISTA trusted model directory is unavailable")
    index = actual_model / "model.safetensors.index.json"
    if not index.is_file() or _sha256_file(index) != _MODEL_INDEX_SHA256:
        raise VistaCurrentSourceError("VISTA model index hash differs")
    shards: list[dict[str, object]] = []
    if {path.name for path in actual_model.glob("model-*.safetensors")} != set(_MODEL_SHARDS):
        raise VistaCurrentSourceError("VISTA model shard set differs")
    for name, (expected_bytes, expected_sha256) in sorted(_MODEL_SHARDS.items()):
        shard = actual_model / name
        if not shard.is_file() or shard.stat().st_size != expected_bytes or _sha256_file(shard) != expected_sha256:
            raise VistaCurrentSourceError("VISTA model shard hash differs")
        shards.append({"name": name, "bytes": expected_bytes, "sha256": expected_sha256})
    return {
        "contract_version": "vista_current_source_receipt_v1",
        "provider_id": VISTA_PROVIDER,
        "model_name": VISTA_MODEL_NAME,
        "runtime_python": str(VISTA_RUNTIME),
        "profile": {"path": str(profile_path), "sha256": _PROFILE_SHA256, "profile_id": profile["profile_id"]},
        "server": {"path": str(server_path), "sha256": _SERVER_SHA256},
        "code_identity": {"app/learn/hybrid/vista_current_source.py": _sha256_file(current_path)},
        "model": {
            "path": str(actual_model), "index_sha256": _MODEL_INDEX_SHA256,
            "shards": shards,
            "auxiliary_identity": _auxiliary_model_identity(actual_model),
        },
    }


def parse_vista_normalized_pair(raw_output_utf8: str) -> list[float]:
    """只接受完整的有限 [x,y]，坐标严格位于 VISTA 归一化闭区间。"""
    if not isinstance(raw_output_utf8, str):
        raise VistaCurrentSourceError("VISTA raw output is not UTF-8 text")
    try:
        value = json.loads(raw_output_utf8)
    except json.JSONDecodeError as exc:
        raise VistaCurrentSourceError("VISTA raw output is not a bare JSON pair") from exc
    if not isinstance(value, list) or len(value) != 2:
        raise VistaCurrentSourceError("VISTA raw output is not a bare JSON pair")
    point: list[float] = []
    for coordinate in value:
        if isinstance(coordinate, bool) or not isinstance(coordinate, (int, float)):
            raise VistaCurrentSourceError("VISTA normalized coordinate is invalid")
        numeric = float(coordinate)
        if not isfinite(numeric) or not 0.0 <= numeric <= 1000.0:
            raise VistaCurrentSourceError("VISTA normalized coordinate is out of range")
        point.append(numeric)
    return point


def _allocate_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _health(port: int, *, timeout_seconds: float = 1.0) -> dict[str, object] | None:
    try:
        with urlrequest.urlopen(f"http://127.0.0.1:{port}/health", timeout=timeout_seconds) as response:
            raw = response.read(16 * 1024)
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, urlerror.URLError):
        return None
    return value if isinstance(value, dict) else None


def _merge_members(existing: list[dict[str, object]], observed: list[dict[str, object]]) -> list[dict[str, object]]:
    values = {
        (int(member["pid"]), str(member["create_time_ns"])): deepcopy(member)
        for member in [*existing, *observed]
    }
    return [values[key] for key in sorted(values)]


def _wait_ready(child: subprocess.Popen[bytes], *, created_ns: int, port: int, timeout_seconds: int, owned_members: list[dict[str, object]]) -> list[dict[str, object]]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if child.poll() is not None:
            raise VistaCurrentSourceError("VISTA owned server exited before readiness")
        owned_members[:] = _merge_members(
            owned_members, _snapshot_owned_tree(child, created_ns=created_ns),
        )
        listener_ready = _verify_owned_listener(port=port, owned_members=owned_members)
        health = _health(port) if listener_ready else None
        if listener_ready and health is not None and health.get("status") == "ok" and health.get("model") == VISTA_MODEL_NAME:
            return owned_members
        time.sleep(0.1)
    raise VistaCurrentSourceError("VISTA owned server readiness timed out")


def _gpu_preflight() -> dict[str, object]:
    try:
        from app.core.gpu_resources import build_model_resource_preflight

        result = build_model_resource_preflight(
            {"profile_id": "vista_4b_transformers", "gpu_memory_gib": 10},
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise VistaCurrentSourceError("VISTA GPU preflight is unavailable") from exc
    if not isinstance(result, dict) or result.get("model_launch_allowed") is not True:
        raise VistaCurrentSourceError("VISTA GPU preflight rejected model launch")
    return deepcopy(result)


def _request_native_pair(*, port: int, roi_bytes: bytes, target_text: str, timeout_seconds: int, response_path: Path) -> str:
    body = json.dumps(
        {
            "model": VISTA_MODEL_NAME,
            "temperature": 0.0,
            "max_tokens": 32,
            "request_timeout_seconds": timeout_seconds,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": target_text + "\nReturn only [x,y] normalized to 0..1000."},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(roi_bytes).decode("ascii")}},
            ]}],
        },
        ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")
    request = urlrequest.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"}, method="POST",
    )
    try:
        with urlrequest.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except (OSError, urlerror.URLError) as exc:
        raise VistaCurrentSourceError("VISTA owned server request failed") from exc
    response_path.write_bytes(raw)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise VistaCurrentSourceError("VISTA owned server response exceeds the limit")
    try:
        payload = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VistaCurrentSourceError("VISTA owned server response is not UTF-8 JSON") from exc
    choices = payload.get("choices") if isinstance(payload, dict) else None
    message = choices[0].get("message") if isinstance(choices, list) and choices and isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise VistaCurrentSourceError("VISTA owned server response has no text content")
    return content


def _write_failure(*, output: Path, stage: str, error: BaseException, child: Mapping[str, object], paths: Mapping[str, Path | None], receipt: Mapping[str, object] | None, roi_sha256: str | None, gpu_preflight: Mapping[str, object] | None) -> None:
    _write_json(output / "failure-result.json", {
        "contract_version": "vista_current_source_failure_v1",
        "outcome": "failed",
        "failure_stage": stage,
        "error": {"type": type(error).__name__, "message": str(error)},
        "child": deepcopy(dict(child)),
        "traces": {name: _trace(path) for name, path in paths.items()},
        "current_source_receipt": deepcopy(dict(receipt)) if receipt is not None else None,
        "roi_image_sha256": roi_sha256,
        "gpu_preflight": deepcopy(dict(gpu_preflight)) if gpu_preflight is not None else None,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    })


def run_vista_once(*, project_root: Path, image_path: Path, target_text: str, out_dir: Path, model_path: Path = DEFAULT_MODEL_PATH) -> dict[str, object]:
    """为一张已准备 ROI 运行一次 VISTA，任何失败都留下非成功持久化记录。"""
    project = Path(project_root).resolve()
    image = Path(image_path).resolve()
    output = Path(out_dir).resolve()
    if not project.is_dir() or not output.is_relative_to(project):
        raise VistaCurrentSourceError("VISTA output must remain under project root")
    if not image.is_file() or not image.is_relative_to(project):
        raise VistaCurrentSourceError("VISTA ROI image must remain under project root")
    if not isinstance(target_text, str) or not target_text.strip() or len(target_text) > 512:
        raise VistaCurrentSourceError("VISTA target text is invalid")
    output.mkdir(parents=True, exist_ok=False)
    stage = "source_identity"
    child: Mapping[str, object] = _not_started_child()
    receipt: dict[str, object] | None = None
    gpu_preflight: dict[str, object] | None = None
    roi_sha256 = _sha256_file(image)
    paths: dict[str, Path | None] = {
        "stdout": output / "vista.stdout.utf8",
        "stderr": output / "vista.stderr.utf8",
        "response": output / "vista.response.bin",
    }
    server: subprocess.Popen[bytes] | None = None
    created_ns = 0
    owned_members: list[dict[str, object]] = []
    try:
        stage = "gpu_preflight"
        gpu_preflight = _gpu_preflight()
        stage = "source_identity"
        receipt = verify_vista_current_source(project_root=project, model_path=model_path)
        port = _allocate_port()
        command = [
            str(VISTA_RUNTIME), "-B", str(project / VISTA_SERVER_PATH),
            "--model-path", str(Path(model_path).resolve()), "--model-name", VISTA_MODEL_NAME,
            "--host", "127.0.0.1", "--port", str(port), "--device", "auto",
            "--dtype", "bfloat16", "--max-new-tokens", "32",
            "--gpu-memory-gib", "10", "--cpu-memory-gib", "2",
        ]
        _write_json(output / "invocation.json", {
            "contract_version": "vista_current_source_invocation_v1",
            "roi_image_path": str(image), "roi_image_sha256": roi_sha256,
            "target_text": target_text, "target_sha256": sha256(target_text.encode("utf-8")).hexdigest(),
            "current_source_receipt": receipt, "port": port,
        })
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        with paths["stdout"].open("wb") as stdout, paths["stderr"].open("wb") as stderr:
            server = subprocess.Popen(command, cwd=str(project), stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, creationflags=flags)
            try:
                import psutil
            except ImportError:
                created_ns = 0
            else:
                try:
                    created_ns = int(psutil.Process(server.pid).create_time() * 1_000_000_000)
                except (OSError, psutil.Error):
                    created_ns = 0
            owned_members = _snapshot_owned_tree(server, created_ns=created_ns)
            stage = "server_readiness"
            owned_members = _wait_ready(
                server, created_ns=created_ns, port=port,
                timeout_seconds=DEFAULT_TIMEOUT_SECONDS, owned_members=owned_members,
            )
            stage = "native_request"
            owned_members = _merge_members(
                owned_members, _snapshot_owned_tree(server, created_ns=created_ns),
            )
            if not _verify_owned_listener(port=port, owned_members=owned_members):
                raise VistaCurrentSourceError("VISTA owned server listener disappeared before request")
            raw = _request_native_pair(
                port=port, roi_bytes=image.read_bytes(), target_text=target_text,
                timeout_seconds=DEFAULT_TIMEOUT_SECONDS, response_path=paths["response"],
            )
            stage = "native_parse"
            point = parse_vista_normalized_pair(raw)
            owned_members = _merge_members(
                owned_members, _snapshot_owned_tree(server, created_ns=created_ns),
            )
            child = _cleanup_owned_tree(
                server, created_ns=created_ns, members=owned_members,
                port=port, status="completed",
            )
            if child["cleanup"]["status"] != "verified_exact_child_killed":
                raise VistaCurrentSourceError("VISTA owned server cleanup is unverified")
            server = None
        result = {
            "contract_version": "vista_current_source_result_v1",
            "raw_output_utf8": raw,
            "source_score": None,
            "provider_id": VISTA_PROVIDER,
            "native_profile": {"contract_version": "vista_native_profile_v1", "native_shape": "vista_normalized_pair_v1", "coordinate_space": "normalized_0_1000"},
            "native_output_ref": {"id": "vista-current-source/" + uuid4().hex, "sha256": sha256(raw.encode("utf-8")).hexdigest()},
            "normalized_point_0_1000": point,
            "roi_image_sha256": roi_sha256,
            "current_source_receipt": receipt,
            "target_sha256": sha256(target_text.encode("utf-8")).hexdigest(),
            "gpu_preflight": gpu_preflight,
            "cleanup": child["cleanup"],
            "child": child,
            "traces": {name: _trace(path) for name, path in paths.items()},
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        }
        _write_json(output / "result.json", result)
        return result
    except (VistaCurrentSourceError, OSError) as error:
        if server is not None:
            try:
                owned_members = _merge_members(
                    owned_members, _snapshot_owned_tree(server, created_ns=created_ns),
                )
            except VistaCurrentSourceError:
                pass
            child = _cleanup_owned_tree(
                server, created_ns=created_ns, members=owned_members,
                port=port, status="failed",
            )
        _write_failure(output=output, stage=stage, error=error, child=child, paths=paths, receipt=receipt, roi_sha256=roi_sha256, gpu_preflight=gpu_preflight)
        raise
    except KeyboardInterrupt as error:
        if server is not None:
            try:
                owned_members = _merge_members(
                    owned_members, _snapshot_owned_tree(server, created_ns=created_ns),
                )
            except VistaCurrentSourceError:
                pass
            child = _cleanup_owned_tree(
                server, created_ns=created_ns, members=owned_members,
                port=port, status="interrupted",
            )
        _write_failure(output=output, stage="interrupted", error=error, child=child, paths=paths, receipt=receipt, roi_sha256=roi_sha256, gpu_preflight=gpu_preflight)
        raise


__all__ = ["DEFAULT_MODEL_PATH", "VISTA_PROVIDER", "VistaCurrentSourceError", "parse_vista_normalized_pair", "run_vista_once", "verify_vista_current_source"]
