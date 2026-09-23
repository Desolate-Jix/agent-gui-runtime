"""浏览器工具栏的完整性不能依赖网页正文的长度。"""
from copy import deepcopy
from types import SimpleNamespace
import sys

import pytest

from app.api import vision
from app.operation.screen_reading import uia_provider as module
from tests.test_uia_provider_pinned_snapshot import _TreeWrapper


def _tree(monkeypatch, *, process="msedge.exe", budget=4):
    root = _TreeWrapper((1,), "Window", "browser", (0, 0, 600, 500))
    doc = _TreeWrapper((2,), "Document", "long page", (0, 80, 600, 500), root)
    page = _TreeWrapper((3,), "Hyperlink", "Back", (0, 200, 80, 240), doc)
    toolbar = _TreeWrapper((4,), "ToolBar", "navigation", (0, 20, 600, 80), root)
    back = _TreeWrapper((5,), "Button", "Back", (0, 20, 40, 60), toolbar)
    root.iter_descendants = lambda **kw: iter([doc, toolbar] if kw.get("depth") == 1 else [doc, page, page, page, toolbar, back])
    root.iter_children = lambda: iter([doc, toolbar])
    toolbar.iter_children = lambda: iter([back])
    back.iter_children = lambda: iter([])
    def forbidden(**kw):
        pytest.fail("chrome traversal must not descend into the page document")
    doc.iter_descendants = forbidden
    doc.iter_children = forbidden
    monkeypatch.setitem(sys.modules, "pywinauto", SimpleNamespace(Desktop=lambda **kw: SimpleNamespace(window=lambda **kw: root)))
    provider = module.WindowsUIAProvider()
    monkeypatch.setattr(provider, "_owned_popup_handles", lambda b: [])
    bound = SimpleNamespace(handle=42, title="browser", process_id=7, process_name=process,
        rect=SimpleNamespace(left=0, top=0, right=600, bottom=500))
    return provider.snapshot_window(bound, max_controls=budget)


def test_long_document_is_pruned_but_later_toolbar_is_complete(monkeypatch):
    result = _tree(monkeypatch)
    assert result["scan_complete"] is False
    chrome = result["browser_chrome_scope"]
    assert chrome["scan_complete"] is True
    assert chrome["scan_scope"] == "browser_chrome"
    assert chrome["excluded_document_count"] == 1
    assert chrome["scan_visited_count"] == 4
    assert [c["control_type"] for c in chrome["controls"]] == ["Window", "ToolBar", "Button"]


def test_native_apps_do_not_get_browser_scope(monkeypatch):
    assert "browser_chrome_scope" not in _tree(monkeypatch, process="notepad.exe")


def test_chrome_scan_budget_does_not_claim_complete_or_eagerly_walk(monkeypatch):
    root = _TreeWrapper((1,), "Window", "browser", (0, 0, 600, 500))
    pulled = []
    def children(**kw):
        assert kw == {}
        for n in range(10000):
            pulled.append(n)
            child = _TreeWrapper((n + 2,), "Button", "tab", (n, 20, n + 1, 30), root)
            child.iter_children = lambda: iter([])
            yield child
    root.iter_children = children
    bound = SimpleNamespace(rect=SimpleNamespace(left=0, top=0))
    result = module.WindowsUIAProvider()._browser_chrome_scope(root, bound=bound, window={"handle": 42})
    assert result["scan_visited_count"] == 1000
    assert len(pulled) == 999
    assert result["scan_complete"] is False
    assert result["truncated"] is True


def test_chrome_scan_error_remains_unavailable():
    root = _TreeWrapper((1,), "Window", "browser", (0, 0, 600, 500))
    def broken(**kw):
        raise RuntimeError("UIA traversal failed")
    root.iter_children = broken
    result = module.WindowsUIAProvider()._browser_chrome_scope(root, bound=None, window={})
    assert result["status"] == "unavailable"
    assert result["scan_complete"] is False
    assert result["reason"] == "browser_chrome_scan_failed"


@pytest.mark.parametrize("change", [None, "wrong_window", "incomplete", "page_goal", "context_only", "negation"])
def test_only_explicit_browser_navigation_uses_scoped_evidence(tmp_path, monkeypatch, change):
    snapshot = _tree(monkeypatch)
    goal = "Click the browser Back button (left-pointing arrow) to return to results"
    if change == "wrong_window":
        snapshot["browser_chrome_scope"]["window"]["handle"] = 99
    if change == "incomplete":
        snapshot["browser_chrome_scope"]["scan_complete"] = False
    if change == "page_goal": goal = "Click the Back link in the page"
    if change == "context_only": goal = "Click the search box below the browser Back button"
    if change == "negation": goal = "Do not click the browser Back button"
    original = deepcopy(snapshot)
    with module.pinned_uia_snapshot(snapshot):
        result = vision._execute_fast_inventory_from_uia(image_path=tmp_path / "frame.png",
            image_size=vision.ImageSize(width=600, height=500), app_name="Microsoft Edge", goal=goal, metadata=None)
    assert result["status"] == ("ready" if change is None else "incomplete")
    if change is None:
        assert result["raw_uia_snapshot"]["scan_scope"] == "browser_chrome"
        assert result["control_count"] == 1
        assert result["screen_reading"]["source_layers"]["windows_uia"]["parent_scan_complete"] is False
    assert snapshot == original
