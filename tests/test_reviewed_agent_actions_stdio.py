"""审核工作流 Agent 动作请求的 MCP 到本地确认纵向回归。"""

from __future__ import annotations

import asyncio
import sys
from hashlib import sha256
from io import BytesIO
from types import SimpleNamespace

from PIL import Image

from mcp import ClientSession
from mcp.client.stdio import stdio_client

from app.agent.desktop_backend import DeterministicFakeBackend
from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore
from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
from app.agent.runtime_receipt_store import RuntimeReceiptStore
from app.desktop_review.host import DesktopReviewHost
from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator
from tests.test_fresh_agent_public_sequence import _mcp_server
from tests.test_formal_graph_exact_review import TASK
from tests.test_reviewed_agent_version_pin import REVIEWER, _publish_v1, _runtime_factory
from tests.test_live_controller_grounded_preview import _ReviewGate
from tests.test_fresh_published_runtime_reuse import _FreshVersionObservations, _current
from app.agent.live_controller import ProjectedObservationCapture
from app.agent.action_learning_capture_archive import ActionLearningSessionEvidence
from app.agent.runtime_contracts import WorkflowRefV1
from app.agent.reviewed_workflow_asset import content_sha256


class _ReviewedActionGate(_ReviewGate):
    """隔离夹具接受既有执行路径传入的已核验上下文。"""

    def evaluate(self, *, selection, grounding, **_context):
        return super().evaluate(selection=selection, grounding=grounding)



class _PinnedReviewedObservations(_FreshVersionObservations):
    """隔离夹具把当前截图以真实哈希固定到现有学习归档。"""

    def bind_learning(self, binding):
        self._binding = binding
        self._images = {}

    def _capture(self, capture_id):
        color = (20, 30, 1) if self.projected_calls >= 3 else (1, 20, 30)
        image = Image.new("RGB", (1440, 900), color)
        buffer = BytesIO(); image.save(buffer, format="PNG")
        png = buffer.getvalue(); digest = sha256(png).hexdigest()
        self._images[capture_id] = (digest, png)
        return digest, png

    def read_cached_grounded_image(self, *, capture_lineage, asset_content_sha256, target_window_handle, target_process_id, **_kwargs):
        capture_id = capture_lineage["capture_id"]
        digest, png = self._images[capture_id]
        assert capture_lineage["screenshot_sha256"] == digest
        assert asset_content_sha256 == content_sha256(self.asset)
        assert target_window_handle == 4242 and target_process_id == 9001
        return png

    def capture_projected(self, *, session_id, workflow, asset, target_window_handle):
        assert target_window_handle == 4242 and asset == self.asset
        self.projected_calls += 1
        transition = asset["transitions"][0]
        state = transition["target_state_id" if self.projected_calls >= 3 else "source_state_id"]
        capture_id = f"capture-reuse-{self.projected_calls}"
        digest, png = self._capture(capture_id)
        current = _current(asset, state, capture_id)
        current["screenshot_sha256"] = digest
        self._binding.owner.capture_archive.pin_current_capture(
            runtime_session_id=session_id, capture_id=capture_id, screenshot_sha256=digest,
            viewport_size={"width": 1440, "height": 900}, asset_content_sha256=content_sha256(asset),
            target_window_handle=4242, target_process_id=9001, png_bytes=png)
        return ProjectedObservationCapture(
            session_id=session_id, workflow=WorkflowRefV1.model_validate(workflow),
            application_identity_key="web:fresh.example", asset_id=asset["asset_id"],
            asset_content_sha256=content_sha256(asset), target_window_handle=4242,
            target_process_id=9001, current_observation=current,
            agent_observation=self._project(session_id, workflow, current))


def test_reviewed_agent_action_is_confirmed_locally_and_result_is_factual(tmp_path):
    """公开 MCP 只能请求既有本地审核；模拟独立批准后才派发并可读取事实。"""
    root = tmp_path / "review"
    host = DesktopReviewHost(tmp_path / "inbox.json", root, REVIEWER)
    coordinator = None
    try:
        connection = host._service.reviewer_call(REVIEWER, "create_connection", {
            "task_id": TASK, "agent_name": "synthetic-reviewed-action-agent"})
        graph, published = _publish_v1(host, connection)
        host._service.reviewer_call(REVIEWER, "set_workflow_memory_scope", {
            "connection_id": connection["connection_id"], "expected_revision": 0,
            "workflow_ids": [graph["logical_workflow_id"]],
            "idempotency_key": "synthetic-reviewed-action-scope"})
        assets = ReviewedWorkflowAssetStore(project_root=root)
        asset = assets.load_workflow_version(graph["logical_workflow_id"], published["version_id"])["asset"]
        windows = SimpleNamespace(bound=SimpleNamespace(handle=4242, process_id=9001, is_active=True))
        windows.get_bound_window = lambda: windows.bound
        windows.bind_window_by_handle = lambda handle: windows.bound if handle == 4242 else None
        backend = DeterministicFakeBackend()
        claims = RuntimeIntentClaimStore(project_root=root, receipt_store=RuntimeReceiptStore(project_root=root))
        instances = []
        coordinator = NativeSingleStepCoordinator(
            root, host.facade, host,
            runtime_factory=_runtime_factory(root, assets, asset, windows, backend, claims, instances, _ReviewedActionGate, _PinnedReviewedObservations),
            enable_agent_learning=True, thread_initializer=lambda: None, thread_finalizer=lambda: None)
        started = host.start()

        async def run():
            async with stdio_client(_mcp_server(started["base_url"], connection["token"])) as streams:
                async with ClientSession(*streams, read_timeout_seconds=60) as client:
                    await client.initialize()
                    names = {tool.name for tool in (await client.list_tools()).tools}
                    assert {"request_learning_action", "get_learning_action_result"} <= names
                    memory = await client.call_tool("get_workflow_memory", {
                        "workflow_id": graph["logical_workflow_id"], "version": published["version_id"]})
                    segment = await client.call_tool("start_learning_segment", {
                        "idempotency_key": "synthetic-reviewed-action-segment", "title": "Synthetic reviewed action"})
                    prepared = await client.call_tool("prepare_learning_runtime", {
                        "segment_id": segment.structured_content["segment_id"],
                        "idempotency_key": "synthetic-reviewed-action-prepare",
                        "asset_id": memory.structured_content["asset_id"],
                        "asset_content_sha256": memory.structured_content["asset_sha256"],
                        "target_window_handle": 4242, "target_process_id": 9001})
                    assert prepared.is_error is False
                    preparation = prepared.structured_content
                    bad_identity = await client.call_tool("request_learning_action", {
                        "segment_id": preparation["segment_id"],
                        "preparation_id": preparation["preparation_id"],
                        "intent_id": " ",
                        "action_id": preparation["actions"][0]["action_id"]})
                    assert bad_identity.is_error is True
                    bad_text = await client.call_tool("request_learning_action", {
                        "segment_id": preparation["segment_id"],
                        "preparation_id": preparation["preparation_id"],
                        "intent_id": "intent-valid-after-invalid",
                        "action_id": preparation["actions"][0]["action_id"],
                        "text_values": {"private": "must-not-be-stored"}})
                    assert bad_text.is_error is True
                    assert backend.attempt_count == 0
                    requested = await client.call_tool("request_learning_action", {
                        "segment_id": preparation["segment_id"],
                        "preparation_id": preparation["preparation_id"],
                        "intent_id": "intent-" + "a" * 32,
                        "action_id": preparation["actions"][0]["action_id"]})
                    assert requested.is_error is False, requested
                    assert backend.attempt_count == 0
                    repeated = await client.call_tool("request_learning_action", {
                        "segment_id": preparation["segment_id"],
                        "preparation_id": preparation["preparation_id"],
                        "intent_id": "intent-" + "a" * 32,
                        "action_id": preparation["actions"][0]["action_id"]})
                    assert repeated.is_error is False
                    assert repeated.structured_content == requested.structured_content
                    pending_result = await client.call_tool("get_learning_action_result", {
                        "segment_id": preparation["segment_id"],
                        "preparation_id": preparation["preparation_id"]})
                    assert pending_result.is_error is False
                    assert pending_result.structured_content["claim_phase"] == "unknown"
                    assert pending_result.structured_content["receipt"]["status"] == "unavailable"
                    assert len(pending_result.content) == 1 and pending_result.content[0].type == "text"
                    changed = await client.call_tool("request_learning_action", {
                        "segment_id": preparation["segment_id"],
                        "preparation_id": preparation["preparation_id"],
                        "intent_id": "intent-" + "b" * 32,
                        "action_id": preparation["actions"][0]["action_id"]})
                    assert changed.is_error is True
                    changed_text = await client.call_tool("request_learning_action", {
                        "segment_id": preparation["segment_id"],
                        "preparation_id": preparation["preparation_id"],
                        "intent_id": "intent-" + "a" * 32,
                        "action_id": preparation["actions"][0]["action_id"],
                        "text_values": {"private": "must-not-leak"}})
                    assert changed_text.is_error is True
                    changed_action = await client.call_tool("request_learning_action", {
                        "segment_id": preparation["segment_id"],
                        "preparation_id": preparation["preparation_id"],
                        "intent_id": "intent-" + "a" * 32,
                        "action_id": "action.changed"})
                    assert changed_action.is_error is True
                    assert backend.attempt_count == 0
                    wrong_scope = await client.call_tool("get_learning_action_result", {
                        "segment_id": "segment.foreign",
                        "preparation_id": preparation["preparation_id"]})
                    assert wrong_scope.is_error is True
                    # 隔离夹具的独立批准，不代表真人批准。
                    native = coordinator.current_agent_review()
                    assert native["confirmation_id"] == requested.structured_content["confirmation_id"]
                    assert native["source_kind"] == "reviewed_learning"
                    coordinator.approve(confirmation_id=native["confirmation_id"],
                                        preview_content_sha256=native["preview"]["content_sha256"])
                    receipt = coordinator.execute(confirmation_id=native["confirmation_id"])
                    assert receipt["kind"] == "receipt", receipt["payload"]
                    factual = await client.call_tool("get_learning_action_result", {
                        "segment_id": preparation["segment_id"], "preparation_id": preparation["preparation_id"]})
                    assert factual.is_error is False, factual
                    public_receipt = factual.structured_content["receipt"]
                    for key in ("receipt_id", "outcome", "reason_code", "attempt_count",
                                "dispatch_status", "effect_status", "destination_status"):
                        assert public_receipt[key] == receipt["payload"][key]
                    assert public_receipt["content_sha256"] == claims.read_committed_terminal_evidence(
                        session_id=preparation["session_id"],
                        observation_id=native["preview"]["observation_id"])[1].content_sha256
                    assert not ({"workflow", "action", "evidence"} & public_receipt.keys())
                    assert factual.structured_content["claim_phase"] == "terminal"
                    assert factual.structured_content["after_observation"]["status"] == "available"
                    screenshot = factual.structured_content["after_observation"]["screenshot"]
                    assert screenshot["width"] == 1440 and screenshot["height"] == 900
                    assert "png_base64" not in screenshot
                    assert factual.content[0].type == "image"
                    assert factual.content[0].mime_type == "image/png"
                    assert all(factual.structured_content[key] is False for key in (
                        "artifact_is_authorization", "operation_dispatches_input", "execution_ready"))
                    public = str(factual.structured_content)
                    assert str(root) not in public and "text_values" not in public
                    assert "text_parameters_ref" not in public and "trace_refs" not in public
                    terminal_path = claims._terminal_path(claims._identity_hash(
                        preparation["session_id"], native["preview"]["observation_id"]))
                    marker_bytes = terminal_path.read_bytes()
                    terminal_path.write_bytes(b"{}")
                    corrupt_terminal = await client.call_tool("get_learning_action_result", {
                        "segment_id": preparation["segment_id"],
                        "preparation_id": preparation["preparation_id"]})
                    assert corrupt_terminal.is_error is False
                    assert corrupt_terminal.structured_content["claim_phase"] == "unknown"
                    assert corrupt_terminal.structured_content["receipt"]["status"] == "unavailable"
                    assert terminal_path.read_bytes() == b"{}"
                    terminal_path.write_bytes(marker_bytes)
                    original_read = host.learning_segments.capture_archive.read_session_evidence

                    def without_after_png(**kwargs):
                        evidence = original_read(**kwargs)
                        value = evidence.evidence()
                        after_digest = value["event_sources"][0]["after"]["screenshot_sha256"]
                        return ActionLearningSessionEvidence(
                            evidence_json=evidence.evidence_json,
                            png_by_sha256=tuple(
                                item for item in evidence.png_by_sha256 if item[0] != after_digest),
                        )

                    host.learning_segments.capture_archive.read_session_evidence = without_after_png
                    missing_after = await client.call_tool("get_learning_action_result", {
                        "segment_id": preparation["segment_id"],
                        "preparation_id": preparation["preparation_id"]})
                    host.learning_segments.capture_archive.read_session_evidence = original_read
                    assert missing_after.is_error is False
                    assert missing_after.structured_content["receipt"] == public_receipt
                    assert missing_after.structured_content["after_observation"] == {
                        "status": "unavailable", "reason_code": "after_image_unavailable"}
                    assert len(missing_after.content) == 1 and missing_after.content[0].type == "text"
                    assert terminal_path.is_file()
                    terminal_path.unlink()
                    for _ in range(2):
                        missing_terminal = await client.call_tool("get_learning_action_result", {
                            "segment_id": preparation["segment_id"],
                            "preparation_id": preparation["preparation_id"]})
                        assert missing_terminal.is_error is False
                        assert missing_terminal.structured_content["claim_phase"] == "unknown"
                        assert missing_terminal.structured_content["receipt"] == {
                            "status": "unavailable", "reason_code": "terminal_evidence_unavailable"}
                        assert missing_terminal.structured_content["after_observation"] == {
                            "status": "unknown", "reason_code": "terminal_evidence_unavailable"}
                        assert not terminal_path.exists()
                    assert backend.attempt_count == 1
                    cancelled = await client.call_tool("cancel_learning_runtime", {
                        "segment_id": preparation["segment_id"], "preparation_id": preparation["preparation_id"]})
                    assert cancelled.is_error is False and cancelled.structured_content["cleanup_verified"] is True
                    assert cancelled.structured_content["phase"] == "cancelled"
                    assert coordinator.learning_runtime_state()["phase"] == "idle"
                    assert coordinator._runtime is None and coordinator._attached is False
                    assert host.status()["contract_version"] == "native_review_host_v1"
                    assert host._single_step_controller.attachment_snapshot() is None
                    assert host._runtime_cleanup_confirmation_id is None
                    assert host._runtime_cleanup_work is None and host.single_step is None
                    host._service.reviewer_call(REVIEWER, "revoke_connection", {
                        "connection_id": connection["connection_id"],
                        "idempotency_key": "revoke-reviewed-action"})
                    revoked = await client.call_tool("get_learning_action_result", {
                        "segment_id": preparation["segment_id"],
                        "preparation_id": preparation["preparation_id"]})
                    assert revoked.is_error is True
                    return preparation, requested.structured_content

        preparation, requested = asyncio.run(asyncio.wait_for(run(), timeout=120))
        assert preparation["phase"] == "observed"
        assert requested["phase"] == "pending_review"
        assert backend.attempt_count == 1
    finally:
        if coordinator is not None:
            primary = sys.exc_info()[0] is not None
            try:
                coordinator.shutdown()
            except Exception:
                if not primary:
                    raise
        else:
            host.close()
