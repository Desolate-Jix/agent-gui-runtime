from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import shlex
import socket
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_NAME = "learn_fusion_calibration_pre_run_check_report.json"
MODEL_PORTS = [11434, 1240, 1241, 1244, 1245, 8000, 8001, 8080]
MODEL_PROCESS_NAMES = {"ollama", "ollama.exe", "llama-server", "llama-server.exe", "llama_server", "llama_server.exe", "text-generation-launcher", "text-generation-launcher.exe"}
MODEL_HOST_PROCESS_NAMES = {"python", "python.exe", "python3", "python3.exe", "uv", "uv.exe", "node", "node.exe"}
SYSTEM_SERVICE_PROCESS_NAMES = {"svchost", "svchost.exe", "services", "services.exe", "lsass", "lsass.exe", "wininit", "wininit.exe", "csrss", "csrss.exe", "smss", "smss.exe"}
MODEL_COMMAND_RE = re.compile(
    r"(llama[-_]server|vista_openai_server|uground_openai_server|vllm|ollama\s+serve|Qwen3VL|VISTA-4B|UGround|OpenAI-compatible|model_servers?[\\/]|model_server|\bqwen[\w.-]*\b|\bphi[\w.-]*\b|\bgemma[\w.-]*\b|\bmistral[\w.-]*\b)",
    re.IGNORECASE,
)


def report_learn_fusion_calibration_pre_run_check(
    *,
    approval_packet_path: str | Path,
    out_dir: str | Path,
    project_root: str | Path | None = None,
    json_stdout: bool = False,
) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    packet_file = _resolve_path(approval_packet_path, root)
    out = _resolve_path(out_dir, root)
    out.mkdir(parents=True, exist_ok=True)

    packet_bytes = packet_file.read_bytes()
    packet_sha256 = hashlib.sha256(packet_bytes).hexdigest()
    packet = _loads_json_bytes(packet_bytes, packet_file)
    commands = _dict(packet.get("commands"))
    expected_outputs = _dict(packet.get("expected_outputs"))
    safety = _dict(packet.get("safety"))
    calibration_preview = str(commands.get("calibration_command_preview") or "")
    refresh_preview = str(commands.get("post_batch_refresh_command_preview") or "")
    calibration_args = _command_options(calibration_preview)
    refresh_args = _command_options(refresh_preview)
    ready_regions = _list_of_int(packet.get("ready_region_numbers"))
    command_regions = _parse_regions(calibration_args.get("--regions"))
    tasks_path = _resolve_optional(calibration_args.get("--tasks"), root)
    batch_plan_path = _resolve_optional(refresh_args.get("--batch-plan"), root)
    refresh_rerun_path = _resolve_optional(refresh_args.get("--rerun-report"), root)
    expected_rerun_path = _resolve_optional(expected_outputs.get("rerun_report_path"), root)
    model_runtime_snapshot = _model_runtime_snapshot()

    checks = {
        "approval_packet_ready": packet.get("approval_packet_status") == "ready_for_user_approval",
        "requires_explicit_user_approval": packet.get("requires_explicit_user_approval") is True,
        "approval_does_not_execute": packet.get("approval_does_not_execute") is True,
        "may_start_after_approval": packet.get("may_start_model_after_user_approval") is True,
        "may_run_calibration_batch_now_false": packet.get("may_run_calibration_batch_now") is False,
        "candidate_blocked_pending_calibration": packet.get("candidate_validation_status") == "blocked_pending_calibration",
        "calibration_command_no_execute_flag": commands.get("command_executes_now") is False,
        "refresh_command_no_execute_flag": commands.get("post_batch_refresh_command_executes_now") is False,
        "calibration_command_has_probe": "run_numbered_region_calibration_probe.py" in calibration_preview,
        "refresh_command_has_refresh_script": "refresh_learn_fusion_after_calibration_batch.py" in refresh_preview,
        "tasks_file_exists": bool(tasks_path and tasks_path.exists() and tasks_path.is_file()),
        "regions_match_ready_regions": bool(command_regions and command_regions == ready_regions),
        "refresh_rerun_report_present": refresh_rerun_path is not None,
        "expected_rerun_report_present": expected_rerun_path is not None,
        "refresh_rerun_report_matches_expected": bool(
            refresh_rerun_path is not None
            and expected_rerun_path is not None
            and refresh_rerun_path.resolve() == expected_rerun_path.resolve()
        ),
        "batch_plan_exists": bool(batch_plan_path and batch_plan_path.exists() and batch_plan_path.is_file()),
        "future_rerun_report_awaiting": expected_outputs.get("rerun_report_status") == "awaiting_future_calibration_output",
        "post_batch_refresh_requires_completed_batch": expected_outputs.get("post_batch_refresh_requires_completed_batch")
        is True,
        "no_model_started": _int_value(safety.get("model_started")) == 0,
        "no_live_clicks": _int_value(safety.get("live_clicks")) == 0,
        "no_live_fills": _int_value(safety.get("live_fills")) == 0,
        "no_live_submits": _int_value(safety.get("live_submits")) == 0,
        "execute_binding_disabled": safety.get("execute_binding_enabled") is not True,
        "artifact_not_authorization": safety.get("artifact_is_authorization") is not True,
        "no_model_ports_listening": model_runtime_snapshot.get("model_ports_clear") is True,
        "no_suspected_model_processes": model_runtime_snapshot.get("model_processes_clear") is True,
    }

    blockers = _blockers(checks)
    blockers.extend(str(item) for item in packet.get("blockers") if isinstance(packet.get("blockers"), list))
    status = "blocked" if blockers else "ready_after_explicit_approval"
    report = {
        "contract_version": "learn_fusion_calibration_pre_run_check_v1",
        "pre_run_status": status,
        "approval_packet_path": _relative_path(packet_file, root),
        "approval_packet_sha256": packet_sha256,
        "requires_explicit_user_approval": packet.get("requires_explicit_user_approval") is True,
        "may_start_model_after_user_approval": status == "ready_after_explicit_approval",
        "may_run_calibration_batch_now": False,
        "ready_region_numbers": ready_regions,
        "command_region_numbers": command_regions,
        "tasks_path": _relative_path(tasks_path, root) if tasks_path is not None else None,
        "batch_plan_path": _relative_path(batch_plan_path, root) if batch_plan_path is not None else None,
        "expected_rerun_report_path": _relative_path(expected_rerun_path, root) if expected_rerun_path is not None else None,
        "refresh_rerun_report_path": _relative_path(refresh_rerun_path, root) if refresh_rerun_path is not None else None,
        "checks": checks,
        "safety": {
            "model_started": bool(_int_value(safety.get("model_started"))),
            "live_clicks": _int_value(safety.get("live_clicks")),
            "live_fills": _int_value(safety.get("live_fills")),
            "live_submits": _int_value(safety.get("live_submits")),
            "execute_binding_enabled": safety.get("execute_binding_enabled") is True,
            "artifact_is_authorization": safety.get("artifact_is_authorization") is True,
        },
        "model_runtime_snapshot": model_runtime_snapshot,
        "blockers": sorted(set(blockers)),
        "interpretation": (
            "No-model pre-run check for the numbered-region calibration batch. "
            "Ready means the packet can be shown for explicit approval; this report does not start models, "
            "run calibration, click, fill, submit, refresh, merge, or promote Runtime PathGraph."
        ),
    }
    report_path = out / REPORT_NAME
    report["report_path"] = str(report_path.resolve())
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if json_stdout:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def _blockers(checks: dict[str, bool]) -> list[str]:
    names = {
        "approval_packet_ready": "approval_packet_not_ready",
        "requires_explicit_user_approval": "explicit_user_approval_not_required",
        "approval_does_not_execute": "approval_packet_may_execute",
        "may_start_after_approval": "may_start_after_approval_false",
        "may_run_calibration_batch_now_false": "may_run_now_not_false",
        "candidate_blocked_pending_calibration": "candidate_not_blocked_pending_calibration",
        "calibration_command_no_execute_flag": "calibration_command_executes_now",
        "refresh_command_no_execute_flag": "post_batch_refresh_command_executes_now",
        "calibration_command_has_probe": "calibration_probe_command_missing",
        "refresh_command_has_refresh_script": "refresh_command_missing",
        "tasks_file_exists": "tasks_file_missing",
        "regions_match_ready_regions": "regions_mismatch_ready_regions",
        "refresh_rerun_report_present": "refresh_rerun_report_missing",
        "expected_rerun_report_present": "expected_rerun_report_missing",
        "refresh_rerun_report_matches_expected": "refresh_rerun_report_mismatch",
        "batch_plan_exists": "batch_plan_missing",
        "future_rerun_report_awaiting": "future_rerun_report_not_awaiting",
        "post_batch_refresh_requires_completed_batch": "post_batch_refresh_not_gated",
        "no_model_started": "model_already_started",
        "no_live_clicks": "live_clicks_detected",
        "no_live_fills": "live_fills_detected",
        "no_live_submits": "live_submits_detected",
        "execute_binding_disabled": "execute_binding_enabled",
        "artifact_not_authorization": "artifact_is_authorization",
        "no_model_ports_listening": "model_ports_listening",
        "no_suspected_model_processes": "suspected_model_process_running",
    }
    return [names[key] for key, passed in checks.items() if not passed]


def _model_runtime_snapshot() -> dict[str, Any]:
    listening_ports = _listening_model_ports(MODEL_PORTS)
    suspected_processes = _suspected_model_processes()
    return {
        "contract_version": "model_runtime_snapshot_v1",
        "checked_at": datetime.now(UTC).isoformat(),
        "checked_ports": MODEL_PORTS,
        "listening_ports": listening_ports,
        "suspected_model_processes": suspected_processes,
        "model_ports_clear": len(listening_ports) == 0,
        "model_processes_clear": len(suspected_processes) == 0,
        "probe_platform": platform.system(),
        "interpretation": "Snapshot only; this report does not stop, start, or contact any model service.",
    }


def _listening_model_ports(ports: list[int]) -> list[int]:
    listening: list[int] = []
    for port in ports:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.08)
            if probe.connect_ex(("127.0.0.1", int(port))) == 0:
                listening.append(int(port))
    return listening


def _suspected_model_processes() -> list[dict[str, Any]]:
    if platform.system().lower() != "windows":
        return []
    script = r"""
$ErrorActionPreference = 'SilentlyContinue'
$patterns = '(llama-server|llama_server|vista_openai_server|uground_openai_server|vllm|ollama serve|Qwen3VL|VISTA-4B|UGround|OpenAI-compatible|model_server|qwen|phi|gemma|mistral)'
$items = Get-CimInstance Win32_Process | Where-Object {
  $_.ProcessId -ne $PID -and (
    $_.Name -match '^(ollama|llama-server|llama_server|text-generation-launcher)(\.exe)?$' -or
    (($_.Name -match '^(python|python3|uv|node)(\.exe)?$') -and ($_.CommandLine -match $patterns)) -or
    ($_.CommandLine -match $patterns -and $_.Name -notmatch 'powershell|pwsh')
  )
} | Select-Object ProcessId,Name,CommandLine
@($items) | ConvertTo-Json -Depth 4
"""
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    text = completed.stdout.strip()
    if not text:
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    items = payload if isinstance(payload, list) else [payload]
    result: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if not _is_suspected_model_process(item.get("Name"), item.get("CommandLine")):
            continue
        result.append(
            {
                "pid": item.get("ProcessId"),
                "name": item.get("Name"),
                "command_line": item.get("CommandLine"),
            }
        )
    return result


def _is_suspected_model_process(name: Any, command_line: Any) -> bool:
    process_name = str(name or "").strip().lower()
    command = str(command_line or "")
    if process_name in MODEL_PROCESS_NAMES:
        return True
    if process_name in SYSTEM_SERVICE_PROCESS_NAMES:
        return False
    if process_name in MODEL_HOST_PROCESS_NAMES:
        return MODEL_COMMAND_RE.search(command) is not None
    if process_name in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
        return False
    return MODEL_COMMAND_RE.search(command) is not None


def _command_options(command: str) -> dict[str, str]:
    normalized = command.replace("\\", "/")
    parts = shlex.split(normalized, posix=False)
    result: dict[str, str] = {}
    index = 0
    while index < len(parts):
        part = parts[index]
        if part.startswith("--"):
            if "=" in part:
                key, value = part.split("=", 1)
            else:
                key = part
                value = parts[index + 1] if index + 1 < len(parts) else ""
                index += 1
            result[key] = value.strip('"')
        index += 1
    return result


def _parse_regions(value: Any) -> list[int]:
    if not isinstance(value, str):
        return []
    result: list[int] = []
    for item in value.split(","):
        try:
            result.append(int(item.strip()))
        except ValueError:
            continue
    return result


def _resolve_optional(value: Any, root: Path) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return _resolve_path(value, root)


def _resolve_path(path: str | Path, root: Path) -> Path:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = root / resolved
    return resolved.resolve()


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return str(path.resolve())


def _read_json(path: Path) -> dict[str, Any]:
    payload = _loads_json_bytes(path.read_bytes(), path)
    return payload


def _loads_json_bytes(payload_bytes: bytes, path: Path) -> dict[str, Any]:
    payload = json.loads(payload_bytes.decode("utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_of_int(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    result: list[int] = []
    for item in value:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result


def _int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a no-model learn-fusion calibration pre-run check.")
    parser.add_argument("--approval-packet", required=True, help="learn_fusion_model_start_approval_packet.json")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--json", action="store_true", help="Print JSON report")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report = report_learn_fusion_calibration_pre_run_check(
        approval_packet_path=args.approval_packet,
        out_dir=args.out,
        json_stdout=args.json,
    )
    return 0 if report.get("pre_run_status") == "ready_after_explicit_approval" else 1


if __name__ == "__main__":
    raise SystemExit(main())
