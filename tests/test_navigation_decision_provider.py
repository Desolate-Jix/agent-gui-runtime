from __future__ import annotations

import json
from urllib.error import URLError

import pytest

from app.agent.navigation_decision_provider import (
    OpenAICompatibleNavigationDecisionProvider,
)


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


def _context() -> dict:
    return {
        "contract_version": "navigation_reading_agent_context_v1",
        "goal": "读取新闻列表并打开相关详情。",
        "interface": {
            "interface_id": "news_list",
            "display_name": "News list",
            "surface_type": "content_collection",
        },
        "current_observation": {
            "interface_id": "news_list",
            "capture_id": "capture-1",
            "screenshot_sha256": "a" * 64,
            "trace_path": "logs/traces/capture-1.json",
        },
        "read_state": {
            "strategy": "infinite_collection",
            "status": "reading",
            "completion": "incomplete",
            "scrolls_used": 0,
            "max_scrolls": 2,
            "items_read": 5,
            "max_items": 20,
        },
        "task_progress": {
            "sequence": 2,
            "visited_interfaces": ["news_list", "news_detail", "news_list"],
            "completed_choice_ids": [
                "transition:open_selected_article",
                "transition:return_to_list",
            ],
            "last_outcome": "passed",
            "bounded_read_content_ids": [],
            "completed_read_content_ids": ["news_detail:content"],
        },
        "choices": [
            {
                "choice_id": "scroll:current_read_region",
                "decision_type": "scroll_for_more",
                "semantic_action": "scroll",
                "display_name": "Scroll current read region",
                "agent_description": "读取更多新闻。",
            },
            {
                "choice_id": "safe_stop:agent_requested_safe_stop",
                "decision_type": "safe_stop",
                "semantic_action": "safe_stop",
                "display_name": "Safe stop",
                "agent_description": "无法安全继续时停止。",
            },
        ],
        "verification_rules": [],
        "blockers": [],
        "execution_contract": {
            "historical_coordinates_forbidden": True,
            "gate_required": True,
            "final_submit_forbidden": True,
        },
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def test_provider_calls_model_with_semantic_context_only(monkeypatch) -> None:
    captured: dict = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "choice_id": "scroll:current_read_region",
                                    "reason": "当前列表尚未满足读取目标。",
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr(
        "app.agent.navigation_decision_provider.urlopen",
        fake_urlopen,
    )
    provider = OpenAICompatibleNavigationDecisionProvider(
        endpoint="http://127.0.0.1:1240/v1/chat/completions",
        model_name="Qwen3VL-8B-Instruct-Q4_K_M.gguf",
        timeout_seconds=12,
    )

    decision = provider.decide(_context())

    payload = json.loads(captured["request"].data.decode("utf-8"))
    prompt_text = payload["messages"][1]["content"]
    assert decision["choice_id"] == "scroll:current_read_region"
    assert decision["decision_source"] == "actual_model_call"
    assert decision["decision_audit"]["model_name"] == (
        "Qwen3VL-8B-Instruct-Q4_K_M.gguf"
    )
    assert decision["decision_audit"]["raw_model_output"]
    assert "bbox" not in prompt_text
    assert "click_point" not in prompt_text
    assert "historical_coordinates" not in prompt_text
    assert "Do not repeat a choice listed in completed_choice_ids" in prompt_text
    assert "Never claim a scroll budget is exhausted" in prompt_text
    prompt_context = json.loads(prompt_text.split("\n", 1)[1])
    assert prompt_context["task_progress"]["visited_interfaces"] == [
        "news_list",
        "news_detail",
        "news_list",
    ]
    assert prompt_context["task_progress"]["completed_choice_ids"] == [
        "transition:open_selected_article",
        "transition:return_to_list",
    ]
    assert captured["timeout"] == 12


def test_provider_rejects_choice_outside_current_context(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.agent.navigation_decision_provider.urlopen",
        lambda *_args, **_kwargs: _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "choice_id": "transition:unknown",
                                    "reason": "猜测。",
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            }
        ),
    )
    provider = OpenAICompatibleNavigationDecisionProvider(
        endpoint="http://127.0.0.1:1240/v1/chat/completions",
        model_name="test-model",
    )

    with pytest.raises(ValueError, match="not available"):
        provider.decide(_context())


def test_provider_surfaces_endpoint_failure_without_retrying_as_success(
    monkeypatch,
) -> None:
    calls = 0

    def fail_urlopen(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise URLError("connection refused")

    monkeypatch.setattr(
        "app.agent.navigation_decision_provider.urlopen",
        fail_urlopen,
    )
    provider = OpenAICompatibleNavigationDecisionProvider(
        endpoint="http://127.0.0.1:1240/v1/chat/completions",
        model_name="test-model",
    )

    with pytest.raises(RuntimeError, match="failed to reach Agent decision endpoint"):
        provider.decide(_context())

    assert calls == 1


def test_provider_surfaces_timeout_without_retrying_as_success(monkeypatch) -> None:
    calls = 0

    def timeout_urlopen(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise TimeoutError("model response timed out")

    monkeypatch.setattr(
        "app.agent.navigation_decision_provider.urlopen",
        timeout_urlopen,
    )
    provider = OpenAICompatibleNavigationDecisionProvider(
        endpoint="http://127.0.0.1:1240/v1/chat/completions",
        model_name="test-model",
        timeout_seconds=0.1,
    )

    with pytest.raises(RuntimeError, match="timed out"):
        provider.decide(_context())

    assert calls == 1
