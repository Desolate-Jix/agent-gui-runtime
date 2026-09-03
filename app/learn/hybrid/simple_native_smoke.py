"""Offline-first, injectible simple-native five-screen diagnostic runner."""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import shutil
from statistics import median
import sys
from time import perf_counter
from typing import Any, Callable, Iterator, Mapping, Protocol, Sequence

from PIL import Image

from app.learn.hybrid.omni_candidates import build_omni_candidate_ledger, omni_inventory_from_ledger
from app.learn.hybrid.qwen_binding import build_simple_native_goal_binding_request
from app.learn.hybrid.simple_native_contracts import (
    OmniNativeItem,
    build_qwen_goal_binding_projection,
    expand_qwen_goal_binding_response,
    parse_omni_native_output,
    parse_vista_normalized_point,
    restore_vista_point_to_capture,
)
from app.learn.recognition.uei.canonical import content_sha256, seal_immutable
from app.learn.recognition.uei.store import UEIObjectStore


_PROVIDER_GOAL = re.compile(
    r"\ASelect the (?P<role>[a-z][a-z0-9_-]*) labeled '(?P<label>[^'\r\n]+)'\Z"
)
_CLEANUP_OBSERVATION_FIELDS = {
    "contract_version",
    "provider",
    "verified",
    "cleanup_status",
    "owned_processes",
    "provider_processes_after",
    "helper_processes_after",
    "orphan_descendant_pids",
    "active_listeners_after",
    "lease_files_after",
}


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
    release_provider: Callable[[str], Mapping[str, object]] | None = None
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


def _parse_provider_goals(case: ProviderCase) -> list[dict[str, str]]:
    parsed: list[dict[str, str]] = []
    seen_semantics: set[tuple[str, str]] = set()
    for index, goal in enumerate(case.goals):
        match = _PROVIDER_GOAL.fullmatch(goal) if isinstance(goal, str) else None
        if match is None or match.group("label").strip() != match.group("label"):
            raise ValueError(f"{case.case_id} provider goal is outside the closed grammar")
        role, label = match.group("role"), match.group("label")
        semantic = (role, label)
        if semantic in seen_semantics:
            raise ValueError(f"{case.case_id} provider goals contain duplicate semantic identity")
        seen_semantics.add(semantic)
        parsed.append({
            "goal_id": f"{case.case_id}/goal-{index + 1:02d}/{_hash({'goal': goal})[:16]}",
            "goal_text": goal,
            "semantic_role": role,
            "semantic_label": label,
        })
    return parsed


def _verify_capture_freshness(capture: Mapping[str, object], provider: str) -> Path:
    capture_path = Path(str(capture.get("capture_path") or ""))
    expected_sha = capture.get("screenshot_sha256")
    image_size = capture.get("image_size")
    if not capture_path.is_file() or not isinstance(expected_sha, str):
        raise ValueError(f"{provider} capture artifact is unavailable")
    if sha256(capture_path.read_bytes()).hexdigest() != expected_sha:
        raise ValueError(f"{provider} capture sha256 mismatch")
    if (
        not isinstance(image_size, Mapping)
        or isinstance(image_size.get("width"), bool)
        or not isinstance(image_size.get("width"), int)
        or isinstance(image_size.get("height"), bool)
        or not isinstance(image_size.get("height"), int)
    ):
        raise ValueError(f"{provider} capture dimensions are invalid")
    with Image.open(capture_path) as opened:
        if opened.size != (image_size["width"], image_size["height"]):
            raise ValueError(f"{provider} capture dimensions changed")
    return capture_path


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


def build_omni_evidence_from_native(
    *, case: ProviderCase, capture: Mapping[str, object], parsed: Sequence[OmniNativeItem], artifact_dir: Path
) -> dict[str, object]:
    """Project parsed Omni items through the shared canonical candidate conversion."""
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
    capture_path = _verify_capture_freshness(capture, "VISTA")
    capture_sha = capture.get("screenshot_sha256")
    capture_id = capture.get("capture_id")
    image_size = capture.get("image_size")
    candidate_id = candidate.get("candidate_id")
    bbox = candidate.get("bbox_original")
    if not isinstance(capture_sha, str):
        raise ValueError("VISTA capture artifact is unavailable")
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


def _record_goal_abstention(
    *, state: dict[str, Any], goal: Mapping[str, str], reason: str, candidate_id: object = None
) -> None:
    state["trace"].append({
        "slot": "vista",
        "status": "abstained",
        "reason": reason,
        **deepcopy(dict(goal)),
        "candidate_id": candidate_id,
        "parent_capture_id": state["capture"]["capture_id"],
    })


def _observe_provider_cleanup(slots: SimpleNativeSlots, provider: str) -> dict[str, object]:
    if slots.release_provider is None:
        return {
            "provider": provider,
            "verified": False,
            "not_applicable": True,
            "reason": "injected replay slot has no managed process lifecycle",
        }
    receipt = slots.release_provider(provider)
    if not isinstance(receipt, Mapping) or set(receipt) != _CLEANUP_OBSERVATION_FIELDS:
        raise ValueError(f"{provider} cleanup observation is invalid")
    observed = dict(receipt)
    if (
        observed.get("contract_version") != "simple_native_provider_cleanup_v1"
        or observed.get("provider") != provider
        or not isinstance(observed.get("verified"), bool)
        or observed.get("cleanup_status") not in {"verified", "failed"}
        or any(
            not isinstance(observed[field], list)
            for field in (
                "owned_processes",
                "provider_processes_after",
                "helper_processes_after",
                "orphan_descendant_pids",
                "active_listeners_after",
                "lease_files_after",
            )
        )
    ):
        raise ValueError(f"{provider} cleanup observation is invalid")
    if (
        observed["verified"] is not True
        or observed["cleanup_status"] != "verified"
        or any(
            observed[field]
            for field in (
                "owned_processes",
                "provider_processes_after",
                "helper_processes_after",
                "orphan_descendant_pids",
                "active_listeners_after",
                "lease_files_after",
            )
        )
    ):
        raise RuntimeError(f"{provider} cleanup observation is not clean; next provider is blocked")
    return observed


@contextmanager
def _provider_phase(
    *, slots: SimpleNativeSlots, provider: str, observations: list[dict[str, object]]
) -> Iterator[None]:
    provider_error: BaseException | None = None
    try:
        yield
    except BaseException as exc:
        provider_error = exc
        raise
    finally:
        try:
            observations.append(_observe_provider_cleanup(slots, provider))
        except BaseException as cleanup_error:
            if provider_error is not None:
                raise cleanup_error from provider_error
            raise


def run_simple_native_regression_diagnostic(
    *,
    cases: Sequence[ProviderCase],
    slots: SimpleNativeSlots,
    artifact_dir: Path,
) -> ProviderDiagnosticArtifact:
    """Run five provider-batched cases without reading Gold or acting."""
    if len(cases) != 5 or [case.case_id for case in cases] != [f"case-{index:03d}" for index in range(1, 6)]:
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
    provider_phase_cleanup: list[dict[str, object]] = []
    for case in cases:
        goals = _parse_provider_goals(case)
        states.append({
            "case": case,
            "capture": _prepare_capture(case, artifact_dir),
            "goals": goals,
            "trace": [],
            "inventory": None,
            "bindings": None,
        })

    # 模型阶段按提供者批处理，避免逐屏切换 GPU 所有权。
    with _provider_phase(slots=slots, provider="omni", observations=provider_phase_cleanup):
        for state in states:
            if invalid_streak["omni"] >= 2:
                continue
            case, capture = state["case"], state["capture"]
            metrics["omni"]["attempted"] += 1
            started, raw = perf_counter(), ""
            try:
                capture_path = _verify_capture_freshness(capture, "Omni")
                raw = slots.omni(capture_path)
                _verify_capture_freshness(capture, "Omni")
                parsed = parse_omni_native_output(raw)
                evidence = build_omni_evidence_from_native(case=case, capture=capture, parsed=parsed, artifact_dir=artifact_dir)
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

    with _provider_phase(slots=slots, provider="qwen", observations=provider_phase_cleanup):
        for state in states:
            inventory = state["inventory"]
            if inventory is None or invalid_streak["qwen"] >= 2:
                continue
            capture = state["capture"]
            metrics["qwen"]["attempted"] += 1
            started, raw, runtime_request, projection = perf_counter(), "", None, None
            try:
                capture_path = _verify_capture_freshness(capture, "Qwen")
                runtime_request = build_simple_native_goal_binding_request(
                    capture["bundle"], inventory, state["goals"]
                )
                projection = build_qwen_goal_binding_projection(runtime_request)
                raw = slots.qwen(capture_path, projection)
                _verify_capture_freshness(capture, "Qwen")
                parsed = expand_qwen_goal_binding_response(
                    raw, projection=projection, runtime_request=runtime_request
                )
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
                    "expanded": parsed,
                    "parsed": parsed,
                    "parent_capture_id": capture["capture_id"],
                    "parent_inventory_sha256": inventory["content_sha256"],
                    "raw_sha256": _hash(raw),
                })
            except TimeoutError as exc:
                metrics["qwen"]["timeout"] += 1
                invalid_streak["qwen"] += 1
                _record_failure(state=state, slot="qwen", raw=raw, error=exc, error_class="timeout")
                if runtime_request is not None and projection is not None:
                    state["trace"][-1].update({"runtime_request_sha256": _hash(runtime_request), "wire_input": projection})
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                metrics["qwen"]["schema_invalid"] += 1
                invalid_streak["qwen"] += 1
                _record_failure(state=state, slot="qwen", raw=raw, error=exc, error_class="schema")
                if runtime_request is not None and projection is not None:
                    state["trace"][-1].update({"runtime_request_sha256": _hash(runtime_request), "wire_input": projection})
            metrics["qwen"]["latencies"].append(round((perf_counter() - started) * 1000, 3))
            metrics["qwen"]["raw_output_bytes"] += len(state["trace"][-1].get("raw", "").encode("utf-8"))

    with _provider_phase(slots=slots, provider="vista", observations=provider_phase_cleanup):
        for state in states:
            inventory, bindings = state["inventory"], state["bindings"]
            capture = state["capture"]
            candidates = (
                {candidate.get("candidate_id"): candidate for candidate in inventory.get("candidates", []) if isinstance(candidate, Mapping)}
                if isinstance(inventory, Mapping) else {}
            )
            bound_by_goal = (
                {binding.get("goal_index"): binding for binding in bindings.get("bindings", []) if isinstance(binding, Mapping)}
                if isinstance(bindings, Mapping) else {}
            )
            for goal_index, goal in enumerate(state["goals"]):
                binding = bound_by_goal.get(goal_index)
                candidate_id = binding.get("candidate_id") if isinstance(binding, Mapping) else None
                candidate = candidates.get(candidate_id) if isinstance(candidate_id, str) else None
                if not isinstance(binding, Mapping) or binding.get("status") != "BOUND" or not isinstance(candidate, Mapping):
                    metrics["abstained"] += 1
                    _record_goal_abstention(
                        state=state,
                        goal=goal,
                        reason=(
                            "provider_evidence_unavailable"
                            if not isinstance(inventory, Mapping) or not isinstance(bindings, Mapping)
                            else "goal_binding_not_unique_active_eligible"
                        ),
                    )
                    continue
                if candidate.get("active") is not True:
                    metrics["abstained"] += 1
                    _record_goal_abstention(
                        state=state, goal=goal, reason="goal_bound_candidate_inactive", candidate_id=candidate_id
                    )
                    continue
                if invalid_streak["vista"] >= 2:
                    metrics["abstained"] += 1
                    _record_goal_abstention(
                        state=state, goal=goal, reason="vista_schema_circuit_open", candidate_id=candidate_id
                    )
                    continue
                metrics["vista"]["attempted"] += 1
                started, raw, roi_crop = perf_counter(), "", None
                try:
                    _verify_capture_freshness(capture, "VISTA")
                    roi_crop = _persist_vista_roi_crop(capture=capture, candidate=candidate, artifact_dir=artifact_dir)
                    roi = tuple(roi_crop["roi_xyxy"])
                    target = f"{binding['role']}: {binding['label']}"
                    raw = slots.vista(Path(roi_crop["crop_path"]), target)
                    _verify_capture_freshness(capture, "VISTA")
                    normalized = parse_vista_normalized_point(raw)
                    point = restore_vista_point_to_capture(normalized, roi_xyxy=roi)
                    if not (roi[0] < point[0] < roi[2] and roi[1] < point[1] < roi[3]):
                        raise ValueError("restored VISTA point is outside strict candidate interior")
                    metrics["vista"]["schema_valid"] += 1
                    invalid_streak["vista"] = 0
                    state["trace"].append({
                        "slot": "vista", "status": "selected", "raw": raw, "parsed": list(normalized),
                        "capture_point": list(point), "roi_xyxy": list(roi),
                        **deepcopy(dict(goal)),
                        "candidate_id": candidate_id, "parent_capture_id": capture["capture_id"],
                        "roi_crop": roi_crop,
                        "raw_sha256": _hash(raw),
                    })
                except TimeoutError as exc:
                    metrics["vista"]["timeout"] += 1
                    invalid_streak["vista"] += 1
                    metrics["abstained"] += 1
                    _record_failure(state=state, slot="vista", raw=raw, error=exc, error_class="timeout")
                    state["trace"][-1].update({"status": "abstained", **deepcopy(dict(goal)), "candidate_id": candidate_id})
                    if roi_crop is not None:
                        state["trace"][-1]["roi_crop"] = roi_crop
                except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                    metrics["vista"]["schema_invalid"] += 1
                    invalid_streak["vista"] += 1
                    metrics["abstained"] += 1
                    _record_failure(state=state, slot="vista", raw=raw, error=exc, error_class="schema")
                    state["trace"][-1].update({"status": "abstained", **deepcopy(dict(goal)), "candidate_id": candidate_id})
                    if roi_crop is not None:
                        state["trace"][-1]["roi_crop"] = roi_crop
                metrics["vista"]["latencies"].append(round((perf_counter() - started) * 1000, 3))
                metrics["vista"]["raw_output_bytes"] += len(raw.encode("utf-8"))

    records = [{
        "case_id": state["case"].case_id,
        "goal_count": len(state["case"].goals),
        "goals": deepcopy(state["goals"]),
        "capture": {key: deepcopy(value) for key, value in state["capture"].items() if key not in {"bundle", "path"}},
        "trace": state["trace"],
    } for state in states]
    for slot in ("omni", "qwen", "vista"):
        metrics[slot] = _finish(metrics[slot])
    observed_cleanup = (
        dict(slots.cleanup()) if slots.cleanup is not None
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
        "provider_phase_cleanup": provider_phase_cleanup,
        "cleanup_receipt": observed_cleanup,
        "action_candidates": [],
        "artifact_is_authorization": False,
        "execute_binding": False,
    })
    path = artifact_dir / "provider-diagnostic.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return ProviderDiagnosticArtifact(path=path, cases=tuple(records), metrics=metrics, screen_count=5, target_count=25)


def _validate_provider_artifact_structure(provider_payload: Mapping[str, object]) -> None:
    cases = provider_payload.get("cases")
    metrics = provider_payload.get("metrics")
    vista_metrics = metrics.get("vista") if isinstance(metrics, Mapping) else None
    if (
        not isinstance(cases, list)
        or len(cases) != 5
        or [case.get("case_id") if isinstance(case, Mapping) else None for case in cases]
        != [f"case-{index:03d}" for index in range(1, 6)]
        or not isinstance(metrics, Mapping)
        or not isinstance(vista_metrics, Mapping)
        or isinstance(vista_metrics.get("attempted"), bool)
        or not isinstance(vista_metrics.get("attempted"), int)
        or not 0 <= vista_metrics["attempted"] <= 25
        or isinstance(metrics.get("denominator"), bool)
        or not isinstance(metrics.get("denominator"), int)
        or isinstance(provider_payload.get("target_count"), bool)
        or not isinstance(provider_payload.get("target_count"), int)
        or metrics.get("denominator") != 25
        or provider_payload.get("target_count") != metrics.get("denominator")
    ):
        raise ValueError("provider artifact structure has inconsistent cases or denominator")
    total_goals = total_outcomes = abstained_outcomes = 0
    for case in cases:
        assert isinstance(case, Mapping)
        case_id = case["case_id"]
        goals = case.get("goals")
        trace = case.get("trace")
        goal_count = case.get("goal_count")
        if (
            isinstance(goal_count, bool)
            or not isinstance(goal_count, int)
            or goal_count != 5
            or not isinstance(goals, list)
            or len(goals) != goal_count
            or not isinstance(trace, list)
        ):
            raise ValueError("provider artifact structure has invalid goals or trace")
        validated_goals: dict[str, Mapping[str, object]] = {}
        semantic_goals: set[tuple[object, object]] = set()
        for index, goal in enumerate(goals):
            if not isinstance(goal, Mapping) or set(goal) != {
                "goal_id", "goal_text", "semantic_role", "semantic_label"
            }:
                raise ValueError("provider artifact structure has malformed goal identity")
            goal_text = goal.get("goal_text")
            match = _PROVIDER_GOAL.fullmatch(goal_text) if isinstance(goal_text, str) else None
            expected_goal_id = (
                f"{case_id}/goal-{index + 1:02d}/{_hash({'goal': goal_text})[:16]}"
                if match is not None
                else None
            )
            semantic = (goal.get("semantic_role"), goal.get("semantic_label"))
            if (
                match is None
                or match.group("label").strip() != match.group("label")
                or semantic != (match.group("role"), match.group("label"))
                or goal.get("goal_id") != expected_goal_id
                or not isinstance(goal.get("goal_id"), str)
                or goal["goal_id"] in validated_goals
                or semantic in semantic_goals
            ):
                raise ValueError("provider artifact structure has duplicate or inconsistent goals")
            validated_goals[goal["goal_id"]] = goal
            semantic_goals.add(semantic)
        outcomes = [entry for entry in trace if isinstance(entry, Mapping) and entry.get("slot") == "vista"]
        if len(outcomes) != goal_count:
            raise ValueError("provider artifact structure must contain one VISTA outcome per goal")
        seen_outcomes: set[str] = set()
        semantic_outcomes: set[tuple[object, object]] = set()
        for outcome in outcomes:
            goal_id = outcome.get("goal_id")
            goal = validated_goals.get(goal_id) if isinstance(goal_id, str) else None
            semantic = (outcome.get("semantic_role"), outcome.get("semantic_label"))
            status = outcome.get("status")
            if (
                goal is None
                or goal_id in seen_outcomes
                or semantic in semantic_outcomes
                or outcome.get("goal_text") != goal.get("goal_text")
                or semantic != (goal.get("semantic_role"), goal.get("semantic_label"))
                or status not in {"selected", "abstained"}
                or (status == "selected" and "capture_point" not in outcome)
                or (status == "abstained" and "capture_point" in outcome)
            ):
                raise ValueError("provider artifact structure has duplicate or inconsistent VISTA outcomes")
            seen_outcomes.add(goal_id)
            semantic_outcomes.add(semantic)
            if status == "abstained":
                abstained_outcomes += 1
        if seen_outcomes != set(validated_goals):
            raise ValueError("provider artifact structure is missing a VISTA goal outcome")
        total_goals += len(goals)
        total_outcomes += len(outcomes)
    if (
        total_goals != 25
        or total_outcomes != 25
        or metrics.get("abstained") != abstained_outcomes
    ):
        raise ValueError("provider artifact structure has inconsistent outcome totals")


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
    _validate_provider_artifact_structure(provider_payload)
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
