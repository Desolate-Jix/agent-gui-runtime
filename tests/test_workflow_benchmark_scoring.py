import pytest

from app.learning_memory.benchmark_scoring import compare_runs


def test_pilot_cannot_accumulate_formal_credit_and_keeps_unknowns():
    rows = []
    for family in ("query_verify", "unique_row_detail", "current_detail_downstream"):
        for index in range(20):
            for route in ("A", "C", "B"):
                rows.append(run(route, f"{family}-{index}", purpose="pilot", task_family=family,
                    variation="stable" if index < 8 else "unseen" if index < 14 else "layout",
                    telemetry={"planning": False, "grounding": False, "verification": False}))
    result = compare_runs(rows)
    assert result["purpose"] == "pilot"
    assert result["formal_quota_credit"] == 0
    assert result["empirical_acceptance"] is False
    assert result["formal_acceptance_eligible"] is False
    assert result["sample_sufficiency"]["meets_required_ac"] is False
    assert result["sample_sufficiency"]["meets_required_b"] is False
    assert result["benefit_assessment"]["overall"]["state"] != "met"
    assert result["benefit_assessment"]["overall"]["reason"] == "pilot_not_formal_acceptance"
    assert result["routes"]["A"]["model_calls"]["total"] is None
    for family in result["benefit_assessment"]["by_task_family"].values():
        assert not family["sample_sufficiency"]["meets_required_ac"]
        assert family["overall"]["reason"] == "pilot_not_formal_acceptance"


def test_mixed_purpose_rejected_and_legacy_rows_are_formal():
    with pytest.raises(ValueError, match="purpose"):
        compare_runs([run("A", purpose="pilot"), run("C")])
    assert compare_runs([run("A"), run("C", purpose="formal")])["purpose"] == "formal"


def test_empty_pilot_keeps_explicit_purpose_and_rejects_row_drift():
    result = compare_runs([], purpose="pilot")
    assert result["purpose"] == "pilot" and result["formal_quota_credit"] == 0
    with pytest.raises(ValueError, match="purpose"):
        compare_runs([run("A")], purpose="pilot")


def run(route, case="one", **changes):
    row = {
        "schema": "workflow_benchmark_run.v1", "run_id": f"{route}-{case}",
        "route": route, "case_id": case, "task_family": "lookup",
        "source": "agent_current", "model": "same-model", "config_digest": "sha256:123",
        "variation": "stable", "cold_or_warm": "warm", "attempt_index": 1,
        "is_negative": False, "first_attempt_success": True, "completed": True,
        "safe_rejection": False, "wrong_clicks": 0, "recovery_count": 0,
        "elapsed_ns": 100, "timed_out": False, "events": [],
        "telemetry": {"planning": True, "grounding": True, "verification": True},
    }
    row.update(changes)
    return row


def model_event(run_id, role, event_id, usage=None):
    return {
        "schema": "workflow_measurement.v1", "event_id": event_id,
        "run_id": run_id, "step_id": "s", "request_id": "req",
        "phase": role, "source": "agent_current", "started_ns": 0,
        "ended_ns": 10, "status": "success", "usage": usage,
        "evidence_refs": [],
    }


def test_failures_timeout_and_recovery_remain_in_all_attempts():
    a = run("A", events=[model_event("A-one", "planning", "p", {"input_tokens": 10, "output_tokens": 2})])
    c = run("C", first_attempt_success=False, completed=True, wrong_clicks=1, recovery_count=1,
            timed_out=True, elapsed_ns=300, events=[model_event("C-one", "grounding", "g")])
    result = compare_runs([a, c])
    assert result["pairs"]["count"] == 1
    assert result["routes"]["C"]["attempts"] == 1
    assert result["routes"]["C"]["first_attempt_success_rate"] == 0
    assert result["routes"]["C"]["completion_rate"] == 1
    assert result["routes"]["C"]["timeout_count"] == 1
    assert result["routes"]["C"]["wrong_clicks"] == 1
    assert result["routes"]["C"]["recovery_count"] == 1
    assert result["pairs"]["common_success_time_ns"]["count"] == 0
    assert result["routes"]["C"]["tokens"] is None


def test_exact_pairing_rejects_config_drift_and_keeps_b_separate():
    rows = [run("A"), run("C", config_digest="other"), run("B")]
    result = compare_runs(rows)
    assert result["pairs"]["count"] == 0
    assert result["unmatched"] == {"A": 1, "C": 1}
    assert result["routes"]["B"]["attempts"] == 1
    with pytest.raises(ValueError, match="duplicate"):
        compare_runs([run("A"), run("A", run_id="another")])


def test_negative_rejection_does_not_inflate_positive_success():
    rows = [run("A", "positive", completed=False, first_attempt_success=False),
            run("C", "positive", completed=False, first_attempt_success=False),
            run("A", "negative", is_negative=True, first_attempt_success=False, completed=False, safe_rejection=True),
            run("C", "negative", is_negative=True, first_attempt_success=False, completed=False, safe_rejection=True)]
    result = compare_runs(rows)
    assert result["routes"]["C"]["positive_attempts"] == 1
    assert result["routes"]["C"]["positive_success_rate"] == 0
    assert result["routes"]["C"]["negative_correct_rejections"] == 1
    assert result["sample_sufficiency"]["ac_pairs_by_family"] == {"lookup": 1}


def test_usage_coverage_and_break_even_are_honest():
    a = run("A", elapsed_ns=100, events=[model_event("A-one", "planning", "p", {"input_tokens": 10, "output_tokens": 2})])
    c = run("C", elapsed_ns=50, events=[])
    result = compare_runs([a, c], learning_cost={"elapsed_ns": 200, "total_tokens": 24})
    assert result["break_even"]["elapsed_reuses"] == 4
    assert result["break_even"]["token_reuses"] is None
    assert result["pairs"]["all_attempt_time_ns"]["median_saving"] == 50
    assert result["family_time_ns"]["lookup"]["A"]["p95"] == 100
    assert result["family_time_ns"]["lookup"]["C"]["p95"] == 50
    assert result["routes"]["A"]["tokens"]["total_tokens"] == 12
    assert result["routes"]["C"]["tokens"] is None
    assert result["sample_sufficiency"]["meets_required_ac"] is False
    assert compare_runs([a, run("C", elapsed_ns=150)], learning_cost={"elapsed_ns": 200})["break_even"]["elapsed_reuses"] is None


def test_missing_role_coverage_keeps_total_calls_unknown():
    a = run("A", telemetry={"planning": True, "grounding": False, "verification": True})
    result = compare_runs([a, run("C")])
    assert result["routes"]["A"]["model_calls"]["grounding"] is None
    assert result["routes"]["A"]["model_calls"]["total"] is None


def test_token_break_even_requires_observed_positive_saving():
    a = run("A", events=[model_event("A-one", "planning", "p", {"input_tokens": 10, "output_tokens": 2})])
    c = run("C", events=[model_event("C-one", "planning", "p", {"input_tokens": 3, "output_tokens": 1})])
    result = compare_runs([a, c], learning_cost={"total_tokens": 24})
    assert result["pairs"]["token_saving"]["median"] == 8
    assert result["break_even"]["token_reuses"] == 3


def test_retries_do_not_create_independent_samples_or_improve_first_success():
    rows = [run(route, attempt_index=index, run_id=f"{route}-{index}",
                first_attempt_success=index == 1, completed=True)
            for route in ("A", "C") for index in range(1, 21)]
    result = compare_runs(rows)
    assert result["routes"]["C"]["attempts"] == 20
    assert result["routes"]["C"]["first_attempt_success_rate"] == 1
    assert result["sample_sufficiency"]["ac_pairs_by_family"] == {"lookup": 1}
    assert result["sample_sufficiency"]["meets_required_ac"] is False


@pytest.mark.parametrize("changes", [
    {"attempt_index": 2}, {"wrong_clicks": 1}, {"recovery_count": 1}, {"timed_out": True},
])
def test_first_attempt_success_rejects_contradictions(changes):
    with pytest.raises(ValueError, match="first.attempt"):
        compare_runs([run("A", **changes)])


def test_missing_first_attempt_is_rejected():
    with pytest.raises(ValueError, match="first.attempt"):
        compare_runs([run("A", attempt_index=2, first_attempt_success=False)])


def test_b_requires_same_case_pair_and_strata_are_explicit():
    rows = [run("A", "same"), run("C", "same"), run("B", "other")]
    result = compare_runs(rows)
    assert result["sample_sufficiency"]["b_runs_by_family"] == {}
    assert result["strata"]["lookup"]["stable"]["warm"]["pairs"]["count"] == 1


def test_negative_or_failed_pairs_do_not_create_break_even_saving():
    rows = [run("A", "negative", is_negative=True, first_attempt_success=False, completed=False, elapsed_ns=100),
            run("C", "negative", is_negative=True, first_attempt_success=False, completed=False, elapsed_ns=1),
            run("A", "failed", completed=False, first_attempt_success=False, elapsed_ns=100),
            run("C", "failed", completed=False, first_attempt_success=False, elapsed_ns=1)]
    assert compare_runs(rows, learning_cost={"elapsed_ns": 100})["break_even"]["elapsed_reuses"] is None


def test_benefit_stays_unknown_without_quota_or_telemetry():
    result = compare_runs([run("A", telemetry={"planning": False, "grounding": True, "verification": True}), run("C")])
    assert result["benefit_assessment"]["model_use"]["state"] == "unknown"
    assert "missing_model_telemetry" in result["benefit_assessment"]["model_use"]["blockers"]
    assert result["benefit_assessment"]["speed"]["state"] == "unknown"
    assert "insufficient_independent_pairs" in result["benefit_assessment"]["speed"]["blockers"]


def test_perfect_baseline_accuracy_is_parity_not_improvement():
    result = compare_runs([run("A"), run("C")])
    assert result["benefit_assessment"]["correctness"]["state"] == "parity"


def test_case_metadata_drift_cannot_manufacture_more_samples():
    with pytest.raises(ValueError, match="identity drift"):
        compare_runs([run("A", "same"), run("A", "same", run_id="A-retry",
                                     attempt_index=2, first_attempt_success=False, variation="layout")])


def _quota_rows():
    rows = []
    for family in ("query", "row", "handoff"):
        for variation, count in (("stable", 8), ("unseen", 6), ("layout", 6), ("ambiguous", 1)):
            for index in range(count):
                case = f"{family}-{variation}-{index}"
                common = {"task_family": family, "variation": variation}
                rows.append(run("A", case, elapsed_ns=100, wrong_clicks=int(variation == "ambiguous"),
                                first_attempt_success=variation != "ambiguous", **common,
                                events=[model_event(f"A-{case}", "planning", f"p-{case}"),
                                        model_event(f"A-{case}", "grounding", f"g-{case}")]))
                rows.append(run("C", case, elapsed_ns=60, **common,
                                events=[model_event(f"C-{case}", "planning", f"p-{case}")]))
                if variation == "stable" and index < 5:
                    rows.append(run("B", case, **common))
    return rows


def test_frozen_quota_and_all_three_benefits_are_scored_separately():
    rows = _quota_rows()
    result = compare_runs(rows)
    assert result["sample_sufficiency"]["meets_required_ac"] is True
    assert result["sample_sufficiency"]["meets_required_b"] is True
    assert result["sample_sufficiency"]["ac_by_family_variation"]["query"] == {
        "stable": 8, "unseen": 6, "layout": 6, "ambiguous": 1}
    assert result["benefit_assessment"]["model_use"]["state"] == "met"
    assert result["benefit_assessment"]["speed"]["state"] == "met"
    assert result["benefit_assessment"]["correctness"]["state"] == "met"


def test_family_regression_is_not_hidden_by_aggregate_model_saving():
    rows = _quota_rows()
    for row in rows:
        if row["route"] == "A" and row["task_family"] != "query":
            row["events"] = [model_event(row["run_id"], "planning", f"p-{i}") for i in range(10)]
        if row["route"] == "C" and row["task_family"] == "query":
            row["events"] = [model_event(row["run_id"], "planning", f"p-{i}") for i in range(3)]
    assessment = compare_runs(rows)["benefit_assessment"]
    assert assessment["model_use"]["state"] == "met"
    assert assessment["scope"] == "matched_aggregate"
    query = assessment["by_task_family"]["query"]
    assert query["model_use"]["state"] == "not_met"
    assert query["model_use"]["saving_fraction"] == -.5
    assert query["speed"]["stable_median_saving_fraction"] == .4
    assert query["correctness"]["first_attempt_success_rate"] == {"A": 20 / 21, "C": 1}
    assert assessment["all_families"]["state"] == "not_met"


@pytest.mark.parametrize("missing", ["telemetry", "b_quota", "ac_quota"])
def test_family_missing_evidence_stays_unknown(missing):
    rows = _quota_rows()
    if missing == "telemetry":
        next(row for row in rows if row["route"] == "C" and row["task_family"] == "query")["telemetry"]["grounding"] = False
    else:
        rows = [row for row in rows if not (row["task_family"] == "query" and
                (row["route"] == "B" if missing == "b_quota" else row["variation"] == "layout"))]
    assessment = compare_runs(rows)["benefit_assessment"]
    assert assessment["by_task_family"]["query"]["model_use"]["state"] == "unknown"
    assert assessment["all_families"]["state"] == "unknown"


def test_family_perfect_baseline_reports_parity_and_cannot_claim_all_benefits():
    rows = _quota_rows()
    for row in rows:
        if row["route"] == "A":
            row.update(first_attempt_success=True, wrong_clicks=0)
    assessment = compare_runs(rows)["benefit_assessment"]
    assert assessment["by_task_family"]["query"]["correctness"]["state"] == "parity"
    assert assessment["all_families"]["state"] == "unknown"


def test_family_correctness_regression_survives_aggregate_success():
    rows = _quota_rows()
    for row in rows:
        if row["route"] == "C" and row["case_id"] in {"query-unseen-0", "query-unseen-1"}:
            row.update(first_attempt_success=False, completed=False)
    assessment = compare_runs(rows)["benefit_assessment"]
    assert assessment["correctness"]["state"] == "met"
    assert assessment["by_task_family"]["query"]["correctness"]["state"] == "not_met"
    assert assessment["all_families"]["state"] == "not_met"


def test_family_retry_and_speed_regression_are_scoped_and_visible():
    rows = _quota_rows()
    rows.append(run("C", "query-unseen-0", run_id="C-query-retry", task_family="query",
                    variation="unseen", attempt_index=2, first_attempt_success=False))
    assessment = compare_runs(rows)["benefit_assessment"]
    assert assessment["by_task_family"]["query"]["speed"]["state"] == "unknown"
    assert "retry_cost_not_comparable" in assessment["by_task_family"]["query"]["speed"]["blockers"]
    assert assessment["by_task_family"]["row"]["overall"]["state"] == "met"
    rows.pop()
    for row in rows:
        if row["route"] == "C" and row["task_family"] == "query":
            row["elapsed_ns"] = 120
    assessment = compare_runs(rows)["benefit_assessment"]
    assert assessment["speed"]["stable_median_saving_fraction"] == .4
    assert assessment["by_task_family"]["query"]["speed"]["state"] == "not_met"
    assert assessment["by_task_family"]["query"]["speed"]["stable_median_saving_fraction"] == -.2
    assert assessment["all_families"]["state"] == "not_met"


def test_unseen_case_repeated_failures_cannot_be_hidden_by_first_pair_benefits():
    rows = _quota_rows()
    for row in rows:
        if row["case_id"] == "query-unseen-0":
            row.update(first_attempt_success=False, completed=False)
    for index in range(2, 7):
        for route in ("A", "C"):
            rows.append(run(route, "query-unseen-0", run_id=f"{route}-retry-{index}",
                task_family="query", variation="unseen", attempt_index=index,
                first_attempt_success=False, completed=route == "A"))
    result = compare_runs(rows)
    assert result["routes"]["C"]["positive_success_rate"] < .95
    assert result["benefit_assessment"]["overall"]["state"] != "met"
    assert "retry_cost_not_comparable" in result["benefit_assessment"]["correctness"]["blockers"]


def test_different_matched_model_cohorts_cannot_be_pooled_for_break_even():
    rows = [run("A", "one", elapsed_ns=100), run("C", "one", elapsed_ns=50),
            run("A", "two", config_digest="other", elapsed_ns=100),
            run("C", "two", config_digest="other", elapsed_ns=50)]
    result = compare_runs(rows, learning_cost={"elapsed_ns": 100})
    assert result["pairs"]["count"] == 2
    assert result["break_even"]["elapsed_reuses"] is None
    assert "model_configuration_mixed" in result["benefit_assessment"]["model_use"]["blockers"]


def test_break_even_accumulates_failed_first_attempt_and_retry_cost():
    a = run("A", elapsed_ns=100)
    c1 = run("C", elapsed_ns=10, completed=False, first_attempt_success=False)
    c2 = run("C", attempt_index=2, run_id="C-retry", elapsed_ns=300,
             first_attempt_success=False, completed=True)
    result = compare_runs([a, c1, c2], learning_cost={"elapsed_ns": 100})
    assert result["routes"]["C"]["attempts"] == 2
    assert result["break_even"]["elapsed_reuses"] is None
    assert result["benefit_assessment"]["speed"]["state"] == "unknown"
    assert "retry_cost_not_comparable" in result["benefit_assessment"]["speed"]["blockers"]
    assert "retry_cost_not_comparable" in result["benefit_assessment"]["model_use"]["blockers"]
    c2["elapsed_ns"] = 40
    assert compare_runs([a, c1, c2], learning_cost={"elapsed_ns": 100})["break_even"]["elapsed_reuses"] == 2


def test_break_even_requires_contiguous_attempts_and_observed_retry_tokens():
    a = run("A", events=[model_event("A-one", "planning", "a", {"input_tokens": 10, "output_tokens": 0})])
    c1 = run("C", completed=False, first_attempt_success=False, elapsed_ns=10,
             events=[model_event("C-one", "planning", "c", {"input_tokens": 2, "output_tokens": 0})])
    c3 = run("C", attempt_index=3, run_id="C-third", completed=True, first_attempt_success=False,
             events=[model_event("C-third", "planning", "d")])
    with pytest.raises(ValueError, match="attempt.*missing"):
        compare_runs([a, c1, c3])
    c3["attempt_index"] = 2
    result = compare_runs([a, c1, c3], learning_cost={"total_tokens": 10})
    assert result["break_even"]["token_reuses"] is None


def test_break_even_does_not_select_only_observed_or_successful_cases():
    rows = [run("A", "good", elapsed_ns=100,
                events=[model_event("A-good", "planning", "a", {"input_tokens": 10, "output_tokens": 0})]),
            run("C", "good", elapsed_ns=50,
                events=[model_event("C-good", "planning", "c", {"input_tokens": 2, "output_tokens": 0})]),
            run("A", "unknown", elapsed_ns=100,
                events=[model_event("A-unknown", "planning", "a")]),
            run("C", "unknown", elapsed_ns=50,
                events=[model_event("C-unknown", "planning", "c")])]
    result = compare_runs(rows, learning_cost={"total_tokens": 8})
    assert result["break_even"]["token_reuses"] is None
    assert result["break_even"]["scope"] == "positive_stable_warm_completed_cases"
    rows[-1]["completed"] = False
    rows[-1]["first_attempt_success"] = False
    assert compare_runs(rows, learning_cost={"elapsed_ns": 100})["break_even"]["elapsed_reuses"] is None
