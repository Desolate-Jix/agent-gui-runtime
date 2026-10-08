"""离线预检、显式单次付费视觉评估；不采图、不输入、不改变默认配置。"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time
from typing import Literal
from uuid import uuid4

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, model_validator

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.vision.external_grounding_api import (
    ApiGroundingError, ApiGroundingProfile, ChatCompletionsGrounder, load_api_grounding_profile,
)
from app.vision.grounding_contract import BoundingBox, ImageSize
from app.vision.recognition_source import _invalid_constant, _unique_object


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class BenchmarkCapture(_StrictModel):
    capture_id: str = Field(min_length=1, max_length=256)
    image_path: str = Field(min_length=1, max_length=4096)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    image_size: ImageSize
    captured_at_utc: str = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def validate_timestamp(self):
        timestamp = datetime.fromisoformat(self.captured_at_utc.replace("Z", "+00:00"))
        if timestamp.tzinfo is None or timestamp.utcoffset().total_seconds() != 0:
            raise ValueError("benchmark_capture_timestamp_must_be_UTC")
        return self


class BenchmarkTruth(_StrictModel):
    status: Literal["found", "absent", "ambiguous"]
    bboxes: list[BoundingBox] = Field(max_length=16)

    @model_validator(mode="after")
    def validate_box_count(self):
        count = len(self.bboxes)
        if (self.status == "found" and count != 1 or self.status == "absent" and count != 0
                or self.status == "ambiguous" and count < 2):
            raise ValueError("benchmark_truth_box_count_invalid")
        if len({(box.x, box.y, box.width, box.height) for box in self.bboxes}) != count:
            raise ValueError("benchmark_truth_boxes_must_be_distinct")
        return self


class BenchmarkCase(_StrictModel):
    case_id: str = Field(min_length=1, max_length=128)
    goal: str = Field(min_length=1, max_length=4096)
    capture: BenchmarkCapture
    truth: BenchmarkTruth

    @model_validator(mode="after")
    def validate_truth_bounds(self):
        if not self.goal.strip():
            raise ValueError("benchmark_goal_empty")
        size = self.capture.image_size
        if any(box.x + box.width > size.width or box.y + box.height > size.height
               for box in self.truth.bboxes):
            raise ValueError("benchmark_truth_outside_image")
        return self


class BenchmarkManifest(_StrictModel):
    schema_version: Literal["external_vision_benchmark.v1"]
    suite_id: str = Field(min_length=1, max_length=128)
    truth_source: str = Field(min_length=1, max_length=1024)
    cases: list[BenchmarkCase] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def validate_case_ids(self):
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ValueError("benchmark_case_id_duplicate")
        identities = {}
        for case in self.cases:
            capture = case.capture
            identity = (capture.sha256, capture.image_size.width, capture.image_size.height, capture.captured_at_utc)
            if capture.capture_id in identities and identities[capture.capture_id] != identity:
                raise ValueError("benchmark_capture_id_conflict")
            identities[capture.capture_id] = identity
        return self


def load_benchmark_manifest(path):
    path = Path(path).resolve()
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"),
                             object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
        manifest = BenchmarkManifest.model_validate(payload)
    except (OSError, ValueError):
        raise ValueError("benchmark_manifest_invalid") from None
    for case in manifest.cases:
        image = Path(case.capture.image_path)
        if not image.is_absolute():
            case.capture.image_path = str((path.parent / image).resolve())
    return manifest


def preflight(manifest, profile, *, max_calls=12):
    if type(max_calls) is not int or not 1 <= max_calls <= 32:
        raise ValueError("benchmark_call_cap_invalid")
    if len(manifest.cases) > max_calls:
        raise ValueError("benchmark_call_cap_exceeded")
    for case in manifest.cases:
        capture = case.capture
        try:
            with Path(capture.image_path).open("rb") as stream:
                data = stream.read(profile.max_image_bytes + 1)
            if len(data) > profile.max_image_bytes:
                raise ValueError("benchmark_image_too_large")
            if sha256(data).hexdigest() != capture.sha256:
                raise ValueError("benchmark_capture_changed")
            with Image.open(BytesIO(data)) as image:
                if image.format != "PNG" or image.size != (capture.image_size.width, capture.image_size.height):
                    raise ValueError("benchmark_capture_invalid")
                image.verify()
        except (OSError, TypeError, SyntaxError):
            raise ValueError("benchmark_capture_invalid") from None
    return {"suite_id": manifest.suite_id, "cases": len(manifest.cases), "maximum_calls": max_calls,
            "model": profile.model, "requested_reasoning_effort": None, "network_called": False,
            "truth_sent_to_provider": False, "action_executed": False}


def _iou(left, right):
    width = max(0, min(left["x"] + left["width"], right["x"] + right["width"]) - max(left["x"], right["x"]))
    height = max(0, min(left["y"] + left["height"], right["y"] + right["height"]) - max(left["y"], right["y"]))
    intersection = width * height
    return intersection / (left["width"] * left["height"] + right["width"] * right["height"] - intersection)


def _ambiguous_boxes_match(candidates, truth, threshold):
    if len(candidates) != len(truth):
        return False
    matches = {}

    def assign(truth_index, visited):
        for candidate_index, candidate in enumerate(candidates):
            if candidate_index in visited or _iou(candidate["bbox"], truth[truth_index]) < threshold:
                continue
            visited.add(candidate_index)
            previous = matches.get(candidate_index)
            if previous is None or assign(previous, visited):
                matches[candidate_index] = truth_index
                return True
        return False

    return all(assign(index, set()) for index in range(len(truth)))


def _score(case, result, threshold):
    expected = case.truth.status
    accuracy = {"status_correct": result is not None and result["status"] == expected,
                "bbox_iou": None, "bbox_correct": None, "click_in_truth": None,
                "ambiguous_boxes_correct": None, "passed": False}
    if expected == "found":
        accuracy.update(bbox_correct=False, click_in_truth=False)
        if result is not None and result["status"] == "found":
            candidate = next(item for item in result["candidates"] if item["id"] == result["selected_candidate_id"])
            truth = case.truth.bboxes[0].model_dump()
            iou = _iou(candidate["bbox"], truth)
            point = candidate["click_point"]
            hit = (truth["x"] <= point["x"] < truth["x"] + truth["width"]
                   and truth["y"] <= point["y"] < truth["y"] + truth["height"])
            accuracy.update(bbox_iou=round(iou, 6), bbox_correct=iou >= threshold, click_in_truth=hit)
        accuracy["passed"] = accuracy["status_correct"] and accuracy["bbox_correct"] and accuracy["click_in_truth"]
    elif expected == "ambiguous":
        accuracy["ambiguous_boxes_correct"] = accuracy["status_correct"] and _ambiguous_boxes_match(
            result["candidates"], [box.model_dump() for box in case.truth.bboxes], threshold)
        accuracy["passed"] = accuracy["status_correct"] and accuracy["ambiguous_boxes_correct"]
    else:
        accuracy["passed"] = accuracy["status_correct"]
    return accuracy


def _latencies(values):
    values = sorted(value for value in values if type(value) in {int, float} and math.isfinite(value) and value >= 0)
    if not values:
        return {"count": 0, "p50_ms": None, "p95_ms": None, "min_ms": None, "max_ms": None}
    return {"count": len(values), "p50_ms": round(statistics.median(values), 3),
            "p95_ms": round(values[math.ceil(0.95 * len(values)) - 1], 3),
            "min_ms": round(values[0], 3), "max_ms": round(values[-1], 3)}


def _summary(cases):
    count = len(cases)
    found = [case for case in cases if case["truth"]["status"] == "found"]
    return {"cases": count, "passed": sum(case["accuracy"]["passed"] for case in cases),
            "failures": sum(case["error"] is not None for case in cases),
            "classification_accuracy": sum(case["accuracy"]["status_correct"] for case in cases) / count if count else None,
            "found_cases": len(found),
            "found_bbox_accuracy": sum(case["accuracy"]["bbox_correct"] for case in found) / len(found) if found else None,
            "found_click_accuracy": sum(case["accuracy"]["click_in_truth"] for case in found) / len(found) if found else None,
            "end_to_end_latency": _latencies([case["end_to_end_ms"] for case in cases]),
            "http_latency": _latencies([(case["provider"] or {}).get("http_elapsed_ms") for case in cases]),
            "provider_latency": _latencies([(case["provider"] or {}).get("server_processing_ms") for case in cases])}


def run_benchmark(manifest, profile, *, output_path, max_calls=12, iou_threshold=0.5, transport=None):
    preflight(manifest, profile, max_calls=max_calls)
    if type(iou_threshold) not in {float, int} or not math.isfinite(iou_threshold) or not 0 < iou_threshold <= 1:
        raise ValueError("benchmark_iou_threshold_invalid")
    if not (os.environ.get(profile.api_key_env) or "").strip():
        raise ApiGroundingError("api_key_missing")
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {"schema_version": "external_vision_benchmark_result.v1", "suite_id": manifest.suite_id,
        "truth_source": manifest.truth_source, "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "manifest_sha256": sha256(json.dumps(manifest.model_dump(), ensure_ascii=False, sort_keys=True,
            separators=(",", ":")).encode("utf-8")).hexdigest(),
        "profile": {"model": profile.model, "protocol": profile.protocol, "endpoint": profile.endpoint,
                    "requested_reasoning_effort": None, "timeout_seconds": profile.timeout_seconds,
                    "max_completion_tokens": profile.max_completion_tokens},
        "maximum_calls": max_calls, "iou_threshold": iou_threshold, "status": "running",
        "automatic_retry_allowed": False, "truth_sent_to_provider": False,
        "action_executed": False, "cases": [], "summary": _summary([])}

    def persist(stream):
        report["summary"] = _summary(report["cases"])
        stream.seek(0)
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
        stream.truncate()
        stream.flush()
        os.fsync(stream.fileno())

    # 独占创建可防止复跑覆盖首次失败；每案立即落盘，零自动重试。
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        persist(stream)
        with ChatCompletionsGrounder(profile, transport=transport, capture_trace=True) as grounder:
            for case in manifest.cases:
                request_id = "vision-benchmark-" + uuid4().hex
                entry = {"case_id": case.case_id, "goal": case.goal, "capture": case.capture.model_dump(),
                         "truth": case.truth.model_dump(), "request_id": request_id,
                         "first_attempt": True, "result": None, "provider": None, "trace": None, "error": None}
                started = time.perf_counter_ns()
                try:
                    value = grounder.ground(request_id=request_id, capture=case.capture.model_dump(), goal=case.goal)
                    entry.update(result=value["result"], provider=value["provider"], trace=value["trace"])
                except ApiGroundingError as error:
                    entry.update(provider=error.provider, trace=error.trace, error={"code": error.code,
                        "status_code": error.status_code, "attempt": error.attempt})
                except KeyboardInterrupt:
                    report["status"] = "interrupted"
                    entry["error"] = {"code": "benchmark_interrupted", "status_code": None, "attempt": None}
                    entry["end_to_end_ms"] = round((time.perf_counter_ns() - started) / 1_000_000, 3)
                    entry["accuracy"] = _score(case, None, iou_threshold)
                    report["cases"].append(entry)
                    persist(stream)
                    raise
                entry["end_to_end_ms"] = round((time.perf_counter_ns() - started) / 1_000_000, 3)
                entry["accuracy"] = _score(case, entry["result"], iou_threshold)
                report["cases"].append(entry)
                persist(stream)
        report["status"] = "completed"
        report["ended_at_utc"] = datetime.now(timezone.utc).isoformat()
        persist(stream)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-calls", type=int, default=12)
    parser.add_argument("--iou-threshold", type=float, default=0.5)
    parser.add_argument("--execute", action="store_true", help="Send exactly one paid API request per case; no retry.")
    args = parser.parse_args(argv)
    if args.execute and args.output is None:
        parser.error("--execute requires --output")
    try:
        manifest = load_benchmark_manifest(args.manifest)
        profile = load_api_grounding_profile(args.profile)
        if not args.execute:
            result = preflight(manifest, profile, max_calls=args.max_calls)
            print(json.dumps(result, ensure_ascii=False))
            return 0
        report = run_benchmark(manifest, profile, output_path=args.output,
                               max_calls=args.max_calls, iou_threshold=args.iou_threshold)
        print(json.dumps({"suite_id": report["suite_id"], "output": str(args.output.resolve()),
                          "summary": report["summary"]}, ensure_ascii=False))
        return 0 if report["summary"]["passed"] == len(manifest.cases) else 1
    except (OSError, ValueError) as error:
        code = error.code if isinstance(error, ApiGroundingError) else (
            str(error) if str(error).startswith("benchmark_") else "benchmark_input_or_output_invalid")
        print(json.dumps({"error": code, "network_retry_attempted": False}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
