"""已审核 Agent 动作的可选协商与 MCP 事实投影。"""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from io import BytesIO
from threading import Event, RLock
from types import SimpleNamespace

import pytest
from PIL import Image

from app.agent_link.contracts import AgentLinkError, MAX_LOCAL_IMAGE_RESPONSE_BYTES
from app.agent_link.mcp_bridge import _observation_mcp_result, _response_limit, _timeout_seconds
from app.agent_link.service import AgentLinkService
from app.agent_link.store import AgentLinkStore
from app.desktop_review.learning_runtime import LearningRuntimeProvider
from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinatorError


def _result(*, image: bool) -> dict:
    after = {"status": "unavailable", "reason_code": "terminal_not_committed"}
    if image:
        buffer = BytesIO()
        Image.new("RGB", (8, 6), (10, 20, 30)).save(buffer, format="PNG")
        png = buffer.getvalue()
        after = {"status": "available", "observation_id": "observation.after",
                 "capture_id": "capture.after", "screenshot": {
                     "mime_type": "image/png", "sha256": sha256(png).hexdigest(),
                     "width": 8, "height": 6,
                     "png_base64": base64.b64encode(png).decode("ascii")}}
    return {
        "contract_version": "agent_reviewed_learning_action_v1",
        "segment_id": "segment.one", "preparation_id": "preparation-one",
        "intent_id": "intent.one", "action_id": "action.one",
        "phase": "terminal" if image else "grounded_confirmation_pending",
        "claim_phase": "terminal" if image else "grounded_confirmation_pending",
        "receipt": ({"status": "available", "receipt_id": "receipt.one",
                     "content_sha256": "1" * 64, "outcome": "ACTION_RECORDED",
                     "reason_code": "none", "attempt_count": 1,
                     "dispatch_status": "dispatched", "effect_status": "not_verified",
                     "destination_status": "matched", "artifact_is_authorization": False}
                    if image else {"status": "unavailable", "reason_code": "terminal_not_committed"}),
        "after_observation": after,
        "artifact_is_authorization": False,
        "operation_dispatches_input": False,
        "execution_ready": False,
    }


def test_old_peer_does_not_advertise_optional_reviewed_action_capability(tmp_path):
    store = AgentLinkStore(tmp_path / "inbox.json")
    service = AgentLinkService(store, reviewer_token="reviewer-secret-value-123")
    connection = service.reviewer_call("reviewer-secret-value-123", "create_connection", {
        "task_id": "task-old-peer", "agent_name": "old-peer"})
    try:
        status = service.agent_call(connection["token"], "status", {})
        assert "reviewed_learning_actions" not in status
        with pytest.raises(AgentLinkError) as error:
            service.agent_call(connection["token"], "request_learning_action", {
                "segment_id": "segment.one", "preparation_id": "preparation-one",
                "intent_id": "intent.one", "action_id": "action.one"})
        assert error.value.code == "operation_forbidden"
    finally:
        store.close()


def test_reviewed_result_rejects_a_fresh_preparation():
    binding = SimpleNamespace(connection_id="connection.one", task_id="task.one",
                              segment_id="segment.one")
    provider = object.__new__(LearningRuntimeProvider)
    provider._guard = RLock()
    provider._records = {"preparation-fresh": {
        "preparation_id": "preparation-fresh", "binding": binding,
        "source_kind": "fresh_learning", "phase": "observed",
    }}
    with pytest.raises(AgentLinkError) as denied:
        provider.get_reviewed_action_result(
            connection_id="connection.one", task_id="task.one", segment_id="segment.one",
            preparation_id="preparation-fresh")
    assert denied.value.code == "not_found"


def test_reviewed_result_without_image_is_metadata_only():
    result = _observation_mcp_result(_result(image=False))
    assert len(result.content) == 1 and result.content[0].type == "text"
    assert result.structured_content["after_observation"]["status"] == "unavailable"


def test_reviewed_result_uses_existing_bounded_image_response_limit():
    assert _response_limit("get_learning_action_result") == MAX_LOCAL_IMAGE_RESPONSE_BYTES
    assert _response_limit("get_learning_runtime") == 2_500_000


def test_reviewed_request_uses_existing_long_native_review_timeout():
    assert _timeout_seconds("request_learning_action") == 180
    assert _timeout_seconds("get_learning_action_result") == 10


def test_reviewed_result_image_is_verified_and_base64_removed_from_metadata():
    result = _observation_mcp_result(_result(image=True))
    assert result.content[0].type == "image"
    assert "png_base64" not in result.structured_content["after_observation"]["screenshot"]


@pytest.mark.parametrize("damage", ["authority", "digest", "dimensions", "private"])
def test_reviewed_result_rejects_unsafe_or_corrupt_image(damage):
    value = _result(image=True)
    if damage == "authority":
        value["execution_ready"] = True
    elif damage == "digest":
        value["after_observation"]["screenshot"]["sha256"] = "0" * 64
    elif damage == "private":
        value["receipt"]["evidence"] = {"trace_refs": ["C:/Users/private/secret"]}
    else:
        value["after_observation"]["screenshot"]["width"] = 9
    with pytest.raises(RuntimeError, match="observation response is invalid"):
        _observation_mcp_result(value)


def test_cancelled_preparation_cannot_be_overwritten_by_late_review_request():
    entered, release = Event(), Event()
    binding = SimpleNamespace(connection_id="connection.one", task_id="task.one",
                              segment_id="segment.one")

    class Owner:
        def get(self, **_scope):
            return {"children": []}

    class Coordinator:
        def learning_runtime_state(self):
            return {"binding": binding, "phase": "observed", "busy": True,
                    "shutdown": False}

        def request_review(self, **_request):
            entered.set()
            assert release.wait(10)
            return {"confirmation_id": "grounded-confirmation." + "a" * 64,
                    "preview": {"observation_id": "observation.one"}}

        def cancel(self, **_request):
            return {"phase": "idle", "cleanup_verified": True}

    provider = object.__new__(LearningRuntimeProvider)
    provider.owner = Owner()
    provider._coordinator = Coordinator()
    provider._guard = RLock()
    provider._requests = {}
    provider._active = "preparation-one"
    provider._records = {"preparation-one": {
        "preparation_id": "preparation-one", "binding": binding,
        "selection": SimpleNamespace(), "phase": "observed",
        "cleanup_verified": False, "cancel_requested": False,
        "session_id": "session.one",
        "actions": [{"action_id": "action.one", "semantic_action": "open_detail",
                     "target": "state.two"}],
    }}
    scope = {"connection_id": "connection.one", "task_id": "task.one",
             "segment_id": "segment.one", "preparation_id": "preparation-one"}
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(provider.request_reviewed_action, **scope,
                              intent_id="intent.one", action_id="action.one")
        assert entered.wait(10)
        cancelled = provider.cancel(**scope)
        assert cancelled["phase"] == "cancelled" and cancelled["cleanup_verified"] is True
        provider._records["preparation-two"] = {
            "preparation_id": "preparation-two", "binding": binding,
            "selection": SimpleNamespace(), "phase": "observed",
            "cleanup_verified": False, "cancel_requested": False,
            "session_id": "session.two",
            "actions": [{"action_id": "action.two", "semantic_action": "open_detail",
                         "target": "state.three"}],
        }
        provider._active = "preparation-two"
        release.set()
        late = pending.result(timeout=10)
    assert late["phase"] == "cancelled"
    assert "confirmation_id" not in late
    assert provider._records["preparation-one"]["phase"] == "cancelled"
    assert provider._active == "preparation-two"
    assert "reviewed_action" not in provider._records["preparation-two"]


def test_invalid_fill_values_do_not_consume_preparation_identity():
    binding = SimpleNamespace(connection_id="connection.one", task_id="task.one",
                              segment_id="segment.one")

    class Owner:
        def get(self, **_scope):
            return {"children": []}

    class Coordinator:
        def request_review(self, *, text_values, **_request):
            if text_values != {"name": "valid"}:
                raise NativeSingleStepCoordinatorError(
                    "text_input_invalid", "invalid", result_unknown=False)
            return {"confirmation_id": "grounded-confirmation." + "b" * 64,
                    "preview": {"observation_id": "observation.one"}}

    provider = object.__new__(LearningRuntimeProvider)
    provider.owner = Owner()
    provider._coordinator = Coordinator()
    provider._guard = RLock()
    provider._requests = {}
    provider._active = "preparation-one"
    provider._records = {"preparation-one": {
        "preparation_id": "preparation-one", "binding": binding,
        "selection": SimpleNamespace(), "phase": "observed",
        "cleanup_verified": False, "cancel_requested": False,
        "session_id": "session.one",
        "actions": [{"action_id": "action.fill", "semantic_action": "fill_field",
                     "target": "state.two"}],
    }}
    scope = {"connection_id": "connection.one", "task_id": "task.one",
             "segment_id": "segment.one", "preparation_id": "preparation-one",
             "intent_id": "intent.one", "action_id": "action.fill"}
    with pytest.raises(AgentLinkError) as invalid:
        provider.request_reviewed_action(**scope, text_values={"wrong": "value"})
    assert invalid.value.code == "invalid_arguments"
    assert "reviewed_action" not in provider._records["preparation-one"]
    pending = provider.request_reviewed_action(**scope, text_values={"name": "valid"})
    assert pending["phase"] == "pending_review"
