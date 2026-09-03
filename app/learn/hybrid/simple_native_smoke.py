"""Offline-first, injectible simple-native five-screen diagnostic runner."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import shutil
from statistics import median
import sys
from time import perf_counter
from typing import Any, Callable, Mapping, Protocol, Sequence

from PIL import Image

from app.learn.hybrid.omni_candidates import build_omni_candidate_ledger, omni_inventory_from_ledger
from app.learn.hybrid.qwen_binding import build_qwen_binding_request, parse_qwen_candidate_bindings
from app.learn.hybrid.simple_native_contracts import (
    OmniNativeItem,
    build_qwen_model_projection,
    expand_qwen_model_response,
    parse_omni_native_output,
    parse_vista_normalized_point,
    restore_vista_point_to_capture,
)
from app.learn.recognition.uei.canonical import content_sha256, seal_immutable
from app.learn.recognition.uei.store import UEIObjectStore


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
    cleanup: Callable[[], Mapping[str, object]] | None = None


@dataclass(frozen=True)
class ProviderCase:
    case_id: str
    image_path: Path
    image_size: tuple[int, int]
    image_sha256: str
    goals: tuple[str, ...]


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


def _hash(value: object) -> str:
    return sha256(_canonical(value)).hexdigest()


def _raw_text(value: object) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _metric() -> dict[str, object]:
    return {"attempted": 0, "schema_valid": 0, "schema_invalid": 0, "timeout": 0, "latencies": [], "raw_output_bytes": 0}


def _finish(metric: dict[str, object]) -> dict[str, object]:
    values = metric.pop("latencies")
    metric["latency_p50_ms"] = median(values) if values else 0
    metric["latency_p95_ms"] = max(values) if values else 0
    return metric


def _window_binding(case: ProviderCase) -> dict[str, object]:
    width, height = case.image_size
    return {
        "window_binding_id": f"offline-regression-file:{case.case_id}",
        "process_id": os.getpid(),
        "process_name": Path(sys.executable).name,
        "rect": {"left": 0, "top": 0, "right": width, "bottom": height},
    }


def _put(store: UEIObjectStore, value: dict[str, object]) -> dict[str, str]:
    return store.put(seal_immutable(value))


def _persist_review_only_result(
    *,
    root: Path,
    capture_lineage_ref: Mapping[str, object],
    provider_id: str,
    profile_id: str,
    suffix: str,
    declared_output_kinds: list[str],
    items: list[dict[str, object]],
) -> tuple[dict[str, object], dict[str, str]]:
    store = UEIObjectStore(root=root / "artifacts" / "uei-shadow-store")
    lineage_ref = deepcopy(dict(capture_lineage_ref))
    request_ref = _put(store, {
        "contract_version": "screen_parse_request_v1",
        "request_id": f"request/simple-native/{suffix}",
        "capture_lineage_ref": lineage_ref,
        "requested_profiles": [{"provider_id": provider_id, "profile_id": profile_id, "mode": "Advisory"}],
        "privacy_policy": "minimal",
        "requester_id": "simple-native-diagnostic",
    })
    registration_ref = _put(store, {
        "contract_version": "trusted_provider_registration_v1",
        "registration_id": f"registration/simple-native/{suffix}",
        "provider_id": provider_id,
        "profile_ids": [profile_id],
        "enabled": True,
        "allowed_modes": ["Advisory"],
        "allowed_privacy_policies": ["minimal"],
        "egress_policy": "local_only",
        "wire_payload_policy": "restricted_store_only",
        "safe_payload_limits": {
            "max_json_bytes": 1048576,
            "max_depth": 12,
            "max_array_items": 10000,
            "max_object_properties": 64,
            "max_string_chars": 4096,
            "allowed_json_types": ["object", "array", "string", "number", "boolean", "null"],
        },
        "required_conformance_suite": "simple-native-diagnostic-v1",
    })
    manifest_ref = _put(store, {
        "contract_version": "provider_manifest_v1",
        "manifest_id": f"manifest/simple-native/{suffix}",
        "provider_id": provider_id,
        "provider_version": "simple-native-diagnostic-v1",
        "profiles": [{
            "profile_id": profile_id,
            "operation": "screen_parse",
            "input_contract": "screen_parse_request_v1",
            "output_contract": "provider_safe_result_v1",
            "declared_output_kinds": declared_output_kinds,
            "supported_coordinate_spaces": ["capture_pixel_xyxy"],
            "supports_capture_artifact": True,
            "privacy_capabilities": ["minimal"],
            "mode_allowlist": ["Advisory"],
        }],
    })
    result = seal_immutable({
        "contract_version": "provider_safe_result_v1",
        "result_id": f"result/simple-native/{suffix}",
        "request_ref": request_ref,
        "requested_provider_id": provider_id,
        "requested_profile_id": profile_id,
        "registration_resolution": "resolved",
        "manifest_resolution": "resolved",
        "registration_ref": registration_ref,
        "manifest_ref": manifest_ref,
        "provider_id": provider_id,
        "profile_id": profile_id,
        "provider_version": "simple-native-diagnostic-v1",
        "capture_lineage_ref": lineage_ref,
        "status": "success",
        "review_only": True,
        "items": items,
        "redaction_summary": {"redacted_item_count": 0, "redacted_field_count": 0, "secret_detected": False, "sensitive_categories": []},
    })
    result_ref = store.put(result)
    return store.get(result_ref, contract_version="provider_safe_result_v1"), result_ref


def _persist_empty_context_source(
    *, root: Path, identity: Mapping[str, object], window_binding: dict[str, object], run_id: str, source_kind: str
) -> dict[str, object]:
    provider_id = f"local.diagnostic/{source_kind}"
    profile_id = f"{provider_id}/unavailable-empty-v1"
    _, evidence_ref = _persist_review_only_result(
        root=root,
        capture_lineage_ref=identity["capture_lineage_ref"],
        provider_id=provider_id,
        profile_id=profile_id,
        suffix=f"{run_id}-{source_kind}",
        declared_output_kinds=["text" if source_kind == "ocr" else "element"],
        items=[],
    )
    return {
        "source_kind": source_kind,
        "capture_lineage_ref": deepcopy(identity["capture_lineage_ref"]),
        "run_id": run_id,
        "workflow_revision": 1,
        "window_binding": deepcopy(window_binding),
        "evidence_contract_version": "provider_safe_result_v1",
        "evidence_ref": evidence_ref,
    }


def _prepare_capture(case: ProviderCase, artifact_dir: Path) -> dict[str, object]:
    from app.learn.hybrid.capture import seal_hybrid_capture_bundle, seal_hybrid_capture_identity

    if not case.image_path.is_file():
        raise ValueError("diagnostic source image is missing")
    source_sha = sha256(case.image_path.read_bytes()).hexdigest()
    if source_sha != case.image_sha256:
        raise ValueError("diagnostic source image sha256 mismatch")
    with Image.open(case.image_path) as opened:
        if opened.size != case.image_size:
            raise ValueError("diagnostic source image dimensions mismatch")
    copied = artifact_dir / "artifacts" / "screenshots" / case.case_id / case.image_path.name
    copied.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(case.image_path, copied)
    if sha256(copied.read_bytes()).hexdigest() != source_sha:
        raise ValueError("diagnostic capture copy sha256 mismatch")
    run_id = f"simple-native-{case.case_id}"
    binding = _window_binding(case)
    identity = seal_hybrid_capture_identity(
        project_root=artifact_dir,
        image_path=copied,
        run_id=run_id,
        workflow_revision=1,
        window_binding=binding,
    )
    sources = [
        _persist_empty_context_source(root=artifact_dir, identity=identity, window_binding=binding, run_id=run_id, source_kind=kind)
        for kind in ("ocr", "uia")
    ]
    bundle = seal_hybrid_capture_bundle(
        project_root=artifact_dir,
        image_path=copied,
        run_id=run_id,
        workflow_revision=1,
        window_binding=binding,
        ocr_uia_context={"capture_lineage_ref": deepcopy(identity["capture_lineage_ref"]), "sources": sources, "derived_views": []},
        capture_envelope=identity.capture_envelope,
    )
    return {
        "path": copied,
        "bundle": bundle,
        "capture_id": identity["capture_id"],
        "screenshot_sha256": identity["screenshot_sha256"],
        "image_size": deepcopy(identity["image_size"]),
        "bundle_ref": deepcopy(bundle["bundle_ref"]),
        "context_ref": deepcopy(bundle["context_ref"]),
        "context_availability": {"ocr": "unavailable_empty", "uia": "unavailable_empty"},
        "source_path": str(case.image_path),
        "capture_path": str(copied),
    }


def _normalized_capture_bbox(item: OmniNativeItem, *, image_size: tuple[int, int]) -> list[int]:
    width, height = image_size
    x1, y1 = math.floor(item.bbox[0] * width), math.floor(item.bbox[1] * height)
    x2, y2 = math.ceil(item.bbox[2] * width), math.ceil(item.bbox[3] * height)
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise ValueError("Omni normalized bbox does not map inside capture")
    return [x1, y1, x2, y2]


def _omni_safe_items(parsed: Sequence[OmniNativeItem], *, image_size: tuple[int, int]) -> list[dict[str, object]]:
    safe_kinds = {"element", "text", "role", "state", "icon", "structure"}
    result = []
    for index, item in enumerate(parsed):
        result.append({
            "source_item_id": f"omni-native/{index:04d}/{_hash(asdict(item))[:16]}",
            "source_id_origin": "uei_deterministic_projection",
            "kind": item.type if item.type in safe_kinds else "element",
            "safe_text": item.content or None,
            "safe_role": item.type,
            "safe_states": ["interactive"] if item.interactivity else ["inactive"],
            "source_bbox": list(item.bbox),
            "capture_bbox": _normalized_capture_bbox(item, image_size=image_size),
            "source_coordinate_space": "image_normalized_xyxy",
            "coordinate_transform_ref": None,
            "opaque_attributes": {"native_type": item.type, "native_interactivity": item.interactivity, "normalization": "floor_min_ceil_max"},
            "provider_confidence": None,
        })
    return result


def _build_omni_evidence(
    *, case: ProviderCase, capture: Mapping[str, object], parsed: Sequence[OmniNativeItem], artifact_dir: Path
) -> dict[str, object]:
    bundle = capture["bundle"]
    assert isinstance(bundle, Mapping)
    result, result_ref = _persist_review_only_result(
        root=artifact_dir,
        capture_lineage_ref=bundle["capture_lineage_ref"],
        provider_id="local.runtime/omniparser",
        profile_id="local.runtime/omniparser/simple-native-v1",
        suffix=f"simple-native-{case.case_id}-omni",
        declared_output_kinds=["element", "text", "icon", "structure"],
        items=_omni_safe_items(parsed, image_size=case.image_size),
    )
    ledger = build_omni_candidate_ledger(safe_result=result, capture_bundle=bundle)
    inventory = omni_inventory_from_ledger(ledger)
    return {"provider_result": result, "provider_result_ref": result_ref, "ledger": ledger, "inventory": inventory}


def _eligible_bindings(bindings: Mapping[str, object], inventory: Mapping[str, object]) -> list[tuple[Mapping[str, object], Mapping[str, object]]]:
    candidates, parsed = inventory.get("candidates"), bindings.get("bindings")
    ambiguity_sets = bindings.get("ambiguity_sets")
    if not isinstance(candidates, list) or not isinstance(parsed, list):
        return []
    ambiguous_ids = {
        candidate_id
        for ambiguity in ambiguity_sets or []
        if isinstance(ambiguity, Mapping)
        for candidate_id in ambiguity.get("candidate_ids", [])
        if isinstance(candidate_id, str)
    }
    semantic_counts = Counter(
        (binding.get("role"), binding.get("label"))
        for binding in parsed
        if isinstance(binding, Mapping) and binding.get("ambiguity") is None and float(binding.get("semantic_confidence") or 0) > 0
    )
    by_id = {candidate.get("candidate_id"): candidate for candidate in candidates if isinstance(candidate, Mapping)}
    result = []
    for binding in parsed:
        if not isinstance(binding, Mapping):
            continue
        candidate = by_id.get(binding.get("candidate_id"))
        key = (binding.get("role"), binding.get("label"))
        if (
            isinstance(candidate, Mapping)
            and candidate.get("active") is True
            and binding.get("candidate_id") not in ambiguous_ids
            and binding.get("ambiguity") is None
            and float(binding.get("semantic_confidence") or 0) > 0
            and semantic_counts[key] == 1
        ):
            result.append((binding, candidate))
    return result


def _persist_vista_roi_crop(
    *, capture: Mapping[str, object], candidate: Mapping[str, object], artifact_dir: Path
) -> dict[str, object]:
    capture_path = Path(str(capture.get("capture_path") or ""))
    capture_sha = capture.get("screenshot_sha256")
    capture_id = capture.get("capture_id")
    image_size = capture.get("image_size")
    candidate_id = candidate.get("candidate_id")
    bbox = candidate.get("bbox_original")
    if not capture_path.is_file() or not isinstance(capture_sha, str):
        raise ValueError("VISTA capture artifact is unavailable")
    if sha256(capture_path.read_bytes()).hexdigest() != capture_sha:
        raise ValueError("VISTA capture sha256 mismatch")
    if (
        not isinstance(image_size, Mapping)
        or isinstance(image_size.get("width"), bool)
        or not isinstance(image_size.get("width"), int)
        or isinstance(image_size.get("height"), bool)
        or not isinstance(image_size.get("height"), int)
    ):
        raise ValueError("VISTA capture dimensions are invalid")
    width, height = image_size["width"], image_size["height"]
    if (
        not isinstance(candidate_id, str)
        or not isinstance(bbox, list)
        or len(bbox) != 4
        or any(isinstance(value, bool) or not isinstance(value, int) for value in bbox)
        or not (0 <= bbox[0] < bbox[2] <= width and 0 <= bbox[1] < bbox[3] <= height)
    ):
        raise ValueError("VISTA candidate ROI is not an integer in-capture bbox")
    crop_path = artifact_dir / "vista-roi" / f"{_hash({'capture_id': capture_id, 'candidate_id': candidate_id, 'bbox': bbox})}.png"
    crop_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(capture_path) as opened:
        if opened.size != (width, height):
            raise ValueError("VISTA capture dimensions changed")
        crop = opened.convert("RGB").crop(tuple(bbox))
        crop.save(crop_path)
    crop_bytes = crop_path.read_bytes()
    crop_width, crop_height = bbox[2] - bbox[0], bbox[3] - bbox[1]
    with Image.open(crop_path) as persisted:
        if persisted.size != (crop_width, crop_height):
            raise ValueError("VISTA persisted ROI dimensions mismatch")
    return {
        "contract_version": "simple_native_vista_roi_v1",
        "capture_id": capture_id,
        "capture_sha256": capture_sha,
        "candidate_id": candidate_id,
        "roi_xyxy": list(bbox),
        "source_path": str(capture_path),
        "source_sha256": capture_sha,
        "crop_path": str(crop_path),
        "crop_sha256": sha256(crop_bytes).hexdigest(),
        "crop_size": {"width": crop_width, "height": crop_height},
    }


def _record_failure(
    *, state: dict[str, Any], slot: str, raw: object, error: BaseException, error_class: str
) -> None:
    state["trace"].append({
        "slot": slot,
        "raw": _raw_text(raw),
        "error_class": error_class,
        "parse_error": str(error),
        "parent_capture_id": state["capture"]["capture_id"],
    })


def run_simple_native_regression_diagnostic(
    *,
    cases: Sequence[ProviderCase],
    slots: SimpleNativeSlots,
    artifact_dir: Path,
    cleanup_receipt: Mapping[str, object] | None = None,
) -> ProviderDiagnosticArtifact:
    """Run five provider-batched cases without reading Gold or acting."""
    if len(cases) != 5 or {case.case_id for case in cases} != {f"case-{index:03d}" for index in range(1, 6)}:
        raise ValueError("simple-native diagnostic requires exactly case-001 through case-005")
    if sum(len(case.goals) for case in cases) != 25:
        raise ValueError("simple-native diagnostic requires exactly 25 goals")
    artifact_dir = artifact_dir.resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    metrics: dict[str, Any] = {
        "omni": _metric(), "qwen": _metric(), "vista": _metric(),
        "denominator": 25, "abstained": 0, "correct_selected": 0, "wrong_selected": 0,
    }
    invalid_streak = {"omni": 0, "qwen": 0, "vista": 0}
    states: list[dict[str, Any]] = []
    for case in cases:
        states.append({
            "case": case,
            "capture": _prepare_capture(case, artifact_dir),
            "trace": [],
            "inventory": None,
            "bindings": None,
        })

    # 模型阶段按提供者批处理，避免逐屏切换 GPU 所有权。
    for state in states:
        if invalid_streak["omni"] >= 2:
            continue
        case, capture = state["case"], state["capture"]
        metrics["omni"]["attempted"] += 1
        started, raw = perf_counter(), ""
        try:
            raw = slots.omni(Path(capture["capture_path"]))
            parsed = parse_omni_native_output(raw)
            evidence = _build_omni_evidence(case=case, capture=capture, parsed=parsed, artifact_dir=artifact_dir)
            state["inventory"] = evidence["inventory"]
            metrics["omni"]["schema_valid"] += 1
            invalid_streak["omni"] = 0
            state["trace"].append({
                "slot": "omni",
                "raw": _raw_text(raw),
                "parsed_native": [
                    {**asdict(item), "bbox": list(item.bbox)} for item in parsed
                ],
                **evidence,
                "parent_capture_id": capture["capture_id"],
                "raw_sha256": _hash(raw),
            })
        except TimeoutError as exc:
            metrics["omni"]["timeout"] += 1
            invalid_streak["omni"] += 1
            _record_failure(state=state, slot="omni", raw=raw, error=exc, error_class="timeout")
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            metrics["omni"]["schema_invalid"] += 1
            invalid_streak["omni"] += 1
            _record_failure(state=state, slot="omni", raw=raw, error=exc, error_class="schema")
        metrics["omni"]["latencies"].append(round((perf_counter() - started) * 1000, 3))
        metrics["omni"]["raw_output_bytes"] += len(state["trace"][-1].get("raw", "").encode("utf-8"))

    for state in states:
        inventory = state["inventory"]
        if inventory is None or invalid_streak["qwen"] >= 2:
            continue
        capture = state["capture"]
        runtime_request = build_qwen_binding_request(capture["bundle"], inventory)
        projection = build_qwen_model_projection(runtime_request)
        metrics["qwen"]["attempted"] += 1
        started, raw = perf_counter(), ""
        try:
            raw = slots.qwen(Path(capture["capture_path"]), projection)
            expanded = expand_qwen_model_response(raw, projection=projection, runtime_request=runtime_request)
            parsed = parse_qwen_candidate_bindings(expanded, inventory, context_ref=runtime_request["context_ref"])
            state["bindings"] = parsed
            metrics["qwen"]["schema_valid"] += 1
            invalid_streak["qwen"] = 0
            state["trace"].append({
                "slot": "qwen",
                "runtime_request": runtime_request,
                "runtime_request_sha256": _hash(runtime_request),
                "wire_input": projection,
                "wire_input_sha256": _hash(projection),
                "raw": _raw_text(raw),
                "expanded": expanded,
                "parsed": parsed,
                "parent_capture_id": capture["capture_id"],
                "parent_inventory_sha256": inventory["content_sha256"],
                "raw_sha256": _hash(raw),
            })
        except TimeoutError as exc:
            metrics["qwen"]["timeout"] += 1
            invalid_streak["qwen"] += 1
            _record_failure(state=state, slot="qwen", raw=raw, error=exc, error_class="timeout")
            state["trace"][-1].update({"runtime_request_sha256": _hash(runtime_request), "wire_input": projection})
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            metrics["qwen"]["schema_invalid"] += 1
            invalid_streak["qwen"] += 1
            _record_failure(state=state, slot="qwen", raw=raw, error=exc, error_class="schema")
            state["trace"][-1].update({"runtime_request_sha256": _hash(runtime_request), "wire_input": projection})
        metrics["qwen"]["latencies"].append(round((perf_counter() - started) * 1000, 3))
        metrics["qwen"]["raw_output_bytes"] += len(state["trace"][-1].get("raw", "").encode("utf-8"))

    for state in states:
        inventory, bindings = state["inventory"], state["bindings"]
        if not isinstance(inventory, Mapping) or not isinstance(bindings, Mapping):
            continue
        capture = state["capture"]
        eligible = _eligible_bindings(bindings, inventory)
        eligible_ids = {binding["candidate_id"] for binding, _candidate in eligible}
        parsed_bindings = bindings.get("bindings")
        if isinstance(parsed_bindings, list):
            for binding in parsed_bindings:
                if isinstance(binding, Mapping) and binding.get("candidate_id") not in eligible_ids:
                    metrics["abstained"] += 1
                    state["trace"].append({
                        "slot": "vista",
                        "status": "abstained",
                        "reason": "candidate_not_uniquely_bound_active_eligible",
                        "semantic_role": binding.get("role"),
                        "semantic_label": binding.get("label"),
                        "candidate_id": binding.get("candidate_id"),
                        "parent_capture_id": capture["capture_id"],
                    })
        for binding, candidate in eligible:
            if invalid_streak["vista"] >= 2:
                metrics["abstained"] += 1
                state["trace"].append({
                    "slot": "vista",
                    "status": "abstained",
                    "reason": "vista_schema_circuit_open",
                    "semantic_role": binding["role"],
                    "semantic_label": binding["label"],
                    "candidate_id": binding["candidate_id"],
                    "parent_capture_id": capture["capture_id"],
                })
                continue
            metrics["vista"]["attempted"] += 1
            started, raw, roi_crop = perf_counter(), "", None
            try:
                roi_crop = _persist_vista_roi_crop(capture=capture, candidate=candidate, artifact_dir=artifact_dir)
                roi = tuple(roi_crop["roi_xyxy"])
                target = f"{binding['role']}: {binding['label']}"
                raw = slots.vista(Path(roi_crop["crop_path"]), target)
                normalized = parse_vista_normalized_point(raw)
                point = restore_vista_point_to_capture(normalized, roi_xyxy=roi)
                if not (roi[0] < point[0] < roi[2] and roi[1] < point[1] < roi[3]):
                    raise ValueError("restored VISTA point is outside strict candidate interior")
                metrics["vista"]["schema_valid"] += 1
                invalid_streak["vista"] = 0
                state["trace"].append({
                    "slot": "vista", "raw": raw, "parsed": list(normalized),
                    "capture_point": list(point), "roi_xyxy": list(roi),
                    "semantic_role": binding["role"], "semantic_label": binding["label"],
                    "candidate_id": binding["candidate_id"], "parent_capture_id": capture["capture_id"],
                    "roi_crop": roi_crop,
                    "raw_sha256": _hash(raw),
                })
            except TimeoutError as exc:
                metrics["vista"]["timeout"] += 1
                invalid_streak["vista"] += 1
                metrics["abstained"] += 1
                _record_failure(state=state, slot="vista", raw=raw, error=exc, error_class="timeout")
                state["trace"][-1].update({"semantic_role": binding["role"], "semantic_label": binding["label"], "candidate_id": binding["candidate_id"]})
                if roi_crop is not None:
                    state["trace"][-1]["roi_crop"] = roi_crop
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                metrics["vista"]["schema_invalid"] += 1
                invalid_streak["vista"] += 1
                metrics["abstained"] += 1
                _record_failure(state=state, slot="vista", raw=raw, error=exc, error_class="schema")
                state["trace"][-1].update({"semantic_role": binding["role"], "semantic_label": binding["label"], "candidate_id": binding["candidate_id"]})
                if roi_crop is not None:
                    state["trace"][-1]["roi_crop"] = roi_crop
            metrics["vista"]["latencies"].append(round((perf_counter() - started) * 1000, 3))
            metrics["vista"]["raw_output_bytes"] += len(raw.encode("utf-8"))

    records = [{
        "case_id": state["case"].case_id,
        "goal_count": len(state["case"].goals),
        "capture": {key: deepcopy(value) for key, value in state["capture"].items() if key not in {"bundle", "path"}},
        "trace": state["trace"],
    } for state in states]
    for slot in ("omni", "qwen", "vista"):
        metrics[slot] = _finish(metrics[slot])
    observed_cleanup = (
        dict(cleanup_receipt) if cleanup_receipt is not None
        else dict(slots.cleanup()) if slots.cleanup is not None
        else {"verified": False, "reason": "runner received no lifecycle cleanup observation"}
    )
    payload = seal_immutable({
        "contract_version": "simple_native_provider_diagnostic_v2",
        "regression_diagnostic_only": True,
        "promotion_eligible": False,
        "screen_count": 5,
        "target_count": 25,
        "metrics": metrics,
        "cases": records,
        "cleanup_receipt": observed_cleanup,
        "action_candidates": [],
        "artifact_is_authorization": False,
        "execute_binding": False,
    })
    path = artifact_dir / "provider-diagnostic.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return ProviderDiagnosticArtifact(path=path, cases=tuple(records), metrics=metrics, screen_count=5, target_count=25)


def score_simple_native_regression(
    *, provider_artifact: ProviderDiagnosticArtifact, gold_path: Path
) -> RegressionDiagnosticReport:
    """The only Gold-reading boundary; the provider artifact must already exist."""
    if not provider_artifact.path.is_file():
        raise ValueError("provider artifact must be finalized before scoring")
    provider_payload = json.loads(provider_artifact.path.read_text(encoding="utf-8"))
    if (
        not isinstance(provider_payload, Mapping)
        or provider_payload.get("contract_version") != "simple_native_provider_diagnostic_v2"
        or provider_payload.get("content_sha256") != content_sha256(dict(provider_payload))
        or provider_payload.get("screen_count") != 5
        or provider_payload.get("target_count") != 25
        or not isinstance(provider_payload.get("cases"), list)
    ):
        raise ValueError("provider artifact is not a finalized sealed diagnostic")
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    targets = gold.get("targets") if isinstance(gold, Mapping) else None
    if not isinstance(targets, list):
        raise ValueError("Gold targets are invalid")
    gold_by_screen: dict[str, list[Mapping[str, object]]] = {}
    for target in targets:
        if isinstance(target, Mapping) and target.get("partition") == "regression" and isinstance(target.get("screen_id"), str):
            gold_by_screen.setdefault(target["screen_id"], []).append(target)
    correct = wrong = abstained = 0
    for case in provider_payload["cases"]:
        if not isinstance(case, Mapping):
            raise ValueError("provider artifact case is invalid")
        screen = case.get("case_id")
        expected = gold_by_screen.get(screen) if isinstance(screen, str) else None
        if not expected:
            raise ValueError("provider artifact case has no regression Gold join")
        observed = [entry for entry in case.get("trace", []) if isinstance(entry, Mapping) and entry.get("slot") == "vista"]
        capture = case.get("capture") if isinstance(case.get("capture"), Mapping) else {}
        for target in expected:
            role, label = target.get("role"), target.get("label")
            if not isinstance(role, str) or not isinstance(label, str):
                raise ValueError("Gold semantic identity is invalid")
            matches = [
                entry for entry in observed
                if entry.get("semantic_role") == role
                and entry.get("semantic_label") == label
                and "capture_point" in entry
            ]
            if len(matches) != 1:
                abstained += 1
                continue
            entry = matches[0]
            point = entry.get("capture_point")
            bbox = target.get("bbox")
            roi = entry.get("roi_xyxy")
            crop = entry.get("roi_crop")
            if (
                not isinstance(point, list)
                or len(point) != 2
                or any(isinstance(value, bool) or not isinstance(value, int) for value in point)
                or not isinstance(roi, list)
                or len(roi) != 4
                or any(isinstance(value, bool) or not isinstance(value, int) for value in roi)
                or not (roi[0] < point[0] < roi[2] and roi[1] < point[1] < roi[3])
                or not isinstance(crop, Mapping)
                or crop.get("capture_id") != capture.get("capture_id")
                or crop.get("capture_sha256") != capture.get("screenshot_sha256")
                or crop.get("candidate_id") != entry.get("candidate_id")
                or crop.get("roi_xyxy") != roi
            ):
                abstained += 1
            elif (
                not isinstance(bbox, list)
                or len(bbox) != 4
                or any(isinstance(value, bool) or not isinstance(value, int) for value in bbox)
            ):
                raise ValueError("Gold target bbox is invalid")
            elif bbox[0] < point[0] < bbox[2] and bbox[1] < point[1] < bbox[3]:
                correct += 1
            else:
                wrong += 1
    return RegressionDiagnosticReport(
        sha256(provider_artifact.path.read_bytes()).hexdigest(), True, False,
        int(provider_payload["target_count"]), correct, wrong, abstained,
    )
