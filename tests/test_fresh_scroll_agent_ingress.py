"""Fresh Agent Link 滚动参数只进入不可变意图，不产生执行权限。"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json

from mcp import ClientSession
from mcp.client.stdio import stdio_client
import pytest

from app.agent.fresh_learning_action_contracts import (
    FreshLearningActionContractError,
    FreshLearningIntent,
    canonical_json_bytes,
)
from app.agent.scroll_parameters import ReviewedScrollParameters
from tests.test_formal_learning_runtime_controls import _mcp_server
from tests.test_fresh_agent_stdio import _rig


PARAMETERS = ReviewedScrollParameters(
    target_container_id="results-pane",
    axis="vertical",
    direction="down",
    wheel_clicks=3,
    unit="wheel_detent",
).to_payload()


def _intent(**changes):
    value = {
        "contract_version": "fresh_learning_action_intent_v1",
        "intent_id": "intent.scroll",
        "session_id": "session.scroll",
        "observation_id": "observation.scroll",
        "source_sha256": "a" * 64,
        "action_id": "action.scroll",
        "semantic_action": "scroll_region",
        "goal": "Scroll the current results pane",
        "scroll_parameters": deepcopy(PARAMETERS),
    }
    value.update(changes)
    return value


def test_fresh_scroll_intent_round_trip_is_immutable_and_semantic_specific():
    source = _intent()
    intent = FreshLearningIntent.from_dict(source)
    source["scroll_parameters"]["wheel_clicks"] = 20

    assert intent.scroll_parameters == PARAMETERS
    assert intent.to_dict() == _intent()
    returned = intent.scroll_parameters
    returned["wheel_clicks"] = 1
    assert intent.scroll_parameters == PARAMETERS

    direct = FreshLearningIntent(
        "intent.scroll", "session.scroll", "observation.scroll", "a" * 64,
        "action.scroll", "scroll_region", "Scroll the current results pane",
        None, None, canonical_json_bytes(PARAMETERS),
    )
    assert direct.scroll_parameters == PARAMETERS

    with pytest.raises(FreshLearningActionContractError):
        FreshLearningIntent.from_dict({key: value for key, value in _intent().items()
                                       if key != "scroll_parameters"})
    with pytest.raises(FreshLearningActionContractError):
        FreshLearningIntent.from_dict(_intent(semantic_action="open_detail"))
    with pytest.raises(FreshLearningActionContractError):
        FreshLearningIntent(
            "intent.open", "session.scroll", "observation.scroll", "a" * 64,
            "action.open", "open_detail", "Open current result",
            None, None, canonical_json_bytes(PARAMETERS),
        )


def test_fresh_scroll_real_stdio_reaches_one_frozen_intent_without_input(tmp_path, monkeypatch):
    with _rig(tmp_path) as (host, coordinator, connection, segment, staged, instances):
        captured = []

        def accept_review(**arguments):
            captured.append({"intent": deepcopy(arguments["intent"])})
            return {"confirmation_id": "confirmation-scroll"}

        monkeypatch.setattr(coordinator, "request_fresh_review", accept_review)

        async def check():
            async with stdio_client(_mcp_server(host.status()["base_url"], connection["token"])) as streams:
                async with ClientSession(*streams, read_timeout_seconds=60) as client:
                    await client.initialize()
                    tools = {item.name: item for item in (await client.list_tools()).tools}
                    schema = tools["request_fresh_learning_action"].input_schema
                    assert "scroll_parameters" in schema["properties"]
                    serialized_schema = json.dumps(schema, sort_keys=True)
                    assert all(value in serialized_schema for value in (
                        "reviewed_scroll_parameters_v1", "target_container_id", "axis",
                        "direction", "wheel_clicks", "unit",
                    ))

                    prepared = await client.call_tool("prepare_fresh_learning_runtime", {
                        "segment_id": segment["segment_id"], "batch_id": staged["batch_id"],
                        "idempotency_key": "prepare.scroll-ingress",
                    })
                    assert not prepared.is_error, prepared
                    provider = host._service._learning_runtime_provider
                    monkeypatch.setattr(provider, "get_fresh", lambda **scope: {
                        "contract_version": "agent_fresh_learning_runtime_v1",
                        "preparation_id": scope["preparation_id"],
                        "phase": "pending_review",
                        "cleanup_verified": False,
                        "artifact_is_authorization": False,
                        "operation_dispatches_input": False,
                        "execution_ready": False,
                    })
                    scope = {"segment_id": segment["segment_id"],
                             "preparation_id": prepared.structured_content["preparation_id"]}
                    request = {**scope, "intent_id": "intent.scroll", "action_id": "action.scroll",
                               "semantic_action": "scroll_region", "goal": "Scroll current results",
                               "scroll_parameters": deepcopy(PARAMETERS)}
                    pending = await client.call_tool("request_fresh_learning_action", request)
                    assert not pending.is_error, (pending, captured)
                    assert len(captured) == 1
                    assert captured[0]["intent"]["scroll_parameters"] == PARAMETERS
                    assert instances[0][2].commands == []

                    repeated = await client.call_tool("request_fresh_learning_action", request)
                    assert not repeated.is_error and len(captured) == 1
                    changed = deepcopy(request)
                    changed["scroll_parameters"]["wheel_clicks"] = 4
                    conflict = await client.call_tool("request_fresh_learning_action", changed)
                    assert conflict.is_error and len(captured) == 1

                    missing = {key: value for key, value in request.items() if key != "scroll_parameters"}
                    assert (await client.call_tool("request_fresh_learning_action", missing)).is_error
                    extra = {**request, "semantic_action": "open_detail"}
                    assert (await client.call_tool("request_fresh_learning_action", extra)).is_error
                    assert instances[0][2].commands == []

        asyncio.run(asyncio.wait_for(check(), timeout=120))
