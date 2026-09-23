from types import SimpleNamespace as NS
import sys

import pytest

from app.agent import windows_form_control_reader as reader


TARGET = {"handle": 10, "process_id": 20}
IDENTITY = {
    "contract_version": "windows_native_identity_observation_v1",
    "provider": "windows_native_identity", "status": "observed",
    "target_window_handle": 10, "process_id": 20,
    "process_create_time": 123.0, "executable_path": "C:\\fixture.exe",
}


def test_complete_form_tree_above_512_still_checks_later_duplicate(setup):
    target = Node("choice", "CheckBox", (1, 1))
    target.iface_toggle = NS(CurrentToggleState=0)
    padding = [Node("", "Group", (2, n)) for n in range(550)]
    coordinator = setup(target, *padding)
    result = reader.read_form_control(coordinator, TARGET, "choice", "checkbox")
    assert result["checked"] is False
    other = Node("choice", "CheckBox", (3, 1))
    coordinator = setup(target, *padding, other)
    with pytest.raises(reader.FormControlReadError, match="form_control_ambiguous") as error:
        reader.read_form_control(coordinator, TARGET, "choice", "checkbox")
    assert error.value.diagnostics["graph_scan_complete"] is True
    assert error.value.diagnostics["node_count"] == 552


@pytest.fixture(autouse=True)
def compare_elements_boundary(monkeypatch):
    monkeypatch.setattr(reader, "_same_element", lambda left, right: left is right, raising=False)


def rect(x=100, y=200, w=600, h=500):
    return NS(left=x, top=y, right=x + w, bottom=y + h)


class Node:
    def __init__(self, name="同意", kind="CheckBox", rid=(1, 2), *, children=(),
                 pid=20, handle=10, visible=True, enabled=True, password=False):
        self.element_info = NS(name=name, control_type=kind, runtime_id=list(rid),
                               process_id=pid, rectangle=rect(120, 230, 100, 25))
        self.element_info.element = self
        self.CurrentIsPassword = password
        self.CurrentProcessId = pid
        self.CurrentName = name
        self.top_handle = handle
        self.visible, self.enabled = visible, enabled
        self.nodes = list(children)
        self.parent_node = None
        for child in self.nodes:
            child.parent_node = self

    def top_level_parent(self):
        return NS(element_info=NS(handle=self.top_handle))

    def is_visible(self):
        return self.visible

    def is_enabled(self):
        return self.enabled


class Walker:
    def GetParentElement(self, node):
        return node.parent_node

    def GetFirstChildElement(self, node):
        return node.nodes[0] if node.nodes else None

    def GetNextSiblingElement(self, node):
        siblings = node.parent_node.nodes
        position = siblings.index(node) + 1
        return siblings[position] if position < len(siblings) else None


class Array:
    def __init__(self, *nodes):
        self.nodes = nodes
        self.Length = len(nodes)

    def GetElement(self, index):
        return self.nodes[index]


@pytest.fixture
def setup(monkeypatch):
    def build(*controls, identities=None, bounds=None):
        monkeypatch.setattr(reader, "_native_owned_popups", lambda handle, pid: [])
        root = Node("root", "Window", (0, 1), children=controls)
        snapshots = list(identities or [IDENTITY, IDENTITY])
        windows = list(bounds or [NS(handle=10, process_id=20, rect=rect())] * 2)
        owner = NS(active=False, count=0)

        def call(fn):
            owner.count += 1
            owner.active = True
            try:
                return fn()
            finally:
                owner.active = False

        owner.call = call

        def next_bound():
            assert owner.active
            return windows.pop(0)

        def native_identity(_handle):
            assert owner.active
            return snapshots.pop(0)

        manager = NS(get_bound_window=next_bound)
        coordinator = NS(_owner=owner, _windows=lambda: manager)

        def uia():
            assert owner.active
            desktop = NS(window=lambda **kw: NS(wrapper_object=lambda: root))
            return desktop, Walker(), lambda element: element

        monkeypatch.setattr(reader, "_uia_factory", uia)
        monkeypatch.setattr(reader, "_finite_children", lambda node: node.nodes, raising=False)
        monkeypatch.setattr(reader, "WindowsNativeIdentityReader",
                            lambda **kw: NS(read_identity=native_identity))
        return coordinator
    return build


def read(setup, node, kind="checkbox", **kwargs):
    return reader.read_form_control(setup(node), TARGET, node.CurrentName, kind, **kwargs)


@pytest.mark.parametrize("state,expected", [(0, False), (1, True), (2, None), (3, None),
    (None, None), ("1", None), (True, None)])
def test_dropdown_expanded_is_explicit_raw_pattern_state(setup, state, expected):
    node = Node(kind="ComboBox")
    node.iface_expand_collapse = NS(CurrentExpandCollapseState=state,
        Expand=lambda: pytest.fail("read must not expand"), Collapse=lambda: pytest.fail("read must not collapse"))
    node.get_expand_state = lambda: pytest.fail("wrapper state fallback must not run")
    assert read(setup, node, "dropdown")["expanded"] is expected


def test_dropdown_missing_expand_pattern_is_unknown_not_collapsed(setup):
    node = Node(kind="ComboBox")
    node.get_expand_state = lambda: False
    assert read(setup, node, "dropdown")["expanded"] is None


def test_dropdown_expansion_change_during_snapshot_is_rejected(setup):
    class Pattern:
        def __init__(self):
            self.values = iter([0, 1])
        @property
        def CurrentExpandCollapseState(self):
            return next(self.values)
    node = Node(kind="ComboBox")
    node.iface_expand_collapse = Pattern()
    with pytest.raises(reader.FormControlReadError, match="form_control_expansion_changed"):
        read(setup, node, "dropdown")


def test_checkbox_reads_state_and_relative_geometry_on_owner(setup):
    node = Node()
    node.iface_toggle = NS(CurrentToggleState=1)
    coordinator = setup(node)
    result = reader.read_form_control(coordinator, TARGET, "  同意  ", "checkbox")
    assert result == {
        "source": "windows_uia", "runtime_id": [1, 2],
        "bbox": {"x": 20, "y": 30, "w": 100, "h": 25},
        "window_identity": {**IDENTITY, "executable_path": "c:\\fixture.exe"},
        "window_rect": [100, 200, 600, 500], "kind": "checkbox", "label": "同意",
        "value": None, "checked": True, "options": [], "state_available": True,
    }
    assert coordinator._owner.count == 1


@pytest.mark.parametrize("state, expected", [(0, False), (1, True), (2, None), (None, None), ("0", None)])
def test_checkbox_never_fabricates_unknown_state(setup, state, expected):
    node = Node()
    node.iface_toggle = NS(CurrentToggleState=state)
    result = read(setup, node)
    assert result["checked"] is expected
    assert result["state_available"] is (expected is not None)


def test_missing_pattern_is_unknown_not_unchecked(setup):
    result = read(setup, Node())
    assert result["checked"] is None
    assert result["state_available"] is False


@pytest.mark.parametrize("state", [True, False])
def test_radio_reads_selection_item_without_toggle(setup, state):
    node = Node(kind="RadioButton")
    node.iface_selection_item = NS(CurrentIsSelected=state)
    result = read(setup, node, "radio")
    assert result["checked"] is state


@pytest.mark.parametrize("options", [(), (Node("elsewhere", rid=(1, 9)),)])
def test_dropdown_without_selection_never_invents_empty_value(setup, options):
    node = Node(kind="ComboBox", children=options)
    node.iface_selection = NS(GetCurrentSelection=lambda: Array())
    result = read(setup, node, "dropdown")
    assert result["value"] is None
    assert result["state_available"] is False


def test_dropdown_reads_value_and_only_own_options(setup):
    first = Node("甲", "ListItem", (1, 3))
    first.iface_selection_item = NS(CurrentIsSelected=True)
    second = Node("乙", "ListItem", (1, 4))
    combo = Node("地区", "ComboBox", children=[Node("list", "List", (1, 8), children=[first, second])])
    combo.iface_value = NS(CurrentValue="甲")
    sibling = Node("外部", "ListItem", (1, 5))
    result = reader.read_form_control(setup(combo, sibling), TARGET, "地区", "dropdown")
    assert result["value"] == "甲"
    assert [option["label"] for option in result["options"]] == ["甲", "乙"]
    assert [option["selected"] for option in result["options"]] == [True, None]


def test_dropdown_selection_pattern_reads_owned_selected_label(setup):
    option = Node("甲", "ListItem", (1, 3))
    combo = Node("地区", "ComboBox", children=[option])
    combo.iface_selection = NS(GetCurrentSelection=lambda: Array(option))
    assert read(setup, combo, "dropdown")["value"] == "甲"


def test_dropdown_selection_cannot_read_unowned_or_password_node(setup):
    secret = Node("secret", "ListItem", (1, 3), password=True)
    combo = Node("地区", "ComboBox")
    combo.iface_selection = NS(GetCurrentSelection=lambda: Array(secret))
    assert read(setup, combo, "dropdown")["value"] is None


@pytest.mark.parametrize("nodes, code", [
    ([Node(), Node(rid=(2, 3))], "form_control_ambiguous"),
    ([Node(enabled=False)], "form_control_unavailable"),
    ([Node(visible=False)], "form_control_unavailable"),
    ([Node(handle=99)], "form_control_tree_scope_changed"),
    ([Node(pid=99)], "form_control_window_mismatch"),
    ([Node(kind="Button")], "form_control_not_found"),
    ([Node(password=True)], "form_control_password_protected"),
])
def test_rejects_non_exact_or_unavailable_target(setup, nodes, code):
    with pytest.raises(reader.FormControlReadError) as error:
        reader.read_form_control(setup(*nodes), TARGET, "同意", "checkbox")
    assert error.value.reason_code == code


def test_expected_runtime_identity_cannot_select_among_duplicate_labels(setup):
    with pytest.raises(reader.FormControlReadError, match="form_control_ambiguous"):
        reader.read_form_control(setup(Node(), Node(rid=(2, 3))), TARGET, "同意", "checkbox",
                                 expected_runtime_id=[1, 2])


def test_expected_runtime_identity_rejects_replacement(setup):
    with pytest.raises(reader.FormControlReadError, match="form_control_identity_changed"):
        read(setup, Node(), expected_runtime_id=[9, 9])


@pytest.mark.parametrize("changes", [
    {"identities": [IDENTITY, {**IDENTITY, "process_create_time": 124.0}]},
    {"bounds": [NS(handle=10, process_id=20, rect=rect()), NS(handle=10, process_id=20, rect=rect(101))]},
])
def test_native_identity_and_geometry_rechecked_after_read(setup, changes):
    with pytest.raises(reader.FormControlReadError, match="form_control_window_changed"):
        reader.read_form_control(setup(Node(), **changes), TARGET, "同意", "checkbox")


def test_control_geometry_change_during_state_read_is_rejected(setup):
    node = Node()

    class Toggle:
        @property
        def CurrentToggleState(self):
            node.element_info.rectangle = rect(150, 230, 100, 25)
            return 0

    node.iface_toggle = Toggle()
    with pytest.raises(reader.FormControlReadError, match="form_control_identity_changed"):
        read(setup, node)


def test_bounded_option_tree_rejects_overflow(setup):
    combo = Node(kind="ComboBox", children=[Node(str(i), "ListItem", (1, i + 5)) for i in range(129)])
    with pytest.raises(reader.FormControlReadError, match="form_control_scan_limit"):
        read(setup, combo, "dropdown")


def test_provider_errors_are_redacted(setup, monkeypatch):
    coordinator = setup(Node())

    def fail():
        raise RuntimeError("secret provider content")

    monkeypatch.setattr(reader, "_uia_factory", fail)
    with pytest.raises(reader.FormControlReadError) as error:
        reader.read_form_control(coordinator, TARGET, "同意", "checkbox")
    assert str(error.value) == "form_control_provider_unavailable"
    assert error.value.__suppress_context__ is True


def test_unicode_normalization_does_not_fuzzy_match(setup):
    node = Node("Café")
    result = reader.read_form_control(setup(node), TARGET, "Cafe\u0301", "checkbox")
    assert result["label"] == "Café"
    with pytest.raises(reader.FormControlReadError, match="form_control_not_found"):
        reader.read_form_control(setup(node), TARGET, "Cafe", "checkbox")


def test_uia_factory_wraps_raw_com_element_info_before_wrapper(monkeypatch):
    marker = object()
    walker = object()
    monkeypatch.setitem(sys.modules, "pywinauto", NS(Desktop=lambda **kw: "desktop"))
    monkeypatch.setitem(sys.modules, "pywinauto.uia_defines", NS(IUIA=lambda: NS(iuia=NS(ControlViewWalker=walker))))
    monkeypatch.setitem(sys.modules, "pywinauto.uia_element_info", NS(UIAElementInfo=lambda raw: ("info", raw)))
    monkeypatch.setitem(sys.modules, "pywinauto.controls.uiawrapper", NS(UIAWrapper=lambda info: ("wrapper", info)))
    desktop, actual_walker, wrap = reader._uia_factory()
    assert desktop == "desktop"
    assert actual_walker is walker
    assert wrap(marker) == ("wrapper", ("info", marker))


def test_bounded_window_scan_rejects_overflow(setup):
    controls = [Node(str(i), "Text", (1, i + 5)) for i in range(reader.MAX_FORM_SCAN_EDGES)] + [Node()]
    with pytest.raises(reader.FormControlReadError, match="form_control_scan_limit"):
        reader.read_form_control(setup(*controls), TARGET, "同意", "checkbox")


@pytest.mark.parametrize("target,label,kind", [
    ({"handle": True, "process_id": 20}, "label", "checkbox"),
    ({"handle": 10, "process_id": 0}, "label", "checkbox"),
    (TARGET, "  ", "checkbox"), (TARGET, "label", "toggle"),
])
def test_invalid_request_rejected_before_owner(setup, target, label, kind):
    coordinator = setup(Node())
    with pytest.raises(reader.FormControlReadError, match="form_control_request_invalid"):
        reader.read_form_control(coordinator, target, label, kind)
    assert coordinator._owner.count == 0


def test_unknown_radio_state_and_empty_known_dropdown_value(setup):
    assert read(setup, Node(kind="RadioButton"), "radio")["checked"] is None
    combo = Node(kind="ComboBox")
    combo.iface_value = NS(CurrentValue="")
    result = read(setup, combo, "dropdown")
    assert result["value"] == ""
    assert result["state_available"] is True


@pytest.mark.parametrize("controls, expected_counts", [
    ([], {}),
    ([Node("private chrome name", "Pane", (1, 8), children=[Node("private toolbar", "ToolBar")])],
     {"Pane": 1, "ToolBar": 1}),
    ([Node("private document name", "Document", (1, 8), children=[Node("other private label")])],
     {"Document": 1, "CheckBox": 1}),
])
def test_missing_control_reports_structure_without_labels_or_retry(setup, controls, expected_counts):
    import json

    coordinator = setup(*controls)
    with pytest.raises(reader.FormControlReadError) as error:
        reader.read_form_control(coordinator, TARGET, "absent", "checkbox")
    diagnostic = error.value.diagnostics
    assert diagnostic == {
        "scope": "window_finite_children", "window_handle": 10, "process_id": 20,
        "node_count": sum(expected_counts.values()), "control_type_counts": expected_counts,
        "document_count": expected_counts.get("Document", 0), "match_count": 0,
        "scan_started": True, "scan_complete": True, "graph_scan_complete": True,
        "provider_tree_valid": True, "edge_count": sum(expected_counts.values()),
        "alias_count": 0, "cycle_count": 0,
    }
    assert error.value.to_reference()["diagnostics"] == diagnostic
    assert "private" not in json.dumps(error.value.to_reference())
    assert coordinator._owner.count == 1


def test_scan_budget_failure_retains_incomplete_count(setup):
    controls = [Node(str(i), "Text", (1, i + 5)) for i in range(reader.MAX_FORM_SCAN_EDGES + 1)]
    with pytest.raises(reader.FormControlReadError) as error:
        reader.read_form_control(setup(*controls), TARGET, "absent", "checkbox")
    assert error.value.reason_code == "form_control_scan_limit"
    assert error.value.diagnostics["node_count"] == reader.MAX_FORM_SCAN_EDGES
    assert error.value.diagnostics["scan_complete"] is False
    assert error.value.diagnostics["control_type_counts"] == {"Text": reader.MAX_FORM_SCAN_EDGES}


def test_duplicate_matches_report_count_without_matched_content(setup):
    with pytest.raises(reader.FormControlReadError) as error:
        reader.read_form_control(setup(Node(), Node(rid=(2, 3))), TARGET, "同意", "checkbox")
    assert error.value.reason_code == "form_control_ambiguous"
    assert error.value.diagnostics["match_count"] == 2
    assert error.value.diagnostics["scan_complete"] is True


def test_unknown_control_type_is_redacted_from_diagnostics(setup):
    import json

    with pytest.raises(reader.FormControlReadError) as error:
        reader.read_form_control(setup(Node("private name", "private provider type")),
                                 TARGET, "absent", "checkbox")
    assert error.value.diagnostics["control_type_counts"] == {"Other": 1}
    assert "private" not in json.dumps(error.value.to_reference())


def test_exception_diagnostics_drop_unknown_keys_and_untyped_values():
    error = reader.FormControlReadError("form_control_not_found", diagnostics={
        "scope": "private", "window_handle": True, "process_id": "private", "node_count": -1,
        "control_type_counts": {"Text": 2, "private": 3, "Edit": "private"},
        "document_count": 0, "match_count": 0, "scan_complete": "private",
        "label": "secret", "value": "secret", "raw_error": "secret",
    })
    assert error.diagnostics == {"control_type_counts": {"Text": 2}, "document_count": 0, "match_count": 0}
    reference = error.to_reference()
    reference["diagnostics"]["control_type_counts"]["Text"] = 999
    assert error.diagnostics["control_type_counts"]["Text"] == 2


def test_provider_failure_before_scan_reports_not_started(setup, monkeypatch):
    coordinator = setup(Node())

    def fail():
        raise RuntimeError("private provider content")

    monkeypatch.setattr(reader, "_uia_factory", fail)
    with pytest.raises(reader.FormControlReadError) as error:
        reader.read_form_control(coordinator, TARGET, "同意", "checkbox")
    assert error.value.diagnostics["scan_started"] is False
    assert error.value.diagnostics["scan_complete"] is False
    assert error.value.diagnostics["node_count"] == 0


@pytest.mark.parametrize("cycle", ["root", "ancestor", "sibling"])
def test_proven_alias_graph_is_complete_but_provider_tree_is_invalid(monkeypatch, cycle):
    root = Node("root", "Window", (0, 1))
    first = Node("first", "Pane", (0, 2))
    second = Node("second", "Text", (0, 3))
    first.parent_node = root
    second.parent_node = first
    root.nodes = [first]
    first.nodes = [second]
    second.nodes = [root if cycle == "root" else first] if cycle != "sibling" else []
    if cycle == "sibling":
        root.nodes.append(first)
    monkeypatch.setattr(reader, "_finite_children", lambda node: node.nodes, raising=False)

    class Graph(Walker):
        def GetFirstChildElement(self, node):
            if node is root:
                return first
            if node is first:
                return second
            return root if cycle == "root" else first if cycle == "ancestor" else None

        def GetNextSiblingElement(self, node):
            return second if cycle == "sibling" and node is second else None

    diagnostic = {}
    assert list(reader._descendants(root, Graph(), lambda node: node, limit=3,
                                   diagnostics=diagnostic)) == [first, second]
    assert diagnostic["graph_scan_complete"] is True
    assert diagnostic["provider_tree_valid"] is False
    assert diagnostic["alias_count"] == 1
    assert diagnostic["cycle_count"] == (0 if cycle == "sibling" else 1)


@pytest.mark.parametrize("escape", ["ancestor", "external_control"])
def test_dropdown_subtree_rejects_edges_to_unowned_ancestor_or_control(monkeypatch, escape):
    root = Node("window", "Window", (0, 1))
    combo = Node("combo", "ComboBox", (0, 2))
    outside = Node("same choice", "ListItem", (0, 3))
    other_combo = Node("other combo", "ComboBox", (0, 4))
    combo.parent_node = root
    other_combo.parent_node = root
    outside.parent_node = other_combo
    combo.nodes = [root if escape == "ancestor" else outside]
    monkeypatch.setattr(reader, "_finite_children", lambda node: node.nodes, raising=False)

    class Graph(Walker):
        def GetFirstChildElement(self, node):
            return (root if escape == "ancestor" else outside) if node is combo else None

        def GetNextSiblingElement(self, node):
            return None

    with pytest.raises(reader.FormControlReadError, match="form_control_tree_scope_changed"):
        reader._dropdown(combo, Graph(), lambda node: node, 10, 20, (0, 0, 600, 500))


def test_dropdown_proven_self_alias_never_becomes_an_option(monkeypatch):
    combo = Node("combo", "ComboBox", (0, 2))
    combo.nodes = [combo]
    monkeypatch.setattr(reader, "_finite_children", lambda node: node.nodes, raising=False)

    class Graph(Walker):
        def GetFirstChildElement(self, node):
            return combo

        def GetNextSiblingElement(self, node):
            return None

    assert reader._dropdown(combo, Graph(), lambda node: node, 10, 20, (0, 0, 600, 500)) == (None, [])


def test_finite_children_primary_never_calls_broken_sibling_cursor(monkeypatch):
    root = Node("root", "Window", (0, 1))
    first = Node("first", "Pane", (0, 2))
    second = Node("second", "Text", (0, 3))
    root.nodes = [first, second]
    first.parent_node = second.parent_node = root
    monkeypatch.setattr(reader, "_finite_children", lambda node: node.nodes, raising=False)

    class BrokenCursor(Walker):
        def GetFirstChildElement(self, node):
            raise AssertionError("must use finite children")

        def GetNextSiblingElement(self, node):
            raise AssertionError("must use finite children")

    assert list(reader._descendants(root, BrokenCursor(), lambda node: node, limit=3)) == [first, second]


def test_repeated_same_com_element_is_reported_as_alias_not_a_second_match(setup):
    node = Node()
    result = reader.read_form_control(setup(node, node), TARGET, "同意", "checkbox")
    assert result["diagnostics"]["alias_count"] == 1
    assert result["diagnostics"]["graph_scan_complete"] is True
    assert result["diagnostics"]["provider_tree_valid"] is False
    assert result["diagnostics"]["match_count"] == 1


def test_alias_does_not_drop_real_siblings_remaining_in_finite_array(setup):
    first = Node("first", "Pane", (0, 2))
    wanted = Node()
    result = reader.read_form_control(setup(first, first, wanted), TARGET, "同意", "checkbox")
    assert result["runtime_id"] == [1, 2]
    assert result["diagnostics"]["node_count"] == 2
    assert result["diagnostics"]["edge_count"] == 3


def test_same_runtime_id_with_different_com_identity_is_rejected(setup):
    with pytest.raises(reader.FormControlReadError, match="form_control_tree_runtime_id_conflict"):
        reader.read_form_control(setup(Node(), Node()), TARGET, "同意", "checkbox")


@pytest.mark.parametrize("fault", ["parent", "process", "window"])
def test_alias_identity_or_canonical_parent_change_is_rejected(monkeypatch, fault):
    root = Node("root", "Window", (0, 1))
    node = Node("node", "Pane", (0, 2))
    node.parent_node = root

    def children(parent):
        if parent is not root:
            return iter(())
        yield node
        if fault == "parent":
            node.parent_node = Node("outside", "Window", (9, 9))
        elif fault == "process":
            node.element_info.process_id = node.CurrentProcessId = 99
        else:
            node.top_handle = 99
        yield node

    monkeypatch.setattr(reader, "_finite_children", children)
    with pytest.raises(reader.FormControlReadError, match="form_control_tree_identity_changed"):
        list(reader._descendants(root, Walker(), lambda node: node, limit=3))


def test_many_alias_edges_still_consume_finite_budget(setup):
    node = Node()
    with pytest.raises(reader.FormControlReadError, match="form_control_scan_limit"):
        reader.read_form_control(setup(*([node] * (reader.MAX_FORM_SCAN_EDGES + 1))), TARGET, "同意", "checkbox")
