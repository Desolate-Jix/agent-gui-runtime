"""步骤定义与不可变版本的隔离契约。"""
from copy import deepcopy
from pathlib import Path

import pytest

from app.learning_memory.workflow_program import WorkflowProgramService
from app.learning_memory.target_recipe import action_semantics_sha256


WORKFLOW = "workflow-" + "a" * 64
SNAPSHOT = "workflow-project-snapshot-" + "b" * 64


class Library:
    def __init__(self, path):
        self._workspace_root = Path(path)


@pytest.fixture
def program_service(tmp_path, monkeypatch):
    memory = {"snapshot_id": SNAPSHOT, "graph": {"workflow": {"goal": "搜索"},
        "nodes": [{"node_id": "home"}, {"node_id": "results"}],
        "edges": [{"edge_id": "edge-1", "source_node_id": "home", "target_node_id": "results",
            "provenance": "observed_action_agent_judged", "operation": "input_sequence",
            "action_hints": {"field_goal": "搜索框", "submit_search": True, "clear_existing": True},
            "input_binding": {"kind": "variable", "name": "query"}, "label": "搜索地点"},
            {"edge_id": "edge-2", "source_node_id": "results", "target_node_id": "home",
             "provenance": "editorial_not_observed", "expected_result": "返回首页", "label": "人工关系"}]}}
    monkeypatch.setattr("app.learning_memory.workflow_program.read_project",
                        lambda library, workflow_id, snapshot_id=None: deepcopy(memory))
    return WorkflowProgramService(Library(tmp_path))


def test_draft_preserves_editorial_relationship_and_observed_input(program_service):
    draft = program_service.load(WORKFLOW)
    assert draft["program_id"] is None and draft["project_snapshot_id"] == SNAPSHOT
    assert len(draft["definition"]["steps"]) == 2
    assert draft["definition"]["steps"][0]["action"]["text"] == {"source": "input", "name": "query"}
    assert draft["definition"]["steps"][1]["provenance"] == "editorial"
    assert {item["reason"] for item in draft["review_items"]} == {"needs_review", "needs_definition"}


def test_semantic_edit_invalidates_recipe_but_title_edit_does_not(program_service, monkeypatch):
    reference = {"recipe_id": "target-recipe-" + "c" * 64, "interface_key": "search", "state_key": "home"}
    scope = {"task_id": "memory-local", "interface_key": "search", "state_key": "home"}
    strategies = [{"kind": "uia", "name": "搜索", "control_type": "Edit"}]
    action = {"kind": "input_sequence", "field_goal": "搜索框", "submit_search": True}
    recipe = {"scope": scope, "strategies": strategies,
              "action_semantics_sha256": action_semantics_sha256(action, scope=scope, strategies=strategies)}
    monkeypatch.setattr("app.learning_memory.workflow_program.load_target_recipe", lambda library, ref: recipe)
    draft = program_service.load(WORKFLOW)
    definition = deepcopy(draft["definition"])
    definition["steps"][0]["action"]["target_memory"] = reference
    definition["steps"][1]["action"]["goal"] = "返回首页"
    saved = program_service.save(WORKFLOW, draft["content_sha256"], definition, "recipe-save")
    renamed = deepcopy(saved["definition"])
    renamed["steps"][0]["title"] = "新标题"
    title_version = program_service.save(WORKFLOW, saved["content_sha256"], renamed, "title-edit")
    assert title_version["definition"]["steps"][0]["action"]["target_memory"] == reference
    changed = deepcopy(title_version["definition"])
    changed["steps"][0]["action"]["field_goal"] = "另一个搜索框"
    semantic_version = program_service.save(WORKFLOW, title_version["content_sha256"], changed, "target-edit")
    assert "target_memory" not in semantic_version["definition"]["steps"][0]["action"]
    assert program_service.load(WORKFLOW, title_version["program_id"])["definition"]["steps"][0]["action"]["target_memory"] == reference


def test_saved_program_load_rechecks_missing_recipe(program_service, monkeypatch):
    reference = {"recipe_id": "target-recipe-" + "c" * 64, "interface_key": "search", "state_key": "home"}
    scope = {"task_id": "memory-local", "interface_key": "search", "state_key": "home"}
    strategies = [{"kind": "uia", "name": "搜索", "control_type": "Edit"}]
    recipe = {"scope": scope, "strategies": strategies,
              "action_semantics_sha256": action_semantics_sha256(
                  {"kind": "input_sequence", "field_goal": "搜索框", "submit_search": True},
                  scope=scope, strategies=strategies)}
    monkeypatch.setattr("app.learning_memory.workflow_program.load_target_recipe", lambda library, ref: recipe)
    draft = program_service.load(WORKFLOW)
    definition = deepcopy(draft["definition"])
    definition["steps"][0]["action"]["target_memory"] = reference
    definition["steps"][1]["action"]["goal"] = "返回首页"
    saved = program_service.save(WORKFLOW, draft["content_sha256"], definition, "recipe-save")
    def missing(library, ref):
        raise ValueError("target_recipe_file_invalid")
    monkeypatch.setattr("app.learning_memory.workflow_program.load_target_recipe", missing)
    with pytest.raises(ValueError, match="target_recipe_file_invalid"):
        program_service.load(WORKFLOW, saved["program_id"])


def test_observed_reference_survives_draft_save_and_trial_prepare(program_service, tmp_path, monkeypatch):
    from app.learning_memory.workflow_trial import TrialService
    reference = {"recipe_id": "target-recipe-" + "c" * 64, "interface_key": "search", "state_key": "home"}
    scope = {"task_id": "memory-local", "interface_key": "search", "state_key": "home"}
    strategies = [{"kind": "uia", "name": "搜索", "control_type": "Edit"}]
    recipe = {"scope": scope, "strategies": strategies,
              "action_semantics_sha256": action_semantics_sha256(
                  {"kind": "input_sequence", "field_goal": "搜索框", "submit_search": True},
                  scope=scope, strategies=strategies)}
    monkeypatch.setattr("app.learning_memory.workflow_program.load_target_recipe", lambda library, ref: recipe)
    from app.learning_memory import workflow_program
    original = workflow_program.read_project
    def observed(library, workflow_id, snapshot_id=None):
        memory = original(library, workflow_id, snapshot_id)
        memory["graph"]["edges"][0]["action_hints"]["target_memory"] = reference
        return memory
    monkeypatch.setattr(workflow_program, "read_project", observed)
    draft = program_service.load(WORKFLOW)
    assert draft["definition"]["steps"][0]["action"]["target_memory"] == reference
    definition = deepcopy(draft["definition"])
    definition["steps"][1]["action"]["goal"] = "返回首页"
    saved = program_service.save(WORKFLOW, draft["content_sha256"], definition, "save-observed")
    trial = TrialService(program_service.library, tmp_path / "session")
    run = trial.start(WORKFLOW, saved["program_id"], "step-1", {"query": "新查询"}, "start-observed")
    ticket = trial.prepare(run["run_id"], "prepare-observed")
    assert ticket["suggested_command"]["request"]["target_memory"] == reference
    assert ticket["suggested_command"]["request"]["text"] == "新查询"


def test_edit_new_version_idempotency_and_old_snapshot(program_service):
    draft = program_service.load(WORKFLOW)
    definition = deepcopy(draft["definition"])
    definition["steps"][0]["action"]["field_goal"] = "新搜索目标"
    definition["steps"][1]["action"]["goal"] = "返回首页"
    saved = program_service.save(WORKFLOW, draft["content_sha256"], definition, "edit-one")
    assert saved["definition"]["steps"][0]["action"]["field_goal"] == "新搜索目标"
    assert saved["definition"]["steps"][0]["provenance"] == "editorial"
    assert program_service.save(WORKFLOW, draft["content_sha256"], definition, "edit-one") == saved
    with pytest.raises(ValueError, match="idempotency_conflict"):
        program_service.save(WORKFLOW, draft["content_sha256"], draft["definition"], "edit-one")
    with pytest.raises(ValueError, match="stale_revision"):
        program_service.save(WORKFLOW, draft["content_sha256"], draft["definition"], "edit-two")
    next_definition = deepcopy(definition)
    next_definition["steps"][0]["action"]["field_goal"] = "另一个目标"
    newer = program_service.save(WORKFLOW, saved["content_sha256"], next_definition, "edit-two")
    assert newer["program_id"] != saved["program_id"]
    assert program_service.load(WORKFLOW, saved["program_id"])["definition"] == saved["definition"]
    assert program_service.load(WORKFLOW)["program_id"] == newer["program_id"]


@pytest.mark.parametrize("mutate,match", [
    (lambda d: d["steps"][0]["action"].update(text={"source": "input", "name": "missing"}), "input_unknown"),
    (lambda d: d["steps"][0]["action"].update(text={"source": "output", "step_id": "step-2", "name": "x"}), "upstream_output_unknown"),
    (lambda d: d["steps"][0]["branches"].update(success="absent"), "branch_target_invalid"),
    (lambda d: d["steps"][0]["preconditions"].append({"left": {"source": "input", "name": "query"}, "operator": "eval", "value": "x"}), "condition_operator_invalid"),
])
def test_invalid_references_and_branches_rejected(program_service, mutate, match):
    draft = program_service.load(WORKFLOW)
    definition = deepcopy(draft["definition"])
    definition["steps"][1]["action"]["goal"] = "返回首页"
    mutate(definition)
    with pytest.raises(ValueError, match=match):
        program_service.save(WORKFLOW, draft["content_sha256"], definition, "bad")


def test_output_type_and_upstream_reference_checked(program_service):
    draft = program_service.load(WORKFLOW)
    definition = deepcopy(draft["definition"])
    definition["steps"][1]["action"]["goal"] = "返回首页"
    definition["steps"][0]["outputs"] = [{"name": "found", "type": "boolean"}]
    definition["steps"][0]["success_conditions"] = [{"left": {"source": "output", "step_id": "step-1", "name": "found"}, "operator": "eq", "value": True}]
    definition["steps"][1]["preconditions"] = [{"left": {"source": "output", "step_id": "step-1", "name": "found"}, "operator": "eq", "value": True}]
    assert program_service.save(WORKFLOW, draft["content_sha256"], definition, "output")


def test_new_step_cannot_claim_observed_and_branch_cycle_rejected(program_service):
    draft = program_service.load(WORKFLOW)
    definition = deepcopy(draft["definition"])
    definition["steps"][1]["action"]["goal"] = "返回首页"
    definition["steps"].append({"step_id": "manual", "title": "人工新步骤", "source_node_id": None,
        "target_node_id": None, "action": {"kind": "click", "goal": "打开"},
        "preconditions": [], "success_conditions": [], "branches": {"success": None, "failure": None, "uncertain": None},
        "outputs": [], "review_status": "pending", "provenance": "observed"})
    saved = program_service.save(WORKFLOW, draft["content_sha256"], definition, "new-step")
    assert saved["definition"]["steps"][-1]["provenance"] == "manual"
    cyclic = deepcopy(saved["definition"])
    cyclic["steps"][0]["branches"]["success"] = "step-2"
    cyclic["steps"][1]["branches"]["success"] = "step-1"
    with pytest.raises(ValueError, match="branch_cycle_invalid"):
        program_service.save(WORKFLOW, saved["content_sha256"], cyclic, "cycle")


def test_condition_value_must_match_declared_output_type(program_service):
    draft = program_service.load(WORKFLOW)
    definition = deepcopy(draft["definition"])
    definition["steps"][1]["action"]["goal"] = "返回首页"
    definition["steps"][0]["outputs"] = [{"name": "found", "type": "boolean"}]
    definition["steps"][1]["preconditions"] = [{"left": {"source": "output", "step_id": "step-1", "name": "found"},
        "operator": "eq", "value": "true"}]
    with pytest.raises(ValueError, match="condition_value_type_invalid"):
        program_service.save(WORKFLOW, draft["content_sha256"], definition, "bad-type")


@pytest.mark.parametrize("malformed", [None, {}, {"title": "任务", "inputs": [], "outputs": []},
    {"title": "任务", "inputs": None, "outputs": [], "steps": []}])
def test_malformed_definition_reports_validation_error(program_service, malformed):
    draft = program_service.load(WORKFLOW)
    with pytest.raises(ValueError, match="task_program_definition_invalid|inputs_invalid"):
        program_service.save(WORKFLOW, draft["content_sha256"], malformed, "malformed")


def test_semantic_edit_resets_review_but_pure_review_and_unaffected_step_survive(program_service):
    draft = program_service.load(WORKFLOW)
    definition = deepcopy(draft["definition"])
    definition["steps"][1]["action"]["goal"] = "返回首页"
    first = program_service.save(WORKFLOW, draft["content_sha256"], definition, "define-editorial")
    reviewed = deepcopy(first["definition"])
    for step in reviewed["steps"]:
        step["review_status"] = "reviewed"
    second = program_service.save(WORKFLOW, first["content_sha256"], reviewed, "review-only")
    assert all(step["review_status"] == "reviewed" for step in second["definition"]["steps"])
    changed = deepcopy(second["definition"])
    changed["inputs"][0]["required"] = False
    third = program_service.save(WORKFLOW, second["content_sha256"], changed, "change-input")
    assert third["definition"]["steps"][0]["review_status"] == "pending"
    assert third["definition"]["steps"][0]["provenance"] == "editorial"
    assert third["definition"]["steps"][1]["review_status"] == "reviewed"
    changed_action = deepcopy(third["definition"])
    changed_action["steps"][1]["action"]["goal"] = "另一个返回目标"
    fourth = program_service.save(WORKFLOW, third["content_sha256"], changed_action, "change-action")
    assert fourth["definition"]["steps"][1]["review_status"] == "pending"
    assert fourth["definition"]["steps"][0]["review_status"] == "pending"
