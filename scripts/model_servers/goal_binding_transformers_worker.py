"""Bounded provider-isolated worker; --help never imports model runtimes."""
from __future__ import annotations
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import time
from typing import Mapping


def _closed_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("worker JSON has duplicate keys")
        result[key] = value
    return result


def native_trace_envelope(*, profile_identity: Mapping[str, object], raw_native_output: str, resource_metrics: Mapping[str, object], parsed_native: object = None, worker_process_identity: Mapping[str, object] | None = None) -> dict[str, object]:
    if not isinstance(profile_identity, Mapping) or set(profile_identity) != {"profile_id", "preprocessing_sha256", "runtime_sha256", "native_output_kind"} or not isinstance(raw_native_output, str) or not isinstance(resource_metrics, Mapping):
        raise ValueError("worker native trace is invalid")
    metrics = dict(resource_metrics)
    if set(metrics) != {"latency_ms", "peak_vram_bytes"} or isinstance(metrics["latency_ms"], bool) or not isinstance(metrics["latency_ms"], (int, float)) or isinstance(metrics["peak_vram_bytes"], bool) or not isinstance(metrics["peak_vram_bytes"], int) or metrics["peak_vram_bytes"] < 0:
        raise ValueError("worker resource metrics are invalid")
    identity = dict(worker_process_identity or {"pid": os.getpid(), "create_time_ns": time.time_ns()})
    if set(identity) != {"pid", "create_time_ns"} or any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in identity.values()):
        raise ValueError("worker process identity is invalid")
    return {"contract_version": "goal_binding_native_trace_v1", "profile_identity": dict(profile_identity), "raw_native_output": raw_native_output, "parsed_native": parsed_native, "resource_metrics": metrics, "worker_process_identity": identity}


def _run_provider_once(payload: Mapping[str, object]) -> dict[str, object]:
    if set(payload) != {"image_path", "goal", "profile"}:
        raise ValueError("worker request must contain exactly one screenshot and one short goal")
    image_path, goal, profile = payload["image_path"], payload["goal"], payload["profile"]
    if not isinstance(image_path, str) or not Path(image_path).is_file() or not isinstance(goal, str) or not goal.strip() or len(goal) > 512 or not isinstance(profile, Mapping):
        raise ValueError("worker request is invalid")
    raise RuntimeError("provider-specific inference is unavailable until its pinned runtime artifact is acquired")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one bounded goal-binding provider request.")
    parser.add_argument("--execute", action="store_true", help="Execute one verified provider request.")
    parser.add_argument("--request-json", type=Path, help="Closed worker request JSON.")
    args = parser.parse_args(argv)
    if not args.execute:
        parser.error("--execute is required")
    if args.request_json is None:
        parser.error("--request-json is required")
    try:
        payload = json.loads(args.request_json.read_text(encoding="utf-8"), object_pairs_hook=_closed_object)
        if not isinstance(payload, Mapping):
            raise ValueError("worker request must be an object")
        envelope = _run_provider_once(payload)
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    print(json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
