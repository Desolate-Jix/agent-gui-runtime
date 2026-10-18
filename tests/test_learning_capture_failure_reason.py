"""采集失败必须保留安全原因，不能泄漏异常细节或绕过可见性检查。"""

from types import SimpleNamespace

import pytest

from app.core.screenshot import ScreenshotService
from app.agent_link.mcp_bridge import _learning_observation_tool_call
from tests.test_formal_learning_observation import _rig, _request
from tests.test_formal_fresh_learning_observation import _owner


@pytest.mark.parametrize("reason", ["capture_window_minimized", "capture_window_occluded"])
def test_capture_visibility_failure_reaches_agent_with_safe_remediation(tmp_path, monkeypatch, reason):
    import app.agent.fresh_learning_factory as factory
    from mcp.server.mcpserver.exceptions import ToolError

    manager = SimpleNamespace(validate_bound_capture_visibility=lambda **kwargs: {
        "allowed": False, "reason": reason, "private": "private-window-value"})
    screenshot = ScreenshotService(window_manager=manager)
    attempts = []

    def capture(**kwargs):
        attempts.append(kwargs)
        screenshot._require_capture_visibility(None, {})
        pytest.fail("未通过可见性校验时不能生成截图")

    with _rig(tmp_path, monkeypatch) as (host, connection, segment, _):
        monkeypatch.setattr(factory, "create_fresh_learning_observation_owner", lambda **kwargs:
            _owner(kwargs["project_root"], application=kwargs["application_identity"],
                   screenshot=SimpleNamespace(capture_window=capture)))
        host.start()
        before = host._store.read(lambda state: state)
        with pytest.raises(ToolError) as denied:
            _learning_observation_tool_call(host.status()["base_url"], connection["token"],
                "observe_learning_screen", _request(segment))
        assert reason in str(denied.value)
        assert "restore and uncover" in str(denied.value)
        assert "private-window-value" not in str(denied.value)
        assert "before retrying" in str(denied.value)
        assert len(attempts) == 1 and attempts[0]["focus_window"] is False
        assert host.facade.list_batches() == []
        assert host._store.read(lambda state: state) == before


def test_untyped_visibility_looking_message_stays_generic(tmp_path, monkeypatch):
    import app.agent.fresh_learning_factory as factory
    from mcp.server.mcpserver.exceptions import ToolError

    def capture(**kwargs):
        raise ValueError("capture_window_minimized: secret-path-value")

    with _rig(tmp_path, monkeypatch) as (host, connection, segment, _):
        monkeypatch.setattr(factory, "create_fresh_learning_observation_owner", lambda **kwargs:
            _owner(kwargs["project_root"], application=kwargs["application_identity"],
                   screenshot=SimpleNamespace(capture_window=capture)))
        host.start()
        with pytest.raises(ToolError) as denied:
            _learning_observation_tool_call(host.status()["base_url"], connection["token"],
                "observe_learning_screen", _request(segment))
        assert "observation_failed" in str(denied.value)
        assert "secret-path-value" not in str(denied.value)
        assert "capture_window_minimized" not in str(denied.value)
        assert host.facade.list_batches() == []
