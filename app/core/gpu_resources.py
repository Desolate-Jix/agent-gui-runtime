from __future__ import annotations

import csv
import locale
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import psutil

from app.core.model_server import load_model_profiles, model_profile_pid_path


ROOT_DIR = Path(__file__).resolve().parents[2]


def build_model_resource_preflight(profile: dict[str, Any]) -> dict[str, Any]:
    """在启动真实模型前评估用户侧 GPU 与系统内存占用。"""

    snapshot = _gpu_snapshot()
    known_pids = _known_model_pids()
    profile_pids = _profile_model_pids(profile)
    resident_profile = bool(profile_pids & known_pids)
    processes = [item for item in snapshot.get("compute_processes") or [] if isinstance(item, dict)]
    known_processes = [item for item in processes if int(item.get("pid") or 0) in known_pids]
    observed_external_processes = [item for item in processes if int(item.get("pid") or 0) not in known_pids]
    external_processes = [item for item in observed_external_processes if int(item.get("used_memory_mib") or 0) > 0]
    reported_known_memory_mib = sum(max(0, int(item.get("used_memory_mib") or 0)) for item in known_processes)
    devices = [item for item in snapshot.get("devices") or [] if isinstance(item, dict)]
    total_memory_mib = sum(max(0, int(item.get("memory_total_mib") or 0)) for item in devices)
    used_memory_mib = sum(max(0, int(item.get("memory_used_mib") or 0)) for item in devices)
    available_memory_mib = sum(max(0, int(item.get("memory_free_mib") or 0)) for item in devices)
    reserved_known_memory_mib = _known_model_reserved_memory_mib(known_pids)
    if known_processes and reported_known_memory_mib == 0 and reserved_known_memory_mib > 0:
        known_memory_mib = min(used_memory_mib, reserved_known_memory_mib)
        known_memory_source = "profile_reserved_memory"
    else:
        known_memory_mib = reported_known_memory_mib
        known_memory_source = "nvidia_process_memory"
    requested_memory_mib = max(0, int(float(profile.get("gpu_memory_gib") or 0) * 1024))
    required_launch_memory_mib = int(requested_memory_mib * 0.9)
    external_memory_mib = max(0, used_memory_mib - known_memory_mib)
    external_memory_ratio = external_memory_mib / total_memory_mib if total_memory_mib else 0.0
    max_utilization = max((max(0, int(item.get("utilization_percent") or 0)) for item in devices), default=0)
    utilization_attributed_to_known_model = bool(known_processes) and not external_processes and external_memory_ratio < 0.18

    memory = psutil.virtual_memory()
    system_available_ratio = float(memory.available) / float(memory.total) if memory.total else 0.0
    reason_codes: list[str] = []
    severity = 0
    if snapshot.get("available") is not True:
        reason_codes.append("gpu_probe_unavailable")
        severity = max(severity, 1)
    if external_processes:
        reason_codes.append("external_gpu_process_detected")
        severity = max(severity, 1)
    if (
        not external_processes
        and observed_external_processes
        and external_memory_ratio >= 0.18
        and max_utilization >= 5
    ):
        reason_codes.append("unattributed_wddm_gpu_memory_use")
        severity = max(severity, 1)
    if external_memory_ratio >= 0.65:
        reason_codes.append("high_external_gpu_memory_use")
        severity = max(severity, 2)
    elif external_memory_ratio >= 0.25:
        reason_codes.append("elevated_external_gpu_memory_use")
        severity = max(severity, 1)
    if not utilization_attributed_to_known_model:
        if max_utilization >= 70:
            reason_codes.append("high_gpu_utilization")
            severity = max(severity, 2)
        elif max_utilization >= 35:
            reason_codes.append("elevated_gpu_utilization")
            severity = max(severity, 1)
    if (
        snapshot.get("available") is True
        and requested_memory_mib > 0
        and not known_processes
        and available_memory_mib < required_launch_memory_mib
    ):
        reason_codes.append("insufficient_gpu_memory_for_profile")
        severity = max(severity, 2)
    if system_available_ratio < 0.10:
        if resident_profile:
            reason_codes.append("low_system_memory_with_resident_profile")
            severity = max(severity, 1)
        else:
            reason_codes.append("low_system_memory")
            severity = max(severity, 2)
    elif system_available_ratio < 0.20:
        reason_codes.append("constrained_system_memory")
        severity = max(severity, 1)

    resource_mode = "critical" if severity >= 2 else ("constrained" if severity == 1 else "normal")
    recommended_batch_size = (
        1
        if resource_mode == "critical"
        or "low_system_memory_with_resident_profile" in reason_codes
        else (2 if resource_mode == "constrained" else 8)
    )
    return {
        "contract_version": "model_resource_preflight_v1",
        "status": "ready" if snapshot.get("available") is True else "degraded",
        "profile_id": str(profile.get("profile_id") or "") or None,
        "requested_gpu_memory_gib": float(profile.get("gpu_memory_gib") or 0),
        "requested_gpu_memory_mib": requested_memory_mib,
        "required_launch_gpu_memory_mib": required_launch_memory_mib,
        "available_gpu_memory_mib": available_memory_mib,
        "resource_mode": resource_mode,
        "model_launch_allowed": resource_mode != "critical",
        "recommended_batch_size": recommended_batch_size,
        "reason_codes": reason_codes,
        "gpu": {
            "available": snapshot.get("available") is True,
            "probe_reason": snapshot.get("reason"),
            "devices": devices,
            "total_memory_mib": total_memory_mib,
            "used_memory_mib": used_memory_mib,
            "known_model_memory_mib": known_memory_mib,
            "known_model_memory_source": known_memory_source,
            "utilization_attributed_to_known_model": utilization_attributed_to_known_model,
            "estimated_external_memory_mib": external_memory_mib,
            "estimated_external_memory_ratio": round(external_memory_ratio, 4),
            "max_utilization_percent": max_utilization,
        },
        "external_gpu_process_count": len(external_processes),
        "external_gpu_processes": external_processes,
        "observed_external_gpu_process_count": len(observed_external_processes),
        "observed_external_gpu_processes": observed_external_processes,
        "known_model_process_count": len(known_processes),
        "resident_profile": resident_profile,
        "system_memory": {
            "total_bytes": int(memory.total),
            "available_bytes": int(memory.available),
            "available_ratio": round(system_available_ratio, 4),
        },
        "interpretation": "Resource preflight only; normal still uses bounded batches and never authorizes GUI actions.",
    }


def _gpu_snapshot() -> dict[str, Any]:
    executable = shutil.which("nvidia-smi")
    if not executable:
        return {
            "available": False,
            "reason": "nvidia_smi_unavailable",
            "devices": [],
            "compute_processes": [],
        }
    try:
        device_rows = _run_nvidia_query(
            executable,
            "index,memory.total,memory.used,memory.free,utilization.gpu",
        )
        process_rows = _run_nvidia_query(
            executable,
            "pid,process_name,used_gpu_memory",
            scope="compute-apps",
            allow_failure=True,
        )
        devices = [
            {
                "index": _int_value(row, 0),
                "memory_total_mib": _int_value(row, 1),
                "memory_used_mib": _int_value(row, 2),
                "memory_free_mib": _int_value(row, 3),
                "utilization_percent": _int_value(row, 4),
            }
            for row in device_rows
            if len(row) >= 5
        ]
        processes = [
            {
                "pid": _int_value(row, 0),
                "process_name": str(row[1]).strip(),
                "used_memory_mib": _int_value(row, 2),
            }
            for row in process_rows
            if len(row) >= 3 and _int_value(row, 0) > 0
        ]
        return {
            "available": bool(devices),
            "reason": None if devices else "nvidia_smi_no_devices",
            "devices": devices,
            "compute_processes": processes,
        }
    except (OSError, UnicodeError, subprocess.SubprocessError, ValueError) as exc:
        return {
            "available": False,
            "reason": f"nvidia_smi_failed:{type(exc).__name__}",
            "devices": [],
            "compute_processes": [],
        }


def _run_nvidia_query(
    executable: str,
    fields: str,
    *,
    scope: str = "gpu",
    allow_failure: bool = False,
) -> list[list[str]]:
    completed = subprocess.run(
        [executable, f"--query-{scope}={fields}", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=False,
        timeout=8,
        check=False,
    )
    stdout = _decode_nvidia_output(completed.stdout or b"")
    stderr = _decode_nvidia_output(completed.stderr or b"")
    if completed.returncode != 0:
        if allow_failure:
            return []
        raise subprocess.CalledProcessError(completed.returncode, completed.args, stdout, stderr)
    return [row for row in csv.reader(stdout.splitlines()) if row]


def _decode_nvidia_output(value: bytes | str) -> str:
    if isinstance(value, str):
        return value
    encodings = ["utf-8", _windows_ansi_encoding(), locale.getpreferredencoding(False), "gb18030"]
    last_error: UnicodeDecodeError | None = None
    for encoding in dict.fromkeys(item for item in encodings if item):
        try:
            return value.decode(encoding, errors="strict")
        except (LookupError, UnicodeDecodeError) as exc:
            if isinstance(exc, UnicodeDecodeError):
                last_error = exc
    if last_error is not None:
        raise last_error
    return value.decode("utf-8", errors="strict")


def _windows_ansi_encoding() -> str | None:
    if os.name != "nt":
        return None
    try:
        import ctypes

        return f"cp{int(ctypes.windll.kernel32.GetACP())}"
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def _known_model_pids() -> set[int]:
    pids: set[int] = set()
    for profile in load_model_profiles():
        path = model_profile_pid_path(profile, root_dir=ROOT_DIR)
        try:
            pid = int(path.read_text(encoding="utf-8").strip())
        except (OSError, TypeError, ValueError):
            continue
        if pid > 0 and psutil.pid_exists(pid):
            pids.add(pid)
            try:
                children = psutil.Process(pid).children(recursive=True)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                children = []
            pids.update(
                int(child.pid)
                for child in children
                if int(getattr(child, "pid", 0) or 0) > 0 and psutil.pid_exists(int(child.pid))
            )
    return pids


def _profile_model_pids(profile: dict[str, Any]) -> set[int]:
    path = model_profile_pid_path(profile, root_dir=ROOT_DIR)
    try:
        launcher_pid = int(path.read_text(encoding="utf-8").strip())
    except (OSError, TypeError, ValueError):
        return set()
    if launcher_pid <= 0 or not psutil.pid_exists(launcher_pid):
        return set()
    pids = {launcher_pid}
    try:
        children = psutil.Process(launcher_pid).children(recursive=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        children = []
    pids.update(
        int(child.pid)
        for child in children
        if int(getattr(child, "pid", 0) or 0) > 0
        and psutil.pid_exists(int(child.pid))
    )
    return pids


def _known_model_reserved_memory_mib(known_pids: set[int]) -> int:
    reserved_mib = 0
    counted_launcher_pids: set[int] = set()
    for profile in load_model_profiles():
        path = model_profile_pid_path(profile, root_dir=ROOT_DIR)
        try:
            launcher_pid = int(path.read_text(encoding="utf-8").strip())
        except (OSError, TypeError, ValueError):
            continue
        if launcher_pid <= 0 or launcher_pid not in known_pids or launcher_pid in counted_launcher_pids:
            continue
        counted_launcher_pids.add(launcher_pid)
        reserved_mib += max(0, int(float(profile.get("gpu_memory_gib") or 0) * 1024))
    return reserved_mib


def _int_value(row: list[str], index: int) -> int:
    try:
        return int(float(str(row[index]).strip()))
    except (IndexError, TypeError, ValueError):
        return 0
