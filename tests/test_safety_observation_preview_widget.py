"""离屏预览必须显示原始拦截建议，不能把观察模式伪装为 Gate 通过。"""
from datetime import datetime, timedelta, timezone
from PySide6.QtCore import QCoreApplication, QEvent
from app.agent.fresh_learning_action_preview import build_fresh_learning_action_preview
from app.desktop_review.grounded_preview_widget import GroundedPreviewWidget, validate_review_view
from app.desktop_review.window import ensure_application
from app.operation.recognition.schemas import ScoreBreakdown
from tests.test_fresh_learning_action_preview import _setup, _recognize


def test_warning_only_preview_displays_target_without_promoting_raw_gate(tmp_path):
    def recognize(**kwargs):
        value = _recognize(**kwargs)
        breakdown = ScoreBreakdown(text_similarity=1)
        value['candidate_result']['candidates'][0]['score_breakdown'] = breakdown.to_dict()
        value['candidate_result']['candidates'][0]['score'] = breakdown.total()
        return value

    app = ensure_application()
    host, owner, runtime, backend, claims, source, session, intent = _setup(tmp_path, runner=recognize)
    widget = None
    try:
        bundle = owner.observe_for_action(target_window_handle=4242, target_process_id=9001, goal=intent.goal)
        reference = source.reference()
        scope = {key: reference[key] for key in ('connection_id', 'task_id', 'segment_id')}
        capture_source = host.fresh_learning.archive.record(bundle.packet, **scope)
        preview = build_fresh_learning_action_preview(bundle=bundle, capture_source=capture_source,
            observation=session.current_observation.to_dict(), intent=intent, source_reference=reference,
            automatic_safety_interception=False).to_dict()
        assert preview['pre_click_decision']['allowed'] is False
        now = datetime.now(timezone.utc)
        view = {'phase': 'pending_review', 'source_kind': 'fresh_learning', 'confirmation_id': 'grounded-confirmation.' + 'a' * 64,
            'preview': preview, 'requested_at': now.isoformat(), 'expires_at': (now + timedelta(seconds=300)).isoformat(),
            'owner_is_current': True, 'png_bytes': bundle.packet.png_bytes}
        checked, image = validate_review_view(view)
        assert not image.isNull()
        widget = GroundedPreviewWidget()
        widget.set_review(checked)
        assert '自动安全拦截：已关闭' in widget.metadata_text.toPlainText()
        assert '原始 Gate 判断：建议拦截' in widget.metadata_text.toPlainText()
        assert widget.review['preview']['pre_click_decision']['allowed'] is False
        assert backend.commands == []
    finally:
        if widget is not None:
            widget.deleteLater()
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        runtime.abandon_session(session_id=session.session_id)
        host.close()
