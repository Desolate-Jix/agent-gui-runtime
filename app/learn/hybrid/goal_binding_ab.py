"""Frozen-Omni, one-arm goal-binding diagnostic runner.

This module deliberately owns only the binder seam.  Discovery remains sealed in
``omni_snapshot`` and VISTA remains the existing non-authorizing refinement
path.  It never creates an Omni caller and never reads Gold.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter
from typing import Any

from app.learn.hybrid.goal_binding_provider import (
    NativePointProposal,
    map_native_point_to_candidate,
    validate_goal_binding_provider_result,
)
from app.learn.hybrid.omni_snapshot import load_verified_omni_snapshot
from app.learn.hybrid.simple_native_contracts import (
    expand_qwen_goal_binding_response,
    parse_vista_normalized_point,
    restore_vista_point_to_capture,
)
from app.learn.hybrid.simple_native_smoke import (
    ProviderCase,
    ProviderDiagnosticArtifact,
    VistaNativeCaller,
    _parse_provider_goals,
    _persist_vista_roi_crop,
    _verify_capture_freshness,
)
from app.learn.recognition.uei.canonical import seal_immutable


_CLEANUP_FIELDS = frozenset({
    "contract_version", "provider", "verified", "cleanup_status", "owned_processes",
    "provider_processes_after", "helper_processes_after", "orphan_descendant_pids",
    "active_listeners_after", "lease_files_after",
})
_CLEANUP_LISTS = (
    "owned_processes", "provider_processes_after", "helper_processes_after",
    "orphan_descendant_pids", "active_listeners_after", "lease_files_after",
)


@dataclass(frozen=True)
class GoalBindingArm:
    arm_id: str
    provider_id: str
    call: Callable[[Path, Mapping[str, object]], object]
    adapt: Callable[[object, int, Mapping[str, object]], Mapping[str, object]]
    cleanup: Callable[[], Mapping[str, object]]


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _hash(value: object) -> str:
    return sha256(_canonical(value)).hexdigest()


def _text_hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _raw_text(value: object) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _metric() -> dict[str, object]:
    return {"attempted": 0, "schema_valid": 0, "schema_invalid": 0, "timeout": 0, "latencies": [], "raw_output_bytes": 0}


def _finish(metric: dict[str, object]) -> dict[str, object]:
    values = metric.pop("latencies")
    assert isinstance(values, list)
    metric["latency_p50_ms"] = sorted(values)[len(values) // 2] if values else 0
    metric["latency_p95_ms"] = max(values) if values else 0
    return metric


def _require_arm(arm: GoalBindingArm) -> None:
    if (
        not isinstance(arm, GoalBindingArm)
        or not isinstance(arm.arm_id, str)
        or not arm.arm_id.strip()
        or not isinstance(arm.provider_id, str)
        or not arm.provider_id.strip()
        or not callable(arm.call)
        or not callable(arm.adapt)
        or not callable(arm.cleanup)
    ):
        raise ValueError("goal-binding arm is invalid")


def _snapshot_ref(snapshot: Mapping[str, object]) -> dict[str, str]:
    digest = snapshot.get("snapshot_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError("frozen Omni snapshot hash is invalid")
    return {"id": f"omni-snapshot/{digest}", "sha256": digest}


def _capture_for_vista(case: ProviderCase, frozen_case: Mapping[str, object]) -> tuple[dict[str, object], dict[str, str]]:
    frozen_capture = frozen_case.get("capture")
    if not isinstance(frozen_capture, Mapping):
        raise ValueError("frozen Omni capture is unavailable")
    capture_id = frozen_capture.get("capture_id")
    screenshot_sha = frozen_capture.get("screenshot_sha256")
    image_size = frozen_capture.get("image_size")
    if (
        not isinstance(capture_id, str)
        or not isinstance(screenshot_sha, str)
        or not isinstance(image_size, Mapping)
        or image_size != {"width": case.image_size[0], "height": case.image_size[1]}
        or screenshot_sha != case.image_sha256
    ):
        raise ValueError("frozen Omni capture does not match the requested case")
    capture = {
        "capture_id": capture_id,
        "screenshot_sha256": screenshot_sha,
        "image_size": deepcopy(dict(image_size)),
        "capture_path": str(case.image_path),
    }
    return capture, {"id": f"capture/{capture_id}", "sha256": screenshot_sha}


def _provider_failure(*, goal_index: int, provider_id: str, context: Mapping[str, object], reason: str) -> dict[str, object]:
    return map_native_point_to_candidate(
        proposal=NativePointProposal(
            goal_index=goal_index,
            point=None,
            coordinate_space="capture_pixels",
            confidence=None,
            status="PROVIDER_FAILURE",
            failure_reason=reason,
        ),
        image_size=context["image_size"],  # type: ignore[arg-type]
        candidates=context["candidates"],  # type: ignore[arg-type]
        provider_id=provider_id,
        capture_ref=context["capture_ref"],  # type: ignore[arg-type]
        native_output_ref=context["native_output_ref"],  # type: ignore[arg-type]
        omni_snapshot_ref=context["omni_snapshot_ref"],  # type: ignore[arg-type]
    )


def _record_native_parsed(context: Mapping[str, object], value: Mapping[str, object]) -> None:
    """Record adapter parsing as diagnostic-only evidence, never as authority."""
    recorder = context.get("record_native_parsed")
    if recorder is None:
        return
    if not callable(recorder) or not isinstance(value, Mapping):
        raise ValueError("native parsed evidence recorder is invalid")
    recorder(deepcopy(dict(value)))


def _selected_candidate_evidence(
    *, binding: Mapping[str, object], candidate: Mapping[str, object], capture_ref: Mapping[str, str], snapshot_ref: Mapping[str, str]
) -> dict[str, object]:
    index, bbox = binding.get("candidate_index"), candidate.get("bbox_original")
    if (
        isinstance(index, bool)
        or not isinstance(index, int)
        or not isinstance(bbox, list)
        or len(bbox) != 4
        or any(isinstance(value, bool) or not isinstance(value, int) for value in bbox)
        or not bbox[0] < bbox[2]
        or not bbox[1] < bbox[3]
    ):
        raise ValueError("selected frozen candidate geometry is invalid")
    return {
        "candidate_id": binding["candidate_id"],
        "candidate_index": index,
        "bbox_original": list(bbox),
        "center_capture_pixel": [
            (bbox[0] + bbox[2]) / 2.0,
            (bbox[1] + bbox[3]) / 2.0,
        ],
        "capture_ref": deepcopy(dict(capture_ref)),
        "omni_snapshot_ref": deepcopy(dict(snapshot_ref)),
    }


def make_native_point_adapter(
    parser: Callable[[object], NativePointProposal] | Callable[..., NativePointProposal],
    profile: Mapping[str, object],
) -> Callable[[object, int, Mapping[str, object]], Mapping[str, object]]:
    """Bind a sealed native parser to the frozen candidates via the sole mapper."""
    sealed_profile = deepcopy(dict(profile))

    def adapt(raw: object, goal_index: int, context: Mapping[str, object]) -> Mapping[str, object]:
        try:
            proposal = parser(raw, goal_index=goal_index, profile=deepcopy(sealed_profile))
        except (TypeError, ValueError) as exc:
            raise ValueError("native point parser invocation failed") from exc
        if not isinstance(proposal, NativePointProposal):
            raise ValueError("native point parser returned an invalid proposal")
        _record_native_parsed(context, {
            "contract_version": "goal_binding_native_point_proposal_v1",
            "goal_index": proposal.goal_index,
            "point": list(proposal.point) if proposal.point is not None else None,
            "coordinate_space": proposal.coordinate_space,
            "confidence": proposal.confidence,
            "status": proposal.status,
            "failure_reason": proposal.failure_reason,
        })
        return map_native_point_to_candidate(
            proposal=proposal,
            image_size=context["image_size"],  # type: ignore[arg-type]
            candidates=context["candidates"],  # type: ignore[arg-type]
            provider_id=context["provider_id"],  # type: ignore[arg-type]
            capture_ref=context["capture_ref"],  # type: ignore[arg-type]
            native_output_ref=context["native_output_ref"],  # type: ignore[arg-type]
            omni_snapshot_ref=context["omni_snapshot_ref"],  # type: ignore[arg-type]
        )

    return adapt


def adapt_incumbent_candidate_index(
    raw: object, goal_index: int, context: Mapping[str, object]
) -> Mapping[str, object]:
    """Use the existing single-goal Qwen ordinal parser without fabricating a point."""
    projection = context.get("incumbent_projection")
    request = context.get("incumbent_runtime_request")
    candidates = context.get("candidates")
    if not isinstance(projection, Mapping) or not isinstance(request, Mapping) or not isinstance(candidates, list):
        raise ValueError("incumbent candidate-index context is unavailable")
    expanded = expand_qwen_goal_binding_response(raw, projection=projection, runtime_request=request)
    _record_native_parsed(context, expanded)
    bindings = expanded.get("bindings")
    if not isinstance(bindings, list) or len(bindings) != 1 or not isinstance(bindings[0], Mapping):
        raise ValueError("incumbent candidate-index response is incomplete")
    binding = bindings[0]
    if binding.get("status") != "BOUND":
        result = {
            "contract_version": "goal_binding_provider_result_v1",
            "goal_index": goal_index,
            "candidate_index": None,
            "candidate_id": None,
            "status": "UNBOUND",
            "reason": "provider_abstained",
            "binding_basis": "direct_candidate_index",
            "confidence": binding.get("confidence"),
            "canonical_capture_pixel_point": None,
            "provider_id": context["provider_id"],
            "native_output_ref": context["native_output_ref"],
            "omni_snapshot_ref": context["omni_snapshot_ref"],
            "capture_ref": context["capture_ref"],
            "artifact_is_authorization": False,
        }
        return validate_goal_binding_provider_result(result)
    candidate_id = binding.get("candidate_id")
    candidate_index = next(
        (index for index, candidate in enumerate(candidates) if isinstance(candidate, Mapping) and candidate.get("candidate_id") == candidate_id),
        None,
    )
    if candidate_index is None or not isinstance(candidate_id, str):
        raise ValueError("incumbent candidate-index does not refer to the frozen snapshot")
    candidate = candidates[candidate_index]
    if not isinstance(candidate, Mapping) or candidate.get("active") is not True:
        raise ValueError("incumbent candidate-index is inactive in the frozen snapshot")
    confidence = binding.get("confidence")
    result = {
        "contract_version": "goal_binding_provider_result_v1",
        "goal_index": goal_index,
        "candidate_index": candidate_index,
        "candidate_id": candidate_id,
        "status": "BOUND",
        "reason": None,
        "binding_basis": "direct_candidate_index",
        "confidence": confidence,
        "canonical_capture_pixel_point": None,
        "provider_id": context["provider_id"],
        "native_output_ref": context["native_output_ref"],
        "omni_snapshot_ref": context["omni_snapshot_ref"],
        "capture_ref": context["capture_ref"],
        "artifact_is_authorization": False,
    }
    return validate_goal_binding_provider_result(result)


def _incumbent_request(*, goal: Mapping[str, object], candidates: list[dict[str, object]], image_size: tuple[int, int]) -> tuple[dict[str, object], dict[str, object]]:
    request = {
        "contract_version": "simple_native_qwen_goal_binding_request_v1",
        "screenshot": {"image_size": {"width": image_size[0], "height": image_size[1]}},
        "goals": [{"goal_index": 0, "role": goal["semantic_role"], "label": goal["semantic_label"]}],
        "candidates": [
            {
                "candidate_id": candidate["candidate_id"],
                "bbox_original": deepcopy(candidate["bbox_original"]),
                "active": candidate["active"],
            }
            for candidate in candidates
        ],
    }
    from app.learn.hybrid.simple_native_contracts import build_qwen_goal_binding_projection

    return request, build_qwen_goal_binding_projection(request)


def _validated_binding(binding: object, *, goal_index: int, arm: GoalBindingArm, context: Mapping[str, object]) -> dict[str, object]:
    result = validate_goal_binding_provider_result(binding)
    if (
        result["goal_index"] != goal_index
        or result["provider_id"] != arm.provider_id
        or result["native_output_ref"] != context["native_output_ref"]
        or result["omni_snapshot_ref"] != context["omni_snapshot_ref"]
        or result["capture_ref"] != context["capture_ref"]
    ):
        raise ValueError("adapter binding lineage or goal does not match this frozen call")
    if result["status"] == "BOUND":
        candidates = context["candidates"]
        assert isinstance(candidates, list)
        index = result["candidate_index"]
        if (
            isinstance(index, bool)
            or not isinstance(index, int)
            or not 0 <= index < len(candidates)
            or not isinstance(candidates[index], Mapping)
            or candidates[index].get("candidate_id") != result["candidate_id"]
            or candidates[index].get("active") is not True
        ):
            raise ValueError("adapter bound candidate is not a legal frozen candidate")
        if result["binding_basis"] == "native_point":
            point = result["canonical_capture_pixel_point"]
            if not isinstance(point, list) or len(point) != 2:
                raise ValueError("adapter native point is invalid")
            recomputed = map_native_point_to_candidate(
                proposal=NativePointProposal(
                    goal_index=goal_index,
                    point=(point[0], point[1]),  # type: ignore[arg-type]
                    coordinate_space="capture_pixels",
                    confidence=result["confidence"],  # type: ignore[arg-type]
                    status="OK",
                    failure_reason=None,
                ),
                image_size=context["image_size"],  # type: ignore[arg-type]
                candidates=context["candidates"],  # type: ignore[arg-type]
                provider_id=arm.provider_id,
                capture_ref=context["capture_ref"],  # type: ignore[arg-type]
                native_output_ref=context["native_output_ref"],  # type: ignore[arg-type]
                omni_snapshot_ref=context["omni_snapshot_ref"],  # type: ignore[arg-type]
            )
            if recomputed != result:
                raise ValueError("adapter native bound result differs from authoritative frozen mapping")
    return result


def _cleanup(arm: GoalBindingArm) -> dict[str, object]:
    receipt = arm.cleanup()
    if not isinstance(receipt, Mapping) or set(receipt) != _CLEANUP_FIELDS:
        raise RuntimeError("binder cleanup observation is invalid; next model is blocked")
    result = deepcopy(dict(receipt))
    if result.get("provider") != arm.provider_id:
        raise RuntimeError("binder cleanup provider does not match the arm; next model is blocked")
    if (
        result.get("contract_version") != "simple_native_provider_cleanup_v1"
        or not isinstance(result.get("provider"), str)
        or result.get("verified") is not True
        or result.get("cleanup_status") != "verified"
        or any(not isinstance(result[field], list) or result[field] for field in _CLEANUP_LISTS)
    ):
        raise RuntimeError("binder cleanup is not clean; arm finalization and next model are blocked")
    return result


def _vista_outcome(
    *, binding: Mapping[str, object], goal: Mapping[str, object], capture: Mapping[str, object], candidate: Mapping[str, object] | None,
    vista: VistaNativeCaller, artifact_dir: Path, metrics: dict[str, object], snapshot_ref: Mapping[str, str],
) -> dict[str, object]:
    base = {
        "slot": "vista", **deepcopy(dict(goal)), "parent_capture_id": capture["capture_id"],
        "parent_omni_snapshot_ref": deepcopy(dict(snapshot_ref)), "candidate_id": binding.get("candidate_id"),
    }
    if binding.get("status") != "BOUND" or candidate is None:
        metrics["abstained"] = int(metrics["abstained"]) + 1
        return {**base, "status": "abstained", "reason": "goal_binding_not_unique_active_eligible"}
    started, raw, crop = perf_counter(), "", None
    binder_metrics = metrics["vista"]
    assert isinstance(binder_metrics, dict)
    binder_metrics["attempted"] = int(binder_metrics["attempted"]) + 1
    try:
        _verify_capture_freshness(capture, "VISTA")
        crop = _persist_vista_roi_crop(capture=capture, candidate=candidate, artifact_dir=artifact_dir)
        roi = tuple(crop["roi_xyxy"])
        raw = vista(Path(crop["crop_path"]), f"{goal['semantic_role']}: {goal['semantic_label']}")
        _verify_capture_freshness(capture, "VISTA")
        point = restore_vista_point_to_capture(parse_vista_normalized_point(raw), roi_xyxy=roi)
        if not (roi[0] < point[0] < roi[2] and roi[1] < point[1] < roi[3]):
            raise ValueError("restored VISTA point is outside strict candidate interior")
        binder_metrics["schema_valid"] = int(binder_metrics["schema_valid"]) + 1
        return {**base, "status": "selected", "raw": raw, "parsed": list(parse_vista_normalized_point(raw)), "raw_sha256": _hash(raw), "capture_point": list(point), "roi_xyxy": list(roi), "roi_crop": crop}
    except TimeoutError as exc:
        binder_metrics["timeout"] = int(binder_metrics["timeout"]) + 1
        metrics["abstained"] = int(metrics["abstained"]) + 1
        return {**base, "status": "abstained", "reason": "vista_timeout", "raw": raw, "parse_error": str(exc), "raw_sha256": _hash(raw), **({"roi_crop": crop} if crop is not None else {})}
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        binder_metrics["schema_invalid"] = int(binder_metrics["schema_invalid"]) + 1
        metrics["abstained"] = int(metrics["abstained"]) + 1
        return {**base, "status": "abstained", "reason": "vista_schema_invalid", "raw": raw, "parse_error": str(exc), "raw_sha256": _hash(raw), **({"roi_crop": crop} if crop is not None else {})}
    finally:
        binder_metrics["latencies"].append(round((perf_counter() - started) * 1000, 3))
        binder_metrics["raw_output_bytes"] = int(binder_metrics["raw_output_bytes"]) + len(raw.encode("utf-8"))


def run_goal_binding_arm(
    *, cases: Sequence[ProviderCase], snapshot_path: Path, arm: GoalBindingArm,
    vista: VistaNativeCaller, artifact_dir: Path,
    expected_omni_provider_identity: Mapping[str, object],
) -> ProviderDiagnosticArtifact:
    """Run one 25-goal non-authorizing arm against a verified frozen snapshot."""
    _require_arm(arm)
    expected = tuple(cases)
    if len(expected) != 5 or [case.case_id for case in expected] != [f"case-{index:03d}" for index in range(1, 6)] or sum(len(case.goals) for case in expected) != 25:
        raise ValueError("goal-binding arm requires the exact five-screen 25-goal regression set")
    snapshot_path = snapshot_path.resolve()
    snapshot = load_verified_omni_snapshot(
        snapshot_path,
        expected_cases=expected,
        expected_provider_identity=expected_omni_provider_identity,
    )
    snapshot_ref = _snapshot_ref(snapshot)
    frozen_cases = snapshot.get("cases")
    if not isinstance(frozen_cases, list) or len(frozen_cases) != 5:
        raise ValueError("frozen Omni snapshot cases are invalid")
    artifact_dir = artifact_dir.resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    metrics: dict[str, object] = {
        "omni": _metric(), "binder": _metric(), "vista": _metric(), "denominator": 25,
        "abstained": 0, "correct_selected": 0, "wrong_selected": 0,
    }
    states: list[dict[str, object]] = []
    try:
        for case, frozen_case in zip(expected, frozen_cases, strict=True):
            if not isinstance(frozen_case, Mapping) or frozen_case.get("case_id") != case.case_id:
                raise ValueError("frozen Omni snapshot case order is invalid")
            frozen_candidates = frozen_case.get("candidates")
            if not isinstance(frozen_candidates, list):
                raise ValueError("frozen Omni candidates are unavailable")
            candidates = [deepcopy(dict(candidate)) for candidate in frozen_candidates if isinstance(candidate, Mapping)]
            if len(candidates) != len(frozen_candidates):
                raise ValueError("frozen Omni candidate is invalid")
            capture, capture_ref = _capture_for_vista(case, frozen_case)
            goals = _parse_provider_goals(case)
            trace: list[dict[str, object]] = []
            for goal_index, goal in enumerate(goals):
                raw: object = ""
                error: str | None = None
                native_ref = {"id": f"native-output/{arm.arm_id}/{case.case_id}/{goal_index}", "sha256": "0" * 64}
                context: dict[str, object] = {
                    "provider_id": arm.provider_id, "case_id": case.case_id, "goal": deepcopy(goal),
                    "image_size": case.image_size, "candidates": deepcopy(candidates), "capture_ref": capture_ref,
                    "native_output_ref": native_ref, "omni_snapshot_ref": snapshot_ref,
                }
                if arm.provider_id == "qwen3_vl_8b_q4_k_m":
                    request, projection = _incumbent_request(goal=goal, candidates=candidates, image_size=case.image_size)
                    context["incumbent_runtime_request"] = request
                    context["incumbent_projection"] = projection
                request = {
                    "contract_version": "goal_binding_arm_request_v1", "regression_diagnostic_only": True,
                    "artifact_is_authorization": False, "execute_binding": False, "goal": deepcopy(goal),
                    "image_size": list(case.image_size), "candidates": deepcopy(candidates), "omni_snapshot_ref": deepcopy(snapshot_ref),
                }
                started = perf_counter()
                binder_metrics = metrics["binder"]
                assert isinstance(binder_metrics, dict)
                binder_metrics["attempted"] = int(binder_metrics["attempted"]) + 1
                parsed_evidence: list[dict[str, object]] = []

                def record_native_parsed(value: object) -> None:
                    if not isinstance(value, Mapping) or parsed_evidence:
                        raise ValueError("native parsed evidence is invalid")
                    parsed_evidence.append(deepcopy(dict(value)))

                try:
                    _verify_capture_freshness(capture, "GoalBindingProvider")
                    raw = arm.call(case.image_path, request)
                    _verify_capture_freshness(capture, "GoalBindingProvider")
                    raw_text = _raw_text(raw)
                    native_ref["sha256"] = _text_hash(raw_text)
                    adapter_context = deepcopy(context)
                    adapter_context["record_native_parsed"] = record_native_parsed
                    binding = _validated_binding(arm.adapt(raw, goal_index, adapter_context), goal_index=goal_index, arm=arm, context=context)
                    if binding["status"] == "PROVIDER_FAILURE":
                        reason = binding["reason"]
                        if reason == "provider_timeout":
                            binder_metrics["timeout"] = int(binder_metrics["timeout"]) + 1
                        else:
                            binder_metrics["schema_invalid"] = int(binder_metrics["schema_invalid"]) + 1
                    else:
                        binder_metrics["schema_valid"] = int(binder_metrics["schema_valid"]) + 1
                except TimeoutError as exc:
                    error = str(exc)
                    raw_text = _raw_text(raw)
                    native_ref["sha256"] = _text_hash(raw_text)
                    binding = _provider_failure(goal_index=goal_index, provider_id=arm.provider_id, context=context, reason="provider_timeout")
                    binder_metrics["timeout"] = int(binder_metrics["timeout"]) + 1
                except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                    error = str(exc)
                    raw_text = _raw_text(raw)
                    native_ref["sha256"] = _text_hash(raw_text)
                    binding = _provider_failure(goal_index=goal_index, provider_id=arm.provider_id, context=context, reason="malformed_native_output")
                    binder_metrics["schema_invalid"] = int(binder_metrics["schema_invalid"]) + 1
                finally:
                    binder_metrics["latencies"].append(round((perf_counter() - started) * 1000, 3))
                    binder_metrics["raw_output_bytes"] = int(binder_metrics["raw_output_bytes"]) + len(_raw_text(raw).encode("utf-8"))
                raw_text = _raw_text(raw)
                selected_candidate = None
                candidate = None
                if binding["status"] == "BOUND":
                    index = binding["candidate_index"]
                    assert isinstance(index, int)
                    candidate = candidates[index]
                    selected_candidate = _selected_candidate_evidence(
                        binding=binding, candidate=candidate, capture_ref=capture_ref, snapshot_ref=snapshot_ref,
                    )
                trace.append({
                    "slot": "binder", **deepcopy(goal), "native_raw": raw_text, "native_raw_sha256": native_ref["sha256"],
                    "native_parsed": parsed_evidence[0] if parsed_evidence else None,
                    "native_parsed_sha256": _hash(parsed_evidence[0]) if parsed_evidence else None,
                    "canonical_binding": binding, "canonical_binding_sha256": _hash(binding),
                    "selected_candidate": selected_candidate, "native_error": error,
                    "native_error_sha256": _text_hash(error) if error is not None else None,
                    "parent_capture_id": capture["capture_id"], "parent_omni_snapshot_ref": deepcopy(snapshot_ref),
                })
            states.append({
                "case_id": case.case_id, "goal_count": len(goals), "goals": deepcopy(goals), "capture": deepcopy(capture), "trace": trace,
            })
    finally:
        cleanup_receipt = _cleanup(arm)
    # A verified binder cleanup is a hard precondition for all VISTA dispatch.
    for state in states:
        trace = state["trace"]
        assert isinstance(trace, list)
        capture = state["capture"]
        assert isinstance(capture, Mapping)
        binder_by_goal = {
            entry["goal_id"]: entry for entry in trace
            if isinstance(entry, Mapping) and entry.get("slot") == "binder" and isinstance(entry.get("goal_id"), str)
        }
        for goal in state["goals"]:
            assert isinstance(goal, Mapping)
            binder = binder_by_goal.get(goal["goal_id"])
            if not isinstance(binder, Mapping):
                raise ValueError("binder outcome is missing before VISTA dispatch")
            binding = binder.get("canonical_binding")
            selected = binder.get("selected_candidate")
            candidate = None
            if isinstance(selected, Mapping):
                bbox = selected.get("bbox_original")
                candidate_id = selected.get("candidate_id")
                if isinstance(bbox, list) and isinstance(candidate_id, str):
                    candidate = {"candidate_id": candidate_id, "bbox_original": list(bbox), "active": True}
            if not isinstance(binding, Mapping):
                raise ValueError("canonical binder outcome is unavailable")
            trace.append(_vista_outcome(binding=binding, goal=goal, capture=capture, candidate=candidate, vista=vista, artifact_dir=artifact_dir, metrics=metrics, snapshot_ref=snapshot_ref))
    for name in ("omni", "binder", "vista"):
        metric = metrics[name]
        assert isinstance(metric, dict)
        metrics[name] = _finish(metric)
    payload = seal_immutable({
        "contract_version": "simple_native_provider_diagnostic_v2", "regression_diagnostic_only": True,
        "promotion_eligible": False, "screen_count": 5, "target_count": 25, "metrics": metrics,
        "cases": states, "provider_phase_cleanup": [cleanup_receipt], "cleanup_receipt": cleanup_receipt,
        "action_candidates": [], "artifact_is_authorization": False, "execute_binding": False,
        "arm_id": arm.arm_id, "provider_id": arm.provider_id, "omni_snapshot_ref": snapshot_ref,
    })
    path = artifact_dir / "provider-diagnostic.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return ProviderDiagnosticArtifact(path=path, cases=tuple(states), metrics=metrics, screen_count=5, target_count=25)
