"""Offline-first, injectible simple-native five-screen diagnostic runner."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any, Callable, Mapping, Protocol, Sequence

from app.learn.hybrid.simple_native_contracts import (
    build_qwen_model_projection, expand_qwen_model_response,
    parse_omni_native_output, parse_vista_normalized_point, restore_vista_point_to_capture,
)


class OmniNativeCaller(Protocol):
    def __call__(self, image: Path) -> object: ...
class QwenNativeCaller(Protocol):
    def __call__(self, image: Path, projection: Mapping[str, object]) -> object: ...
class VistaNativeCaller(Protocol):
    def __call__(self, roi_image: Path, target_text: str) -> str: ...

@dataclass(frozen=True)
class SimpleNativeSlots:
    omni: OmniNativeCaller
    qwen: QwenNativeCaller
    vista: VistaNativeCaller

@dataclass(frozen=True)
class ProviderCase:
    case_id: str
    image_path: Path
    image_size: tuple[int, int]
    targets: tuple[str, ...]
    runtime_request: Mapping[str, object]
    omni_inventory: Mapping[str, object] | None = None

@dataclass(frozen=True)
class ProviderDiagnosticArtifact:
    path: Path
    cases: tuple[dict[str, object], ...]
    metrics: dict[str, object]
    screen_count: int
    target_count: int
    regression_diagnostic_only: bool = True
    promotion_eligible: bool = False

@dataclass(frozen=True)
class RegressionDiagnosticReport:
    provider_artifact_sha256: str
    regression_diagnostic_only: bool
    promotion_eligible: bool
    target_count: int
    correct_selected: int = 0
    wrong_selected: int = 0
    abstained: int = 0


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
def _hash(value: object) -> str: return sha256(_canonical(value)).hexdigest()
def _raw_text(value: object) -> str: return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(",", ":"))

def _metric() -> dict[str, object]:
    return {"attempted": 0, "schema_valid": 0, "schema_invalid": 0, "timeout": 0, "latencies": [], "raw_output_bytes": 0}
def _finish(metric: dict[str, object]) -> dict[str, object]:
    values = metric.pop("latencies")
    metric["latency_p50_ms"] = median(values) if values else 0
    metric["latency_p95_ms"] = max(values) if values else 0
    return metric

def run_simple_native_regression_diagnostic(*, cases: Sequence[ProviderCase], slots: SimpleNativeSlots, artifact_dir: Path, cleanup_receipt: Mapping[str, object] | None = None) -> ProviderDiagnosticArtifact:
    """Run exactly five injected replay-compatible cases; never reads Gold or acts."""
    if len(cases) != 5 or {case.case_id for case in cases} != {f"case-{index:03d}" for index in range(1, 6)}:
        raise ValueError("simple-native diagnostic requires exactly case-001 through case-005")
    if sum(len(case.targets) for case in cases) != 25:
        raise ValueError("simple-native diagnostic requires exactly 25 targets")
    metrics: dict[str, Any] = {"omni": _metric(), "qwen": _metric(), "vista": _metric(), "denominator": 25, "abstained": 0, "correct_selected": 0, "wrong_selected": 0}
    invalid_streak = {"omni": 0, "qwen": 0, "vista": 0}
    records: list[dict[str, object]] = []
    for case in cases:
        trace: list[dict[str, object]] = []
        omni_items = ()
        if invalid_streak["omni"] < 2:
            metrics["omni"]["attempted"] += 1; started = perf_counter()
            try:
                raw = slots.omni(case.image_path); parsed = parse_omni_native_output(raw)
                omni_items = parsed; metrics["omni"]["schema_valid"] += 1; invalid_streak["omni"] = 0
                trace.append({"slot": "omni", "raw": _raw_text(raw), "parsed": [asdict(item) for item in parsed], "parent_id": case.case_id, "raw_sha256": _hash(raw)})
            except Exception as exc:
                metrics["omni"]["schema_invalid"] += 1; invalid_streak["omni"] += 1
                trace.append({"slot": "omni", "raw": "", "parse_error": str(exc), "parent_id": case.case_id})
            metrics["omni"]["latencies"].append(round((perf_counter() - started) * 1000, 3)); metrics["omni"]["raw_output_bytes"] += len(trace[-1].get("raw", "").encode("utf-8"))
        qwen_bindings: list[dict[str, object]] = []
        if invalid_streak["qwen"] < 2:
            metrics["qwen"]["attempted"] += 1; started = perf_counter(); projection = build_qwen_model_projection(case.runtime_request)
            try:
                raw = slots.qwen(case.image_path, projection); expanded = expand_qwen_model_response(raw, projection=projection, runtime_request=case.runtime_request)
                qwen_bindings = list(expanded["bindings"]); metrics["qwen"]["schema_valid"] += 1; invalid_streak["qwen"] = 0
                trace.append({"slot": "qwen", "input": projection, "raw": _raw_text(raw), "parsed": expanded, "parent_id": case.case_id, "raw_sha256": _hash(raw)})
            except Exception as exc:
                metrics["qwen"]["schema_invalid"] += 1; invalid_streak["qwen"] += 1
                trace.append({"slot": "qwen", "raw": "", "parse_error": str(exc), "parent_id": case.case_id})
            metrics["qwen"]["latencies"].append(round((perf_counter() - started) * 1000, 3)); metrics["qwen"]["raw_output_bytes"] += len(trace[-1].get("raw", "").encode("utf-8"))
        bound = [binding for binding in qwen_bindings if binding["binding_status"] == "BOUND"]
        geometry = {str(candidate["candidate_id"]): candidate["bbox_original"] for candidate in case.runtime_request["candidates"]}
        for target, binding in zip(case.targets, bound, strict=False):
            if invalid_streak["vista"] >= 2: metrics["abstained"] += 1; continue
            metrics["vista"]["attempted"] += 1; started = perf_counter(); raw = ""
            try:
                bbox = geometry.get(str(binding["candidate_id"]))
                if not isinstance(bbox, list) or len(bbox) != 4: raise ValueError("grounding candidate geometry is unavailable")
                roi = tuple(int(value) for value in bbox)
                raw = slots.vista(case.image_path, target); normalized = parse_vista_normalized_point(raw)
                point = restore_vista_point_to_capture(normalized, roi_xyxy=roi)
                # Strict interior containment: boundaries are abstentions, never clipped.
                if not (roi[0] < point[0] < roi[2] and roi[1] < point[1] < roi[3]): raise ValueError("restored VISTA point is outside strict candidate interior")
                metrics["vista"]["schema_valid"] += 1; invalid_streak["vista"] = 0
                trace.append({"slot": "vista", "raw": raw, "parsed": list(normalized), "capture_point": list(point), "roi_xyxy": list(roi), "target": target, "candidate_id": binding["candidate_id"], "parent_id": case.case_id, "raw_sha256": _hash(raw)})
            except TimeoutError as exc:
                metrics["vista"]["timeout"] += 1; invalid_streak["vista"] += 1; metrics["abstained"] += 1
                trace.append({"slot": "vista", "raw": raw, "error_class": "timeout", "parse_error": str(exc), "target": target, "parent_id": case.case_id})
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                metrics["vista"]["schema_invalid"] += 1; invalid_streak["vista"] += 1; metrics["abstained"] += 1
                trace.append({"slot": "vista", "raw": raw, "error_class": "schema", "parse_error": str(exc), "target": target, "parent_id": case.case_id})
            metrics["vista"]["latencies"].append(round((perf_counter() - started) * 1000, 3)); metrics["vista"]["raw_output_bytes"] += len(raw.encode("utf-8"))
        metrics["abstained"] += max(0, len(case.targets) - len(bound))
        records.append({"case_id": case.case_id, "runtime_request_sha256": _hash(case.runtime_request), "trace": trace})
    for slot in ("omni", "qwen", "vista"): metrics[slot] = _finish(metrics[slot])
    artifact_dir.mkdir(parents=True, exist_ok=True); path = artifact_dir / "provider-diagnostic.json"
    observed_cleanup = dict(cleanup_receipt) if cleanup_receipt is not None else {"verified": False, "reason": "runner received no lifecycle cleanup observation"}
    payload = {"contract_version": "simple_native_provider_diagnostic_v1", "regression_diagnostic_only": True, "promotion_eligible": False, "screen_count": 5, "target_count": 25, "metrics": metrics, "cases": records, "cleanup_receipt": observed_cleanup, "action_candidates": [], "artifact_is_authorization": False, "execute_binding": False}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return ProviderDiagnosticArtifact(path=path, cases=tuple(records), metrics=metrics, screen_count=5, target_count=25)

def score_simple_native_regression(*, provider_artifact: ProviderDiagnosticArtifact, gold_path: Path) -> RegressionDiagnosticReport:
    """唯一可打开 Gold 的边界；只接受已关闭的 provider artifact。"""
    if not provider_artifact.path.is_file(): raise ValueError("provider artifact must be finalized before scoring")
    # Gold is opened only after the provider artifact is finalized and never enters a caller payload.
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    targets = gold.get("targets") if isinstance(gold, Mapping) else None
    if not isinstance(targets, list): raise ValueError("Gold targets are invalid")
    gold_by_screen: dict[str, list[Mapping[str, object]]] = {}
    for target in targets:
        if isinstance(target, Mapping) and target.get("partition") == "regression" and isinstance(target.get("screen_id"), str): gold_by_screen.setdefault(target["screen_id"], []).append(target)
    correct = wrong = abstained = 0
    for case in provider_artifact.cases:
        screen = case.get("case_id")
        expected = gold_by_screen.get(screen) if isinstance(screen, str) else None
        if not expected: raise ValueError("provider artifact case has no regression Gold join")
        observed = [entry for entry in case.get("trace", []) if isinstance(entry, Mapping) and entry.get("slot") == "vista"]
        for index, target in enumerate(expected):
            entry = observed[index] if index < len(observed) else None
            point = entry.get("capture_point") if isinstance(entry, Mapping) else None
            bbox = target.get("bbox")
            if not isinstance(point, list) or len(point) != 2: abstained += 1; continue
            if isinstance(bbox, list) and len(bbox) == 4 and bbox[0] < point[0] < bbox[2] and bbox[1] < point[1] < bbox[3]: correct += 1
            else: wrong += 1
    return RegressionDiagnosticReport(_hash(provider_artifact.path.read_text(encoding="utf-8")), True, False, provider_artifact.target_count, correct, wrong, abstained)
