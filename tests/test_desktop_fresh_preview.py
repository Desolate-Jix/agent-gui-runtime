"""首次学习的原生预览只能展示已验证的当前证据。"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256

import pytest
from PySide6.QtWidgets import QGraphicsLineItem, QGraphicsPixmapItem, QGraphicsRectItem

from app.agent.fresh_learning_action_contracts import canonical_json_bytes
from app.agent.fresh_learning_action_preview import FreshLearningActionPreview
from app.agent.fresh_learning_recording import fresh_preview_geometry
from app.desktop_review.grounded_preview_widget import (
    GroundedPreviewWidget,
    validate_review_view,
)
from app.desktop_review.window import ensure_application
from tests.test_fresh_learning_action_preview import _setup


def _fresh_review_view(tmp_path):
    """经真实持久确认读取仅供显示的首次学习预览和原图。"""

    host, owner, runtime, _backend, _claims, source, session, intent = _setup(tmp_path)
    try:
        claim = runtime.request_grounded_confirmation(
            intent.to_dict(), target_process_id=9001,
        )
        grounded = claim.grounded_confirmation
        assert grounded is not None
        persisted = runtime.get_local_grounded_confirmation(
            confirmation_id=grounded.confirmation_id,
        )
        persisted_grounded = persisted.grounded_confirmation
        assert persisted_grounded is not None
        assert persisted_grounded.confirmation_id == grounded.confirmation_id
        assert persisted_grounded.owner_is_current is True
        image = runtime.get_local_grounded_image(
            confirmation_id=persisted_grounded.confirmation_id,
        )
        return {
            "phase": "pending_review",
            "confirmation_id": persisted_grounded.confirmation_id,
            "preview": persisted_grounded.preview.to_dict(),
            "requested_at": persisted_grounded.requested_at.isoformat().replace("+00:00", "Z"),
            "expires_at": persisted_grounded.expires_at.isoformat().replace("+00:00", "Z"),
            "owner_is_current": persisted_grounded.owner_is_current,
            "png_bytes": image,
            "source_kind": "fresh_learning",
        }, intent
    finally:
        try:
            if session.session_id in runtime._grounded_publications:
                runtime.cancel_grounded_review(session_id=session.session_id)
            else:
                runtime.abandon_session(session_id=session.session_id)
        finally:
            # 夹具失败时不得把隔离模拟窗口 lease 留给下一项测试。
            for current in runtime._sessions.values():
                runtime._release_window_lease(current.window_lease)
            host.close()


def test_widget_renders_actual_fresh_preview_without_reviewed_asset_labels(tmp_path):
    ensure_application()
    review, intent = _fresh_review_view(tmp_path)
    widget = GroundedPreviewWidget()
    try:
        widget.set_review(review)

        displayed = widget.review
        assert displayed["source_kind"] == "fresh_learning"
        assert displayed["preview"] == review["preview"]
        evidence = review["preview"]["observation_evidence"]
        viewport = evidence["capture"]["viewport_size"]
        assert widget.view.sceneRect().width() == viewport["width"]
        assert widget.view.sceneRect().height() == viewport["height"]
        geometry = fresh_preview_geometry(
            FreshLearningActionPreview.from_dict(review["preview"]),
        )
        items = widget.view.scene().items()
        pixmaps = [item for item in items if isinstance(item, QGraphicsPixmapItem)]
        rectangles = [item for item in items if isinstance(item, QGraphicsRectItem)]
        lines = [item for item in items if isinstance(item, QGraphicsLineItem)]
        assert len(pixmaps) == 1
        assert (pixmaps[0].pixmap().width(), pixmaps[0].pixmap().height()) == (
            viewport["width"], viewport["height"],
        )
        assert len(rectangles) == 1
        bbox = geometry["bbox"]
        assert (rectangles[0].pos().x(), rectangles[0].pos().y()) == (bbox["x"], bbox["y"])
        assert (rectangles[0].rect().width(), rectangles[0].rect().height()) == (bbox["w"], bbox["h"])
        horizontal = next(item.line() for item in lines if item.line().dx() != 0)
        vertical = next(item.line() for item in lines if item.line().dy() != 0)
        assert (vertical.x1(), horizontal.y1()) == tuple(geometry["click_point"])
        details = widget.metadata_text.toPlainText()
        assert "首次学习 · 操作预览" in details
        assert f"动作：{intent.semantic_action}" in details
        assert f"Agent 目标：{intent.goal}" in details
        assert review["preview"]["source_sha256"] in details
        assert evidence["application"]["canonical_origin"] in details
        assert evidence["capture"]["capture_id"] in details
        assert "资产：" not in details
        assert "审核限定：" not in details
    finally:
        widget.close()


def test_fresh_review_rejects_png_tamper_before_qt_display(tmp_path):
    review, _intent = _fresh_review_view(tmp_path)
    tampered = deepcopy(review)
    png = bytearray(tampered["png_bytes"])
    png[-1] ^= 1
    tampered["png_bytes"] = bytes(png)

    with pytest.raises(ValueError):
        validate_review_view(tampered)


def test_fresh_review_rejects_rehashed_source_that_differs_from_agent_intent(tmp_path):
    review, _intent = _fresh_review_view(tmp_path)
    tampered = deepcopy(review)
    preview = tampered["preview"]
    preview["source_sha256"] = "b" * 64
    preview["preview_sha256"] = sha256(canonical_json_bytes({
        key: value for key, value in preview.items() if key != "preview_sha256"
    })).hexdigest()

    with pytest.raises(ValueError):
        validate_review_view(tampered)
