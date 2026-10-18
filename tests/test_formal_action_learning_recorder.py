from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from app.agent.action_learning_recorder import (
    ActionLearningRecorder,
    ActionLearningRecorderError,
    STORE_ROOT as ACTION_LEARNING_STORE_ROOT,
)
from app.agent.desktop_backend import DeterministicFakeBackend
from app.agent.live_controller import LiveController, LiveControllerDecision, ServerWorkflowBinding
from app.agent.reviewed_workflow_asset import content_sha256
from app.agent.runtime_intent_claim_store import (
    RuntimeIntentClaimStore,
    RuntimeIntentClaimStoreError,
)
from app.agent.runtime_receipt_store import RuntimeReceiptStore
from app.api.agent_runtime import AgentRuntimeIntentRequest
from app.agent.text_parameters import resolve_text_parameters
from tests.test_live_controller_w4 import (
    _Gate,
    _ObservationSource,
    _TargetResolver,
    _TrustedAssetLoader,
    _WindowVisibilityChecker,
    _asset,
    _intent,
)
from tests.test_native_scroll_roundtrip import _request as _scroll_request
from tests.test_native_scroll_roundtrip import _runtime as _scroll_runtime
from tests.test_text_formal_execution import approve as _approve_text
from tests.test_text_formal_execution import formal_text as _formal_text_fixture


formal_text = _formal_text_fixture


def _controller(
    root: Path,
    recorder: ActionLearningRecorder | None,
    *,
    backend=None,
):
    asset = deepcopy(_asset())
    source = _ObservationSource(asset)
    receipts = RuntimeReceiptStore(project_root=root)
    claims = RuntimeIntentClaimStore(project_root=root, receipt_store=receipts)
    actual_backend = backend or DeterministicFakeBackend()
    controller = LiveController(
        binding=ServerWorkflowBinding(
            workflow_id="workflow.seek.portfolio",
            asset_id=asset["asset_id"],
            application_identity_key="web:nz.seek.com",
            target_window_handle=4242,
        ),
        asset_loader=_TrustedAssetLoader(asset),
        observation_source=source,
        target_resolver=_TargetResolver("resolved"),
        gate=_Gate(allowed=True),
        window_visibility_checker=_WindowVisibilityChecker(bound_window_handle=4242),
        backend=actual_backend,
        intent_claim_store=claims,
        action_learning_recorder=recorder,
        grounding_policy={"minimum_confidence": 0.9, "minimum_score_margin": 0.2},
        verification_max_capture_attempts=1,
        verification_poll_interval_seconds=0.0,
        verification_sleeper=lambda _seconds: None,
        verification_monotonic_clock=lambda: 0.0,
    )
    return controller, source, actual_backend, claims, receipts


def _event(session: dict) -> dict:
    assert len(session["events"]) == 1
    return next(iter(session["events"].values()))


def test_none_injection_creates_no_learning_layout(tmp_path: Path) -> None:
    root = tmp_path / "none"
    controller, _, backend, _, _ = _controller(root, None)
    session = controller.start_session()
    assert controller.submit_intent(_intent(session)).outcome == "VERIFIED"
    assert backend.attempt_count == 1
    assert not (root / ACTION_LEARNING_STORE_ROOT).exists()


def test_unbound_controller_is_noop_and_lifecycle_performs_no_input(tmp_path: Path) -> None:
    recorder = ActionLearningRecorder(project_root=tmp_path)
    controller, source, backend, _, _ = _controller(tmp_path, recorder)

    started = recorder.start_learning_session(
        learning_session_id="learning.control",
        runtime_session_id="session.not-running",
    )
    assert started["status"] == "active"
    assert backend.attempt_count == 0
    assert source.projected_calls == 0
    assert recorder.finish_learning_session(
        learning_session_id="learning.control",
        runtime_session_id="session.not-running",
    )["status"] == "finished"
    assert backend.attempt_count == 0
    assert source.projected_calls == 0

    session = controller.start_session()
    receipt = controller.submit_intent(_intent(session))
    assert receipt.outcome == "VERIFIED"
    assert backend.attempt_count == 1
    assert recorder.list_learning_sessions() == [
        recorder.get_learning_session(learning_session_id="learning.control")
    ]


def test_click_records_fresh_before_and_authoritative_terminal_once(tmp_path: Path) -> None:
    recorder = ActionLearningRecorder(project_root=tmp_path)
    controller, source, backend, claims, receipts = _controller(tmp_path, recorder)
    session = controller.start_session()
    recorder.start_learning_session(
        learning_session_id="learning.click",
        runtime_session_id=session.session_id,
    )

    payload = _intent(session)
    receipt = controller.submit_intent(payload)
    replay = controller.submit_intent(payload)

    assert replay == receipt
    assert backend.attempt_count == 1
    recorded = recorder.get_learning_session(learning_session_id="learning.click")
    assert recorded["recording_gaps"] == []
    event = _event(recorded)
    assert event["runtime"]["session_id"] == session.session_id
    assert event["runtime"]["observation_id"] == session.current_observation.observation_id
    assert event["before"]["capture"]["capture_id"] == "capture-current"
    assert event["before"]["capture"]["capture_id"] != "capture-initial"
    assert event["terminal"]["receipt_id"] == receipt.receipt_id
    assert event["terminal"]["outcome"] == receipt.outcome
    terminal_ref = claims.get_for_observation(
        session_id=session.session_id,
        observation_id=session.current_observation.observation_id,
    ).terminal_receipt_ref
    assert event["terminal"]["receipt_content_sha256"] == terminal_ref["content_sha256"]
    with pytest.raises(ActionLearningRecorderError, match="verified by the claim store"):
        recorder.observe_terminal_receipt(receipts.get(terminal_ref))  # type: ignore[arg-type]
    assert source.projected_calls == 2


class _UnknownBackend:
    def __init__(self) -> None:
        self.attempt_count = 0

    def dispatch(self, _command, *, authority):
        self.attempt_count += 1
        raise RuntimeError("synthetic lost result")


def test_unknown_replay_is_one_attempt_one_event_without_arrival(tmp_path: Path) -> None:
    recorder = ActionLearningRecorder(project_root=tmp_path)
    backend = _UnknownBackend()
    controller, _, _, _, _ = _controller(tmp_path, recorder, backend=backend)
    session = controller.start_session()
    recorder.start_learning_session(
        learning_session_id="learning.unknown",
        runtime_session_id=session.session_id,
    )
    payload = _intent(session)

    receipt = controller.submit_intent(payload)
    replay = controller.submit_intent(payload)

    assert receipt.outcome == "INDETERMINATE"
    assert replay == receipt
    assert backend.attempt_count == 1
    event = _event(recorder.get_learning_session(learning_session_id="learning.unknown"))
    assert event["terminal"]["outcome"] == "INDETERMINATE"
    assert event["terminal"]["destination_status"] == "indeterminate"
    assert event["terminal"]["next_observation_id"] is None


def test_before_persistence_failure_prevents_dispatch_marker_and_backend(tmp_path: Path, monkeypatch) -> None:
    recorder = ActionLearningRecorder(project_root=tmp_path)
    controller, _, backend, claims, _ = _controller(tmp_path, recorder)
    session = controller.start_session()
    recorder.start_learning_session(
        learning_session_id="learning.before-failure",
        runtime_session_id=session.session_id,
    )

    monkeypatch.setattr(recorder, "_write_ledger", lambda _ledger: (_ for _ in ()).throw(OSError("disk full")))
    result = controller.submit_intent(_intent(session))

    assert isinstance(result, LiveControllerDecision)
    assert result.reason_code == "learning_recording_failed"
    assert backend.attempt_count == 0
    assert claims.get_for_observation(
        session_id=session.session_id,
        observation_id=session.current_observation.observation_id,
    ).phase == "claimed"


def test_post_failure_keeps_receipt_gap_and_restart_recovery_never_dispatches(
    tmp_path: Path, monkeypatch
) -> None:
    recorder = ActionLearningRecorder(project_root=tmp_path)
    controller, _, backend, claims, _ = _controller(tmp_path, recorder)
    session = controller.start_session()
    recorder.start_learning_session(
        learning_session_id="learning.recovery",
        runtime_session_id=session.session_id,
    )
    original_write = recorder._write_ledger
    calls = 0

    def fail_second(ledger):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("synthetic terminal journal failure")
        return original_write(ledger)

    monkeypatch.setattr(recorder, "_write_ledger", fail_second)
    receipt = controller.submit_intent(_intent(session))

    assert receipt.outcome == "VERIFIED"
    assert backend.attempt_count == 1
    gap = recorder.get_learning_session(learning_session_id="learning.recovery")
    assert gap["events"] == {}
    assert gap["recording_gaps"] == [session.current_observation.observation_id]
    assert len(gap["pending_before_refs"]) == 1
    pending_ref = gap["pending_before_refs"][0]
    assert pending_ref["observation_id"] == session.current_observation.observation_id
    assert pending_ref["intent_id"] == "intent.open-detail"
    assert pending_ref["capture_id"] == "capture-current"
    assert len(pending_ref["content_sha256"]) == 64

    restarted = ActionLearningRecorder(project_root=tmp_path)
    restarted_claims = RuntimeIntentClaimStore(
        project_root=tmp_path,
        receipt_store=RuntimeReceiptStore(project_root=tmp_path),
    )
    recovered = restarted.recover_pending(
        learning_session_id="learning.recovery",
        claim_store=restarted_claims,
    )
    assert recovered["recording_gaps"] == []
    assert len(recovered["events"]) == 1
    assert backend.attempt_count == 1
    assert restarted_claims.load_terminal_receipt(
        session_id=session.session_id,
        observation_id=session.current_observation.observation_id,
    ) == receipt
    assert len(restarted.get_learning_session(learning_session_id="learning.recovery")["events"]) == 1


def test_recovery_refuses_corrupt_authoritative_receipt_not_caller_fact(
    tmp_path: Path, monkeypatch
) -> None:
    recorder = ActionLearningRecorder(project_root=tmp_path)
    controller, _, backend, claims, receipts = _controller(tmp_path, recorder)
    session = controller.start_session()
    recorder.start_learning_session(
        learning_session_id="learning.corrupt",
        runtime_session_id=session.session_id,
    )
    original_write = recorder._write_ledger
    calls = 0

    def fail_second(ledger):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("synthetic terminal journal failure")
        return original_write(ledger)

    monkeypatch.setattr(recorder, "_write_ledger", fail_second)
    controller.submit_intent(_intent(session))
    terminal_ref = claims.get_for_observation(
        session_id=session.session_id,
        observation_id=session.current_observation.observation_id,
    ).terminal_receipt_ref
    receipts._object_path(terminal_ref["content_sha256"]).write_text("{}", encoding="utf-8")

    restarted = ActionLearningRecorder(project_root=tmp_path)
    restarted_claims = RuntimeIntentClaimStore(
        project_root=tmp_path,
        receipt_store=RuntimeReceiptStore(project_root=tmp_path),
    )
    with pytest.raises(RuntimeIntentClaimStoreError, match="receipt"):
        restarted.recover_pending(
            learning_session_id="learning.corrupt",
            claim_store=restarted_claims,
        )
    assert backend.attempt_count == 1
    assert restarted.get_learning_session(learning_session_id="learning.corrupt")["events"] == {}


def test_runtime_scope_cannot_be_rebound_to_another_learning_session(tmp_path: Path) -> None:
    recorder = ActionLearningRecorder(project_root=tmp_path)
    recorder.start_learning_session(
        learning_session_id="learning.a",
        runtime_session_id="session.shared",
    )
    assert recorder.start_learning_session(
        learning_session_id="learning.a",
        runtime_session_id="session.shared",
    ) == recorder.get_learning_session(learning_session_id="learning.a")
    with pytest.raises(ActionLearningRecorderError, match="bound"):
        recorder.start_learning_session(
            learning_session_id="learning.b",
            runtime_session_id="session.shared",
        )
    foreign = tmp_path / "foreign"
    with pytest.raises(ActionLearningRecorderError, match="project root"):
        recorder.recover_pending(
            learning_session_id="learning.a",
            claim_store=RuntimeIntentClaimStore(
                project_root=foreign,
                receipt_store=RuntimeReceiptStore(project_root=foreign),
            ),
        )


def test_restart_rejects_rehashed_nondeterministic_event_identity(tmp_path: Path) -> None:
    recorder = ActionLearningRecorder(project_root=tmp_path)
    controller, _, _, _, _ = _controller(tmp_path, recorder)
    session = controller.start_session()
    recorder.start_learning_session(
        learning_session_id="learning.tamper",
        runtime_session_id=session.session_id,
    )
    controller.submit_intent(_intent(session))
    ledger = json.loads(recorder.ledger_path.read_text(encoding="utf-8"))
    stored = ledger["sessions"]["learning.tamper"]["events"]
    event = next(iter(stored.values()))
    stored.clear()
    event["event_id"] = "learning-event.forged"
    event_payload = dict(event)
    event_payload.pop("content_sha256")
    event["content_sha256"] = hashlib.sha256(
        json.dumps(
            event_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    stored[event["event_id"]] = event
    recorder.ledger_path.write_text(
        json.dumps(
            ledger,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ActionLearningRecorderError, match="deterministic"):
        ActionLearningRecorder(project_root=tmp_path)


def test_failed_locked_read_releases_file_lock_even_with_retained_traceback(
    tmp_path: Path,
) -> None:
    recorder = ActionLearningRecorder(project_root=tmp_path)
    recorder.ledger_path.write_bytes(b"{")
    retained = []
    try:
        recorder.start_learning_session(
            learning_session_id="learning.lock-recovery",
            runtime_session_id="session.lock-recovery",
        )
    except ActionLearningRecorderError as exc:
        retained.append(exc)
    assert retained and retained[0].__traceback__ is not None
    recorder.ledger_path.write_text(
        json.dumps(
            {
                "contract_version": "action_learning_ledger_v1",
                "revision": 0,
                "sessions": {},
                "runtime_bindings": {},
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    assert recorder.start_learning_session(
        learning_session_id="learning.lock-recovery",
        runtime_session_id="session.lock-recovery",
    )["status"] == "active"


def test_scroll_grounded_runtime_records_typed_action_and_deduplicates(tmp_path: Path) -> None:
    runtime = _scroll_runtime(tmp_path)
    recorder = ActionLearningRecorder(project_root=runtime.receipts.project_root)
    original_factory = runtime.service._controller_factory

    def build(binding):
        controller = original_factory(binding)
        controller.set_action_learning_recorder(recorder)
        return controller

    runtime.service._controller_factory = build
    observation = runtime.service.start_session()
    recorder.start_learning_session(
        learning_session_id="learning.scroll",
        runtime_session_id=observation.session_id,
    )
    request = _scroll_request(observation)
    assert runtime.service.prepare_grounded_review(request).to_dict()["status"] == "prepared"
    pending = runtime.service.request_grounded_confirmation(request)
    confirmation_id = pending.grounded_confirmation.confirmation_id
    runtime.service.decide_grounded_confirmation(
        confirmation_id=confirmation_id,
        decision="approved",
    )

    receipt = runtime.service.consume_grounded_confirmation(confirmation_id=confirmation_id)
    assert runtime.service.consume_grounded_confirmation(confirmation_id=confirmation_id) == receipt
    assert len(runtime.input_boundary.scroll_calls) == 1
    event = _event(recorder.get_learning_session(learning_session_id="learning.scroll"))
    assert event["terminal"]["action"]["semantic_action"] == "scroll_region"
    assert event["terminal"]["action"]["scroll_parameters"]["wheel_clicks"] == 2


def test_text_grounded_runtime_records_only_reference_not_plaintext(
    tmp_path: Path, formal_text
) -> None:
    fixture = formal_text(start=False)
    recorder = ActionLearningRecorder(project_root=fixture.receipts.project_root)
    original_factory = fixture.service._controller_factory

    def build(binding):
        controller = original_factory(binding)
        controller.set_action_learning_recorder(recorder)
        return controller

    fixture.service._controller_factory = build
    observation = fixture.service.start_session()
    action = next(item for item in observation.available_actions if item.semantic_action == "fill_field")
    fixture.request = AgentRuntimeIntentRequest(
        intent_id="fill-once",
        session_id=observation.session_id,
        observation_id=observation.observation_id,
        action_id=action.action_id,
    )
    parameters = fixture.service.get_local_reviewed_text_parameters(action_id=action.action_id)
    fixture.resolved = resolve_text_parameters(parameters, {})
    recorder.start_learning_session(
        learning_session_id="learning.text",
        runtime_session_id=observation.session_id,
    )
    confirmation_id = _approve_text(fixture)

    receipt = fixture.service.consume_grounded_confirmation(confirmation_id=confirmation_id)
    assert receipt.outcome == "VERIFIED"
    session = recorder.get_learning_session(learning_session_id="learning.text")
    event = _event(session)
    assert event["terminal"]["action"]["semantic_action"] == "fill_field"
    assert "text_parameters_ref" in event["terminal"]["action"]
    encoded = json.dumps(session, ensure_ascii=False, sort_keys=True)
    assert fixture.resolved.text not in encoded
    assert "ABCD" not in encoded
    assert "original-dib" not in encoded
