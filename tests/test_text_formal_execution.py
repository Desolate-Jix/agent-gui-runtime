"""正式保存资产到唯一输入及持久回读链；只替换 Windows/识别边界。"""
from copy import deepcopy
import json
from hashlib import sha256
from types import SimpleNamespace

import pytest

from app.agent.desktop_backend import DeterministicFakeBackend, ExistingWindowsBackendAdapter
from app.agent.live_controller import LiveController
from app.agent.live_runtime_composition import ExistingWindowsCurrentEvidenceAdapter
from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore, content_sha256
from app.agent.reviewed_workflow_gate import ReviewedWorkflowGateAdapter
from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore, RuntimeIntentClaimStoreError
from app.agent.runtime_receipt_store import RuntimeReceiptStore
from app.agent.runtime_session_selection import RuntimeSessionSelection
from app.agent.text_parameters import resolve_text_parameters
from app.api.agent_runtime import AgentRuntimeIntentRequest, LocalAgentRuntimeCallsite
from app.core import clipboard_transaction as clipboard_module
from app.core import input_controller as input_module
from app.core.input_controller import InputController, VK_A, VK_CONTROL, VK_RETURN, VK_V
from app.core.runtime_input_authority import runtime_backend_input_is_active
from app.desktop_review.workspace import NativeReviewFacade
from tests.test_clipboard_transaction import FakeWin32Api, build_windows_backend
from tests.test_desktop_exact_review import _batch, _new_runtime, _complete, _record_dir, _load
from tests.test_live_controller_w4 import _WindowVisibilityChecker
from tests.test_live_runtime_composition_w3b import _bound, _ScreenshotService, _RecognitionRunner, _recognition, _UIAProvider
from tests.test_native_current_evidence import _NativeIdentityReader
from tests.test_native_text_saved_workflow import _SYNTHETIC_NATIVE_BINDING
from tests.test_text_input_transaction_roundtrip import unicode_bytes, logical_text, assert_restored
from tests.text_field_fixture_support import SyntheticTextFieldReader


class StableScreenshotService(_ScreenshotService):
    def capture_window(self, **kwargs):
        result = super().capture_window(**kwargs)
        # 审核与确认期间合成界面保持不变，采集身份仍每次前进。
        self.paths[-1].write_bytes(self.paths[0].read_bytes())
        return result


def _coherent_text_entry_payloads(asset: dict) -> dict[str, dict]:
    state = next(item for item in asset["states"] if item["state_id"] == asset["entry_state_id"])
    interface_anchor = next(item for item in state["identity_anchors"] if not item.get("text_field_id"))
    field_anchor = next(item for item in state["identity_anchors"] if item.get("text_field_id") == "open")
    return {
        interface_anchor["label"]: _recognition(
            interface_anchor["label"], role="text", candidate_id="candidate-reviewed-interface",
            element_id="current-reviewed-interface",
        ),
        field_anchor["label"]: _recognition(
            field_anchor["label"], role="input", candidate_id="candidate-reviewed-text-field",
            element_id="current-reviewed-text-field",
        ),
    }


@pytest.fixture
def formal_text(tmp_path, monkeypatch):
    resources = []

    def build(*, variable=False, clear=True, wrong_value=False, focus_drift=False,
              region_occluded_at=None, start=True):
        text = "本次中文\r\nB"
        batch = _batch(action_type="fill_field")
        batch["interfaces"][0]["recognition_text"] = "Synthetic editor surface"
        batch["steps"][0]["text_parameters"] = {
            "contract_version": "reviewed_text_parameters_v1", "target_field_id": "open",
            "content": {"kind": "variable", "name": "query"} if variable else {"kind": "literal", "text": text},
            "clear_existing": clear, "sensitive": False, "submit": False, "clipboard_policy": "restore_previous",
        }
        store, inbox, facade, saved = _new_runtime(tmp_path, batch)
        facade.close()
        facade = NativeReviewFacade(inbox, "exact-review-token", tmp_path / "root")
        compiled = _complete(facade, facade.prepare_exact_review(
            "task", "exact-review-batch", saved["revision"], deepcopy(_SYNTHETIC_NATIVE_BINDING)))
        asset = _load(_record_dir(tmp_path / "root") / f"receipt-{compiled['compile_receipt_id']}.json")["asset"]
        facade.publish_exact_review(compiled["compile_receipt_id"])
        bound = _bound()
        bound.is_active, bound.title, bound.process_name = True, "Synthetic Notepad", "editor.exe"
        state = SimpleNamespace(cursor=(0, 0), foreground=999, keys=set(), pasted=[], mouse=[],
                                region_checks=[], fault=wrong_value)
        reader = SyntheticTextFieldReader(value="ABCD", selection=(1, 3))
        original_read = reader.read_field

        def read(**request):
            if request.get("require_keyboard_focus"):
                assert state.foreground == bound.handle
            return original_read(**request)

        reader.read_field = read

        def region_visibility(*, bound, bbox):
            # 合成区域仍须绑定本次窗口及最近字段几何，不能用点可见性代替。
            assert bound is windows.get_bound_window()
            assert reader.calls[-1]["target_window_handle"] == bound.handle
            assert bbox == reader.calls[-1]["target_bbox"]
            state.region_checks.append({"window_handle": bound.handle, "bbox": tuple(bbox)})
            return {"allowed": len(state.region_checks) != region_occluded_at}

        windows = SimpleNamespace(get_bound_window=lambda: bound, list_visible_windows=lambda: [vars(bound)],
            bind_window_by_handle=lambda handle: bound, validate_bound_point_visibility=lambda **kw: {"allowed": True},
            validate_bound_region_visibility=region_visibility)
        captures = tmp_path / "captures"
        captures.mkdir()
        adapter = ExistingWindowsCurrentEvidenceAdapter(project_root=tmp_path / "root",
            application_identity_key="native:editor.exe:notepad", screenshot_service=StableScreenshotService(captures),
            window_manager=windows, native_identity_reader=_NativeIdentityReader(executable_path=r"d:\synthetic\editor.exe"),
            recognition_runner=_RecognitionRunner(_coherent_text_entry_payloads(asset)), uia_provider=_UIAProvider(), text_field_reader=reader)
        original = {clipboard_module.CF_UNICODETEXT: unicode_bytes("original"), clipboard_module.CF_DIB: b"original-dib"}
        api = FakeWin32Api(original)
        clipboard = build_windows_backend(api)
        input_controller = InputController()

        def focus(handle):
            state.foreground = handle
            if focus_drift:
                reader.selection = (0, 0)

        def send_key(key, *, key_up):
            assert runtime_backend_input_is_active()
            assert key != VK_RETURN
            if key_up:
                state.keys.discard(key)
                return
            state.keys.add(key)
            if key in (VK_A, VK_V):
                assert VK_CONTROL in state.keys
            if key == VK_A:
                reader.selection = (0, len(reader.value))
            if key == VK_V:
                value = logical_text(api.current_bytes(clipboard_module.CF_UNICODETEXT))
                state.pasted.append(value)
                start, end = reader.selection
                reader.value = ("A" + value) if state.fault else reader.value[:start] + value + reader.value[end:]
                reader.selection = (start + len(value), start + len(value))

        monkeypatch.setattr(clipboard_module, "WindowsClipboardBackend", lambda: clipboard)
        monkeypatch.setattr(input_module, "window_manager", windows)
        monkeypatch.setattr(input_module, "WINDOWS_INPUT_AVAILABLE", True)
        monkeypatch.setattr(input_module, "win32gui", SimpleNamespace(SetForegroundWindow=focus, GetForegroundWindow=lambda: state.foreground))
        monkeypatch.setattr(input_module, "win32api", SimpleNamespace(GetCursorPos=lambda: state.cursor))
        monkeypatch.setattr(input_controller, "_send_move", lambda x, y: setattr(state, "cursor", (x, y)))
        monkeypatch.setattr(input_controller, "_send_mouse_flags", lambda flags: state.mouse.append(flags))
        monkeypatch.setattr(input_controller, "_send_key", send_key)
        monkeypatch.setattr(input_module.time, "sleep", lambda seconds: None)
        backend = ExistingWindowsBackendAdapter(input_controller=input_controller, window_manager=windows)
        assets = ReviewedWorkflowAssetStore(project_root=tmp_path / "root")
        receipts = RuntimeReceiptStore(project_root=tmp_path)
        claims = RuntimeIntentClaimStore(project_root=tmp_path, receipt_store=receipts)
        controllers = []

        def controller_factory(binding):
            controller = LiveController(binding=binding, asset_loader=assets, observation_source=adapter,
                target_resolver=adapter, gate=ReviewedWorkflowGateAdapter(), backend=backend,
                window_visibility_checker=_WindowVisibilityChecker(bound_window_handle=4242), intent_claim_store=claims,
                grounding_policy={"minimum_confidence": 0.9, "minimum_score_margin": 0.2})
            controllers.append(controller)
            return controller

        service = LocalAgentRuntimeCallsite(project_root=tmp_path, asset_store=assets, claim_store=claims,
            window_manager=windows, controller_factory=controller_factory,
            selection=RuntimeSessionSelection(asset["asset_id"], content_sha256(asset), 4242, 9001))
        request = resolved = None
        if start:
            observation = service.start_session()
            action = next(action for action in observation.available_actions if action.semantic_action == "fill_field")
            request = AgentRuntimeIntentRequest(intent_id="fill-once", session_id=observation.session_id,
                observation_id=observation.observation_id, action_id=action.action_id)
            parameters = service.get_local_reviewed_text_parameters(action_id=action.action_id)
            resolved = resolve_text_parameters(parameters, {"query": text} if variable else {})
        resources.append((store, facade, service, controllers))
        return SimpleNamespace(service=service, request=request, claims=claims, receipts=receipts, state=state,
            reader=reader, api=api, original=original, resolved=resolved, root=tmp_path, asset=asset,
            windows=windows, facade=facade, expected_text=text, controllers=controllers,
            controller_factory=controller_factory, assets=assets, adapter=adapter)

    yield build
    for store, facade, service, controllers in resources:
        for controller in controllers:
            for session_id in list(controller._sessions):
                if session_id in controller._grounded_publications:
                    service.cancel_grounded_review(session_id=session_id)
                else:
                    controller.abandon_session(session_id=session_id)
        facade.close()
        store.close()


def approve(fixture):
    claim = fixture.service.request_grounded_confirmation(fixture.request, text_input=fixture.resolved)
    cid = claim.grounded_confirmation.confirmation_id
    assert fixture.state.pasted == []
    assert fixture.service.decide_grounded_confirmation(confirmation_id=cid, decision="approved").phase == "grounded_confirmation_approved"
    assert fixture.state.pasted == []
    return cid


@pytest.mark.parametrize(("variable", "clear"), [(False, True), (True, False)])
def test_formal_fill_frozen_preview_to_input_readback_and_receipt(formal_text, variable, clear):
    f = formal_text(variable=variable, clear=clear)
    cid = approve(f)
    expected = f.resolved.text if clear else "A" + f.resolved.text + "D"
    receipt = f.service.consume_grounded_confirmation(confirmation_id=cid)
    assert getattr(receipt, "outcome", None) == "VERIFIED", receipt
    assert f.reader.value == expected
    assert f.state.pasted == [f.resolved.text]
    assert len(f.state.mouse) == (2 if clear else 0)
    assert f.state.keys == set()
    assert len(f.state.region_checks) == 2
    assert f.state.region_checks[0] == f.state.region_checks[1]
    assert_restored(f.api, f.original)
    assert f.service.consume_grounded_confirmation(confirmation_id=cid) == receipt
    assert f.state.pasted == [f.resolved.text]
    terminal = f.claims.get_for_grounded_confirmation(confirmation_id=cid)
    assert terminal.phase == "terminal"
    assert f.claims.load_terminal_receipt(session_id=f.request.session_id, observation_id=f.request.observation_id) == receipt
    stored = f.receipts.get(terminal.terminal_receipt_ref)
    proof = stored.verification_evidence["text_field_verification"]
    assert proof["status"] == "verified"
    assert proof["actual"]["value_sha256"] == sha256(expected.encode("utf-8")).hexdigest()
    assert proof["expected"] == terminal.verification_checkpoint.text_field_expectation
    assert proof["expected"] == terminal.grounded_consume.fresh_preview.to_dict()["text_field_expectation_ref"]
    assert proof["actual"]["capture_id"] != proof["expected"]["before"]["capture_id"]
    assert json.dumps(f.resolved.text, ensure_ascii=False) not in json.dumps(stored.verification_evidence, ensure_ascii=False)
    assert "ABCD" not in json.dumps(stored.verification_evidence)


def test_formal_fill_wrong_actual_value_is_failure_not_success(formal_text):
    f = formal_text(wrong_value=True)
    cid = approve(f)
    receipt = f.service.consume_grounded_confirmation(confirmation_id=cid)
    assert getattr(receipt, "outcome", None) == "VERIFICATION_FAILED", receipt
    assert receipt.reason_code == "text_value_mismatch"
    assert f.reader.value == "A" + f.resolved.text
    assert f.state.pasted == [f.resolved.text]
    assert f.service.consume_grounded_confirmation(confirmation_id=cid) == receipt
    assert len(f.state.pasted) == 1


def test_formal_insert_selection_drift_after_focus_does_not_paste(formal_text):
    f = formal_text(variable=True, clear=False, focus_drift=True)
    cid = approve(f)
    receipt = f.service.consume_grounded_confirmation(confirmation_id=cid)
    assert getattr(receipt, "outcome", None) == "INDETERMINATE", receipt
    assert f.state.pasted == []
    assert_restored(f.api, f.original)


@pytest.mark.parametrize("region_occluded_at", [1, 2])
def test_formal_field_region_occlusion_does_not_paste_or_retry(formal_text, region_occluded_at):
    f = formal_text(region_occluded_at=region_occluded_at)
    cid = approve(f)
    receipt = f.service.consume_grounded_confirmation(confirmation_id=cid)
    assert getattr(receipt, "outcome", None) == "INDETERMINATE", receipt
    assert receipt.reason_code == "backend_result_lost"
    assert len(f.state.region_checks) == region_occluded_at
    assert f.state.pasted == [] and f.state.keys == set()
    assert_restored(f.api, f.original)
    assert f.service.consume_grounded_confirmation(confirmation_id=cid) == receipt
    assert len(f.state.region_checks) == region_occluded_at
    assert f.state.pasted == []


def test_formal_field_value_changed_before_consume_invalidates_approval(formal_text):
    f = formal_text()
    cid = approve(f)
    f.reader.value = "changed by user"
    result = f.service.consume_grounded_confirmation(confirmation_id=cid)
    assert result.reason_code == "grounded_confirmation_stale"
    assert f.state.pasted == []
    assert f.state.mouse == []


def test_fresh_owner_recovers_text_checkpoint_without_raw_input_or_redispatch(formal_text, monkeypatch):
    f = formal_text(variable=True, clear=False)
    cid = approve(f)

    def crash(**kwargs):
        raise RuntimeIntentClaimStoreError("synthetic terminal persistence interruption")

    monkeypatch.setattr(f.claims, "persist_grounded_terminal", crash)
    pending = f.service.consume_grounded_confirmation(confirmation_id=cid)
    assert pending.reason_code == "receipt_persistence_failed"
    assert f.state.pasted == [f.resolved.text]
    original_controller = f.controllers[-1]
    # 模拟进程退出只释放本地 lease，不更改任何持久 checkpoint。
    for session in original_controller._sessions.values():
        original_controller._release_window_lease(session.window_lease)
    original_controller._sessions.clear()
    original_controller._grounded_publications.clear()
    claims = RuntimeIntentClaimStore(project_root=f.root, receipt_store=RuntimeReceiptStore(project_root=f.root))
    backend = DeterministicFakeBackend()
    rebuilt = []

    def build(binding):
        controller = LiveController(binding=binding, asset_loader=f.assets, observation_source=f.adapter,
            target_resolver=f.adapter, gate=ReviewedWorkflowGateAdapter(), backend=backend,
            window_visibility_checker=_WindowVisibilityChecker(bound_window_handle=4242), intent_claim_store=claims,
            grounding_policy={"minimum_confidence": 0.9, "minimum_score_margin": 0.2})
        rebuilt.append(controller)
        f.controllers.append(controller)
        return controller

    fresh = LocalAgentRuntimeCallsite(project_root=f.root, asset_store=f.assets, claim_store=claims,
        window_manager=f.windows, controller_factory=build,
        selection=RuntimeSessionSelection(f.asset["asset_id"], content_sha256(f.asset), 4242, 9001))
    receipt = fresh.recover_grounded_confirmation(confirmation_id=cid)
    assert getattr(receipt, "outcome", None) == "VERIFIED", receipt
    assert backend.attempt_count == 0
    assert f.state.pasted == [f.resolved.text]
    assert not rebuilt[0]._grounded_publications
    assert not rebuilt[0]._grounded_recovery_sessions
    assert fresh.recover_grounded_confirmation(confirmation_id=cid) == receipt
    assert backend.attempt_count == 0
