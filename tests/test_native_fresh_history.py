"""首次学习的原生历史只展示已核验事实，绝不恢复或重放动作。"""

from __future__ import annotations

from copy import deepcopy

import pytest

from app.agent.live_controller import LiveControllerDecision
from app.agent.runtime_fresh_receipt import RuntimeFreshResultReceipt
from app.desktop_review.grounded_history import history_item
from app.desktop_review.grounded_history_dialog import _item
from tests.test_fresh_dispatch_graph import _close, _ready


def test_fresh_terminal_history_uses_same_durable_receipt_without_second_dispatch(tmp_path):
    host, _owner, runtime, backend, claims, session, _scope, confirmation_id = _ready(tmp_path)
    try:
        receipt = runtime.consume_grounded_confirmation(confirmation_id=confirmation_id)
        assert isinstance(receipt, RuntimeFreshResultReceipt)
        before = len(backend.commands)
        claim = claims.get_for_grounded_confirmation(confirmation_id=confirmation_id)

        item = history_item(claims, claim)
        checked = _item(item)

        assert checked["phase"] == "terminal"
        assert checked["operation"] == "view_history"
        assert checked["selection"]["source_kind"] == "fresh_learning"
        assert checked["selection"]["source_sha256"] == receipt.source_sha256
        assert checked["receipt"] == receipt.model_dump(mode="json")
        assert len(backend.commands) == before == 1
    finally:
        _close(host, runtime)


def test_fresh_dispatch_started_history_is_indeterminate_without_receipt_or_input(tmp_path, monkeypatch):
    host, _owner, runtime, backend, claims, session, _scope, confirmation_id = _ready(tmp_path)
    original = claims.mark_fresh_dispatch_started
    try:
        def interrupted(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError("isolated dispatch marker response loss")

        monkeypatch.setattr(claims, "mark_fresh_dispatch_started", interrupted)
        result = runtime.consume_grounded_confirmation(confirmation_id=confirmation_id)
        assert isinstance(result, LiveControllerDecision)
        assert result.status == "RECOVERY_REQUIRED"
        claim = claims.get_for_grounded_confirmation(confirmation_id=confirmation_id)

        checked = _item(history_item(claims, claim))

        assert checked["phase"] == "dispatch_started"
        assert checked["operation"] == "indeterminate"
        assert checked["receipt"] is None
        assert backend.commands == []
    finally:
        _close(host, runtime)


def test_fresh_history_rejects_foreign_receipt_even_when_it_has_valid_shape(tmp_path):
    host, _owner, runtime, _backend, claims, _session, _scope, confirmation_id = _ready(tmp_path)
    try:
        receipt = runtime.consume_grounded_confirmation(confirmation_id=confirmation_id)
        assert isinstance(receipt, RuntimeFreshResultReceipt)
        foreign = receipt.model_dump(mode="json")
        foreign["source_sha256"] = "b" * 64
        foreign["evidence"]["source_sha256"] = "b" * 64
        foreign_receipt = RuntimeFreshResultReceipt.from_dict(foreign)

        class ForeignReceiptStore:
            def load_terminal_receipt(self, *, session_id, observation_id):
                assert (session_id, observation_id) == (receipt.session_id, receipt.observation_id)
                return foreign_receipt

        claim = claims.get_for_grounded_confirmation(confirmation_id=confirmation_id)
        with pytest.raises(ValueError):
            history_item(ForeignReceiptStore(), claim)
    finally:
        _close(host, runtime)
