"""同帧祖先共享父链查询，不跨快照保留拓扑，也不忽略歧义或环。"""
from types import SimpleNamespace
from app.operation.screen_reading.uia_provider import _confirmed_ancestor_control_ids


class Node:
    def __init__(self, rid, parent=None):
        self.element_info = SimpleNamespace(runtime_id=[rid])
        self.up = parent
        self.calls = 0

    def parent(self):
        self.calls += 1
        return self.up


def observed(nodes):
    return [(n, SimpleNamespace(control_id=str(n.element_info.runtime_id[0]))) for n in nodes]


def test_shared_parent_is_read_once_per_snapshot_and_every_chain_is_preserved():
    root = Node(1)
    pane = Node(2, root)
    leaves = [Node(i, pane) for i in range(3, 103)]
    nodes = [root, pane, *leaves]
    result = _confirmed_ancestor_control_ids(observed(nodes))
    assert result[id(root)] == ()
    assert result[id(pane)] == ('1',)
    assert all(result[id(n)] == ('2', '1') for n in leaves)
    assert sum(n.calls for n in nodes) == len(nodes)


def test_new_snapshot_reads_changed_parent_again():
    root, other = Node(1), Node(2)
    leaf = Node(3, root)
    rows = observed([root, other, leaf])
    assert _confirmed_ancestor_control_ids(rows)[id(leaf)] == ('1',)
    leaf.up = other
    assert _confirmed_ancestor_control_ids(rows)[id(leaf)] == ('2',)
    assert leaf.calls == 2


def test_duplicate_runtime_identity_remains_unusable():
    root, duplicate = Node(1), Node(1)
    leaf = Node(2, root)
    result = _confirmed_ancestor_control_ids(observed([root, duplicate, leaf]))
    assert all(chain == () for chain in result.values())


def test_cycle_remains_invalid_even_with_shared_parent_lookups():
    one, two = Node(1), Node(2)
    one.up, two.up = two, one
    result = _confirmed_ancestor_control_ids(observed([one, two]))
    assert result[id(one)] == result[id(two)] == ()


def test_unemitted_node_requires_confirmed_zero_area_bridge():
    root = Node(1)
    bridge = Node(2, root)
    leaf = Node(3, bridge)
    rows = observed([root, leaf])
    args = {'traversed_wrappers': [root, bridge, leaf]}
    assert _confirmed_ancestor_control_ids(rows, **args)[id(leaf)] == ()
    assert _confirmed_ancestor_control_ids(rows, zero_area_structural_ids={id(bridge)}, **args)[id(leaf)] == ('1',)


def test_parent_read_failure_keeps_only_confirmed_prefix():
    root = Node(1)
    pane = Node(2, root)
    leaves = [Node(i, pane) for i in (3, 4)]
    def unavailable():
        pane.calls += 1
        raise OSError('UIA unavailable')
    pane.parent = unavailable
    result = _confirmed_ancestor_control_ids(observed([root, pane, *leaves]))
    assert all(result[id(n)] == ('2',) for n in leaves)
    assert pane.calls == 1
