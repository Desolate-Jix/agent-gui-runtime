from types import SimpleNamespace

import pytest

from app.operation.screen_reading.uia_content import WindowsUIAContentReader


class Rect:
    def __init__(self, x, y, w, h):
        self.left, self.top, self.right, self.bottom = x, y, x + w, y + h


class Range:
    def __init__(self, text, calls):
        self.text, self.calls = text, calls

    def GetText(self, count):
        self.calls.append(count)
        return self.text[:count]


class Control:
    def __init__(self, name, typ, x, y, text=None, children=None, runtime_id=(1,)):
        self.element_info = SimpleNamespace(name=name, control_type=typ, automation_id=name + "-id", runtime_id=runtime_id)
        self._rect = Rect(x, y, 100, 40)
        self._children = children or []
        self.calls = []
        if text is not None:
            self.iface_text = SimpleNamespace(DocumentRange=Range(text, self.calls))

    def rectangle(self):
        return self._rect

    def descendants(self):
        return self._children

    def children(self):
        return self._children

    def is_visible(self):
        return True

    def window_text(self):
        return self.element_info.name


class Desktop:
    def __init__(self, root):
        self.root = root

    def window(self, handle):
        return SimpleNamespace(wrapper_object=lambda: self.root)


def bound(pid=7):
    return SimpleNamespace(handle=99, process_id=pid, rect=SimpleNamespace(left=0, top=0, right=500, bottom=500))


def make_reader(root):
    return WindowsUIAContentReader(lambda **_: Desktop(root))


def test_method_identity_values_are_stable_across_wrapper_reacquisition():
    def desktop(**kwargs):
        root = Control("正文", "Document", 1, 1, text="中文正文")
        root.handle = 99
        root.process_id = lambda: 7
        root.element_info.process_id = lambda: 7
        root.element_info.automation_id = lambda: "stable-document"
        return Desktop(root)
    reader = WindowsUIAContentReader(desktop)
    ref = reader.inspect_regions(bound())["regions"][0]["reference"]
    assert ref["pid"] == 7 and ref["automation_id"] == "stable-document"
    assert reader.read_region(bound(), ref)["text"] == "中文正文"


def test_long_unicode_text_uses_document_range_and_preserves_last_marker():
    marker = "终点标记"
    text = "中文内容" * 100 + marker
    control = Control("doc", "Document", 10, 10, text=text)
    reader = make_reader(control)
    region = reader.inspect_regions(bound())["regions"][0]
    result = reader.read_region(bound(), region["reference"], max_chars=len(text))
    assert result["text"].endswith(marker)
    assert result["read_complete"] is True
    assert control.calls[-1] == 2 * (len(text) + 1)


def test_utf16_provider_cannot_hide_truncation_behind_supplementary_characters():
    root = Control("正文", "Document", 1, 1, text="unused")
    class Utf16Range:
        def GetText(self, count):
            return ("😀" * 10).encode("utf-16-le")[:count * 2].decode("utf-16-le")
    root.iface_text.DocumentRange = Utf16Range()
    reader = make_reader(root)
    ref = reader.inspect_regions(bound())["regions"][0]["reference"]
    result = reader.read_region(bound(), ref, max_chars=3)
    assert result["text"] == "😀" * 3
    assert result["truncated"] and not result["read_complete"]


def test_document_range_truncates_with_explicit_basis():
    control = Control("doc", "Document", 10, 10, text="abcdef")
    reader = make_reader(control)
    ref = reader.inspect_regions(bound())["regions"][0]["reference"]
    result = reader.read_region(bound(), ref, max_chars=3)
    assert result["text"] == "abc"
    assert result["truncated"] is True and result["read_complete"] is False


def test_changed_pid_and_ambiguous_reference_are_rejected():
    c = Control("doc", "Document", 10, 10, text="x")
    reader = make_reader(c)
    ref = reader.inspect_regions(bound())["regions"][0]["reference"]
    with pytest.raises(ValueError, match="unknown, changed, or ambiguous"):
        reader.read_region(bound(pid=8), ref)
    duplicate = Control("doc", "Document", 10, 10, text="x", runtime_id=(1,))
    root = Control("root", "Window", 0, 0, children=[c, duplicate])
    reader = make_reader(root)
    with pytest.raises(ValueError, match="unknown, changed, or ambiguous"):
        reader.read_region(bound(), ref)


def test_descendant_fallback_is_partial_and_does_not_call_input():
    child = Control("段落", "Text", 20, 20)
    parent = Control("pane", "Pane", 10, 10, children=[child])
    reader = make_reader(parent)
    ref = reader.inspect_regions(bound())["regions"][0]["reference"]
    result = reader.read_region(bound(), ref, max_chars=200)
    assert result["method"] == "descendant_text"
    assert result["read_complete"] is False
    assert result["completion_basis"] == "descendant_inventory_not_proof_of_complete_content"
    assert not any(name in vars(parent) for name in ("click", "set_focus", "scroll", "set_value"))


def test_limits_and_unknown_reference_are_clear():
    reader = make_reader(Control("doc", "Document", 1, 1, text="x"))
    with pytest.raises(ValueError):
        reader.inspect_regions(bound(), 0)
    with pytest.raises(ValueError):
        reader.read_region(bound(), {}, 0)


def test_no_pattern_is_not_an_error_and_get_text_error_is_not_a_fallback():
    class NoPattern:
        def __getattr__(self, name):
            if name == "iface_text":
                raise type("NoPatternInterfaceError", (Exception,), {})()
            raise AttributeError(name)
        element_info = SimpleNamespace(name="pane", control_type="Pane", automation_id="x", runtime_id=(2,))
        def rectangle(self): return Rect(1, 1, 20, 20)
        def children(self): return []
        def is_visible(self): return True
        def window_text(self): return "pane"

    class Broken(Control):
        def __init__(self):
            super().__init__("doc", "Document", 1, 1, text="unused")
            self.iface_text = SimpleNamespace(DocumentRange=SimpleNamespace(GetText=lambda _: (_ for _ in ()).throw(RuntimeError("provider"))))

    assert make_reader(NoPattern()).inspect_regions(bound())["regions"][0]["reader"] == "uia_descendant_text"
    reader = make_reader(Broken())
    ref = reader.inspect_regions(bound())["regions"][0]["reference"]
    with pytest.raises(RuntimeError, match="GetText failed"):
        reader.read_region(bound(), ref)

    broken_pattern = Control("doc", "Document", 1, 1)
    broken_pattern.iface_text = SimpleNamespace(DocumentRange=None)
    with pytest.raises(RuntimeError, match="DocumentRange"):
        make_reader(broken_pattern).inspect_regions(bound())


def test_long_name_is_display_truncated_but_fingerprint_detects_suffix_change():
    first = Control("A" * 200 + "one", "Document", 1, 1, text="x")
    reader = make_reader(first)
    region = reader.inspect_regions(bound())["regions"][0]
    assert len(region["name"]) == 200
    changed = Control("A" * 200 + "two", "Document", 1, 1, text="x")
    with pytest.raises(ValueError):
        make_reader(changed).read_region(bound(), region["reference"])


def test_bfs_tree_is_finite_and_reports_scan_truncation():
    children = [Control(str(i), "Document", 1, 1, text="x") for i in range(4100)]
    root = Control("root", "Window", 0, 0, children=children)
    result = make_reader(root).inspect_regions(bound(), max_regions=80)
    assert result["truncated"] is True
    assert len(result["regions"]) == 80


def test_root_identity_and_read_truncated_tree_are_rejected():
    root = Control("root", "Window", 0, 0, text="x")
    root.handle, root.process_id = 100, 7
    reader = make_reader(root)
    root_bound = bound()
    root_bound.handle = 100
    ref = reader.inspect_regions(root_bound)["regions"][0]["reference"]
    root.process_id = 8
    with pytest.raises(ValueError, match="PID"):
        reader.read_region(root_bound, ref)

    class Failing(Control):
        def children(self):
            raise RuntimeError("stale")
    with pytest.raises(RuntimeError, match="child enumeration"):
        make_reader(Failing("x", "Pane", 1, 1)).inspect_regions(bound())

    huge = Control("root", "Window", 0, 0, children=[Control(str(i), "Document", 1, 1, text="x") for i in range(4100)])
    reader = make_reader(huge)
    ref = reader.inspect_regions(bound())["regions"][0]["reference"]
    with pytest.raises(ValueError, match="truncated enumeration"):
        reader.read_region(bound(), ref)
