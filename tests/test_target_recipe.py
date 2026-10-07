"""固定目标规则的持久化、证据与语义绑定契约。"""
from copy import deepcopy
import hashlib
from pathlib import Path

import pytest

from app.desktop_review.external_mapping import canonical_json_bytes
from app.learning_memory.target_recipe import (
    action_semantics_sha256, load_target_recipe, save_target_recipe, validate_target_reference,
)


INTERFACE = "interface-" + "a" * 8 + "-" + "a" * 4 + "-" + "a" * 4 + "-" + "a" * 4 + "-" + "a" * 12
VERSION = "interface-version-" + "b" * 64
TEMPLATE = "template-" + "c" * 64


class Library:
    def __init__(self, root):
        self._artifact_root = Path(root)
        self.raw = b"fresh-evidence"
        self.sha = hashlib.sha256(self.raw).hexdigest()
        self.image = self._artifact_root / "source.png"
        self.image.write_bytes(self.raw)
        self.content = {"interface_id": INTERFACE, "version_id": VERSION,
                        "content_sha256": "d" * 64,
                        "source": {"kind": "execution_memory_v1", "task_id": "memory-local",
                                   "interface_key": "search", "state_key": "home"}}

    def load_interface_content(self, interface_id, version_id):
        if (interface_id, version_id) != (INTERFACE, VERSION):
            raise ValueError("pinned interface missing")
        return deepcopy(self.content)

    def load_interface_content_evidence(self, interface_id, version_id):
        return {"image_path": "source.png", "sha256": self.sha}

    def _artifact_file(self, relative, label):
        return self._artifact_root / relative


def recipe(library, *, goal="打开详情", anchors=None):
    scope = {"task_id": "memory-local", "interface_key": "search", "state_key": "home"}
    if anchors is not None:
        scope.update(application={"executable_name": "fixture.exe", "window_class": "Fixture"}, anchors=anchors)
    strategies = [{"kind": "uia", "name": "详情", "control_type": "Button", "automation_id": "details"}]
    body = {"contract_version": "target_recipe.v1", "interface_id": INTERFACE,
            "interface_version_id": VERSION, "scope": scope, "strategies": strategies,
            "action_semantics_sha256": action_semantics_sha256({"kind": "click", "goal": goal},
                scope=scope, strategies=strategies),
            "evidence_refs": [{"kind": "interface_content", "content_sha256": "d" * 64,
                               "source_image_sha256": library.sha}]}
    return {**body, "recipe_id": "target-recipe-" + hashlib.sha256(canonical_json_bytes(body)).hexdigest()}


def reference(value):
    return {"recipe_id": value["recipe_id"], "interface_key": "search", "state_key": "home"}


def test_save_reopen_and_exact_reference(tmp_path):
    library = Library(tmp_path)
    value = recipe(library, anchors=[{"kind": "uia", "name": "页面", "control_type": "Pane"}])
    assert save_target_recipe(library, value) == value
    assert load_target_recipe(library, reference(value)) == value
    assert validate_target_reference(reference(value)) == reference(value)
    with pytest.raises(ValueError, match="reference_invalid"):
        validate_target_reference({**reference(value), "path": "C:/outside"})
    with pytest.raises(ValueError, match="reference_mismatch"):
        load_target_recipe(library, {**reference(value), "state_key": "results"})


def test_missing_and_corrupt_evidence_rejected(tmp_path):
    library = Library(tmp_path)
    value = recipe(library)
    save_target_recipe(library, value)
    library.content["content_sha256"] = "e" * 64
    with pytest.raises(ValueError, match="interface_evidence_mismatch"):
        load_target_recipe(library, reference(value))
    library.content["content_sha256"] = "d" * 64
    library.image.write_bytes(b"changed")
    with pytest.raises(ValueError, match="image_evidence_mismatch"):
        load_target_recipe(library, reference(value))
    library.image.unlink()
    with pytest.raises(OSError):
        load_target_recipe(library, reference(value))


def test_recipe_digest_and_schema_are_closed(tmp_path):
    library = Library(tmp_path)
    value = recipe(library)
    with pytest.raises(ValueError, match="digest_mismatch"):
        save_target_recipe(library, {**value, "action_semantics_sha256": "0" * 64})
    with pytest.raises(ValueError, match="scope_invalid"):
        save_target_recipe(library, {**value, "scope": {**value["scope"], "image_path": "source.png"}})
    with pytest.raises(ValueError, match="strategy_invalid"):
        save_target_recipe(library, {**value, "strategies": [{"kind": "python", "script": "click()"}]})


def test_action_semantics_ignores_run_value_but_changes_target_or_action(tmp_path):
    library = Library(tmp_path)
    value = recipe(library)
    scope, strategies = value["scope"], value["strategies"]
    base = action_semantics_sha256({"kind": "input_sequence", "field_goal": "搜索框",
                                    "submit_search": True, "text": {"source": "constant", "value": "A"}},
                                   scope=scope, strategies=strategies)
    changed_value = action_semantics_sha256({"kind": "input_sequence", "field_goal": "搜索框",
                                             "submit_search": True, "text": {"source": "constant", "value": "B"}},
                                            scope=scope, strategies=strategies)
    assert base == changed_value
    assert base != action_semantics_sha256({"kind": "input_sequence", "field_goal": "另一个框",
                                            "submit_search": True}, scope=scope, strategies=strategies)
    assert value["action_semantics_sha256"] != action_semantics_sha256(
        {"kind": "click", "goal": "其他目标"}, scope=scope, strategies=strategies)


def test_action_request_models_accept_exact_reference():
    from app.api.models.request import ExecuteRecognitionPlanRequest
    from app.desktop_review.input_sequence import InputSequenceRequest
    from app.desktop_review.local_action_contract import _validated_request
    ref = {"recipe_id": "target-recipe-" + "a" * 64, "interface_key": "search", "state_key": "home"}
    assert ExecuteRecognitionPlanRequest.model_validate({"goal": "打开", "target_memory": ref}).target_memory == ref
    assert InputSequenceRequest.model_validate({"field_goal": "搜索", "text": "新词",
                                                 "submit_search": False, "target_memory": ref}).target_memory == ref
    assert _validated_request("execute_recognition_plan", {"goal": "打开", "target_memory": ref})["target_memory"] == ref
    with pytest.raises(ValueError):
        InputSequenceRequest.model_validate({"field_goal": "搜索", "text": "新词",
                                              "submit_search": False, "target_memory": {**ref, "path": "outside"}})


def test_legacy_reader_template_bridge_uses_recipe_reference(monkeypatch):
    from app.learning_memory import reader
    template_ref = {"template_id": TEMPLATE, "interface_key": "search", "state_key": "home"}
    expected = {"recipe_id": "target-recipe-" + "a" * 64, "interface_key": "search", "state_key": "home"}
    memory = {"snapshot_id": "snapshot", "graph": {"edges": [{"edge_id": "edge", "operation": "execute_recognition_plan",
        "provenance": "observed_action_agent_judged", "input_binding_required": False,
        "input_binding": None, "action_hints": {"goal": "打开", "click_kind": "single", "template_memory": template_ref}}]}}
    monkeypatch.setattr(reader, "read_project", lambda *args: memory)
    monkeypatch.setattr("app.learning_memory.target_recipe.recipe_from_template",
                        lambda library, template, action: expected)
    advice = reader.prepare_reuse(object(), "workflow", "snapshot", "edge", {})
    assert advice["suggested_command"]["request"] == {"goal": "打开", "click_kind": "single",
                                                       "target_memory": expected}


def test_visible_row_rule_persists_and_hashes_complete_rule(tmp_path):
    library = Library(tmp_path)
    anchor = {"kind": "uia", "name": "结果页", "control_type": "Pane"}
    rule = {"kind": "visible_row", "container": {"name": "结果列表", "control_type": "List"},
            "row": {"control_type": "ListItem"},
            "properties": [{"property": "title", "control_type": "Text", "read": "name"}],
            "constraints": [{"property": "title", "operator": "eq", "value": {"source": "input", "name": "wanted"}}],
            "action": {"name": "打开", "control_type": "Button"}}
    value = recipe(library, anchors=[anchor])
    value["strategies"] = [rule]
    value["action_semantics_sha256"] = action_semantics_sha256(
        {"kind": "click", "goal": "打开详情"}, scope=value["scope"], strategies=[rule])
    value["recipe_id"] = "target-recipe-" + hashlib.sha256(canonical_json_bytes(
        {k: v for k, v in value.items() if k != "recipe_id"})).hexdigest()
    assert load_target_recipe(library, reference(save_target_recipe(library, value))) == value
    changed = deepcopy(rule)
    changed["constraints"][0]["value"]["name"] = "other"
    assert action_semantics_sha256({"kind": "click", "goal": "打开详情"},
        scope=value["scope"], strategies=[changed]) != value["action_semantics_sha256"]
    with pytest.raises(ValueError):
        action_semantics_sha256({"kind": "click", "goal": "打开详情"},
            scope={**value["scope"], "anchors": [rule]}, strategies=[rule])
