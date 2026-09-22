"""有限 UIA 邻接图的共用身份契约；别名不是第二个控件，冲突不能归一化。"""


class UIAGraphError(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def runtime_id(value):
    if (type(value) not in (list, tuple) or not 1 <= len(value) <= 64
            or any(type(item) is not int for item in value)):
        raise UIAGraphError("runtime_id_unavailable")
    return tuple(value)


def tree_identity(node):
    info = node.element_info
    element = info.element
    pid = info.process_id
    if type(pid) is not int or pid <= 0 or element.CurrentProcessId != pid:
        raise UIAGraphError("tree_identity_unavailable")
    root = node.top_level_parent()
    root_info = getattr(root, "element_info", None)
    handle = getattr(root_info, "handle", getattr(root, "handle", 0))
    if type(handle) is not int or handle <= 0:
        raise UIAGraphError("tree_identity_unavailable")
    return (runtime_id(info.runtime_id), pid, info.control_type,
            getattr(element, "CurrentFrameworkId", None),
            getattr(element, "CurrentNativeWindowHandle", None), handle)


def canonical_parent_id(node):
    from pywinauto.uia_defines import IUIA
    from pywinauto.uia_element_info import UIAElementInfo
    parent = IUIA().iuia.ControlViewWalker.GetParentElement(node.element_info.element)
    return runtime_id(UIAElementInfo(parent).runtime_id) if parent else None


def same_element(left, right):
    from pywinauto.uia_defines import IUIA
    return IUIA().iuia.CompareElements(left.element_info.element, right.element_info.element)


class CanonicalUIAGraph:
    def __init__(self, root, *, identity=tree_identity, parent=canonical_parent_id, compare=same_element):
        self.identity, self.parent, self.compare = identity, parent, compare
        self.root_identity = identity(root)
        if self.root_identity[-1] is None:
            raise UIAGraphError("tree_identity_unavailable")
        self.root_id = self.root_identity[0]
        self.seen = {self.root_id: (root, self.root_identity, parent(root))}
        self.alias_count = self.cycle_count = 0
        self.provider_tree_valid = True

    def visit(self, node, *, expected_parent, path):
        identity = self.identity(node)
        key = identity[0]
        parent = self.parent(node)
        if key in self.seen:
            self.provider_tree_valid = False
            original, original_identity, original_parent = self.seen[key]
            same = self.compare(original, node)
            if type(same) not in (bool, int) or same != 1:
                raise UIAGraphError("tree_runtime_id_conflict")
            if identity != original_identity or parent != original_parent:
                raise UIAGraphError("tree_identity_changed")
            self.alias_count += 1
            self.cycle_count += int(key in path)
            return True
        if parent != expected_parent or identity[-1] != self.root_identity[-1]:
            self.provider_tree_valid = False
            raise UIAGraphError("tree_scope_changed")
        self.seen[key] = (node, identity, parent)
        return False
