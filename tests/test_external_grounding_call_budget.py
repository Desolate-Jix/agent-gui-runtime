"""单次只读定位预算不改变共享客户端配置。"""
import math
import httpx
import pytest
from tests.test_external_grounding_api import capture, profile, reply
from app.vision.external_grounding_api import ChatCompletionsGrounder, ApiGroundingError


def test_call_budget_caps_http_and_preserves_profile(capture, monkeypatch):
    monkeypatch.setenv("TEST_VISION_KEY", "test-key")
    seen = []
    def handler(request):
        seen.append(request.extensions["timeout"]["read"])
        return httpx.Response(200, json=reply())
    with ChatCompletionsGrounder(profile(timeout_seconds=30.0), transport=httpx.MockTransport(handler)) as g:
        g.ground(request_id="request-1", capture=capture, goal="player", timeout_seconds=1.25)
        assert g.profile.timeout_seconds == 30.0
    assert 0 < seen[0] <= 1.25


@pytest.mark.parametrize("budget", [0, -1, True, math.nan, math.inf, "1"])
def test_invalid_call_budget_rejected(capture, monkeypatch, budget):
    monkeypatch.setenv("TEST_VISION_KEY", "test-key")
    with ChatCompletionsGrounder(profile(), transport=httpx.MockTransport(lambda _: pytest.fail("network"))) as g:
        with pytest.raises(ApiGroundingError, match="api_timeout_invalid"):
            g.ground(request_id="request-1", capture=capture, goal="player", timeout_seconds=budget)
