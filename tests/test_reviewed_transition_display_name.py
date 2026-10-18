"""编译 transition 保留图上已审核标题，缺失时维持旧回退。"""
import pytest

from tests.test_reviewed_workflow_compiler_v2 import _base_review, _persist_reviewed_workflow, _run_compile


@pytest.mark.parametrize(("display_name", "operation_id", "expected"), [
    ("查看示例详情", "legacy-operation", "查看示例详情"),
    ("open_detail · ACTION_RECORDED", "legacy-operation", "open_detail · ACTION_RECORDED"),
    (None, "legacy-operation", "legacy-operation"),
    (None, None, "home_to_detail"),
])
def test_transition_display_name_preserves_reviewed_edge_title_and_old_fallback(
    tmp_path, display_name, operation_id, expected,
):
    review = _base_review()
    edge = review["edges"][0]
    if display_name is not None:
        edge["display_name"] = display_name
    if operation_id is None:
        edge.pop("operation_id", None)
    else:
        edge["operation_id"] = operation_id
    source, digest = _persist_reviewed_workflow(tmp_path, review)
    result = _run_compile(tmp_path, source, digest)
    assert result["status"] == "compiled", result["blocked_reasons"]
    transition = next(item for item in result["asset"]["transitions"]
                      if item["semantic_action"] == "open_detail")
    assert transition["display_name"] == expected
