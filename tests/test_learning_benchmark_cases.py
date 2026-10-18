from copy import deepcopy

import pytest

from app.learning_memory.benchmark_manifest import FAMILIES, freeze_manifest
from scripts.learning_benchmark_cases import build_cases, scenario_for


def execution_binding(tmp_path):
    return {"workflow_id": "workflow-" + "1" * 64,
            "program_id": "task-program-" + "2" * 64, "content_sha256": "2" * 64,
            "project_snapshot_id": "snapshot-current", "start_step_id": "query",
            "artifact_path": str((tmp_path / "program.json").resolve()),
            "target_memory_steps": ["query"], "rule_verification_steps": ["query"]}


def test_execution_metadata_preserves_scenario_and_real_driver_prepare(tmp_path):
    from scripts.learning_benchmark_fixture import RecordDeskCaseDriver
    case = deepcopy(build_cases(41)[5])
    expected = scenario_for(case)
    case.update(timeout_seconds=180, c_workflow=execution_binding(tmp_path))
    assert scenario_for(case) == expected
    records = {record["id"]: record for record in expected["records"]}
    observed = {"snapshot": {"case_id": case["case_id"],
        "records": [records[identity] for identity in expected["ordered_ids"]],
        "visible_ids": expected["ordered_ids"], "layout_variant": expected["layout_variant"],
        "query": "", "selected_id": None, "controlled_value": "",
        "detail_text": "No record selected", "verification_text": "Not verified",
        "notice_visible": False, "reset_event_index": 1, "event_index": 1},
        "events": [{"event_index": 1, "action": "case_reset", "case_id": case["case_id"]}]}
    driver = object.__new__(RecordDeskCaseDriver)
    def request(action, **fields):
        if action == "load_case":
            assert fields["scenario"] == expected
        return deepcopy(observed)
    driver._request = request
    assert driver.prepare(case) == observed


@pytest.mark.parametrize("timeout", [0, -1, True, "180", float("inf"), float("nan")])
def test_scenario_validates_timeout_without_manifest(timeout):
    case = deepcopy(build_cases(41)[5]); case["timeout_seconds"] = timeout
    with pytest.raises(ValueError, match="timeout"):
        scenario_for(case)


@pytest.mark.parametrize("mutation", ["missing", "relative_path", "invalid_hash", "empty_steps"])
def test_scenario_validates_binding_without_manifest(tmp_path, mutation):
    case = deepcopy(build_cases(41)[5]); binding = execution_binding(tmp_path)
    if mutation == "missing":
        binding.pop("program_id")
    elif mutation == "relative_path":
        binding["artifact_path"] = "program.json"
    elif mutation == "invalid_hash":
        binding["content_sha256"] = "bad"
    else:
        binding["target_memory_steps"] = []
    case["c_workflow"] = binding
    with pytest.raises(ValueError, match="benchmark"):
        scenario_for(case)


@pytest.mark.parametrize("field", ["inputs", "seed", "success_rule", "routes", "cohort", "cold_or_warm", "is_negative", "initial_truth"])
def test_execution_metadata_does_not_allow_scenario_drift(tmp_path, field):
    case = deepcopy(build_cases(41)[5])
    case.update(timeout_seconds=180, c_workflow=execution_binding(tmp_path))
    case[field] = {"injected": True}
    with pytest.raises(ValueError, match="case"):
        scenario_for(case)


def test_frozen_cases_are_deterministic_and_have_exact_quota():
    cases = build_cases(41)
    assert cases == build_cases(41)
    assert len(cases) == 60
    assert len({case["seed"] for case in cases}) == 60
    assert len({case["case_id"] for case in cases}) == 60
    for family in FAMILIES:
        family_cases = [case for case in cases if case["task_family"] == family]
        assert {variation: sum(case["variation"] == variation for case in family_cases)
                for variation in ("stable", "unseen", "layout")} == {
                    "stable": 8, "unseen": 6, "layout": 6}
        assert sum("B" in case["routes"] for case in family_cases) >= 5
    assert all(set(case["inputs"]) == {"record_id", "query"} for case in cases)
    assert all(case["success_rule"] == {"all": [{"path": ["result", "case_verdict", "completed"], "equals": True}]}
               for case in cases)


def test_stable_repeats_and_unseen_changes_are_real():
    cases = build_cases(41)
    for family in FAMILIES:
        stable = [case for case in cases if case["task_family"] == family and case["variation"] == "stable"]
        unseen = [case for case in cases if case["task_family"] == family and case["variation"] == "unseen"]
        stable_scenes = [scenario_for(case) for case in stable]
        assert all(scene["records"] == stable_scenes[0]["records"] for scene in stable_scenes)
        assert all(scene["ordered_ids"] == stable_scenes[0]["ordered_ids"] for scene in stable_scenes)
        assert len({case["inputs"]["record_id"] for case in unseen}) == 6
        assert all(case["inputs"]["record_id"] != stable[0]["inputs"]["record_id"] for case in unseen)
        details = [next(record["detail"] for record in scenario_for(case)["records"]
                        if record["id"] == case["inputs"]["record_id"]) for case in unseen]
        assert len(set(details)) == 6
        assert all(case["inputs"]["record_id"] not in detail and detail.startswith("state-")
                   for case, detail in zip(unseen, details))
    assert scenario_for(build_cases(42)[0])["records"] != scenario_for(cases[0])["records"]


def test_layout_cases_keep_stable_content_and_move_target():
    cases = build_cases(41)
    for family in FAMILIES:
        stable = next(case for case in cases if case["task_family"] == family and case["variation"] == "stable")
        baseline = scenario_for(stable)
        layout_cases = [case for case in cases if case["task_family"] == family and case["variation"] == "layout"]
        for case in layout_cases:
            scene = scenario_for(case)
            assert scene["records"] == baseline["records"]
            assert case["inputs"] == stable["inputs"]
            assert scene["ordered_ids"] != baseline["ordered_ids"]
            assert scene["layout_variant"] != baseline["layout_variant"]
            assert scene["ordered_ids"].index(case["inputs"]["record_id"]) != baseline["ordered_ids"].index(stable["inputs"]["record_id"])
        if family == "query_verify":
            assert all(scenario_for(case)["layout_variant"] == "search_below_rows" for case in layout_cases)
        else:
            assert all(scenario_for(case)["layout_variant"] == "detail_above_rows" for case in layout_cases)


@pytest.mark.parametrize("field", ["inputs", "seed", "case_id", "success_rule"])
def test_scenario_refuses_mutated_case(field):
    case = deepcopy(build_cases(41)[0])
    case[field] = {"record_id": "fake", "query": "fake"} if field == "inputs" else (
        case["seed"] + 1 if field == "seed" else "fake" if field == "case_id" else {})
    with pytest.raises(ValueError, match="case"):
        scenario_for(case)


def test_generated_cases_pass_manifest_validation(tmp_path):
    root = tmp_path / "root"
    scoring = root / "app/learning_memory/benchmark_scoring.py"
    scoring.parent.mkdir(parents=True)
    scoring.write_text("score = 1\n", encoding="utf-8")
    spec = {"benchmark_id": "bench-41", "model": {"source": "agent_current", "model": "fixed",
            "config_digest": "a" * 64}, "cases": build_cases(41), "artifacts": []}
    frozen = freeze_manifest(spec, root=root, destination=tmp_path / "manifest.json")
    assert len(frozen["cases"]) == 60
