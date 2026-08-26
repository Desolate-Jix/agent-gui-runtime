"""Benchmark-v2 spawned observation worker 的精确只读窗口绑定。"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import sys
from threading import RLock
from typing import Any, Iterator, Mapping

from app.core.window_manager import BoundWindow, window_manager
from app.learn.hybrid.benchmark_v2_contracts import (
    canonical_json_bytes,
    content_sha256,
    require_sha256,
)
from app.learn.hybrid.benchmark_v2_window_owner import (
    _load_events,
    _load_root,
    _raw_hwnd_attestation,
    _validate_binding,
)
from app.operation.screen_reading.uia_provider import (
    pinned_uia_snapshot,
    uia_provider,
)


WORKER_BINDING_CONTRACT = "portfolio_hybrid_benchmark_v2_worker_window_binding_v1"
JOB_MEMBERSHIP_REF_CONTRACT = (
    "portfolio_hybrid_benchmark_v2_worker_job_membership_ref_v1"
)
SNAPSHOT_REF_CONTRACT = "portfolio_hybrid_benchmark_v2_worker_uia_snapshot_ref_v1"
ADOPTED_RECEIPT_CONTRACT = (
    "portfolio_hybrid_benchmark_v2_worker_window_binding_adopted_v1"
)
NORMAL_CLEAR_RECEIPT_CONTRACT = (
    "portfolio_hybrid_benchmark_v2_worker_window_binding_normal_clear_v1"
)
_INSTALL_LOCK = RLock()
_SERIALIZED_FIELDS = {
    "contract_version",
    "operation_id",
    "exact_hwnd",
    "process_identity",
    "job_name",
    "job_membership_ref",
    "screenshot_sha256",
    "capture_sha256",
    "capture_image_path",
    "image_dimensions",
    "owner_journal_path",
    "owner_journal_content_sha256",
    "owner_ready_event_sha256",
    "owner_binding_content_sha256",
    "owner_id",
    "expected_uia_root_hwnd",
    "expected_uia_owner_pid",
    "expected_uia_root_content_sha256",
    "window_class",
    "window_title",
    "window_rect",
    "client_rect",
    "dpi",
    "artifact_is_authorization",
    "execute_binding_enabled",
    "display_only",
    "payload_sha256",
}


def _payload_sha256(value: Mapping[str, object]) -> str:
    unhashed = {key: item for key, item in value.items() if key != "payload_sha256"}
    return hashlib.sha256(canonical_json_bytes(unhashed)).hexdigest()


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{name} must be exact non-empty text")
    return value


def _process_identity(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping) or set(value) != {"pid", "create_time_ns"}:
        raise ValueError("worker binding process identity is invalid")
    pid = value.get("pid")
    create_time_ns = value.get("create_time_ns")
    if (
        isinstance(pid, bool)
        or not isinstance(pid, int)
        or pid <= 0
        or isinstance(create_time_ns, bool)
        or not isinstance(create_time_ns, int)
        or create_time_ns <= 0
    ):
        raise ValueError("worker binding process identity is invalid")
    return {"pid": pid, "create_time_ns": create_time_ns}


def _capture_sha256(capture_ref: Mapping[str, object]) -> str:
    value = capture_ref.get("capture_sha256")
    if value is None:
        value = capture_ref.get("screenshot_sha256")
    if value is None:
        value = capture_ref.get("content_sha256")
    return require_sha256(value, "capture_sha256")


def _capture_image_path(capture_ref: Mapping[str, object]) -> Path:
    value = capture_ref.get("capture_image_path")
    if value is None:
        value = capture_ref.get("image_path")
    path = Path(_required_text(value, "capture_image_path"))
    if not path.is_absolute() or str(path) != str(path.resolve()):
        raise ValueError("worker binding capture image path must be canonical and absolute")
    return path


def _job_membership_ref(
    *, job_name: str, process_identity: Mapping[str, int], members: list[int]
) -> dict[str, object]:
    value: dict[str, object] = {
        "contract_version": JOB_MEMBERSHIP_REF_CONTRACT,
        "job_name": job_name,
        "process_identity": dict(process_identity),
        "member_pids": list(members),
    }
    value["content_sha256"] = content_sha256(value)
    return value


def serialize_worker_window_binding(
    *,
    operation_ref: Mapping[str, object],
    owner: Mapping[str, object],
    capture_ref: Mapping[str, object],
) -> dict[str, object]:
    """把server-owned owner journal收敛为spawn可传递的闭集。"""

    if not isinstance(operation_ref, Mapping):
        raise ValueError("worker binding operation_ref must be an object")
    if not isinstance(owner, Mapping):
        raise ValueError("worker binding owner must be an object")
    if not isinstance(capture_ref, Mapping):
        raise ValueError("worker binding capture_ref must be an object")
    operation_id = _required_text(operation_ref.get("operation_id"), "operation_id")
    if owner.get("operation_id") != operation_id:
        raise ValueError("worker binding operation lineage differs")
    _validate_binding(owner)
    attestation = _raw_hwnd_attestation(owner)
    process_identity = _process_identity(owner.get("process_identity"))
    capture_sha256 = _capture_sha256(capture_ref)
    screenshot_sha256 = require_sha256(
        owner.get("screenshot_sha256"), "screenshot_sha256"
    )
    if capture_sha256 != screenshot_sha256:
        raise ValueError("worker binding capture SHA differs from screenshot")
    capture_image_path = _capture_image_path(capture_ref)
    if str(capture_image_path) != owner.get("screenshot_path"):
        raise ValueError("worker binding capture image path differs from screenshot")
    journal_path = Path(_required_text(owner.get("journal_path"), "owner_journal_path"))
    if not journal_path.is_absolute() or str(journal_path) != str(journal_path.resolve()):
        raise ValueError("worker binding owner journal path must be canonical and absolute")
    uia_root = owner.get("uia_root_identity")
    if not isinstance(uia_root, Mapping):
        raise ValueError("worker binding expected UIA root is invalid")
    expected_hwnd = uia_root.get("window_handle")
    expected_pid = uia_root.get("window_process_id")
    if expected_hwnd != owner.get("hwnd") or expected_pid != process_identity["pid"]:
        raise ValueError("worker binding expected UIA root differs")
    expected_uia_sha256 = require_sha256(
        uia_root.get("content_sha256"), "expected_uia_root_content_sha256"
    )
    events = _load_events(journal_path, owner_id=str(owner["owner_id"]))
    ready = [event for event in events if event.get("event_type") == "ready"]
    if len(ready) != 1:
        raise ValueError("worker binding owner ready event is ambiguous")
    members = list(attestation["job_member_pids"])
    job_name = _required_text(owner.get("scope_name"), "job_name")
    serialized: dict[str, object] = {
        "contract_version": WORKER_BINDING_CONTRACT,
        "operation_id": operation_id,
        "exact_hwnd": int(owner["hwnd"]),
        "process_identity": process_identity,
        "job_name": job_name,
        "job_membership_ref": _job_membership_ref(
            job_name=job_name,
            process_identity=process_identity,
            members=members,
        ),
        "screenshot_sha256": screenshot_sha256,
        "capture_sha256": capture_sha256,
        "capture_image_path": str(capture_image_path),
        "image_dimensions": deepcopy(dict(owner["image_dimensions"])),
        "owner_journal_path": str(journal_path),
        "owner_journal_content_sha256": require_sha256(
            owner.get("journal_root_sha256"), "owner_journal_content_sha256"
        ),
        "owner_ready_event_sha256": require_sha256(
            ready[0].get("content_sha256"), "owner_ready_event_sha256"
        ),
        "owner_binding_content_sha256": require_sha256(
            owner.get("content_sha256"), "owner_binding_content_sha256"
        ),
        "owner_id": _required_text(owner.get("owner_id"), "owner_id"),
        "expected_uia_root_hwnd": int(expected_hwnd),
        "expected_uia_owner_pid": int(expected_pid),
        "expected_uia_root_content_sha256": expected_uia_sha256,
        "window_class": _required_text(owner.get("window_class"), "window_class"),
        "window_title": _required_text(owner.get("window_title"), "window_title"),
        "window_rect": deepcopy(dict(owner["window_rect"])),
        "client_rect": deepcopy(dict(owner["client_rect"])),
        "dpi": int(owner["dpi"]),
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "display_only": True,
    }
    serialized["payload_sha256"] = _payload_sha256(serialized)
    return serialized


def _validate_job_ref(
    value: object,
    *,
    job_name: str,
    process_identity: Mapping[str, int],
) -> dict[str, object]:
    fields = {
        "contract_version",
        "job_name",
        "process_identity",
        "member_pids",
        "content_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError("worker binding Job membership ref is invalid")
    ref = deepcopy(dict(value))
    if (
        ref.get("contract_version") != JOB_MEMBERSHIP_REF_CONTRACT
        or ref.get("job_name") != job_name
        or ref.get("process_identity") != dict(process_identity)
        or ref.get("member_pids") != [process_identity["pid"]]
        or ref.get("content_sha256") != content_sha256(ref)
    ):
        raise ValueError("worker binding Job membership ref differs")
    return ref


def _validate_serialized(value: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != _SERIALIZED_FIELDS:
        raise ValueError("worker binding serialized schema is not closed")
    serialized = deepcopy(dict(value))
    if serialized.get("contract_version") != WORKER_BINDING_CONTRACT:
        raise ValueError("worker binding contract is invalid")
    if serialized.get("payload_sha256") != _payload_sha256(serialized):
        raise ValueError("worker binding payload SHA is invalid")
    operation_id = _required_text(serialized.get("operation_id"), "operation_id")
    process_identity = _process_identity(serialized.get("process_identity"))
    job_name = _required_text(serialized.get("job_name"), "job_name")
    _validate_job_ref(
        serialized.get("job_membership_ref"),
        job_name=job_name,
        process_identity=process_identity,
    )
    screenshot_sha256 = require_sha256(
        serialized.get("screenshot_sha256"), "screenshot_sha256"
    )
    capture_sha256 = require_sha256(
        serialized.get("capture_sha256"), "capture_sha256"
    )
    if capture_sha256 != screenshot_sha256:
        raise ValueError("worker binding capture SHA differs from screenshot")
    capture_image_path = Path(
        _required_text(serialized.get("capture_image_path"), "capture_image_path")
    )
    if (
        not capture_image_path.is_absolute()
        or str(capture_image_path) != str(capture_image_path.resolve())
    ):
        raise ValueError("worker binding capture image path must be canonical and absolute")
    path = Path(_required_text(serialized.get("owner_journal_path"), "owner_journal_path"))
    if not path.is_absolute() or str(path) != str(path.resolve()):
        raise ValueError("worker binding journal path must be canonical and absolute")
    require_sha256(
        serialized.get("owner_journal_content_sha256"),
        "owner_journal_content_sha256",
    )
    require_sha256(
        serialized.get("owner_ready_event_sha256"),
        "owner_ready_event_sha256",
    )
    require_sha256(
        serialized.get("owner_binding_content_sha256"),
        "owner_binding_content_sha256",
    )
    _required_text(serialized.get("owner_id"), "owner_id")
    require_sha256(
        serialized.get("expected_uia_root_content_sha256"),
        "expected_uia_root_content_sha256",
    )
    exact_hwnd = serialized.get("exact_hwnd")
    expected_hwnd = serialized.get("expected_uia_root_hwnd")
    expected_pid = serialized.get("expected_uia_owner_pid")
    if (
        isinstance(exact_hwnd, bool)
        or not isinstance(exact_hwnd, int)
        or exact_hwnd <= 0
        or expected_hwnd != exact_hwnd
        or expected_pid != process_identity["pid"]
    ):
        raise ValueError("worker binding expected HWND or owner PID differs")
    _required_text(serialized.get("window_class"), "window_class")
    _required_text(serialized.get("window_title"), "window_title")
    for name, fields in (
        (
            "client_rect",
            {"left", "top", "right", "bottom", "width", "height"},
        ),
        ("window_rect", {"left", "top", "right", "bottom"}),
        ("image_dimensions", {"width", "height"}),
    ):
        rect = serialized.get(name)
        if not isinstance(rect, Mapping) or set(rect) != fields:
            raise ValueError(f"worker binding {name} is invalid")
        if any(
            isinstance(item, bool) or not isinstance(item, int)
            for item in rect.values()
        ):
            raise ValueError(f"worker binding {name} is invalid")
    dpi = serialized.get("dpi")
    if isinstance(dpi, bool) or not isinstance(dpi, int) or dpi <= 0:
        raise ValueError("worker binding DPI is invalid")
    if (
        serialized.get("artifact_is_authorization") is not False
        or serialized.get("execute_binding_enabled") is not False
        or serialized.get("display_only") is not True
    ):
        raise ValueError("worker binding safety seal is invalid")
    serialized["operation_id"] = operation_id
    return serialized


def _owner_from_journal(serialized: Mapping[str, object]) -> dict[str, object]:
    journal_path = Path(str(serialized["owner_journal_path"]))
    root = _load_root(journal_path)
    if root.get("content_sha256") != serialized["owner_journal_content_sha256"]:
        raise ValueError("worker binding journal content ref differs")
    events = _load_events(journal_path, owner_id=str(root["owner_id"]))
    ready = [event for event in events if event.get("event_type") == "ready"]
    if len(ready) != 1:
        raise ValueError("worker binding owner journal ready receipt is ambiguous")
    if ready[0].get("content_sha256") != serialized["owner_ready_event_sha256"]:
        raise ValueError("worker binding owner ready event ref differs")
    payload = ready[0].get("payload")
    owner = payload.get("binding") if isinstance(payload, Mapping) else None
    if not isinstance(owner, Mapping):
        raise ValueError("worker binding owner journal lost sealed binding")
    owner = deepcopy(dict(owner))
    return owner


def _assert_owner_matches_serialized(
    *, serialized: Mapping[str, object], owner: Mapping[str, object]
) -> dict[str, object]:
    process_identity = dict(serialized["process_identity"])
    expected = {
        "operation_id": serialized["operation_id"],
        "owner_id": serialized["owner_id"],
        "hwnd": serialized["exact_hwnd"],
        "process_identity": process_identity,
        "scope_name": serialized["job_name"],
        "screenshot_sha256": serialized["screenshot_sha256"],
        "screenshot_path": serialized["capture_image_path"],
        "image_dimensions": serialized["image_dimensions"],
        "journal_path": serialized["owner_journal_path"],
        "journal_root_sha256": serialized["owner_journal_content_sha256"],
        "content_sha256": serialized["owner_binding_content_sha256"],
        "window_class": serialized["window_class"],
        "window_title": serialized["window_title"],
        "window_rect": serialized["window_rect"],
        "client_rect": serialized["client_rect"],
        "dpi": serialized["dpi"],
    }
    if any(owner.get(key) != item for key, item in expected.items()):
        raise ValueError("worker binding owner journal lineage differs")
    uia_identity = owner.get("uia_root_identity")
    if (
        not isinstance(uia_identity, Mapping)
        or uia_identity.get("window_handle") != serialized["expected_uia_root_hwnd"]
        or uia_identity.get("window_process_id") != serialized["expected_uia_owner_pid"]
        or uia_identity.get("content_sha256")
        != serialized["expected_uia_root_content_sha256"]
    ):
        raise ValueError("worker binding expected UIA identity differs")
    attestation = _raw_hwnd_attestation(owner)
    if (
        attestation.get("process_identity") != process_identity
        or attestation.get("job_member_pids") != [process_identity["pid"]]
        or attestation.get("hwnd") != serialized["exact_hwnd"]
        or attestation.get("client_rect") != serialized["client_rect"]
        or attestation.get("dpi") != serialized["dpi"]
        or attestation.get("screenshot_sha256") != serialized["screenshot_sha256"]
    ):
        raise ValueError("worker binding child attestation differs")
    return attestation


def _snapshot_sha256(snapshot: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json_bytes(snapshot)).hexdigest()


def _snapshot_ref(snapshot: Mapping[str, object]) -> dict[str, object]:
    value: dict[str, object] = {
        "contract_version": SNAPSHOT_REF_CONTRACT,
        "provider": snapshot.get("provider"),
        "provider_version": snapshot.get("provider_version"),
        "control_count": snapshot.get("control_count"),
        "content_sha256": _snapshot_sha256(snapshot),
    }
    return value


def validate_spawned_worker_uia_snapshot(
    *,
    snapshot: Mapping[str, object],
    serialized: Mapping[str, object],
    owner: Mapping[str, object],
) -> dict[str, object]:
    sealed = _validate_serialized(serialized)
    if not isinstance(snapshot, Mapping):
        raise ValueError("worker binding UIA snapshot is invalid")
    if set(snapshot) != {
        "control_count",
        "controls",
        "provider",
        "provider_version",
        "status",
        "window",
    }:
        raise ValueError("worker binding UIA snapshot schema is not closed")
    window = snapshot.get("window")
    controls = snapshot.get("controls")
    if (
        snapshot.get("provider") != "windows_uia"
        or snapshot.get("provider_version") != "windows_uia_provider_v1"
        or snapshot.get("status") != "ok"
        or not isinstance(window, Mapping)
        or set(window)
        != {"handle", "title", "process_id", "process_name", "bbox"}
        or not isinstance(controls, list)
        or not controls
        or snapshot.get("control_count") != len(controls)
        or not isinstance(controls[0], Mapping)
    ):
        raise ValueError("worker binding child-local UIA snapshot is invalid")
    outer = dict(sealed["window_rect"])
    expected_outer = {
        "x": outer["left"],
        "y": outer["top"],
        "w": outer["right"] - outer["left"],
        "h": outer["bottom"] - outer["top"],
    }
    expected_local = {
        "x": 0,
        "y": 0,
        "w": expected_outer["w"],
        "h": expected_outer["h"],
    }
    root = controls[0]
    control_fields = {
        "provider",
        "control_id",
        "name",
        "control_type",
        "automation_id",
        "class_name",
        "bbox",
        "screen_bbox",
        "enabled",
        "visible",
        "patterns",
    }
    if any(not isinstance(control, Mapping) or set(control) != control_fields for control in controls):
        raise ValueError("worker binding UIA control schema is not closed")
    owner_uia = owner.get("uia_root_identity")
    owner_root = owner_uia.get("root_control") if isinstance(owner_uia, Mapping) else None
    if (
        window.get("handle") != sealed["expected_uia_root_hwnd"]
        or window.get("process_id") != sealed["expected_uia_owner_pid"]
        or window.get("title") != sealed["window_title"]
        or window.get("process_name") != Path(sys._base_executable).name
        or window.get("bbox") != expected_local
        or not isinstance(owner_root, Mapping)
        or root.get("control_id") != owner_root.get("control_id")
        or root.get("name") != owner_root.get("name")
        or root.get("control_type") != owner_root.get("control_type")
        or root.get("automation_id") != owner_root.get("automation_id")
        or root.get("class_name") != owner_root.get("class_name")
        or root.get("screen_bbox") != expected_outer
        or root.get("bbox") != expected_local
        or root.get("provider") != "windows_uia"
        or root.get("enabled") is not True
        or root.get("visible") is not True
        or root.get("patterns")
        != ["Invoke", "Value", "Text", "Selection", "ExpandCollapse", "Toggle"]
    ):
        raise ValueError("worker binding child-local UIA snapshot root differs")
    return _snapshot_ref(snapshot)


def validate_spawned_worker_observation_payload(
    *, payload: Mapping[str, object], serialized: Mapping[str, object]
) -> None:
    sealed = _validate_serialized(serialized)
    if not isinstance(payload, Mapping):
        raise ValueError("worker observation payload must be an object")
    if payload.get("capture_live") is not False:
        raise ValueError("benchmark-v2 worker capture_live must be false")
    image_path = payload.get("image_path")
    if image_path != sealed["capture_image_path"]:
        raise ValueError("benchmark-v2 worker image_path differs from sealed capture")


@contextmanager
def _hold_screenshot_read_only(path: Path) -> Iterator[bytes]:
    if os.name != "nt":
        raise RuntimeError("Windows screenshot sharing seal is unavailable")
    import msvcrt

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(str(path), 0x80000000, 0x00000001, None, 3, 0x80, None)
    invalid = ctypes.c_void_p(-1).value
    if not handle or int(handle) == invalid:
        raise ValueError("worker binding screenshot read-only sharing handle failed")
    descriptor = None
    stream = None
    try:
        descriptor = msvcrt.open_osfhandle(int(handle), os.O_RDONLY | os.O_BINARY)
        handle = None
        stream = os.fdopen(descriptor, "rb")
        descriptor = None
        raw = stream.read()
        stream.seek(0)
        yield raw
    finally:
        if stream is not None:
            stream.close()
        elif descriptor is not None:
            os.close(descriptor)
        elif handle is not None:
            kernel.CloseHandle(handle)


def _adopted_receipt(
    *, serialized: Mapping[str, object], snapshot: Mapping[str, object]
) -> dict[str, object]:
    value: dict[str, object] = {
        "contract_version": ADOPTED_RECEIPT_CONTRACT,
        "operation_id": serialized["operation_id"],
        "binding_payload_sha256": serialized["payload_sha256"],
        "capture_sha256": serialized["capture_sha256"],
        "uia_root_hwnd": serialized["expected_uia_root_hwnd"],
        "uia_owner_pid": serialized["expected_uia_owner_pid"],
        "snapshot_ref": _snapshot_ref(snapshot),
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    value["content_sha256"] = content_sha256(value)
    return value


def _normal_clear_receipt(
    *, serialized: Mapping[str, object], prior: BoundWindow | None
) -> dict[str, object]:
    current = window_manager._bound_window
    if prior is None:
        cleared = current is None
        restored_hwnd = None
    else:
        cleared = current is prior
        restored_hwnd = prior.handle if current is prior else None
    if not cleared:
        raise RuntimeError("worker binding process-local state was not restored")
    value: dict[str, object] = {
        "contract_version": NORMAL_CLEAR_RECEIPT_CONTRACT,
        "operation_id": serialized["operation_id"],
        "binding_payload_sha256": serialized["payload_sha256"],
        "worker_pid": os.getpid(),
        "cleared": True,
        "prior_binding_restored": prior is not None,
        "restored_hwnd": restored_hwnd,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    value["content_sha256"] = content_sha256(value)
    return value


@contextmanager
def install_spawned_worker_window_binding(
    *,
    serialized: Mapping[str, object],
    worker_operation_id: str,
) -> Iterator[dict[str, object]]:
    """在当前spawn child中重验、绑定并仅发布只读pinned UIA snapshot。"""

    sealed = _validate_serialized(serialized)
    operation_id = _required_text(worker_operation_id, "worker_operation_id")
    if operation_id != sealed["operation_id"]:
        raise ValueError("worker binding operation ID differs")
    lifecycle: dict[str, object] = {}
    with _INSTALL_LOCK:
        prior = window_manager._bound_window
        from app.operation.screen_reading.uia_provider import _PINNED_UIA_SNAPSHOT

        if prior is not None or _PINNED_UIA_SNAPSHOT.get() is not None:
            raise ValueError("worker binding ambient or multiple bound window exists")
        pinned = None
        try:
            owner = _owner_from_journal(sealed)
            screenshot_path = Path(str(sealed["capture_image_path"]))
            with _hold_screenshot_read_only(screenshot_path) as screenshot_raw:
                if (
                    hashlib.sha256(screenshot_raw).hexdigest()
                    != sealed["screenshot_sha256"]
                ):
                    raise ValueError("worker binding screenshot SHA is stale")
                _validate_binding(owner)
                pre = _assert_owner_matches_serialized(serialized=sealed, owner=owner)
                bound = window_manager.bind_window_by_handle(int(sealed["exact_hwnd"]))
                if (
                    bound.handle != sealed["expected_uia_root_hwnd"]
                    or bound.process_id != sealed["expected_uia_owner_pid"]
                ):
                    raise ValueError("worker binding bound HWND owner differs")
                snapshot = uia_provider.snapshot_bound_window()
                validate_spawned_worker_uia_snapshot(
                    snapshot=snapshot,
                    serialized=sealed,
                    owner=owner,
                )
                post = _raw_hwnd_attestation(owner)
                if pre != post:
                    raise ValueError("worker binding changed around child UIA snapshot")
                lifecycle["snapshot"] = deepcopy(dict(snapshot))
                lifecycle["adopted_receipt"] = _adopted_receipt(
                    serialized=sealed,
                    snapshot=snapshot,
                )
                pinned = pinned_uia_snapshot(snapshot)
                pinned.__enter__()
                yield lifecycle
        finally:
            if pinned is not None:
                pinned.__exit__(None, None, None)
            window_manager._bound_window = prior
            lifecycle["normal_clear_receipt"] = _normal_clear_receipt(
                serialized=sealed,
                prior=prior,
            )
