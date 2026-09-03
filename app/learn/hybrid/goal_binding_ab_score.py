"""Gold-reading, binder-only regression scoring for frozen GoalBinding arms."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from app.learn.hybrid.goal_binding_provider import validate_goal_binding_provider_result
from app.learn.recognition.uei.canonical import content_sha256


_DENOMINATOR = 25
_CLEANUP_LISTS = (
    "owned_processes", "provider_processes_after", "helper_processes_after",
    "orphan_descendant_pids", "active_listeners_after", "lease_files_after",
)
_CLEANUP_FIELDS = frozenset({
    "contract_version", "provider", "verified", "cleanup_status", "owned_processes",
    "provider_processes_after", "helper_processes_after", "orphan_descendant_pids",
    "active_listeners_after", "lease_files_after",
})


def _pair(value: object, *, name: str) -> dict[str, int]:
    if not isinstance(value, Mapping) or set(value) != {"numerator", "denominator"}:
        raise ValueError(f"{name} metric is invalid")
    numerator, denominator = value["numerator"], value["denominator"]
    if any(isinstance(item, bool) or not isinstance(item, int) for item in (numerator, denominator)) or denominator != _DENOMINATOR or not 0 <= numerator <= denominator:
        raise ValueError(f"{name} metric is invalid")
    return {"numerator": numerator, "denominator": denominator}


def _contains_forbidden(value: object) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            name = str(key).lower()
            if (
                name in {"action_authority", "execute", "approved_to_click"}
                or "holdout" in name
                or "gold" in name
                or ("action" in name and name != "action_candidates")
                or _contains_forbidden(item)
            ):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_forbidden(item) for item in value)
    return False


def _load_artifact(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise ValueError("provider artifact must be finalized before scoring")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("provider artifact is unreadable") from exc
    if not isinstance(payload, Mapping) or payload.get("content_sha256") != content_sha256(dict(payload)):
        raise ValueError("provider artifact is not a finalized immutable diagnostic")
    result = deepcopy(dict(payload))
    if (
        result.get("contract_version") != "simple_native_provider_diagnostic_v2"
        or result.get("regression_diagnostic_only") is not True
        or result.get("promotion_eligible") is not False
        or result.get("artifact_is_authorization") is not False
        or result.get("execute_binding") is not False
        or result.get("action_candidates") != []
        or result.get("contains_holdout") not in (None, False)
        or result.get("holdout_accessed") not in (None, False)
        or result.get("screen_count") != 5
        or result.get("target_count") != _DENOMINATOR
        or _contains_forbidden({
            key: value for key, value in result.items()
            if key not in {"content_sha256", "action_candidates", "execute_binding", "contains_holdout", "holdout_accessed"}
        })
    ):
        raise ValueError("provider artifact is not a non-authorizing regression diagnostic")
    return result


def _ref(value: object, *, name: str) -> dict[str, str]:
    if (
        not isinstance(value, Mapping)
        or set(value) != {"id", "sha256"}
        or not isinstance(value.get("id"), str)
        or not value["id"]
        or not isinstance(value.get("sha256"), str)
        or len(value["sha256"]) != 64
        or any(character not in "0123456789abcdef" for character in value["sha256"])
    ):
        raise ValueError(f"{name} lineage is invalid")
    return {"id": value["id"], "sha256": value["sha256"]}


def _verified_cleanup_receipt(value: object, *, provider_id: object) -> dict[str, object] | None:
    if (
        not isinstance(value, Mapping)
        or set(value) != _CLEANUP_FIELDS
        or not isinstance(provider_id, str)
        or value.get("provider") != provider_id
        or value.get("contract_version") != "simple_native_provider_cleanup_v1"
        or value.get("verified") is not True
        or value.get("cleanup_status") != "verified"
        or any(not isinstance(value.get(name), list) or value[name] for name in _CLEANUP_LISTS)
    ):
        return None
    return deepcopy(dict(value))


def _regions(value: object) -> list[list[float]]:
    if not isinstance(value, list):
        raise ValueError("acceptable regions are invalid")
    result: list[list[float]] = []
    for region in value:
        if not isinstance(region, list) or len(region) != 4 or any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in region) or not region[0] < region[2] or not region[1] < region[3]:
            raise ValueError("acceptable regions are invalid")
        result.append([float(item) for item in region])
    return result


def _inside(point: object, regions: Sequence[Sequence[float]]) -> bool:
    return isinstance(point, list) and len(point) == 2 and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in point) and any(region[0] < point[0] < region[2] and region[1] < point[1] < region[3] for region in regions)


def _selected_geometry(selected: Mapping[str, object], binding: Mapping[str, object]) -> list[float]:
    bbox = selected.get("bbox_original")
    if (
        selected.get("candidate_index") != binding.get("candidate_index")
        or not isinstance(bbox, list)
        or len(bbox) != 4
        or any(isinstance(value, bool) or not isinstance(value, int) for value in bbox)
        or not bbox[0] < bbox[2]
        or not bbox[1] < bbox[3]
    ):
        raise ValueError("bound selected candidate geometry is invalid")
    center = [(bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0]
    if selected.get("center_capture_pixel") != center:
        raise ValueError("bound selected candidate center geometry is invalid")
    return center


def _gold(path: Path) -> dict[tuple[str, str, str], dict[str, object]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("regression Gold is unavailable") from exc
    targets = payload.get("targets") if isinstance(payload, Mapping) else None
    if not isinstance(targets, list):
        raise ValueError("regression Gold targets are invalid")
    result: dict[tuple[str, str, str], dict[str, object]] = {}
    for target in targets:
        if not isinstance(target, Mapping) or target.get("partition") != "regression":
            continue
        screen, role, label, goal, candidate_ids = (target.get("screen_id"), target.get("role"), target.get("label"), target.get("goal"), target.get("acceptable_candidate_ids"))
        if not all(isinstance(item, str) and item for item in (screen, role, label, goal)) or not isinstance(candidate_ids, list) or any(not isinstance(item, str) for item in candidate_ids):
            raise ValueError("regression Gold target is invalid")
        key = (screen, role, label)
        if key in result:
            raise ValueError("regression Gold semantic target is duplicated")
        result[key] = {"goal": goal, "acceptable_candidate_ids": list(candidate_ids), "acceptable_regions": _regions(target.get("acceptable_regions"))}
    if len(result) != _DENOMINATOR:
        raise ValueError("regression Gold denominator is not exactly 25")
    return result


def score_goal_binding_arm(*, provider_artifact: Path, gold_path: Path) -> dict[str, object]:
    """Score a finalized Task 4 artifact; this is the sole Gold-reading boundary."""
    artifact = _load_artifact(provider_artifact)
    cases = artifact.get("cases")
    snapshot_ref = _ref(artifact.get("omni_snapshot_ref"), name="artifact snapshot")
    if not isinstance(cases, list) or len(cases) != 5 or not isinstance(artifact.get("arm_id"), str) or not isinstance(artifact.get("provider_id"), str):
        raise ValueError("provider artifact structure is invalid")
    cleanup_receipt = _verified_cleanup_receipt(artifact.get("cleanup_receipt"), provider_id=artifact["provider_id"])
    if cleanup_receipt is None or artifact.get("provider_phase_cleanup") != [cleanup_receipt]:
        raise ValueError("provider artifact cleanup receipt is not exact and verified")
    gold = _gold(gold_path)
    seen: set[tuple[str, str, str]] = set()
    capture_lineage: list[dict[str, str]] = []
    correct = wrong = unbound = provider_failure = native_parse = vista_dispatch = vista_validated = vista_out_of_bounds = end_to_end_correct = 0
    for case in cases:
        if not isinstance(case, Mapping) or not isinstance(case.get("case_id"), str) or case.get("goal_count") != 5 or not isinstance(case.get("goals"), list) or not isinstance(case.get("trace"), list):
            raise ValueError("provider artifact case is invalid")
        case_id = case["case_id"]
        capture = case.get("capture")
        if not isinstance(capture, Mapping) or not isinstance(capture.get("capture_id"), str) or not isinstance(capture.get("screenshot_sha256"), str):
            raise ValueError("provider artifact capture lineage is invalid")
        capture_ref = {"id": f"capture/{capture['capture_id']}", "sha256": capture["screenshot_sha256"]}
        capture_lineage.append(capture_ref)
        goals = case["goals"]
        binders = [entry for entry in case["trace"] if isinstance(entry, Mapping) and entry.get("slot") == "binder"]
        if len(goals) != 5 or len(binders) != 5:
            raise ValueError("provider artifact binder coverage is invalid")
        by_goal = {entry.get("goal_id"): entry for entry in binders if isinstance(entry.get("goal_id"), str)}
        if len(by_goal) != 5:
            raise ValueError("provider artifact binder goals are duplicated")
        for goal in goals:
            if not isinstance(goal, Mapping):
                raise ValueError("provider artifact goal is invalid")
            key = (case_id, goal.get("semantic_role"), goal.get("semantic_label"))
            if not all(isinstance(item, str) for item in key) or key not in gold or key in seen:
                raise ValueError("provider artifact goal does not exactly join regression Gold")
            target = gold[key]
            if goal.get("goal_text") != target["goal"]:
                raise ValueError("provider artifact goal text does not match regression Gold")
            binder = by_goal.get(goal.get("goal_id"))
            if not isinstance(binder, Mapping) or binder.get("semantic_role") != key[1] or binder.get("semantic_label") != key[2]:
                raise ValueError("provider artifact binder semantics are invalid")
            binding = validate_goal_binding_provider_result(binder.get("canonical_binding"))
            if binding["omni_snapshot_ref"] != snapshot_ref or binding["capture_ref"] != capture_ref:
                raise ValueError("provider artifact binder lineage is inconsistent")
            if binding["status"] != "PROVIDER_FAILURE" and isinstance(binder.get("native_parsed"), Mapping):
                native_parse += 1
            if binding["status"] == "BOUND":
                selected = binder.get("selected_candidate")
                if not isinstance(selected, Mapping) or selected.get("candidate_id") != binding["candidate_id"] or selected.get("capture_ref") != capture_ref or selected.get("omni_snapshot_ref") != snapshot_ref:
                    raise ValueError("bound selected candidate evidence is invalid")
                candidate_id = selected["candidate_id"]
                center = _selected_geometry(selected, binding)
                acceptable = candidate_id in target["acceptable_candidate_ids"] or _inside(center, target["acceptable_regions"])
                if acceptable:
                    correct += 1
                else:
                    wrong += 1
            elif binding["status"] == "UNBOUND":
                unbound += 1
            else:
                provider_failure += 1
            seen.add(key)
        for vista in (entry for entry in case["trace"] if isinstance(entry, Mapping) and entry.get("slot") == "vista"):
            if vista.get("candidate_id") is not None:
                vista_dispatch += 1
            if vista.get("status") == "selected":
                vista_validated += 1
                target = gold.get((case_id, vista.get("semantic_role"), vista.get("semantic_label")))
                if isinstance(target, Mapping) and _inside(vista.get("capture_point"), target["acceptable_regions"]):
                    end_to_end_correct += 1
            elif "outside" in str(vista.get("parse_error") or "").lower():
                vista_out_of_bounds += 1
    if len(seen) != _DENOMINATOR or correct + wrong + unbound + provider_failure != _DENOMINATOR:
        raise ValueError("binder score denominator is inconsistent")
    metrics = {
        "native_parse_success": {"numerator": native_parse, "denominator": _DENOMINATOR},
        "correct": {"numerator": correct, "denominator": _DENOMINATOR},
        "wrong": {"numerator": wrong, "denominator": _DENOMINATOR},
        "unbound_abstain": {"numerator": unbound, "denominator": _DENOMINATOR},
        "provider_failure_abstain": {"numerator": provider_failure, "denominator": _DENOMINATOR},
        "safe_abstain": {"numerator": unbound + provider_failure, "denominator": _DENOMINATOR},
        "vista_dispatch": {"numerator": vista_dispatch, "denominator": _DENOMINATOR},
        "vista_validated": {"numerator": vista_validated, "denominator": _DENOMINATOR},
        "vista_out_of_bounds": {"numerator": vista_out_of_bounds, "denominator": _DENOMINATOR},
        "end_to_end_correct": {"numerator": end_to_end_correct, "denominator": _DENOMINATOR},
    }
    source_metrics = artifact.get("metrics")
    binder_metrics = source_metrics.get("binder") if isinstance(source_metrics, Mapping) else None
    if isinstance(binder_metrics, Mapping):
        metrics["latency_bytes"] = {"latency_p50_ms": binder_metrics.get("latency_p50_ms"), "latency_p95_ms": binder_metrics.get("latency_p95_ms"), "raw_output_bytes": binder_metrics.get("raw_output_bytes"), "denominator": _DENOMINATOR}
    return {
        "contract_version": "goal_binding_arm_binder_report_v1",
        "arm_id": artifact["arm_id"], "provider_id": artifact["provider_id"],
        "provider_artifact_sha256": sha256(provider_artifact.read_bytes()).hexdigest(),
        "omni_snapshot_ref": snapshot_ref, "capture_lineage": sorted(capture_lineage, key=lambda item: item["id"]),
        "regression_diagnostic_only": True, "promotion_eligible": False, "contains_holdout": False, "holdout_accessed": False,
        "artifact_is_authorization": False, "action_candidates": [], "metrics": metrics,
        "cleanup_receipt": cleanup_receipt,
    }


def evaluate_binding_hard_gate(*, binder_report: Mapping[str, object], cleanup_receipt: Mapping[str, object]) -> dict[str, object]:
    metrics = binder_report.get("metrics") if isinstance(binder_report, Mapping) else None
    arm_id = binder_report.get("arm_id") if isinstance(binder_report, Mapping) else None
    if not isinstance(metrics, Mapping) or not isinstance(arm_id, str):
        raise ValueError("binder report is invalid")
    wrong = _pair(metrics.get("wrong"), name="wrong")
    parsed = _pair(metrics.get("native_parse_success"), name="native parse")
    correct = _pair(metrics.get("correct"), name="correct")
    reported_receipt = binder_report.get("cleanup_receipt")
    clean = (
        _verified_cleanup_receipt(cleanup_receipt, provider_id=binder_report.get("provider_id")) is not None
        and cleanup_receipt == reported_receipt
    )
    reasons = []
    if wrong["numerator"] != 0: reasons.append("wrong_bind_nonzero")
    if parsed["numerator"] != _DENOMINATOR: reasons.append("native_parse_incomplete")
    if correct["numerator"] < 10: reasons.append("correct_bind_below_ten")
    if not clean: reasons.append("cleanup_residue_or_unverified")
    return {"contract_version": "goal_binding_hard_gate_v1", "arm_id": arm_id, "passed": not reasons, "reasons": reasons, "promotion_eligible": False, "artifact_is_authorization": False}


def _score_pair(metrics: Mapping[str, object], name: str, *, fallback: int = 0) -> int:
    value = metrics.get(name)
    if value is None:
        return fallback
    return _pair(value, name=name)["numerator"]


def build_goal_binding_matrix(*, arm_reports: Sequence[Mapping[str, object]]) -> dict[str, object]:
    if not isinstance(arm_reports, Sequence) or isinstance(arm_reports, (str, bytes)) or not arm_reports:
        raise ValueError("matrix requires one or more arm reports")
    arms: list[dict[str, object]] = []
    identities: set[str] = set()
    snapshot: dict[str, str] | None = None
    capture_lineage: list[dict[str, str]] | None = None
    for report in arm_reports:
        if not isinstance(report, Mapping):
            raise ValueError("matrix arm report is invalid")
        if report.get("contains_holdout") is not False or report.get("holdout_accessed") is not False:
            raise ValueError("matrix arm report contains holdout evidence")
        if report.get("execute_binding") not in (None, False) or _contains_forbidden({
            key: value for key, value in report.items()
            if key not in {"action_candidates", "contains_holdout", "holdout_accessed"}
        }):
            raise ValueError("matrix arm report contains authorizing or action evidence")
        if report.get("contract_version") != "goal_binding_arm_binder_report_v1" or report.get("regression_diagnostic_only") is not True or report.get("promotion_eligible") is not False or report.get("artifact_is_authorization") is not False or report.get("action_candidates") != []:
            raise ValueError("matrix arm report is not regression-only non-authorizing evidence")
        arm_id = report.get("arm_id")
        if not isinstance(arm_id, str) or not arm_id or arm_id in identities:
            raise ValueError("matrix arm IDs are duplicated or invalid")
        identities.add(arm_id)
        current_snapshot = _ref(report.get("omni_snapshot_ref"), name="matrix snapshot")
        current_capture = report.get("capture_lineage")
        if not isinstance(current_capture, list) or len(current_capture) != 5:
            raise ValueError("matrix capture lineage is invalid")
        current_capture = sorted([_ref(item, name="matrix capture") for item in current_capture], key=lambda item: item["id"])
        if snapshot is None:
            snapshot, capture_lineage = current_snapshot, current_capture
        elif snapshot != current_snapshot or capture_lineage != current_capture:
            raise ValueError("matrix snapshot or capture lineage differs between arms")
        gate = evaluate_binding_hard_gate(binder_report=report, cleanup_receipt=report.get("cleanup_receipt"))
        metrics = report.get("metrics")
        assert isinstance(metrics, Mapping)
        presentation: float | None = None
        if gate["passed"]:
            presentation = round(
                40 * _score_pair(metrics, "correct") / _DENOMINATOR
                + 25 * _score_pair(metrics, "end_to_end_correct") / _DENOMINATOR
                + 10 * _score_pair(metrics, "protocol_stability", fallback=_score_pair(metrics, "native_parse_success")) / _DENOMINATOR
                + 10 * _score_pair(metrics, "latency_score") / _DENOMINATOR
                + 5 * _score_pair(metrics, "peak_vram_score") / _DENOMINATOR
                + 5 * _score_pair(metrics, "vista_gain") / _DENOMINATOR
                + 5 * _score_pair(metrics, "lifecycle_cleanup", fallback=_DENOMINATOR) / _DENOMINATOR,
                6,
            )
        arms.append({"arm_id": arm_id, "provider_id": report.get("provider_id"), "hard_gate": gate, "presentation_score": presentation, "binder_report": deepcopy(dict(report))})
    passers = [arm for arm in arms if arm["presentation_score"] is not None]
    winner = max(passers, key=lambda arm: (float(arm["presentation_score"]), str(arm["arm_id"]))) if passers else None
    return {"contract_version": "goal_binding_matrix_v1", "regression_diagnostic_only": True, "promotion_eligible": False, "contains_holdout": False, "holdout_accessed": False, "artifact_is_authorization": False, "action_candidates": [], "omni_snapshot_ref": snapshot, "capture_lineage": capture_lineage, "arms": arms, "winner_arm_id": winner["arm_id"] if winner else None}
