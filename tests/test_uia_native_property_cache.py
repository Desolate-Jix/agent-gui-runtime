"""原生属性缓存只覆盖本帧投影，真实接口与有限图守卫继续有效。"""
from types import SimpleNamespace as NS

import pytest

from app.operation.screen_reading import uia_provider as provider
from app.operation.screen_reading.uia_cache import NativeUIACache, UIACacheError, _read_native_pattern


class NoPattern(Exception):
    pass


NAMES = (
    "RuntimeId", "ProcessId", "FrameworkId", "NativeWindowHandle", "Name", "ControlType",
    "AutomationId", "ClassName", "BoundingRectangle", "IsEnabled", "IsOffscreen", "IsPassword",
    "IsKeyboardFocusable", "HasKeyboardFocus", "ScrollVerticallyScrollable", "ScrollHorizontallyScrollable",
    *["Is" + name + "PatternAvailable" for name in
      ("Invoke", "Value", "Text", "Selection", "SelectionItem", "ExpandCollapse", "Toggle", "Scroll")],
)
IDS = {name: index + 100 for index, name in enumerate(NAMES)}
NOT_SUPPORTED = object()


class Array:
    def __init__(self, values):
        self.values = values
        self.Length = len(values)
        self.reads = []

    def GetElement(self, index):
        self.reads.append(index)
        return self.values[index]


class Element:
    def __init__(self, rid, *, name="field", kind=1, parent=None, text=None):
        self.values = {name: NOT_SUPPORTED for name in NAMES}
        self.values.update(RuntimeId=(rid,), ProcessId=7, FrameworkId="synthetic", NativeWindowHandle=0,
            Name=name, ControlType=kind, AutomationId="id-" + str(rid), ClassName="synthetic",
            BoundingRectangle=(20.0, 30.0, 100.0, 40.0), IsEnabled=True, IsOffscreen=False)
        self.parent_node, self.children, self.text = parent, [], text
        self.interfaces = {}
        if text is not None:
            self.interfaces["Text"] = NS(DocumentRange=NS(GetText=lambda count: text))
        self.cached_reads, self.child_calls, self.root_calls, self.pattern_reads = [], [], [], []
        self.child_arrays = []

    @property
    def CurrentProcessId(self):
        return self.values["ProcessId"]

    @property
    def CurrentFrameworkId(self):
        return self.values["FrameworkId"]

    @property
    def CurrentNativeWindowHandle(self):
        return self.values["NativeWindowHandle"]

    def BuildUpdatedCache(self, request):
        self.root_calls.append(request)
        return self

    def FindAllBuildCache(self, scope, condition, request):
        self.child_calls.append((scope, condition, request))
        array = Array(self.children)
        self.child_arrays.append(array)
        return array

    def GetCachedPropertyValueEx(self, property_id, ignore_default):
        self.cached_reads.append((property_id, ignore_default))
        value = self.values[next(name for name, identity in IDS.items() if identity == property_id)]
        if isinstance(value, Exception):
            raise value
        return value


class Request:
    def __init__(self):
        self.properties = []

    def AddProperty(self, value):
        self.properties.append(value)


def api():
    dll = NS(**{"UIA_" + name + "PropertyId": value for name, value in IDS.items()})
    control_view, true = object(), object()
    return NS(UIA_dll=dll, tree_scope={"element": 1, "children": 2}, true_condition=true,
        known_control_type_ids={1: "Pane", 2: "Edit", 3: "Text", 4: "Document", 5: "Menu", 6: "MenuItem", 7: "ComboBox"},
        iuia=NS(CreateCacheRequest=Request, ControlViewCondition=control_view,
            CheckNotSupported=lambda value: value is NOT_SUPPORTED,
            CompareElements=lambda left, right: left is right,
            ControlViewWalker=NS(GetParentElement=lambda element: element.parent_node)))


class LiveWrapper:
    def __init__(self, element):
        self.element_info = NS(element=element, runtime_id=element.values["RuntimeId"],
            process_id=element.values["ProcessId"], control_type=api().known_control_type_ids.get(element.values["ControlType"], "unsupported"))

    def top_level_parent(self):
        return NS(element_info=NS(handle=42))

    def parent(self):
        value = self.element_info.element.parent_node
        return LiveWrapper(value) if value is not None else None


def pattern(element, name):
    element.pattern_reads.append(name)
    value = element.interfaces.get(name)
    if isinstance(value, Exception):
        raise value
    if value is None:
        raise NoPattern(name)
    return value


def cache(automation=None):
    return NativeUIACache(api=automation or api(), wrap=LiveWrapper,
        read_pattern=pattern, no_pattern_error=NoPattern)


def bound():
    return NS(handle=42, title="fresh", process_id=7, process_name="synthetic.exe",
        rect=NS(left=10, top=20, right=610, bottom=420))


def install(monkeypatch, root, *, popup=None, automation=None):
    import sys
    automation = automation or api()
    monkeypatch.setitem(sys.modules, "pywinauto", NS(Desktop=lambda **kwargs:
        NS(window=lambda **kwargs: NS(wrapper_object=lambda: LiveWrapper(
            popup if popup is not None and kwargs["handle"] == 43 else root)))))
    monkeypatch.setitem(sys.modules, "pywinauto.uia_defines", NS(IUIA=lambda: automation))
    monkeypatch.setitem(sys.modules, "pywinauto.uia_element_info", NS(UIAElementInfo=lambda raw: LiveWrapper(raw).element_info))
    monkeypatch.setattr(provider, "_cached_uia_root", lambda wrapper: cache(automation).root(wrapper))
    monkeypatch.setattr(provider.WindowsUIAProvider, "_owned_popup_handles", staticmethod(lambda value: [43] if popup else []))


def test_native_request_keeps_element_mode_full_and_current_child_range():
    automation = api()
    root = Element(1)
    child = Element(2, parent=root)
    root.children = [child]
    snapshot = cache(automation)
    wrapped = snapshot.root(LiveWrapper(root))
    children = wrapped.cached_children()
    assert children[0].element_info.name == "field"
    request = root.root_calls[0]
    assert request.TreeScope == automation.tree_scope["element"]
    assert request.TreeFilter is automation.iuia.ControlViewCondition
    assert request.AutomationElementMode == 1
    assert request.properties == list(IDS.values())
    assert root.child_calls == [(2, automation.true_condition, request)]
    assert len(child.cached_reads) == len(NAMES)
    assert all(ignore_default is True for _, ignore_default in child.cached_reads)


def test_cached_projection_preserves_name_rich_text_and_real_patterns():
    source = Element(1, name="label", kind=3, text="中文正文 UTF-8")
    source.values["IsInvokePatternAvailable"] = True
    source.values["IsTextPatternAvailable"] = True
    node = cache().root(LiveWrapper(source))
    control = provider.WindowsUIAProvider()._control_from_wrapper(node, bound=bound(), index=0)
    assert control.name == "中文正文 UTF-8"
    assert control.patterns == ("Text",)
    assert source.pattern_reads.count("Text") == 1
    assert source.pattern_reads.count("Invoke") == 1
    assert len(source.cached_reads) == len(NAMES)


def test_edit_name_does_not_become_mutable_value_and_scroll_uses_cache():
    source = Element(1, name="Address", kind=2, text="mutable input")
    source.interfaces["Scroll"] = NS()
    source.values.update(ScrollVerticallyScrollable=True, ScrollHorizontallyScrollable=NOT_SUPPORTED)
    node = cache().root(LiveWrapper(source))
    control = provider.WindowsUIAProvider()._control_from_wrapper(node, bound=bound(), index=0)
    assert control.name == "Address"
    assert control.scroll_axes == {"current_vertical": True, "current_horizontal": None}


@pytest.mark.parametrize("field,value", [
    ("Name", object()), ("RuntimeId", NOT_SUPPORTED), ("RuntimeId", (1, True)),
    ("ProcessId", 0), ("ControlType", 999), ("BoundingRectangle", (0, 0, float("nan"), 10)),
    ("IsEnabled", "true"),
])
def test_invalid_or_opaque_cached_values_never_fall_back_to_current(field, value):
    element = Element(1)
    element.values[field] = value
    with pytest.raises(UIACacheError):
        cache().root(LiveWrapper(element))


def test_optional_not_supported_stays_unknown_without_forged_false():
    element = Element(1)
    element.values.update(ScrollVerticallyScrollable=NOT_SUPPORTED, ScrollHorizontallyScrollable=NOT_SUPPORTED)
    node = cache().root(LiveWrapper(element))
    assert node.scroll_axes() == {"current_vertical": None, "current_horizontal": None}


@pytest.mark.parametrize("field", ["RuntimeId", "ProcessId", "ControlType", "BoundingRectangle", "IsEnabled", "IsOffscreen"])
def test_required_cached_miss_is_explicitly_unavailable(monkeypatch, field):
    element = Element(1)
    element.values[field] = NOT_SUPPORTED
    install(monkeypatch, element)
    result = provider.WindowsUIAProvider().snapshot_window(bound())
    assert result["status"] == "unavailable" and result["controls"] == []
    assert result["scan_complete"] is False
    assert result["acquisition_mode"] == "native_cache_per_parent.v1"
    assert result["cache_error_count"] == 1
    assert result["cache_errors"] == [{"reason": "cached_property_unavailable", "property": field}]


def test_com_property_failure_is_unavailable_not_previous_snapshot(monkeypatch):
    root = Element(1)
    install(monkeypatch, root)
    first = provider.WindowsUIAProvider().snapshot_window(bound())
    assert first["status"] == "ok"
    assert first["scan_complete"] is True
    assert first["acquisition_mode"] == "native_cache_per_parent.v1"
    assert first["cache_error_count"] == 0
    root.values["Name"] = OSError("synthetic stale element")
    second = provider.WindowsUIAProvider().snapshot_window(bound())
    assert second["status"] == "unavailable"
    assert second["controls"] == []
    assert second["scan_complete"] is False and second["cache_error_count"] == 1
    assert second["cache_errors"][0]["property"] == "Name"
    assert first["controls"][0]["name"] == "field"


def test_children_property_failure_keeps_explicit_incomplete_scan(monkeypatch):
    root = Element(1)
    child = Element(2, parent=root)
    child.values["Name"] = OSError("synthetic provider failure")
    root.children = [child]
    install(monkeypatch, root)
    result = provider.WindowsUIAProvider().snapshot_window(bound())
    assert result["scan_complete"] is False
    assert result["traversal_errors"][0]["reason"] == "children_enumeration_failed"
    assert result["cache_error_count"] == 1
    assert result["cache_errors"][0]["property"] == "Name"


def test_fresh_snapshot_refreshes_geometry_and_keeps_duplicate_name_index(monkeypatch):
    root = Element(1)
    first, duplicate = Element(2, parent=root), Element(3, parent=root)
    root.children = [first, duplicate]
    install(monkeypatch, root)
    previous = provider.WindowsUIAProvider().snapshot_window(bound())
    first.values["BoundingRectangle"] = (25, 35, 100, 40)
    current = provider.WindowsUIAProvider().snapshot_window(bound())
    assert previous["controls"][1]["bbox"]["x"] == 10
    assert current["controls"][1]["bbox"]["x"] == 15
    frame_cache = cache()
    frame_cache.root(LiveWrapper(root)).cached_children()[0]
    frame_cache.root_wrapper.cached_children()[1]
    assert len(frame_cache.by_name_type[("field", "Pane")]) == 3
    assert len(root.root_calls) == 3


def test_budget_still_bounds_materialization_and_does_not_expand_document(monkeypatch):
    root = Element(1)
    root.children = [Element(index + 2, parent=root) for index in range(200)]
    install(monkeypatch, root)
    result = provider.WindowsUIAProvider().snapshot_window(bound(), max_controls=3)
    assert result["truncated"] is True and result["scan_complete"] is False
    assert result["scan_visited_count"] == 3
    assert root.child_arrays[0].reads == [0, 1]
    document = Element(500, kind=4, parent=root)
    root.children = [document]
    source = cache().root(LiveWrapper(root))
    walked = provider._bounded_uia_walk(source, budget=10, prune_documents=True)
    assert walked["excluded_document_count"] == 1
    assert document.child_calls == []


def test_non_support_and_interface_failure_are_distinguished(monkeypatch):
    class COMError(Exception):
        hresult = -2147220991
    root = Element(1)
    root.interfaces["Invoke"] = COMError("synthetic COM failure")
    install(monkeypatch, root)
    result = provider.WindowsUIAProvider().snapshot_window(bound())
    assert result["scan_complete"] is False
    assert result["cache_error_count"] == result["cache_com_error_count"] == 1
    assert any(item["reason"] == "cached_interface_read_failed" for item in result["traversal_errors"])


def test_false_availability_skips_com_but_true_and_unknown_require_real_interfaces():
    source = Element(1, text="正文")
    source.values.update({"Is" + name + "PatternAvailable": False for name in
        ("Invoke", "Value", "Text", "Selection", "SelectionItem", "ExpandCollapse", "Toggle", "Scroll")})
    source.values.update(IsTextPatternAvailable=True, IsValuePatternAvailable=NOT_SUPPORTED,
        IsTogglePatternAvailable=True)
    source.interfaces["Value"] = NS()
    node = cache().root(LiveWrapper(source))
    first = provider.WindowsUIAProvider()._control_from_wrapper(node, bound=bound(), index=0)
    second = provider.WindowsUIAProvider()._control_from_wrapper(node, bound=bound(), index=0)
    assert first.patterns == second.patterns == ("Value", "Text")
    assert first.name == second.name == "正文"
    assert source.pattern_reads == ["Text", "Value", "Toggle"]
    assert node.cache_errors == []


def test_native_interface_reader_preserves_com_failure_and_rejects_null_interface(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "pywinauto.uia_defines",
        NS(NoPatternInterfaceError=NoPattern, pattern_ids={"Invoke": (100, "real-interface")}))
    calls = []
    real = NS()
    native = NS(GetCurrentPattern=lambda identity: calls.append(identity) or
        NS(QueryInterface=lambda interface: calls.append(interface) or real))
    assert _read_native_pattern(native, "Invoke") is real
    assert calls == [100, "real-interface"]
    with pytest.raises(NoPattern):
        _read_native_pattern(NS(GetCurrentPattern=lambda identity: None), "Invoke")
    def failed(identity):
        raise OSError("synthetic stale interface")
    with pytest.raises(OSError, match="synthetic stale interface"):
        _read_native_pattern(NS(GetCurrentPattern=failed), "Invoke")


def test_rich_text_com_failure_does_not_fall_back_to_cached_name(monkeypatch):
    root = Element(1, name="must not replace missing rich text")
    calls = []
    def failed(count):
        calls.append(count)
        raise OSError("synthetic rich text unavailable")
    root.interfaces["Text"] = NS(DocumentRange=NS(GetText=failed))
    install(monkeypatch, root)
    result = provider.WindowsUIAProvider().snapshot_window(bound())
    assert result["status"] == "unavailable" and result["controls"] == []
    assert result["cache_errors"][0]["reason"] == "cached_rich_text_read_failed"
    assert calls == [-1]


def test_cached_graph_identity_is_checked_against_current_element(monkeypatch):
    root = Element(1)
    install(monkeypatch, root)
    node = cache().root(LiveWrapper(root))
    root.values["FrameworkId"] = "changed provider"
    metadata = provider._walk_metadata(provider._bounded_uia_walk(node, budget=10))
    assert metadata["scan_complete"] is False
    assert metadata["cache_errors"][0]["reason"] == "cached_identity_changed"


@pytest.mark.parametrize("edge", ["sibling", "self", "root", "cross_parent"])
def test_cached_traversal_keeps_proven_alias_and_cycle_normalization(monkeypatch, edge):
    root = Element(1)
    child, after = Element(2, parent=root), Element(3, parent=root)
    root.children = [child, after]
    if edge == "sibling":
        root.children.insert(1, child)
    elif edge == "self":
        child.children = [child]
    elif edge == "root":
        child.children = [root]
    else:
        after.children = [child]
    install(monkeypatch, root)
    result = provider.WindowsUIAProvider().snapshot_window(bound())
    assert result["scan_complete"] is True and result["traversal_errors"] == []
    assert result["scan_visited_count"] == 4 and result["control_count"] == 3
    assert result["alias_count"] == 1 and result["provider_tree_valid"] is False


def test_cached_child_array_failure_does_not_become_an_empty_complete_tree(monkeypatch):
    root = Element(1)
    def failed(*args):
        raise OSError("synthetic children unavailable")
    root.FindAllBuildCache = failed
    install(monkeypatch, root)
    result = provider.WindowsUIAProvider().snapshot_window(bound())
    assert result["scan_complete"] is False and result["cache_error_count"] == 1
    assert result["cache_errors"][0]["reason"] == "cached_children_acquisition_failed"


def test_repeated_scope_does_not_retry_cached_array_or_child_failure():
    root = Element(1)
    calls = []
    def failed(*args):
        calls.append("read")
        raise OSError("synthetic children unavailable")
    root.FindAllBuildCache = failed
    node = cache().root(LiveWrapper(root))
    for _ in range(2):
        with pytest.raises(UIACacheError):
            node.cached_children()
    assert calls == ["read"]
    root = Element(2)
    child = Element(3, parent=root)
    child.values["Name"] = OSError("synthetic property unavailable")
    root.children = [child]
    children = cache().root(LiveWrapper(root)).cached_children()
    for _ in range(2):
        with pytest.raises(UIACacheError):
            children[0]
    assert root.child_arrays[0].reads == [0]


def test_menu_and_owned_popup_scopes_keep_relationships(monkeypatch):
    root = Element(1, name="main")
    popup = Element(10, name="popup", kind=5)
    item = Element(11, name="Open", kind=6, parent=popup)
    popup.children = [item]
    install(monkeypatch, root, popup=popup)
    result = provider.WindowsUIAProvider().snapshot_window(bound())
    assert result["owned_popup_probe"] == {"status": "ok", "count": 1}
    scope = result["menu_scopes"][0]
    assert scope["status"] == "ok" and scope["owned_popup_handle"] == 43
    assert scope["controls"][1]["ancestor_control_ids"] == [scope["controls"][0]["control_id"]]
    assert len(popup.child_calls) == 1
