"""逐例比较既有评分器的原始结果，不评分模型、不合并人工纠正结果。"""

from collections.abc import Mapping, Sequence


_OUTCOMES = ("correct", "wrong", "abstain", "timeout", "protocol_failure", "not_run")
_ARMS = ("never", "conditional", "always")


def _identity(case_id: object, goal_index: object) -> tuple[str, int]:
    if not isinstance(case_id, str) or not case_id.strip():
        raise ValueError("case_id must be non-empty text")
    if isinstance(goal_index, bool) or not isinstance(goal_index, int) or goal_index < 0:
        raise ValueError("goal_index must be a non-negative integer")
    return case_id, goal_index


def _rows(value: object, expected: set[tuple[str, int]], label: str) -> dict:
    if not isinstance(value, list):
        raise ValueError(f"{label} raw outcomes must be a list")
    result = {}
    for row in value:
        if not isinstance(row, Mapping) or set(row) != {"case_id", "goal_index", "outcome"}:
            raise ValueError(f"{label} raw outcome fields are not closed; human review is separate")
        identity = _identity(row["case_id"], row["goal_index"])
        outcome = row["outcome"]
        if identity not in expected or identity in result:
            raise ValueError(f"{label} contains unknown or duplicate goal")
        if not isinstance(outcome, str) or outcome not in _OUTCOMES:
            raise ValueError(f"{label} contains invalid raw outcome")
        result[identity] = outcome
    if set(result) != expected:
        raise ValueError(f"{label} does not cover every manifest goal")
    return result


def _counts(rows: dict) -> dict[str, int]:
    return {outcome: sum(value == outcome for value in rows.values()) for outcome in _OUTCOMES}


def compare_selection_outcomes(*, expected_goals: Sequence[tuple[str, int]], baseline: list[dict], arms: Mapping[str, list[dict]]) -> dict:
    """按固定 manifest 比较三臂，等总分也不能掩盖原正确样例退化。"""
    if not isinstance(expected_goals, (list, tuple)) or not expected_goals:
        raise ValueError("manifest must contain explicit goals")
    ordered = []
    for goal in expected_goals:
        if not isinstance(goal, (list, tuple)) or len(goal) != 2:
            raise ValueError("manifest goal must be a case_id/goal_index pair")
        ordered.append(_identity(*goal))
    expected = set(ordered)
    if len(expected) != len(ordered):
        raise ValueError("manifest contains duplicate goals")
    if not isinstance(arms, Mapping) or set(arms) != set(_ARMS):
        raise ValueError("policy arms must be exactly never, conditional, always")
    old = _rows(baseline, expected, "baseline")
    result = {}
    for name in _ARMS:
        new = _rows(arms[name], expected, name)
        transitions = [
            {"case_id": case_id, "goal_index": index, "before": old[(case_id, index)], "after": new[(case_id, index)]}
            for case_id, index in ordered
        ]
        regressed = []
        new_wrong = []
        for row in transitions:
            identity = {"case_id": row["case_id"], "goal_index": row["goal_index"]}
            if row["before"] == "correct" and row["after"] != "correct":
                regressed.append(identity)
            if row["before"] != "wrong" and row["after"] == "wrong":
                new_wrong.append(identity)
        counts = _counts(new)
        result[name] = {
            "counts": counts,
            "uncompleted_count": sum(counts[state] for state in _OUTCOMES if state not in {"correct", "wrong"}),
            "transitions": transitions,
            "regressed_goals": regressed,
            "new_wrong_goals": new_wrong,
            "no_regression": not regressed and not new_wrong,
        }
    return {
        "contract_version": "learning_selection_outcome_comparison_v1",
        "goal_count": len(ordered),
        "baseline_counts": _counts(old),
        "arms": result,
        "human_review_included": False,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
