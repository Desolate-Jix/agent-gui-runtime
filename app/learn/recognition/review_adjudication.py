from __future__ import annotations

from typing import Any


QUALITY_METRIC_INTERPRETATIONS = {
    "review_keep_precision": "expected keep groups were not removed",
    "false_group_cleanup": "human-marked false groups were removed",
    "review_relabel_quality": "human-marked relabels matched the expected role",
    "missing_region_detection": "human-marked missing regions were reported by review",
    "missing_region_recovery": "human-marked missing regions were present after deterministic repair",
    "atomic_evidence_preservation": "source atomic evidence identities were preserved",
}


def empty_review_quality_metrics() -> dict[str, Any]:
    metrics: dict[str, Any] = {
        metric_id: {
            "passed": 0,
            "attempted": 0,
            "rate": "not_covered",
            "interpretation": interpretation,
        }
        for metric_id, interpretation in QUALITY_METRIC_INTERPRETATIONS.items()
    }
    metrics["interpretation"] = (
        "human-adjudicated review assertions only; not recognition accuracy or general reliability"
    )
    return metrics


def merge_review_quality_metrics(target: dict[str, Any], source: dict[str, Any]) -> None:
    for metric_id in QUALITY_METRIC_INTERPRETATIONS:
        source_metric = source.get(metric_id) if isinstance(source.get(metric_id), dict) else {}
        target_metric = target.get(metric_id) if isinstance(target.get(metric_id), dict) else {}
        target_metric["passed"] = int(target_metric.get("passed") or 0) + int(
            source_metric.get("passed") or 0
        )
        target_metric["attempted"] = int(target_metric.get("attempted") or 0) + int(
            source_metric.get("attempted") or 0
        )
        target[metric_id] = target_metric


def finalize_review_quality_metrics(metrics: dict[str, Any]) -> None:
    for metric_id in QUALITY_METRIC_INTERPRETATIONS:
        metric = metrics.get(metric_id) if isinstance(metrics.get(metric_id), dict) else {}
        attempted = int(metric.get("attempted") or 0)
        passed = int(metric.get("passed") or 0)
        metric["rate"] = round(passed / attempted, 4) if attempted else "not_covered"
        metrics[metric_id] = metric


def score_review_adjudication(
    *,
    adjudication: dict[str, Any],
    validated_patch: dict[str, Any],
    final_stage2: dict[str, Any],
    integrity_gate: dict[str, Any],
) -> dict[str, Any]:
    """按人工裁决审计复核层，不把结果解释为识别准确率。"""

    if adjudication.get("contract_version") != "learning_model_review_human_adjudication_v1":
        raise ValueError("unsupported human adjudication contract")

    patch_decisions = {
        decision: _records_by_region_id(validated_patch.get(decision))
        for decision in ("keep", "remove", "relabel")
    }
    expected_decisions = _list_of_dicts(adjudication.get("expected_group_decisions"))
    expected_missing = _list_of_dicts(adjudication.get("expected_missing_targets"))
    metrics = empty_review_quality_metrics()
    assertion_failures: list[dict[str, Any]] = []
    false_deletions: list[str] = []
    critical_false_deletions: list[str] = []

    for expected in expected_decisions:
        region_id = str(expected.get("region_id") or "").strip()
        decision = str(expected.get("decision") or "").strip()
        if not region_id or decision not in {"keep", "remove", "relabel"}:
            raise ValueError("invalid expected_group_decisions record")

        if decision == "keep":
            actual_record = patch_decisions["keep"].get(region_id)
            passed = actual_record is not None and region_id not in patch_decisions["remove"]
            _record_metric(metrics, "review_keep_precision", passed)
            if not passed:
                false_deletions.append(region_id)
                if expected.get("critical") is True:
                    critical_false_deletions.append(region_id)
        elif decision == "remove":
            passed = region_id in patch_decisions["remove"]
            _record_metric(metrics, "false_group_cleanup", passed)
        else:
            actual_record = patch_decisions["relabel"].get(region_id)
            expected_role = str(expected.get("expected_role") or "").strip()
            actual_role = str(
                (actual_record or {}).get("new_role")
                or (actual_record or {}).get("role")
                or ""
            ).strip()
            passed = actual_record is not None and bool(expected_role) and actual_role == expected_role
            _record_metric(metrics, "review_relabel_quality", passed)

        if not passed:
            assertion_failures.append(
                {
                    "assertion": "expected_group_decision",
                    "region_id": region_id,
                    "expected": expected,
                    "actual_decision": _actual_decision(region_id, patch_decisions),
                }
            )

    missing_records = _list_of_dicts(validated_patch.get("missing"))
    final_groups = _final_groups(final_stage2)
    for expected in expected_missing:
        target_id = str(expected.get("target_id") or "").strip()
        expected_role = str(expected.get("expected_role") or "").strip()
        expected_roi = expected.get("expected_roi") if _valid_bbox(expected.get("expected_roi")) else None
        if (not target_id and expected_roi is None) or not expected_role:
            raise ValueError("invalid expected_missing_targets record")
        min_expected_coverage = float(expected.get("min_expected_coverage") or 0.8)
        detected = any(
            _missing_matches(
                record,
                target_id=target_id,
                expected_role=expected_role,
                expected_roi=expected_roi,
                min_expected_coverage=min_expected_coverage,
            )
            for record in missing_records
        )
        _record_metric(metrics, "missing_region_detection", detected)
        expected_final_group_id = str(expected.get("expected_final_group_id") or "").strip()
        recovered = any(
            (
                not expected_final_group_id
                or str(group.get("group_id") or "").strip() == expected_final_group_id
            )
            and str(group.get("role") or group.get("group_role") or "").strip() == expected_role
            and (
                expected_roi is None
                or _expected_coverage(group.get("bbox"), expected_roi) >= min_expected_coverage
            )
            for group in final_groups
        )
        _record_metric(metrics, "missing_region_recovery", recovered)
        if not detected:
            assertion_failures.append(
                {
                    "assertion": "missing_region_detection",
                    "target_id": target_id,
                    "expected_role": expected_role,
                    "expected_roi": expected_roi,
                }
            )
        if not recovered:
            assertion_failures.append(
                {
                    "assertion": "missing_region_recovery",
                    "target_id": target_id,
                    "expected_role": expected_role,
                    "expected_roi": expected_roi,
                    "expected_final_group_id": expected_final_group_id or None,
                }
            )

    atomic_failures = {
        "atomic_identity_set_changed",
        "duplicate_atomic_identity",
    }.intersection(str(item) for item in integrity_gate.get("failure_categories", []))
    atomic_preserved = (
        int(integrity_gate.get("source_atomic_count") or 0)
        == int(integrity_gate.get("final_atomic_count") or 0)
        and not atomic_failures
    )
    _record_metric(metrics, "atomic_evidence_preservation", atomic_preserved)
    if not atomic_preserved:
        assertion_failures.append(
            {
                "assertion": "atomic_evidence_preservation",
                "source_atomic_count": integrity_gate.get("source_atomic_count"),
                "final_atomic_count": integrity_gate.get("final_atomic_count"),
                "failure_categories": sorted(atomic_failures),
            }
        )

    finalize_review_quality_metrics(metrics)
    return {
        "contract_version": "learning_model_review_human_adjudication_score_v1",
        "scope": str(adjudication.get("scope") or "review_layer_only"),
        "quality_gate_passed": not assertion_failures,
        "assertion_failures": assertion_failures,
        "false_deletions": sorted(false_deletions),
        "critical_false_deletions": sorted(critical_false_deletions),
        "metrics": metrics,
        "interpretation": (
            "human-adjudicated review assertions only; not recognition accuracy or general reliability"
        ),
    }


def _record_metric(metrics: dict[str, Any], metric_id: str, passed: bool) -> None:
    metric = metrics[metric_id]
    metric["attempted"] += 1
    metric["passed"] += int(passed)


def _records_by_region_id(value: Any) -> dict[str, dict[str, Any]]:
    return {
        str(record.get("region_id") or "").strip(): record
        for record in _list_of_dicts(value)
        if str(record.get("region_id") or "").strip()
    }


def _actual_decision(
    region_id: str,
    patch_decisions: dict[str, dict[str, dict[str, Any]]],
) -> str | None:
    for decision in ("keep", "remove", "relabel"):
        if region_id in patch_decisions[decision]:
            return decision
    return None


def _missing_matches(
    record: dict[str, Any],
    *,
    target_id: str,
    expected_role: str,
    expected_roi: dict[str, Any] | None = None,
    min_expected_coverage: float = 0.8,
) -> bool:
    record_target_id = str(record.get("target_id") or record.get("missing_id") or "").strip()
    record_role = str(record.get("expected_role") or record.get("role") or "").strip()
    if record_role != expected_role:
        return False
    if expected_roi is not None:
        return _expected_coverage(record.get("rough_roi") or record.get("bbox"), expected_roi) >= min_expected_coverage
    if record_target_id:
        return record_target_id == target_id
    description = str(record.get("description") or "").casefold()
    return bool(target_id) and target_id.casefold() in description


def _valid_bbox(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and int(value.get("w") or 0) > 0
        and int(value.get("h") or 0) > 0
    )


def _expected_coverage(actual: Any, expected: dict[str, Any]) -> float:
    if not _valid_bbox(actual) or not _valid_bbox(expected):
        return 0.0
    ax1 = int(actual.get("x") or 0)
    ay1 = int(actual.get("y") or 0)
    ax2 = ax1 + int(actual["w"])
    ay2 = ay1 + int(actual["h"])
    ex1 = int(expected.get("x") or 0)
    ey1 = int(expected.get("y") or 0)
    ex2 = ex1 + int(expected["w"])
    ey2 = ey1 + int(expected["h"])
    intersection = max(0, min(ax2, ex2) - max(ax1, ex1)) * max(0, min(ay2, ey2) - max(ay1, ey1))
    expected_area = max(1, int(expected["w"]) * int(expected["h"]))
    return intersection / expected_area


def _final_groups(stage2: dict[str, Any]) -> list[dict[str, Any]]:
    wrapped_stage2 = stage2.get("stage2_numbering")
    if isinstance(wrapped_stage2, dict):
        stage2 = wrapped_stage2
    groups: list[dict[str, Any]] = []
    for region in _list_of_dicts(stage2.get("regions")):
        groups.extend(_list_of_dicts(region.get("subregion_groups")))
    return groups


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []
