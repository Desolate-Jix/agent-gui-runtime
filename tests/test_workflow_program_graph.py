import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from app.learning_memory.program_graph import project_program_graph
from app.learning_memory.program_graph_widget import ProgramGraphWidget


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def definition():
    return {"title": "查询记录", "inputs": [], "outputs": [], "steps": [
        {"step_id": "find", "title": "查找", "branches": {"success": "open", "failure": "recover", "uncertain": None}},
        {"step_id": "read", "title": "读取", "branches": {"success": None, "failure": None, "uncertain": None}},
        {"step_id": "recover", "title": "恢复", "branches": {"success": None, "failure": None, "uncertain": None}},
        {"step_id": "open", "title": "打开", "branches": {"success": "read", "failure": None, "uncertain": None}},
    ]}


def test_projection_uses_only_explicit_branches_and_step_ids():
    source = definition()
    graph = project_program_graph(source)["graph"]
    assert [node["source_step_id"] for node in graph["nodes"]] == ["find", "read", "recover", "open"]
    assert {(edge["source_node_id"], edge["target_node_id"], edge["branch"]) for edge in graph["edges"]} == {
        ("find", "open", "success"), ("find", "recover", "failure"), ("open", "read", "success")}
    assert graph["display_only"] is True
    assert graph["artifact_is_authorization"] is False
    assert graph["execute_binding_enabled"] is False
    assert "screenshot" not in str(graph)
    assert source == definition()


def test_projection_rejects_dangling_duplicate_and_uncertain_branch():
    source = definition()
    source["steps"][0]["branches"]["success"] = "missing"
    with pytest.raises(ValueError, match="target"):
        project_program_graph(source)
    source = definition()
    source["steps"][1]["step_id"] = "find"
    with pytest.raises(ValueError, match="duplicate"):
        project_program_graph(source)
    source = definition()
    source["steps"][0]["branches"]["uncertain"] = "read"
    with pytest.raises(ValueError, match="uncertain"):
        project_program_graph(source)
    source = definition()
    source["steps"][0]["branches"]["failure"] = ["read"]
    with pytest.raises(ValueError, match="target"):
        project_program_graph(source)


def test_offscreen_graph_renders_and_click_signal_is_source_step_id(app):
    widget = ProgramGraphWidget()
    selected = []
    widget.nodeSelected.connect(selected.append)
    widget.resize(850, 550)
    widget.set_program_graph(definition())
    widget.show()
    app.processEvents()
    assert len(widget._node_items) == 4
    assert len(widget._edge_items) == 3
    assert widget.grab().width() == 850
    assert widget._node_items["find"]._type_text.text() == "步骤"
    widget._node_items["open"].setSelected(True)
    app.processEvents()
    assert selected == ["open"]
    widget.close()
