"""首次学习执行权限只接受显式来源链，并继续复用唯一桌面后端。"""

from dataclasses import FrozenInstanceError

import pytest

from app.agent.desktop_backend import (
    DesktopDispatchCommand,
    DeterministicFakeBackend,
    FreshExecutionSourceLineage,
    _mint_execution_authority,
)


def _command(*, candidate_id: str = "candidate.current") -> DesktopDispatchCommand:
    return DesktopDispatchCommand(
        semantic_action="open_detail",
        capture_id="fresh-capture.current",
        candidate_id=candidate_id,
        click_point=(60.0, 30.0),
        target_window_handle=4242,
    )


def _lineage(**changes) -> FreshExecutionSourceLineage:
    values = {
        "source_sha256": "a" * 64,
        "approved_preview_sha256": "b" * 64,
        "fresh_preview_sha256": "c" * 64,
        "confirmation_id": "grounded-confirmation.fresh",
        "consume_content_sha256": "d" * 64,
    }
    values.update(changes)
    return FreshExecutionSourceLineage(**values)


def _fresh_authority(**changes):
    values = {
        "session_id": "fresh-session.1",
        "observation_id": "fresh-observation.1",
        "intent_id": "fresh-intent.1",
        "semantic_action": "open_detail",
        "capture_id": "fresh-capture.current",
        "candidate_id": "candidate.current",
        "click_point": (60.0, 30.0),
        "target_window_handle": 4242,
        "gate_decision_ref": "fresh-preview:" + "c" * 64,
        "source_lineage": _lineage(),
        "action_evidence_sha256": "c" * 64,
    }
    values.update(changes)
    return _mint_execution_authority(**values)


def test_fresh_authority_is_immutable_one_shot_and_uses_existing_backend() -> None:
    lineage = _lineage()
    authority = _fresh_authority(source_lineage=lineage)
    command = _command()
    backend = DeterministicFakeBackend()

    assert authority.source_lineage is lineage
    assert authority.workflow_revision_hash is None
    assert authority.selection_sha256 is None
    assert authority.action_evidence_sha256 == lineage.fresh_preview_sha256
    with pytest.raises(FrozenInstanceError):
        lineage.source_sha256 = "e" * 64
    with pytest.raises(AttributeError):
        authority.source_lineage = _lineage(source_sha256="e" * 64)

    receipt = backend.dispatch(command, authority=authority)
    assert receipt.status == "dispatched"
    assert backend.commands == [command]
    with pytest.raises(PermissionError, match="already consumed"):
        backend.dispatch(command, authority=authority)
    assert backend.commands == [command]


def test_command_mismatch_does_not_consume_fresh_authority() -> None:
    authority = _fresh_authority()
    backend = DeterministicFakeBackend()

    with pytest.raises(PermissionError, match="does not match"):
        backend.dispatch(_command(candidate_id="candidate.foreign"), authority=authority)
    assert backend.commands == []
    assert backend.dispatch(_command(), authority=authority).status == "dispatched"


@pytest.mark.parametrize(
    "changes",
    [
        {"workflow_revision_hash": "e" * 64},
        {"selection_sha256": "e" * 64},
        {"source_lineage": None},
        {"action_evidence_sha256": None},
        {"action_evidence_sha256": "e" * 64},
        {"source_lineage": {"source_sha256": "a" * 64}},
    ],
)
def test_fresh_authority_rejects_mixed_missing_or_unbound_lineage(changes) -> None:
    with pytest.raises((TypeError, ValueError)):
        _fresh_authority(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"source_sha256": "A" * 64},
        {"approved_preview_sha256": "b" * 63},
        {"fresh_preview_sha256": "b" * 64},
        {"confirmation_id": ""},
        {"confirmation_id": "not allowed"},
        {"consume_content_sha256": "z" * 64},
    ],
)
def test_fresh_lineage_rejects_invalid_or_nonfresh_identity(changes) -> None:
    with pytest.raises(ValueError):
        _lineage(**changes)


def test_reviewed_mint_api_remains_exclusive_and_compatible() -> None:
    authority = _mint_execution_authority(
        session_id="reviewed-session.1",
        observation_id="reviewed-observation.1",
        intent_id="reviewed-intent.1",
        workflow_revision_hash="a" * 64,
        semantic_action="open_detail",
        selection_sha256="b" * 64,
        capture_id="capture.reviewed",
        candidate_id="candidate.reviewed",
        click_point=(10.0, 20.0),
        target_window_handle=101,
        gate_decision_ref="gate.reviewed",
    )

    assert authority.workflow_revision_hash == "a" * 64
    assert authority.selection_sha256 == "b" * 64
    assert authority.source_lineage is None
    assert authority.action_evidence_sha256 is None
    with pytest.raises(ValueError):
        _mint_execution_authority(
            session_id="reviewed-session.1",
            observation_id="reviewed-observation.1",
            intent_id="reviewed-intent.1",
            workflow_revision_hash="a" * 64,
            semantic_action="open_detail",
            selection_sha256="b" * 64,
            capture_id="capture.reviewed",
            candidate_id="candidate.reviewed",
            click_point=(10.0, 20.0),
            target_window_handle=101,
            gate_decision_ref="gate.reviewed",
            source_lineage=_lineage(),
            action_evidence_sha256="c" * 64,
        )
