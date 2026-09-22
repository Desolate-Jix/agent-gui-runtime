from types import SimpleNamespace

import pytest

from app.operation.screen_reading import uia_provider as provider


class Node:
    def __init__(self, identity, kind="Pane", children=()):
        self.element_info = SimpleNamespace(runtime_id=(identity,), control_type=kind,
            process_id=20, element=self)
        self.CurrentProcessId = 20
        self.parent_node = None
        self.children = list(children)
        for child in self.children:
            child.parent_node = self

    def top_level_parent(self):
        return SimpleNamespace(handle=10)


@pytest.fixture(autouse=True)
def canonical_identity_boundary(monkeypatch):
    import sys
    api = SimpleNamespace(iuia=SimpleNamespace(CompareElements=lambda a, b: False,
        ControlViewWalker=SimpleNamespace(GetParentElement=lambda node: node.parent_node)))
    monkeypatch.setitem(sys.modules, "pywinauto.uia_defines", SimpleNamespace(IUIA=lambda: api))
    monkeypatch.setitem(sys.modules, "pywinauto.uia_element_info",
        SimpleNamespace(UIAElementInfo=lambda node: node.element_info))


def run(monkeypatch, root, budget=100, prune=False):
    monkeypatch.setattr(provider, "_finite_uia_children", lambda node: node.children, raising=False)
    return provider._bounded_uia_walk(root, budget=budget, prune_documents=prune)


def test_finite_depth_first_walk_does_not_use_sibling_iterators(monkeypatch):
    leaf = Node(3)
    root = Node(1, children=[Node(2, children=[leaf]), Node(4)])
    root.iter_descendants = lambda: pytest.fail("broken iterator must not be used")
    result = run(monkeypatch, root)
    assert [w.element_info.runtime_id[0] for w in result["wrappers"]] == [1, 2, 3, 4]
    assert result["scan_complete"] is True
    assert result["traversal_errors"] == []


@pytest.mark.parametrize("kind", ["sibling", "ancestor", "cross_parent"])
def test_duplicate_and_cycle_are_not_complete(monkeypatch, kind):
    child = Node(2)
    root = Node(1, children=[child])
    if kind == "sibling": root.children.append(child)
    elif kind == "ancestor": child.children.append(root)
    else: root.children.append(Node(3, children=[child]))
    result = run(monkeypatch, root)
    assert result["scan_complete"] is False
    assert result["truncated"] is False
    assert any(error["reason"] in {"ancestor_cycle", "duplicate_runtime_id"}
               for error in result["traversal_errors"])
    assert len(result["wrappers"]) < 6


def test_document_is_never_enumerated_in_chrome_scope(monkeypatch):
    doc = Node(2, "Document")
    root = Node(1, children=[doc, Node(3)])
    def children(node):
        if node is doc: pytest.fail("document must be pruned")
        return node.children
    monkeypatch.setattr(provider, "_finite_uia_children", children, raising=False)
    result = provider._bounded_uia_walk(root, budget=100, prune_documents=True)
    assert result["scan_complete"] is True
    assert result["excluded_document_count"] == 1


def test_budget_never_reads_extra_child(monkeypatch):
    root = Node(1)
    class Array:
        def __len__(self): return 10000
        def __getitem__(self, i):
            assert i < 2
            return Node(i + 2)
    monkeypatch.setattr(provider, "_finite_uia_children", lambda n: Array() if n is root else [], raising=False)
    result = provider._bounded_uia_walk(root, budget=3)
    assert result["scan_visited_count"] == 3
    assert result["truncated"] is True and result["scan_complete"] is False


def test_findall_error_is_not_reported_as_empty_complete_tree(monkeypatch):
    def failed(_): raise OSError(5, "denied")
    monkeypatch.setattr(provider, "_finite_uia_children", failed, raising=False)
    result = provider._bounded_uia_walk(Node(1), budget=100)
    assert result["scan_complete"] is False
    assert result["traversal_errors"][0]["reason"] == "children_enumeration_failed"
    assert "denied" in result["traversal_errors"][0]["message"]


def test_same_label_with_distinct_identity_is_retained(monkeypatch):
    a, b = Node(2), Node(3)
    a.element_info.name = b.element_info.name = "Back"
    result = run(monkeypatch, Node(1, children=[a, b]))
    assert result["scan_complete"] is True
    assert len(result["wrappers"]) == 3


def test_finite_com_array_only_indexes_requested_elements(monkeypatch):
    calls = []
    array = SimpleNamespace(Length=10000, GetElement=lambda i: calls.append(i) or i)
    result = provider._FiniteUIAChildren(array, lambda e: ("wrapped", e))
    assert len(result) == 10000
    assert calls == []
    assert result[0] == ("wrapped", 0)
    assert calls == [0]


def test_production_children_uses_findall_not_swallowing_wrapper(monkeypatch):
    import sys
    calls = []
    array = SimpleNamespace(Length=2, GetElement=lambda i: ("element", i))
    element = SimpleNamespace(FindAll=lambda scope, condition: calls.append((scope, condition)) or array)
    api = SimpleNamespace(tree_scope={"children": 2}, true_condition="true")
    monkeypatch.setitem(sys.modules, "pywinauto.uia_defines", SimpleNamespace(IUIA=lambda: api))
    monkeypatch.setitem(sys.modules, "pywinauto.uia_element_info", SimpleNamespace(UIAElementInfo=lambda e: e))
    wrapper = SimpleNamespace(element_info=SimpleNamespace(element=element),
        backend=SimpleNamespace(generic_wrapper_class=lambda e: ("wrapper", e)))
    children = provider._finite_uia_children(wrapper)
    assert calls == [(2, "true")]
    assert children[1] == ("wrapper", ("element", 1))


def test_missing_identity_never_claims_complete(monkeypatch):
    root = Node(1)
    root.element_info.runtime_id = None
    result = run(monkeypatch, root)
    assert result["scan_complete"] is False
    assert result["traversal_errors"][0]["reason"] == "runtime_identity_unavailable"


def test_exact_budget_does_not_probe_more_to_claim_completion(monkeypatch):
    root = Node(1)
    def forbidden(_): pytest.fail("budget exhausted")
    monkeypatch.setattr(provider, "_finite_uia_children", forbidden)
    result = provider._bounded_uia_walk(root, budget=1)
    assert result["truncated"] is True and result["scan_complete"] is False
