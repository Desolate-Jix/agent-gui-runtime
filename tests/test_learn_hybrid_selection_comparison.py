from copy import deepcopy

import pytest

from app.learn.hybrid.selection_comparison import compare_selection_outcomes


GOALS = [("case-a", 0), ("case-a", 1), ("case-b", 0)]


def rows(*outcomes):
    return [
        {"case_id": case_id, "goal_index": index, "outcome": outcome}
        for (case_id, index), outcome in zip(GOALS, outcomes, strict=True)
    ]


def compare(baseline, candidate):
    return compare_selection_outcomes(
        expected_goals=GOALS,
        baseline=baseline,
        arms={"never": deepcopy(candidate), "conditional": deepcopy(candidate), "always": deepcopy(candidate)},
    )


def test_equal_totals_do_not_hide_formerly_correct_regression():
    baseline = rows("correct", "abstain", "correct")
    result = compare(baseline, rows("abstain", "correct", "correct"))
    arm = result["arms"]["conditional"]
    assert arm["counts"] == result["baseline_counts"]
    assert arm["regressed_goals"] == [{"case_id": "case-a", "goal_index": 0}]
    assert arm["no_regression"] is False
    assert arm["transitions"][0]["before"] == "correct"
    assert arm["transitions"][0]["after"] == "abstain"


def test_all_failures_remain_in_denominator_and_distinct():
    result = compare(rows("correct", "correct", "correct"), rows("timeout", "protocol_failure", "abstain"))
    arm = result["arms"]["conditional"]
    assert result["goal_count"] == 3
    assert arm["uncompleted_count"] == 3
    assert arm["counts"]["timeout"] == arm["counts"]["protocol_failure"] == arm["counts"]["abstain"] == 1
    assert len(arm["regressed_goals"]) == 3


def test_gains_do_not_offset_new_wrong_targets():
    result = compare(rows("abstain", "abstain", "correct"), rows("correct", "wrong", "correct"))
    arm = result["arms"]["conditional"]
    assert arm["new_wrong_goals"] == [{"case_id": "case-a", "goal_index": 1}]
    assert arm["no_regression"] is False


def test_order_is_manifest_order_and_inputs_are_immutable():
    baseline = rows("correct", "abstain", "correct")
    candidate = list(reversed(rows("correct", "correct", "correct")))
    before = deepcopy(candidate)
    arm = compare(baseline, candidate)["arms"]["conditional"]
    assert arm["no_regression"] is True
    assert [(r["case_id"], r["goal_index"]) for r in arm["transitions"]] == GOALS
    assert candidate == before


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "unknown", "human", "invalid", "boolean_index"])
def test_invalid_or_human_corrected_rows_cannot_be_scored_as_raw(mutation):
    baseline = rows("correct", "abstain", "correct")
    candidate = deepcopy(baseline)
    if mutation == "missing":
        candidate.pop()
    elif mutation == "duplicate":
        candidate[1] = deepcopy(candidate[0])
    elif mutation == "unknown":
        candidate[0]["case_id"] = "foreign"
    elif mutation == "human":
        candidate[0]["human_corrected"] = True
    elif mutation == "invalid":
        candidate[0]["outcome"] = "reviewed_success"
    else:
        candidate[0]["goal_index"] = False
    with pytest.raises(ValueError):
        compare(baseline, candidate)


def test_three_policy_arms_are_required():
    with pytest.raises(ValueError, match="policy arms"):
        compare_selection_outcomes(expected_goals=GOALS, baseline=rows("correct", "correct", "correct"), arms={})


def test_manifest_duplicates_are_rejected():
    with pytest.raises(ValueError, match="manifest"):
        compare_selection_outcomes(expected_goals=[GOALS[0], GOALS[0]], baseline=[], arms={})
