"""显示名修改不重新审核执行语义；真实依赖变化仍失效。"""
from copy import deepcopy

import pytest

from tests.test_workflow_program import program_service, WORKFLOW


def reviewed_chain(service):
    draft = service.load(WORKFLOW)
    definition = deepcopy(draft["definition"])
    first, second = definition["steps"]
    first["outputs"] = [{"name": "found", "type": "text"}]
    second["action"]["goal"] = "打开当前结果"
    second["preconditions"] = [{"left": {"source": "output", "step_id": first["step_id"], "name": "found"},
                                  "operator": "exists"}]
    initial = service.save(WORKFLOW, draft["content_sha256"], definition, "define-chain")
    reviewed = deepcopy(initial["definition"])
    for step in reviewed["steps"]:
        step["review_status"] = "reviewed"
    return service.save(WORKFLOW, initial["content_sha256"], reviewed, "review-chain")


def test_renaming_reviewed_source_preserves_downstream_review_and_old_revision(program_service):
    before = reviewed_chain(program_service)
    changed = deepcopy(before["definition"])
    changed["steps"][0]["title"] = "查询最新记录"
    renamed = program_service.save(WORKFLOW, before["content_sha256"], changed, "rename")
    assert renamed["program_id"] != before["program_id"]
    assert renamed["definition"]["steps"][0]["title"] == "查询最新记录"
    assert [step["review_status"] for step in renamed["definition"]["steps"]] == ["reviewed", "reviewed"]
    assert [step["provenance"] for step in renamed["definition"]["steps"]] == [
        step["provenance"] for step in before["definition"]["steps"]]
    assert renamed["review_items"] == []
    assert program_service.load(WORKFLOW)["definition"] == renamed["definition"]
    assert program_service.load(WORKFLOW, before["program_id"]) == before


@pytest.mark.parametrize("change", ["target", "value", "verification", "condition"])
def test_renaming_with_semantic_edit_still_invalidates_source_and_dependents(program_service, change):
    before = reviewed_chain(program_service)
    definition = deepcopy(before["definition"])
    first = definition["steps"][0]
    first["title"] = "已改名"
    if change == "target":
        first["action"]["field_goal"] = "另一个字段"
    elif change == "value":
        first["action"]["text"] = {"source": "constant", "value": "新的固定值"}
    elif change == "verification":
        first["verification"] = {"kind": "agent_judgment"}
    else:
        first["preconditions"] = [{"left": {"source": "input", "name": "query"}, "operator": "exists"}]
    saved = program_service.save(WORKFLOW, before["content_sha256"], definition, "change-" + change)
    assert [step["review_status"] for step in saved["definition"]["steps"]] == ["pending", "pending"]
    assert program_service.load(WORKFLOW, before["program_id"]) == before


def test_title_change_cannot_promote_pending_review_or_override_explicit_unreview(program_service):
    before = reviewed_chain(program_service)
    definition = deepcopy(before["definition"])
    definition["steps"][0].update(title="需要再次检查", review_status="pending")
    marked = program_service.save(WORKFLOW, before["content_sha256"], definition, "unreview")
    assert [step["review_status"] for step in marked["definition"]["steps"]] == ["pending", "reviewed"]
    again = deepcopy(marked["definition"])
    again["steps"][0]["title"] = "仍未审核"
    saved = program_service.save(WORKFLOW, marked["content_sha256"], again, "rename-pending")
    assert [step["review_status"] for step in saved["definition"]["steps"]] == ["pending", "reviewed"]


def test_title_edit_preserves_observed_action_provenance(program_service):
    draft = program_service.load(WORKFLOW)
    definition = deepcopy(draft["definition"])
    definition["steps"][1]["action"]["goal"] = "返回首页"
    definition["steps"][0]["review_status"] = "reviewed"
    baseline = program_service.save(WORKFLOW, draft["content_sha256"], definition, "defined")
    assert baseline["definition"]["steps"][0]["provenance"] == "observed"
    renamed = deepcopy(baseline["definition"])
    renamed["steps"][0]["title"] = "搜索记录"
    saved = program_service.save(WORKFLOW, baseline["content_sha256"], renamed, "rename-observed")
    assert saved["definition"]["steps"][0]["provenance"] == "observed"
    assert saved["definition"]["steps"][0]["review_status"] == "reviewed"
