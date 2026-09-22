from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from app.operation.screen_reading import uia_provider as provider_module


class _Node:
    def __init__(self, name, runtime_id, parent=None, *, width=100):
        self.element_info = SimpleNamespace(
            name=name,
            runtime_id=(runtime_id,),
            control_type="Pane",
            automation_id=name,
            class_name="Pane",
        )
        self._parent = parent
        self._rect = SimpleNamespace(left=20, top=30, right=20 + width, bottom=70)
        self.children = []

    def rectangle(self):
        return self._rect

    def window_text(self):
        return self.element_info.name

    def parent(self):
        return self._parent


class _Root(_Node):
    def __init__(self, *, flat_count=None, fail_after=None):
        super().__init__("root", 1)
        self.flat_count = flat_count
        self.fail_after = fail_after
        self.eager_calls = 0
        self.yielded = 0

    def _walk(self, node):
        for child in node.children:
            yield child
            yield from self._walk(child)

    def iter_descendants(self):
        if self.flat_count is None:
            descendants = self._walk(self)
        else:
            descendants = (
                _Node(f"child_{index}", index + 2, self)
                for index in range(self.flat_count)
            )
        for child in descendants:
            if self.fail_after is not None and self.yielded == self.fail_after:
                raise RuntimeError("synthetic iterator failure")
            self.yielded += 1
            yield child

    def descendants(self):
        self.eager_calls += 1
        return list(self.iter_descendants())


class _WindowSpecification:
    def __init__(self, root, *, error=None):
        self.root = root
        self.error = error
        self.resolutions = 0

    def wrapper_object(self):
        self.resolutions += 1
        if self.error is not None:
            raise self.error
        return self.root

    def __getattr__(self, name):
        return getattr(self.wrapper_object(), name)


def _install_desktop(monkeypatch, root, *, error=None):
    from app.operation.screen_reading.uia_graph import CanonicalUIAGraph
    monkeypatch.setattr(provider_module, "CanonicalUIAGraph", lambda node: CanonicalUIAGraph(node,
        identity=lambda current: (current.element_info.runtime_id, 7, "Pane", None, None, 42),
        parent=lambda current: current._parent.element_info.runtime_id if current._parent else None,
        compare=lambda left, right: left is right))
    class Children:
        def __init__(self, node): self.node = node
        def __len__(self):
            return root.flat_count if self.node is root and root.flat_count is not None else len(self.node.children)
        def __getitem__(self, index):
            if root.fail_after is not None and root.yielded == root.fail_after:
                raise RuntimeError("synthetic iterator failure")
            root.yielded += 1
            return (_Node(f"child_{index}", index + 2, root)
                    if self.node is root and root.flat_count is not None else self.node.children[index])
    monkeypatch.setattr(provider_module, "_finite_uia_children", Children)
    spec = _WindowSpecification(root, error=error)
    calls = []

    def desktop(*, backend):
        calls.append(("backend", backend))

        def window(*, handle):
            calls.append(("handle", handle))
            return spec

        return SimpleNamespace(window=window)

    monkeypatch.setitem(sys.modules, "pywinauto", SimpleNamespace(Desktop=desktop))
    return spec, calls


def _bound():
    return SimpleNamespace(
        handle=42,
        title="synthetic bounded scan",
        process_id=7,
        process_name="synthetic.exe",
        rect=SimpleNamespace(left=10, top=20, right=610, bottom=420),
    )


def test_default_snapshot_only_pulls_999_of_10000_descendants(monkeypatch):
    root = _Root(flat_count=10_000)
    spec, calls = _install_desktop(monkeypatch, root)

    snapshot = provider_module.WindowsUIAProvider().snapshot_window(_bound())

    assert snapshot["status"] == "ok"
    assert snapshot["control_count"] == 1000
    assert root.yielded == 999
    assert snapshot["truncated"] is True
    assert snapshot["scan_complete"] is False
    assert root.eager_calls == 0
    assert spec.resolutions == 1
    assert calls == [("backend", "uia"), ("handle", 42)]
    assert snapshot["controls"][-1]["control_id"] == "uia_999_child_998"


@pytest.mark.parametrize("limit,expected_children", [(-3, 0), (0, 0), (1, 0), (2, 1), (8, 7)])
def test_scan_limit_counts_root_and_preserves_root_only_boundary(monkeypatch, limit, expected_children):
    root = _Root(flat_count=10_000)
    _install_desktop(monkeypatch, root)

    snapshot = provider_module.WindowsUIAProvider().snapshot_window(_bound(), max_controls=limit)

    assert snapshot["status"] == "ok"
    assert root.yielded == expected_children
    assert root.eager_calls == 0
    assert snapshot["control_count"] == expected_children + 1
    assert snapshot["controls"][0]["control_id"] == "uia_0_root"


@pytest.mark.parametrize("count", [0, 1, 3])
def test_exhausted_tree_still_returns_all_available_controls(monkeypatch, count):
    root = _Root(flat_count=count)
    _install_desktop(monkeypatch, root)

    snapshot = provider_module.WindowsUIAProvider().snapshot_window(_bound(), max_controls=10)

    assert snapshot["status"] == "ok"
    assert snapshot["control_count"] == count + 1
    assert root.yielded == count


def test_depth_first_prefix_keeps_control_ids_and_confirmed_ancestors(monkeypatch):
    root = _Root()
    group = _Node("group", 2, root)
    field = _Node("field", 3, group)
    nested = _Node("nested", 4, field)
    sibling = _Node("sibling", 5, root)
    root.children = [group, sibling]
    group.children = [field]
    field.children = [nested]
    _install_desktop(monkeypatch, root)

    snapshot = provider_module.WindowsUIAProvider().snapshot_window(_bound(), max_controls=4)

    assert [item["control_id"] for item in snapshot["controls"]] == [
        "uia_0_root", "uia_1_group", "uia_2_field", "uia_3_nested",
    ]
    assert snapshot["controls"][-1]["ancestor_control_ids"] == [
        "uia_2_field", "uia_1_group", "uia_0_root",
    ]
    assert snapshot["controls"][-1]["runtime_id"] == [4]
    assert snapshot["controls"][-1]["bbox"] == {"x": 10, "y": 10, "w": 100, "h": 40}
    assert root.yielded == 3


def test_invalid_control_still_consumes_budget_without_renumbering(monkeypatch):
    root = _Root()
    root.children = [
        _Node("invalid", 2, root, width=0),
        _Node("valid", 3, root),
        _Node("outside_budget", 4, root),
    ]
    _install_desktop(monkeypatch, root)

    snapshot = provider_module.WindowsUIAProvider().snapshot_window(_bound(), max_controls=3)

    assert [item["control_id"] for item in snapshot["controls"]] == ["uia_0_root", "uia_2_valid"]
    assert root.yielded == 2


def test_error_beyond_budget_is_never_requested(monkeypatch):
    root = _Root(flat_count=10_000, fail_after=2)
    _install_desktop(monkeypatch, root)

    snapshot = provider_module.WindowsUIAProvider().snapshot_window(_bound(), max_controls=3)

    assert snapshot["status"] == "ok"
    assert snapshot["control_count"] == 3
    assert root.yielded == 2


@pytest.mark.parametrize("failure", ["resolve", "iterate"])
def test_scan_error_returns_explicit_unavailable_not_partial_success(monkeypatch, failure):
    root = _Root(flat_count=10, fail_after=1 if failure == "iterate" else None)
    error = RuntimeError("synthetic resolve failure") if failure == "resolve" else None
    _install_desktop(monkeypatch, root, error=error)

    snapshot = provider_module.WindowsUIAProvider().snapshot_window(_bound())

    if failure == "resolve":
        assert snapshot["status"] == "unavailable"
        assert snapshot["reason"] == "uia_scan_failed"
        assert "synthetic" in snapshot["message"]
        assert snapshot["control_count"] == 0
    else:
        assert snapshot["scan_complete"] is False
        assert snapshot["traversal_errors"][0]["reason"] == "children_enumeration_failed"
        assert "synthetic" in snapshot["traversal_errors"][0]["message"]


def test_pinned_snapshot_does_not_resolve_or_scan_and_is_deep_copied(monkeypatch):
    root = _Root(flat_count=10_000)
    spec, calls = _install_desktop(monkeypatch, root)

    def unexpected_bound_lookup():
        pytest.fail("pinned snapshot must not read a live bound window")

    monkeypatch.setattr(provider_module.window_manager, "get_bound_window", unexpected_bound_lookup)
    supplied = {"status": "ok", "control_count": 1, "controls": [{"name": "固定界面"}]}
    provider = provider_module.WindowsUIAProvider()

    with provider_module.pinned_uia_snapshot(supplied):
        supplied["controls"][0]["name"] = "外部修改"
        first = provider.snapshot_bound_window(max_controls=1)
        first["controls"][0]["name"] = "读取方修改"
        assert provider.snapshot_bound_window()["controls"][0]["name"] == "固定界面"

    assert spec.resolutions == 0
    assert root.yielded == 0
    assert calls == []
