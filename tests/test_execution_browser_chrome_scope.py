"""浏览器工具栏的完整性不能依赖网页正文的长度。"""
from copy import deepcopy
from types import SimpleNamespace
import sys

import pytest

from app.api import vision
from app.operation.recognition.control_target import explicit_browser_navigation_goal
from app.operation.screen_reading import uia_provider as module
from tests.test_uia_provider_pinned_snapshot import _TreeWrapper, canonical_identity_boundary


def _provider_tree(monkeypatch, *, process="msedge.exe", navigation_label="Back", forbid_document=False):
    root = _TreeWrapper((1,), "Window", "browser", (0, 0, 600, 500))
    doc = _TreeWrapper((2,), "Document", "long page", (0, 80, 600, 500), root)
    page = _TreeWrapper((3,), "Hyperlink", navigation_label, (0, 200, 80, 240), doc)
    toolbar = _TreeWrapper((4,), "ToolBar", "navigation", (0, 20, 600, 80), root)
    back = _TreeWrapper((5,), "Button", navigation_label, (0, 20, 40, 60), toolbar)
    root.iter_descendants = lambda **kw: iter([doc, toolbar] if kw.get("depth") == 1 else [doc, page, page, page, toolbar, back])
    root.iter_children = lambda: iter([doc, toolbar])
    toolbar.iter_children = lambda: iter([back])
    back.iter_children = lambda: iter([])
    def forbidden(**kw):
        pytest.fail("chrome traversal must not descend into the page document")
    doc.iter_descendants = forbidden
    doc.iter_children = forbidden
    page2 = _TreeWrapper((6,), "Text", "text", (0, 200, 80, 240), doc)
    page3 = _TreeWrapper((7,), "Text", "text", (0, 250, 80, 290), doc)
    mapping = {id(root): [doc, toolbar], id(doc): [page, page2, page3], id(toolbar): [back]}
    reads = []
    def children(node):
        reads.append(node.element_info.control_type)
        if forbid_document and node is doc:
            pytest.fail("navigation must not perform a full document walk")
        return mapping.get(id(node), [])
    monkeypatch.setattr(module, "_finite_uia_children", children)
    monkeypatch.setitem(sys.modules, "pywinauto", SimpleNamespace(Desktop=lambda **kw: SimpleNamespace(window=lambda **kw: root)))
    provider = module.WindowsUIAProvider()
    monkeypatch.setattr(provider, "_owned_popup_handles", lambda b: [])
    bound = SimpleNamespace(handle=42, title="browser", process_id=7, process_name=process,
        rect=SimpleNamespace(left=0, top=0, right=600, bottom=500))
    return provider, bound, reads


def _tree(monkeypatch, *, process="msedge.exe", budget=4, navigation_label="Back"):
    provider, bound, _ = _provider_tree(monkeypatch, process=process, navigation_label=navigation_label)
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
    class Array:
        def __len__(self): return 10000
        def __getitem__(self, index):
            pulled.append(index)
            return _TreeWrapper((index + 2,), "Button", "tab", (index, 20, index + 1, 30), root)
    monkeypatch.setattr(module, "_finite_uia_children", lambda node: Array() if node is root else [])
    bound = SimpleNamespace(rect=SimpleNamespace(left=0, top=0))
    result = module.WindowsUIAProvider()._browser_chrome_scope(root, bound=bound, window={"handle": 42})
    assert result["scan_visited_count"] == 1000
    assert len(pulled) == 999
    assert result["scan_complete"] is False
    assert result["truncated"] is True


def test_chrome_scan_error_remains_unavailable(monkeypatch):
    root = _TreeWrapper((1,), "Window", "browser", (0, 0, 600, 500))
    def broken(**kw):
        raise RuntimeError("UIA traversal failed")
    root.iter_children = broken
    monkeypatch.setattr(module, "_finite_uia_children", lambda node: broken())
    bound = SimpleNamespace(rect=SimpleNamespace(left=0, top=0))
    result = module.WindowsUIAProvider()._browser_chrome_scope(root, bound=bound, window={})
    assert result["status"] == "ok"
    assert result["scan_complete"] is False
    assert result["traversal_errors"][0]["reason"] == "children_enumeration_failed"


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


@pytest.mark.parametrize("label", ["Back", "Forward", "Refresh", "Reload", "返回", "后退", "前进", "刷新"])
@pytest.mark.parametrize("marker", ["labelled", "labeled", "named"])
def test_quoted_toolbar_navigation_label_is_explicit(label, marker):
    assert explicit_browser_navigation_goal(f'Click the browser toolbar button {marker} "{label}"')


@pytest.mark.parametrize("goal", [
    "Click browser Back button", "Single-click the browser's Forward button",
    "Click the browser Refresh button", "Click the browser Reload button",
    "点击浏览器返回按钮", "点击浏览器工具栏的前进按钮", "点击浏览器后退按钮", "点击浏览器刷新按钮",
    "Click the browser toolbar button named 'Back'",
])
def test_existing_navigation_wording_and_paired_single_quote_remain_explicit(goal):
    assert explicit_browser_navigation_goal(goal)


@pytest.mark.parametrize("goal", [
    'Click the browser toolbar button labelled "Downloads"',
    'Click the browser toolbar button labelled "Back and Forward"',
    'Do not click the browser toolbar button labelled "Back"',
    'Click the browser toolbar button labelled "Back" in the page',
    'Click the browser toolbar button labelled "Back" (in the page body)',
    'Click the browser toolbar button labelled "Back" (the text mentioned in the article)',
    'Click the text "browser toolbar button labelled Back" in the article',
    'Click the search box below the browser toolbar button labelled "Back"',
    'Click the browser toolbar button labelled "Back" then click Search',
    'Click the browser toolbar button labelled "Back" and press Enter',
    'Click the browser toolbar button labelled "Back" or the Forward button',
    'Click the browser toolbar button labelled "Back", click Search',
    'Click the browser toolbar button labelled "Back" but do not navigate',
    'Click the browser toolbar button labelled "Back" to return while opening Settings',
    'Click the browser Back button then click Search',
    'Click the browser Back button text in the page',
    '点击浏览器返回按钮然后点击搜索',
])
def test_navigation_scope_rejects_non_target_or_multiple_actions(goal):
    assert explicit_browser_navigation_goal(goal) is False


@pytest.mark.parametrize("metadata", [None,
    {"task_plan_target": {"name": "返回", "control_type": "Button"}},
    {"control_target": {"label": "返回", "role": "button"}},
])
def test_edge09_quoted_toolbar_goal_uses_complete_chrome_only_without_structured_target(tmp_path, monkeypatch, metadata):
    snapshot = _tree(monkeypatch, navigation_label="返回")
    original = deepcopy(snapshot)
    goal = 'Click the browser toolbar button labelled "返回" at the top-left to return to the preceding search results page.'
    with module.pinned_uia_snapshot(snapshot):
        result = vision._execute_fast_inventory_from_uia(image_path=tmp_path / "frame.png",
            image_size=vision.ImageSize(width=600, height=500), app_name="Microsoft Edge", goal=goal, metadata=metadata)
    assert result["status"] == ("ready" if metadata is None else "incomplete")
    assert result["raw_uia_snapshot"].get("scan_scope", "bound_window") == ("browser_chrome" if metadata is None else "bound_window")
    if metadata is None:
        assert result["control_count"] == 1
        assert [c["name"] for c in result["raw_uia_snapshot"]["controls"] if c["control_type"] == "Button"] == ["返回"]
        assert result["screen_reading"]["source_layers"]["windows_uia"]["parent_scan_complete"] is False
    assert snapshot == original


def _fresh_inventory(tmp_path, monkeypatch, *, goal, metadata=None, process="msedge.exe", forbid_document=False):
    provider, bound, reads = _provider_tree(monkeypatch, process=process,
        navigation_label="返回", forbid_document=forbid_document)
    monkeypatch.setattr(module.window_manager, "get_bound_window", lambda: bound)
    monkeypatch.setattr(vision, "uia_provider", provider)
    result = vision._execute_fast_inventory_from_uia(image_path=tmp_path / "current-frame.png",
        image_size=vision.ImageSize(width=600, height=500), app_name="Microsoft Edge", goal=goal, metadata=metadata)
    return result, reads


NAVIGATION_GOAL = 'Click the browser toolbar button labelled "返回" at the top-left to return to the preceding search results page.'


def test_fresh_navigation_collects_chrome_without_first_walking_document(tmp_path, monkeypatch):
    result, reads = _fresh_inventory(tmp_path, monkeypatch, goal=NAVIGATION_GOAL, forbid_document=True)
    raw = result["raw_uia_snapshot"]
    assert result["status"] == "ready"
    assert raw["scan_scope"] == "browser_chrome"
    assert raw["scan_complete"] is True and raw["truncated"] is False
    assert raw["graph_scan_complete"] is True and raw["provider_tree_valid"] is True
    assert raw["scan_budget"] == 1000 and raw["scan_visited_count"] == 4
    assert raw["excluded_document_count"] == 1
    assert raw["window"]["handle"] == 42 and raw["window"]["process_id"] == 7
    assert raw.get("parent_scan_complete") is None
    assert reads == ["Window", "ToolBar", "Button"]
    assert result["screen_reading"]["image_path"] == str(tmp_path / "current-frame.png")
    assert result["browser_document_observation"]["status"] == "out_of_scope"


@pytest.mark.parametrize("goal,metadata,process", [
    ('Click the link labelled "返回" in the page', None, "msedge.exe"),
    ('Do not click the browser toolbar button labelled "返回"', None, "msedge.exe"),
    ('Click the search box below the browser toolbar button labelled "返回"', None, "msedge.exe"),
    (NAVIGATION_GOAL, {"task_plan_target": {"name": "返回", "control_type": "Button"}}, "msedge.exe"),
    (NAVIGATION_GOAL, {"control_target": {"label": "返回", "role": "button"}}, "msedge.exe"),
    (NAVIGATION_GOAL, None, "notepad.exe"),
])
def test_chrome_optimization_does_not_replace_other_current_window_scans(tmp_path, monkeypatch, goal, metadata, process):
    result, reads = _fresh_inventory(tmp_path, monkeypatch, goal=goal, metadata=metadata, process=process)
    assert result["raw_uia_snapshot"].get("scan_scope", "bound_window") == "bound_window"
    assert "Document" in reads


@pytest.mark.parametrize("defect", ["error", "truncation", "graph_conflict"])
def test_fresh_chrome_failure_does_not_trigger_full_document_fallback(tmp_path, monkeypatch, defect):
    provider, bound, reads = _provider_tree(monkeypatch, forbid_document=True)
    children = module._finite_uia_children
    def defective(node):
        original = children(node)
        if node.element_info.control_type == "ToolBar":
            if defect == "error":
                raise RuntimeError("synthetic chrome enumeration failure")
            if defect == "truncation":
                return [_TreeWrapper((100 + i,), "Button", "tab", (i, 20, i + 1, 30), node) for i in range(1000)]
            return [*original, _TreeWrapper((5,), "Button", "conflicting alias", (80, 20, 100, 40), node)]
        return original
    monkeypatch.setattr(module, "_finite_uia_children", defective)
    monkeypatch.setattr(module.window_manager, "get_bound_window", lambda: bound)
    monkeypatch.setattr(vision, "uia_provider", provider)
    result = vision._execute_fast_inventory_from_uia(image_path=tmp_path / "current-frame.png",
        image_size=vision.ImageSize(width=600, height=500), app_name="Microsoft Edge", goal=NAVIGATION_GOAL, metadata=None)
    raw = result["raw_uia_snapshot"]
    assert result["status"] == "incomplete" and result["screen_inventory"] is None
    assert raw["scan_scope"] == "browser_chrome" and raw["scan_complete"] is False
    assert raw.get("parent_scan_complete") is None and "Document" not in reads
    if defect == "truncation":
        assert raw["scan_budget"] == 1000 and raw["scan_visited_count"] == 1000
        assert raw["truncated"] is True and raw["truncation_reason"] == "control_budget_reached"
    else:
        assert raw["truncated"] is False and raw["traversal_errors"]


def test_fresh_chrome_projection_error_stays_unavailable_without_document_fallback(tmp_path, monkeypatch):
    provider, bound, reads = _provider_tree(monkeypatch, forbid_document=True)
    def broken_projection(*args, **kwargs):
        raise RuntimeError("synthetic chrome projection failure")
    monkeypatch.setattr(provider, "_control_from_wrapper", broken_projection)
    monkeypatch.setattr(module.window_manager, "get_bound_window", lambda: bound)
    monkeypatch.setattr(vision, "uia_provider", provider)
    result = vision._execute_fast_inventory_from_uia(image_path=tmp_path / "current-frame.png",
        image_size=vision.ImageSize(width=600, height=500), app_name="Microsoft Edge", goal=NAVIGATION_GOAL, metadata=None)
    assert result["status"] == "unavailable" and result["screen_inventory"] is None
    raw = result["raw_uia_snapshot"]
    assert raw["scan_scope"] == "browser_chrome" and raw["scan_complete"] is False
    assert raw["reason"] == "browser_chrome_scan_failed"
    assert raw["message"] == "synthetic chrome projection failure"
    assert raw.get("parent_scan_complete") is None and "Document" not in reads
