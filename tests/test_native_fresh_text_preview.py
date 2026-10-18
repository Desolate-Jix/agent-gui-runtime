"""实际 Fresh 确认对象在原生面板展示原值和准确新值。"""

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.desktop_review.window import ensure_application
from app.desktop_review.grounded_preview_widget import GroundedPreviewWidget, validate_review_view
from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator
from app.agent.live_controller import LiveControllerDecision
from tests.test_fresh_text_confirmation import _text_runtime


def _view(runtime, claim):
    grounded = claim.grounded_confirmation
    return {'phase': 'pending_review', 'confirmation_id': grounded.confirmation_id,
        'preview': grounded.preview.to_dict(), 'source_kind': 'fresh_learning',
        'requested_at': grounded.requested_at.isoformat().replace('+00:00', 'Z'),
        'expires_at': grounded.expires_at.isoformat().replace('+00:00', 'Z'), 'owner_is_current': True,
        'png_bytes': runtime.get_local_grounded_image(confirmation_id=grounded.confirmation_id),
        'text_input_local': runtime.get_local_grounded_text_input(confirmation_id=grounded.confirmation_id),
        'text_field_local': runtime.get_local_grounded_text_field_expectation(confirmation_id=grounded.confirmation_id)}


@pytest.mark.parametrize('kind', ['literal', 'variable'])
def test_fresh_panel_displays_frozen_text_and_rejects_mismatch(tmp_path, kind):
    app = ensure_application()
    with _text_runtime(tmp_path, kind) as (_, owner, runtime, backend, claims, session, intent, params):
        claim = runtime.request_grounded_confirmation(intent.to_dict(), target_process_id=9001, text_input=params)
        assert not isinstance(claim, LiveControllerDecision), claim
        view = _view(runtime, claim)
        widget = GroundedPreviewWidget()
        try:
            widget.resize(1000, 760)
            widget.set_review(view)
            widget.show()
            app.processEvents()
            assert widget.text_value_editor.toPlainText() == params.text
            assert widget.text_before_editor.toPlainText() == owner._text_field_reader.value
            assert widget.text_expected_editor.toPlainText() == params.text
            assert widget.text_before_editor.isVisible() and widget.text_expected_editor.isVisible()
            assert widget.text_value_editor.isReadOnly() and widget.text_before_editor.isReadOnly()
            assert ('\u53d8\u91cf query' if kind == 'variable' else '\u56fa\u5b9a\u5185\u5bb9') in widget.metadata_text.toPlainText()
            assert '\u4e0d\u6309 Enter' in widget.metadata_text.toPlainText()
            assert widget.grab().save(str(tmp_path / 'fresh-text-panel.png'))
            widget.clear()
            assert not widget.text_value_editor.isVisible()
            assert widget.text_value_editor.toPlainText() == ''
            wrong = deepcopy(view)
            wrong['text_field_local'] = replace(view['text_field_local'], before=replace(view['text_field_local'].before, value='wrong'))
            with pytest.raises(ValueError):
                widget.set_review(wrong)
            assert widget.review is None
        finally:
            widget.close()
        assert backend.attempt_count == 0


def test_fresh_coordinator_attaches_only_owned_exact_local_values(tmp_path):
    with _text_runtime(tmp_path) as (_, owner, runtime, backend, claims, session, intent, params):
        claim = runtime.request_grounded_confirmation(intent.to_dict(), target_process_id=9001, text_input=params)
        assert not isinstance(claim, LiveControllerDecision), claim
        expected_view = _view(runtime, claim)
        view = {k: v for k, v in expected_view.items() if k not in ('text_input_local', 'text_field_local')}
        coordinator = NativeSingleStepCoordinator.__new__(NativeSingleStepCoordinator)
        coordinator._owner = SimpleNamespace(call=lambda action: action())
        coordinator._attach_local_text(runtime, view)
        assert view == expected_view
        bad = deepcopy(view)
        bad.pop('text_field_local')
        with pytest.raises(ValueError):
            validate_review_view(bad)
