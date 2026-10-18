"""合成样例须隔离、明确来源，不能把测试通过当成真实历史恢复。"""
import pytest
from tests.runtime_path_graph_fixture_support import runtime_graph_fixture


@pytest.mark.parametrize("name", ["github_issues", "python_docs_search", "table_directory"])
def test_fixture_is_synthetic_non_authorizing_and_independent(name, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    first = runtime_graph_fixture(name)
    assert first["fixture_provenance"] == "synthetic_unit_test_only"
    assert first["artifact_is_authorization"] is False
    assert first["execute_binding_enabled"] is False
    first["action_templates"].clear()
    assert runtime_graph_fixture(name)["action_templates"]
    assert list(tmp_path.iterdir()) == []


def test_unknown_fixture_is_rejected_without_historical_fallback():
    with pytest.raises(ValueError, match="Unknown synthetic"):
        runtime_graph_fixture("old-history")
