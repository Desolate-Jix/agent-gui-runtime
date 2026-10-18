from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.desktop_review.graph_review_pane import GraphReviewPane


_APP = QApplication.instance() or QApplication([])


class _Facade:
    pass


def test_set_revision_reports_install_failure_without_replacing_current_graph() -> None:
    pane = GraphReviewPane(_Facade())
    pane.set_revision({
        "not": "a formal revision",
    })

    assert pane._snapshot is None
    assert pane.set_revision({"still": "invalid"}) is False
    assert pane._snapshot is None
    pane.close()


def test_install_revision_reports_success_only_after_graph_view_accepts(monkeypatch) -> None:
    pane = GraphReviewPane(_Facade())
    monkeypatch.setattr(pane.graph_view, "set_revision", lambda _snapshot: (_ for _ in ()).throw(ValueError("bad graph")))

    assert pane._install_revision({"anything": "invalid"}) is False
    assert pane._snapshot is None
    pane.close()
