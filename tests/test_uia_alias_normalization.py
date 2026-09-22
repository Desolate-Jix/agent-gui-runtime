"""有限 UIA 邻接数组仅在 COM 身份与规范父边均证实时归一化。"""
from types import SimpleNamespace as NS

import pytest

from app.operation.screen_reading import uia_provider as provider


class Node:
    def __init__(self, rid, parent=None):
        self.element_info=NS(runtime_id=(rid,),control_type="Pane",process_id=20,element=self)
        self.CurrentProcessId=20
        self.CurrentFrameworkId="Chrome"
        self.CurrentNativeWindowHandle=0
        self.parent_node=parent
        self.children=[]
        self.top_handle=10

    def top_level_parent(self):
        return NS(handle=self.top_handle)


def install(monkeypatch):
    import sys
    api=NS(iuia=NS(CompareElements=lambda a,b:a is b,
        ControlViewWalker=NS(GetParentElement=lambda node:node.parent_node)))
    monkeypatch.setitem(sys.modules,"pywinauto.uia_defines",NS(IUIA=lambda:api))
    monkeypatch.setitem(sys.modules,"pywinauto.uia_element_info",NS(UIAElementInfo=lambda raw:raw.element_info))
    monkeypatch.setattr(provider,"_finite_uia_children",lambda node:node.children)


@pytest.mark.parametrize("edge",["sibling","self","root","cross_parent"])
def test_proven_alias_is_unique_complete_graph_and_keeps_later_siblings(monkeypatch,edge):
    install(monkeypatch)
    root=Node(1)
    first=Node(2,root)
    wanted=Node(3,root)
    root.children=[first,wanted]
    if edge=="sibling": root.children=[first,first,wanted]
    elif edge=="self": first.children=[first]
    elif edge=="root": first.children=[root]
    else: wanted.children=[first]
    result=provider._bounded_uia_walk(root,budget=100)
    assert result["scan_complete"] is True
    assert result["wrappers"]==[root,first,wanted]
    assert result["scan_visited_count"]==4
    assert result["alias_count"]==1
    assert result["graph_scan_complete"] is True
    assert result["provider_tree_valid"] is False
    assert result["traversal_errors"]==[]


@pytest.mark.parametrize("fault",["com_identity","parent","process","window"])
def test_same_runtime_id_conflict_is_never_normalized(monkeypatch,fault):
    install(monkeypatch)
    root=Node(1)
    first=Node(2,root)
    class Array:
        def __len__(self): return 2
        def __getitem__(self,index):
            if index==0:return first
            if fault=="com_identity":return Node(2,root)
            if fault=="parent":first.parent_node=Node(9)
            if fault=="process":first.element_info.process_id=first.CurrentProcessId=99
            if fault=="window":first.top_handle=99
            return first
    monkeypatch.setattr(provider,"_finite_uia_children",lambda node:Array() if node is root else [])
    result=provider._bounded_uia_walk(root,budget=100)
    assert result["scan_complete"] is False
    assert result["traversal_errors"]


def test_alias_edges_consume_budget_without_discarding_remaining_array(monkeypatch):
    install(monkeypatch)
    root=Node(1)
    child=Node(2,root)
    root.children=[child]*100
    result=provider._bounded_uia_walk(root,budget=4)
    assert result["truncated"] is True
    assert result["scan_visited_count"]==4
    assert result["wrappers"]==[root,child]
    assert result["alias_count"]==2


def test_root_alias_requires_unchanged_canonical_parent(monkeypatch):
    install(monkeypatch)
    root=Node(1)
    child=Node(2,root)
    root.children=[child]
    def children(node):
        if node is child:
            root.parent_node=Node(9)
            return [root]
        return node.children
    monkeypatch.setattr(provider,"_finite_uia_children",children)
    result=provider._bounded_uia_walk(root,budget=100)
    assert result["scan_complete"] is False
    assert any(item["reason"]=="tree_identity_changed" for item in result["traversal_errors"])


def test_new_node_with_noncanonical_array_parent_is_not_complete(monkeypatch):
    install(monkeypatch)
    root=Node(1)
    root.children=[Node(2,Node(9))]
    result=provider._bounded_uia_walk(root,budget=100)
    assert result["scan_complete"] is False
    assert result["traversal_errors"][0]["reason"]=="tree_scope_changed"


def test_sanitized_finite_graph_shape_replays_all_edges_and_unique_nodes(monkeypatch):
    install(monkeypatch)
    # 实测结构：253 个唯一后代、256 条有限边、3 个别名，其中 1 个自环。
    root=Node(1)
    root.children=[Node(index+2,root) for index in range(253)]
    shared=root.children[178]
    shared.children=[root.children[0],root.children[1],shared]
    arrays=[]
    monkeypatch.setattr(provider,"_finite_uia_children",lambda node:arrays.append(node) or node.children)
    result=provider._bounded_uia_walk(root,budget=1000)
    assert len(result["wrappers"])==254
    assert len(arrays)==254
    assert result["scan_visited_count"]==257
    assert result["alias_count"]==3 and result["cycle_count"]==1
    assert result["graph_scan_complete"] is True and result["provider_tree_valid"] is False
    assert result["scan_complete"] is True and result["traversal_errors"]==[]
