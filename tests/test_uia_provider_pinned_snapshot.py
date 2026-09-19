from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
from types import SimpleNamespace

import pytest

from app.operation.screen_reading import uia_provider as provider_module


def _snapshot(handle: int) -> dict:
    return {
        "provider": "windows_uia",
        "provider_version": "windows_uia_provider_v1",
        "status": "ok",
        "window": {
            "handle": handle,
            "process_id": handle + 100,
            "bbox": {"x": 0, "y": 0, "w": 320, "h": 200},
        },
        "control_count": 1,
        "controls": [{"control_id": f"control-{handle}"}],
    }


def test_pinned_snapshot_is_private_deep_copied_and_restores_fallback(monkeypatch) -> None:
    provider = provider_module.WindowsUIAProvider()
    fallback = _snapshot(99)
    monkeypatch.setattr(
        provider_module.window_manager,
        "get_bound_window",
        lambda: SimpleNamespace(handle=99),
    )
    monkeypatch.setattr(provider, "snapshot_window", lambda *_args, **_kwargs: deepcopy(fallback))
    supplied = _snapshot(42)

    with provider_module.pinned_uia_snapshot(supplied):
        supplied["controls"][0]["control_id"] = "caller-mutated"
        first = provider.snapshot_bound_window()
        first["controls"][0]["control_id"] = "consumer-mutated"
        second = provider.snapshot_bound_window()

    assert second["controls"][0]["control_id"] == "control-42"
    assert provider.snapshot_bound_window() == fallback


def test_pinned_snapshot_is_isolated_between_concurrent_contexts() -> None:
    provider = provider_module.WindowsUIAProvider()
    barrier = Barrier(2)

    def read(handle: int) -> int:
        with provider_module.pinned_uia_snapshot(_snapshot(handle)):
            barrier.wait()
            return int(provider.snapshot_bound_window()["window"]["handle"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(read, [11, 22])) == [11, 22]



class _TreeWrapper:
    def __init__(self, runtime_id, control_type, name, rect, parent=None):
        self.element_info = SimpleNamespace(
            runtime_id=runtime_id,
            control_type=control_type,
            name=name,
            automation_id=name,
            class_name=control_type,
            rich_text=None,
        )
        self._rect = SimpleNamespace(left=rect[0], top=rect[1], right=rect[2], bottom=rect[3])
        self._parent = parent

    def rectangle(self):
        return self._rect

    def wrapper_object(self):
        return self

    def parent(self):
        return self._parent

    def window_text(self):
        return self.element_info.name

    def is_enabled(self):
        return True

    def is_visible(self):
        return True

    def friendly_class_name(self):
        return self.element_info.control_type


def test_snapshot_records_only_runtime_confirmed_parent_chain(monkeypatch) -> None:
    root = _TreeWrapper((1,), "Document", "root", (10, 20, 610, 420))
    group = _TreeWrapper((2,), "Group", "page", (20, 30, 600, 410), root)
    field = _TreeWrapper((3,), "ComboBox", "search", (100, 80, 300, 120), group)
    root.iter_descendants = lambda: iter([group, field])
    fake_pywinauto = SimpleNamespace(Desktop=lambda **_kwargs: SimpleNamespace(window=lambda **_args: root))
    monkeypatch.setitem(__import__("sys").modules, "pywinauto", fake_pywinauto)
    bound = SimpleNamespace(
        handle=42,
        title="test",
        process_id=7,
        process_name="test.exe",
        rect=SimpleNamespace(left=10, top=20, right=610, bottom=420),
    )

    snapshot = provider_module.WindowsUIAProvider().snapshot_window(bound)
    controls = {item["name"]: item for item in snapshot["controls"]}

    assert controls["root"]["ancestor_control_ids"] == []
    assert controls["page"]["ancestor_control_ids"] == ["uia_0_root"]
    assert controls["search"]["ancestor_control_ids"] == ["uia_1_page", "uia_0_root"]
    assert controls["search"]["runtime_id"] == [3]


def test_snapshot_drops_cycle_or_duplicate_runtime_parent_chain(monkeypatch) -> None:
    root = _TreeWrapper((1,), "Document", "root", (10, 20, 610, 420))
    first = _TreeWrapper((2,), "Group", "first", (20, 30, 600, 410), root)
    duplicate = _TreeWrapper((2,), "ComboBox", "field", (100, 80, 300, 120), first)
    root.iter_descendants = lambda: iter([first, duplicate])
    fake_pywinauto = SimpleNamespace(Desktop=lambda **_kwargs: SimpleNamespace(window=lambda **_args: root))
    monkeypatch.setitem(__import__("sys").modules, "pywinauto", fake_pywinauto)
    bound = SimpleNamespace(
        handle=42,
        title="test",
        process_id=7,
        process_name="test.exe",
        rect=SimpleNamespace(left=10, top=20, right=610, bottom=420),
    )

    snapshot = provider_module.WindowsUIAProvider().snapshot_window(bound)
    controls = {item["name"]: item for item in snapshot["controls"]}
    assert controls["field"]["ancestor_control_ids"] == []



def test_runtime_confirmed_group_ancestor_allows_only_fill_field_overlap(monkeypatch) -> None:
    from app.gate.fresh_action_risk import classify_fresh_action_risk
    from tests.test_fresh_action_risk import _candidate, _local

    root = _TreeWrapper((1,), "Document", "root", (10, 20, 810, 620))
    group = _TreeWrapper((2,), "Group", "page", (10, 20, 810, 620), root)
    field = _TreeWrapper((3,), "ComboBox", "search", (110, 100, 270, 150), group)
    group.iface_invoke = object()
    field.iface_value = object()
    field.iface_text = object()
    root.iter_descendants = lambda: iter([group, field])
    fake_pywinauto = SimpleNamespace(Desktop=lambda **_kwargs: SimpleNamespace(window=lambda **_args: root))
    monkeypatch.setitem(__import__("sys").modules, "pywinauto", fake_pywinauto)
    bound = SimpleNamespace(
        handle=42,
        title="test",
        process_id=7,
        process_name="test.exe",
        rect=SimpleNamespace(left=10, top=20, right=810, bottom=620),
    )
    snapshot = provider_module.WindowsUIAProvider().snapshot_window(bound)
    candidate = _candidate("search", role="input")

    result = classify_fresh_action_risk(
        proposed_semantic_action="fill_field",
        goal="Fill search",
        candidate=candidate,
        local=_local(candidate),
        capture_id="fresh-capture.0123456789abcdef",
        uia_snapshot=snapshot,
    )

    assert result["hard_blocked"] is False
    assert result["risk_class"] == "low_risk_text_input"


def test_snapshot_drops_cyclic_runtime_parent_chain(monkeypatch) -> None:
    root = _TreeWrapper((1,), "Document", "root", (10, 20, 610, 420))
    group = _TreeWrapper((2,), "Group", "page", (20, 30, 600, 410))
    field = _TreeWrapper((3,), "ComboBox", "field", (100, 80, 300, 120), group)
    group._parent = field
    root.iter_descendants = lambda: iter([group, field])
    fake_pywinauto = SimpleNamespace(Desktop=lambda **_kwargs: SimpleNamespace(window=lambda **_args: root))
    monkeypatch.setitem(__import__("sys").modules, "pywinauto", fake_pywinauto)
    bound = SimpleNamespace(
        handle=42,
        title="test",
        process_id=7,
        process_name="test.exe",
        rect=SimpleNamespace(left=10, top=20, right=610, bottom=420),
    )

    snapshot = provider_module.WindowsUIAProvider().snapshot_window(bound)
    controls = {item["name"]: item for item in snapshot["controls"]}
    assert controls["page"]["ancestor_control_ids"] == []
    assert controls["field"]["ancestor_control_ids"] == []



def _tree_snapshot(monkeypatch, root, descendants):
    root.iter_descendants = lambda: iter(descendants)
    fake_pywinauto = SimpleNamespace(Desktop=lambda **_kwargs: SimpleNamespace(window=lambda **_args: root))
    monkeypatch.setitem(__import__("sys").modules, "pywinauto", fake_pywinauto)
    bound = SimpleNamespace(
        handle=42,
        title="test",
        process_id=7,
        process_name="test.exe",
        rect=SimpleNamespace(left=10, top=20, right=810, bottom=620),
    )
    return provider_module.WindowsUIAProvider().snapshot_window(bound)


def test_snapshot_keeps_only_confirmed_prefix_when_group_parent_is_uncollected(monkeypatch) -> None:
    root = _TreeWrapper((1,), "Document", "root", (10, 20, 810, 620))
    uncollected = _TreeWrapper((9,), "Pane", "outside", (10, 20, 810, 620))
    group = _TreeWrapper((2,), "Group", "page", (10, 20, 810, 620), uncollected)
    field = _TreeWrapper((3,), "ComboBox", "field", (110, 100, 270, 150), group)

    snapshot = _tree_snapshot(monkeypatch, root, [group, field])
    controls = {item["name"]: item for item in snapshot["controls"]}

    # group 的未知上层未被当作根或写入；field→group 这一条直接关系仍由 runtime_id 确认。
    assert controls["page"]["ancestor_control_ids"] == []
    assert controls["field"]["ancestor_control_ids"] == ["uia_1_page"]


@pytest.mark.parametrize("case", ["missing_intermediate", "duplicate_parent", "parent_error"])
def test_snapshot_never_skips_unconfirmed_parent_between_field_and_group(monkeypatch, case) -> None:
    root = _TreeWrapper((1,), "Document", "root", (10, 20, 810, 620))
    group = _TreeWrapper((2,), "Group", "page", (10, 20, 810, 620), root)
    field = _TreeWrapper((3,), "ComboBox", "field", (110, 100, 270, 150), group)
    descendants = [group, field]
    if case == "missing_intermediate":
        middle = _TreeWrapper((4,), "Pane", "middle", (20, 30, 800, 610), group)
        field._parent = middle
    elif case == "duplicate_parent":
        duplicate = _TreeWrapper((2,), "Group", "duplicate", (30, 40, 790, 600), root)
        descendants.insert(1, duplicate)
    else:
        def broken_parent():
            raise RuntimeError("parent unavailable")
        field.parent = broken_parent

    group.iface_invoke = object()
    field.iface_value = object()
    field.iface_text = object()
    snapshot = _tree_snapshot(monkeypatch, root, descendants)
    controls = {item["name"]: item for item in snapshot["controls"]}

    assert controls["field"]["ancestor_control_ids"] == []
    from app.gate.fresh_action_risk import classify_fresh_action_risk
    from tests.test_fresh_action_risk import _candidate, _local

    candidate = _candidate("field", role="input")
    result = classify_fresh_action_risk(
        proposed_semantic_action="fill_field",
        goal="Fill field",
        candidate=candidate,
        local=_local(candidate),
        capture_id="fresh-capture.0123456789abcdef",
        uia_snapshot=snapshot,
    )
    assert result["hard_blocked"] is True
    assert "editable_text_field_overlaps_actionable_control" in result["reasons"]
