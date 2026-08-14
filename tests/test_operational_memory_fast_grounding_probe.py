from scripts.run_operational_memory_fast_grounding_real_ab import _summary, evaluate_ab_expectation


def _baseline_summary() -> dict:
    return {
        "pre_click_allowed": True,
        "dry_run": True,
        "action_executed": False,
    }


def test_evaluate_ab_expectation_accepts_current_uia_fast_path() -> None:
    evaluation = evaluate_ab_expectation(
        baseline=_baseline_summary(),
        fast={
            "pre_click_allowed": True,
            "dry_run": True,
            "action_executed": False,
            "fast_grounding_used": True,
            "vision_model_used": False,
            "current_uia_unique_match_count": 1,
            "candidate_freshness_allowed": True,
            "candidate_freshness_source": "current_uia_unique_match_v1",
        },
        expected_fast_path="used",
    )

    assert evaluation["passed"] is True
    assert evaluation["expectation"] == "used"
    assert all(evaluation["checks"].values())


def test_evaluate_ab_expectation_accepts_ambiguous_current_uia_vista_fallback() -> None:
    evaluation = evaluate_ab_expectation(
        baseline=_baseline_summary(),
        fast={
            "pre_click_allowed": True,
            "dry_run": True,
            "action_executed": False,
            "fast_grounding_used": False,
            "fast_grounding_reason": "current_uia_match_not_unique",
            "vision_model_used": True,
            "current_uia_unique_match_count": 2,
            "candidate_freshness_allowed": True,
            "candidate_freshness_source": "current_uia_vista_grounded_v1",
        },
        expected_fast_path="fallback",
    )

    assert evaluation["passed"] is True
    assert evaluation["expectation"] == "fallback"
    assert all(evaluation["checks"].values())


def test_evaluate_ab_expectation_rejects_historical_coordinate_freshness() -> None:
    evaluation = evaluate_ab_expectation(
        baseline=_baseline_summary(),
        fast={
            "pre_click_allowed": True,
            "dry_run": True,
            "action_executed": False,
            "fast_grounding_used": True,
            "vision_model_used": False,
            "current_uia_unique_match_count": 1,
            "candidate_freshness_allowed": True,
            "candidate_freshness_source": "reviewed_interface_memory_seed_v1",
        },
        expected_fast_path="used",
    )

    assert evaluation["passed"] is False
    assert evaluation["checks"]["current_capture_freshness"] is False


def test_summary_reads_freshness_from_nested_recognition_plan() -> None:
    summary = _summary(
        {
            "success": True,
            "data": {
                "result": {
                    "recognition_plan": {
                        "candidate_freshness_decision": {
                            "allowed": True,
                            "candidate_id": "current-uia-file",
                            "candidate_freshness": {
                                "capture_id": "capture-current",
                                "source": "current_uia_unique_match_v1",
                                "freshness": "current_capture",
                            },
                        }
                    }
                }
            },
        }
    )

    assert summary["candidate_freshness_allowed"] is True
    assert summary["candidate_freshness_candidate_id"] == "current-uia-file"
    assert summary["candidate_freshness_source"] == "current_uia_unique_match_v1"
