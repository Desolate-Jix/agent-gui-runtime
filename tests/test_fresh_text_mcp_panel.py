"""真实本地 MCP 到原生填写预览；只替换截图、识别及系统字段边界。"""

import asyncio
from contextlib import contextmanager
from copy import deepcopy
import json
from types import SimpleNamespace

from mcp import ClientSession
from mcp.client.stdio import stdio_client
import pytest

from app.desktop_review.fresh_runtime_callsite import FreshLearningRuntimeCallsite
from app.desktop_review.grounded_preview_widget import GroundedPreviewWidget
from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator
from app.desktop_review.window import ensure_application
from tests.test_formal_fresh_graph_source import _stage
from tests.test_formal_fresh_runtime_session import _runtime
from tests.test_formal_learning_runtime_controls import _mcp_server
from tests.test_fresh_text_preview import _native_owner, _parameters
from tests.text_field_fixture_support import SyntheticTextFieldReader


@contextmanager
def _native_text_rig(root, *, synthetic_input=False):
    initial_owner = _native_owner(root / "capture")
    packet = initial_owner.observe(target_window_handle=4242, target_process_id=9001)
    host, connection, segment, _packet, _args, staged = _stage(root, packet)
    project_root = host.fresh_learning.archive.project_root
    bound = SimpleNamespace(handle=4242, process_id=9001, is_active=True)
    windows = SimpleNamespace(get_bound_window=lambda: bound,
        bind_window_by_handle=lambda handle: bound if handle == 4242 else None)
    instances = []

    def factory(*, project_root, selection, window_manager, learning_binding):
        owner = _native_owner(project_root)
        owner._text_field_reader = SyntheticTextFieldReader()
        runtime, backend, claims, source = _runtime(host, connection, segment, staged,
            observation_owner=owner, source=selection.source)
        runtime.set_action_learning_recorder(host.learning_segments.recorder)
        if synthetic_input:
            from app.agent.desktop_backend import ExistingWindowsBackendAdapter
            from tests.test_fresh_text_dispatch import _Input
            from tests.test_fresh_dispatch_graph import _Visible

            backend = _Input(owner._text_field_reader)
            runtime._backend = ExistingWindowsBackendAdapter(input_controller=backend,
                window_manager=owner._window_manager, post_dispatch_settle_seconds=0)
            runtime._window_visibility_checker = _Visible()
        callsite = FreshLearningRuntimeCallsite(controller=runtime, learning_binding=learning_binding)
        instances.append((runtime, owner, backend, claims))
        return callsite

    factory.window_manager = windows
    coordinator = NativeSingleStepCoordinator(project_root, host.facade, host, runtime_factory=factory,
        enable_agent_learning=True, thread_initializer=lambda: None, thread_finalizer=lambda: None)
    try:
        host.start()
        yield host, coordinator, connection, segment, staged, instances
    finally:
        coordinator.shutdown()
        host.close()


@pytest.mark.parametrize("kind", ["literal", "variable"])
def test_fresh_mcp_text_reaches_native_preview_and_cancels_without_input(tmp_path, kind):
    application = ensure_application()
    assert application.platformName() == "offscreen"
    parameters = _parameters(kind)
    with _native_text_rig(tmp_path) as (host, coordinator, connection, segment, staged, instances):
        async def check():
            async with stdio_client(_mcp_server(host.status()["base_url"], connection["token"])) as streams:
                async with ClientSession(*streams, read_timeout_seconds=60) as client:
                    await client.initialize()
                    prepared = await client.call_tool("prepare_fresh_learning_runtime", {
                        "segment_id": segment["segment_id"], "batch_id": staged["batch_id"],
                        "idempotency_key": "fresh-text-mcp-" + kind})
                    assert not prepared.is_error, prepared
                    assert prepared.structured_content["phase"] == "observed"
                    scope = {"segment_id": segment["segment_id"],
                        "preparation_id": prepared.structured_content["preparation_id"]}
                    arguments = {**scope, "intent_id": "intent.text", "action_id": "action.fill",
                        "semantic_action": "fill_field", "goal": "Fill the search field",
                        "text_parameters": parameters.reviewed.to_payload()}
                    if kind == "variable":
                        arguments["text_values"] = {parameters.reviewed.content.value: parameters.text}
                    pending = await client.call_tool("request_fresh_learning_action", arguments)
                    assert not pending.is_error, pending
                    assert pending.structured_content["phase"] == "pending_review"
                    assert len(instances) == 1
                    runtime, owner, backend, claims = instances[0]
                    view = coordinator.current_fresh_review()
                    assert view["confirmation_id"] == pending.structured_content["confirmation_id"]
                    assert view["text_input_local"] == parameters
                    assert view["text_field_local"].before.value == owner._text_field_reader.value
                    assert view["text_field_local"].expected_value == parameters.text
                    exposed = json.dumps(pending.structured_content, ensure_ascii=False)
                    assert parameters.text not in exposed and owner._text_field_reader.value not in exposed
                    assert "text_input_local" not in exposed and "text_field_local" not in exposed
                    widget = GroundedPreviewWidget()
                    try:
                        widget.resize(1000, 760)
                        widget.set_review(view)
                        widget.show()
                        application.processEvents()
                        assert widget.text_value_editor.toPlainText() == parameters.text
                        assert widget.text_before_editor.toPlainText() == owner._text_field_reader.value
                        assert widget.text_expected_editor.toPlainText() == parameters.text
                        assert widget.text_value_editor.isReadOnly()
                        assert widget.grab().save(str(tmp_path / ("mcp-text-panel-" + kind + ".png")))
                    finally:
                        widget.close()
                    captures = len(owner._screenshot_service.calls)
                    repeated = await client.call_tool("request_fresh_learning_action", arguments)
                    assert not repeated.is_error, repeated
                    assert repeated.structured_content["confirmation_id"] == view["confirmation_id"]
                    assert len(owner._screenshot_service.calls) == captures
                    changed = deepcopy(arguments)
                    if kind == "variable":
                        changed["text_values"][parameters.reviewed.content.value] = "other value"
                    else:
                        changed["text_parameters"]["content"]["text"] = "other value"
                    conflict = await client.call_tool("request_fresh_learning_action", changed)
                    assert conflict.is_error
                    assert len(owner._screenshot_service.calls) == captures
                    assert coordinator.current_fresh_review()["text_input_local"] == parameters
                    assert backend.commands == []
                    assert list(claims.dispatch_started_root.glob("*.json")) == []
                    cancelled = await client.call_tool("cancel_fresh_learning_runtime", scope)
                    assert not cancelled.is_error, cancelled
                    assert cancelled.structured_content["cleanup_verified"] is True
                    assert cancelled.structured_content["claim_phase"] == "grounded_confirmation_closed"
                    repeated_cancel = await client.call_tool("cancel_fresh_learning_runtime", scope)
                    assert not repeated_cancel.is_error, repeated_cancel
                    assert repeated_cancel.structured_content["claim_phase"] == "grounded_confirmation_closed"
                    assert backend.commands == [] and not runtime._sessions
        asyncio.run(asyncio.wait_for(check(), timeout=120))


@pytest.mark.parametrize("kind", ["literal", "variable"])
def test_public_text_confirmation_and_factual_receipt_use_existing_backend_once(tmp_path, kind):
    parameters = _parameters(kind)
    with _native_text_rig(tmp_path, synthetic_input=True) as (host, coordinator, connection, segment, staged, instances):
        async def check():
            async with stdio_client(_mcp_server(host.status()["base_url"], connection["token"])) as streams:
                async with ClientSession(*streams, read_timeout_seconds=60) as client:
                    await client.initialize()
                    prepared = await client.call_tool("prepare_fresh_learning_runtime", {
                        "segment_id": segment["segment_id"], "batch_id": staged["batch_id"],
                        "idempotency_key": "public-fill-" + kind})
                    assert not prepared.is_error, prepared
                    scope = {"segment_id": segment["segment_id"],
                        "preparation_id": prepared.structured_content["preparation_id"]}
                    request = {**scope, "intent_id": "intent.fill", "action_id": "action.fill",
                        "semantic_action": "fill_field", "goal": "Fill the search field",
                        "text_parameters": parameters.reviewed.to_payload()}
                    if kind == "variable":
                        request["text_values"] = {parameters.reviewed.content.value: parameters.text}
                    pending = await client.call_tool("request_fresh_learning_action", request)
                    assert not pending.is_error, pending
                    view = coordinator.current_fresh_review()
                    assert view["text_input_local"] == parameters
                    native_input = instances[0][2]
                    assert native_input.calls == []
                    coordinator.approve(confirmation_id=view["confirmation_id"],
                        preview_content_sha256=view["preview"]["preview_sha256"])
                    assert native_input.calls == []
                    executed = coordinator.execute(confirmation_id=view["confirmation_id"])
                    assert executed["kind"] == "receipt", executed
                    receipt = executed["payload"]
                    assert receipt["effect_status"] == "verified"
                    assert receipt["outcome"] == "ACTION_RECORDED"
                    repeated = await client.call_tool("request_fresh_learning_action", request)
                    assert not repeated.is_error, repeated
                    assert repeated.structured_content["receipt"] == receipt
                    factual = await client.call_tool("get_fresh_learning_runtime", scope)
                    assert not factual.is_error, factual
                    value = factual.structured_content
                    assert value["receipt"] == receipt
                    assert value["observation"]["capture"]["capture_id"] == receipt["evidence"]["text_field_verification"]["actual"]["capture_id"]
                    assert parameters.text not in json.dumps(value, ensure_ascii=False)
                    assert len(native_input.calls) == 1
                    cancelled = await client.call_tool("cancel_fresh_learning_runtime", scope)
                    assert not cancelled.is_error, cancelled
                    assert cancelled.structured_content["cleanup_verified"] is True
                    assert cancelled.structured_content["receipt"] == receipt
                    assert len(native_input.calls) == 1
        asyncio.run(asyncio.wait_for(check(), timeout=120))
