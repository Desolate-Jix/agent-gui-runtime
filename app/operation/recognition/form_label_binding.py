"""从同一有限 UIA 快照中保守关联可见标签与表单控件。"""
from __future__ import annotations

import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence


_FIELDS = frozenset({"Edit", "ComboBox", "CheckBox", "RadioButton"})


def _name(value):
    return " ".join(unicodedata.normalize("NFC", value).split()) if isinstance(value, str) else ""


def _box(value):
    if isinstance(value, Mapping):
        value = tuple(value.get(key) for key in ("x", "y", "w", "h"))
    if (not isinstance(value, (tuple, list)) or len(value) != 4
            or any(type(part) is not int for part in value) or value[2] <= 0 or value[3] <= 0):
        return None
    return tuple(value)


def _rid(value):
    if isinstance(value, (tuple, list)) and value and all(type(part) is int for part in value):
        return tuple(value)
    return None


def _parent(node):
    if "parent_id" in node:
        return node.get("parent_id")
    ancestors = node.get("ancestor_control_ids")
    return ancestors[0] if isinstance(ancestors, (tuple, list)) and ancestors else None


def _same_parent(label, field):
    left, right = _parent(label), _parent(field)
    return left is not None and left == right


def _near_above(label_box, field_box):
    lx, ly, lw, lh = label_box
    fx, fy, fw, _ = field_box
    overlap = min(lx + lw, fx + fw) - max(lx, fx)
    gap = fy - (ly + lh)
    return overlap >= min(lw, fw) / 2 and 0 <= gap <= 24


def _same_field_cluster(first, other):
    a, b = _box(first.get("bbox")), _box(other.get("bbox"))
    if a is None or b is None or not _same_parent(first, other):
        return False
    # 整页高的文件控件外框不能冒充与短输入框同一行的重叠控件。
    if max(a[3], b[3]) > 10 * min(a[3], b[3]):
        return False
    overlap = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    vertical_gap = max(a[1], b[1]) - min(a[1] + a[3], b[1] + b[3])
    return overlap >= min(a[2], b[2]) / 2 and vertical_gap <= 4


def _is_form_field(node):
    if node.get("control_type") in _FIELDS:
        return True
    patterns = {str(pattern).casefold() for pattern in node.get("patterns") or ()}
    return node.get("control_type") == "Button" and {"invoke", "value"} <= patterns


def infer_form_label_bindings(nodes: Sequence[Mapping]) -> list[dict]:
    """返回唯一证实的控件关联；不修改原 Name、bbox 或输入快照。"""
    visible = [node for node in nodes if isinstance(node, Mapping) and node.get("visible") is True
               and _box(node.get("bbox")) is not None]
    labels = [node for node in visible if node.get("control_type") == "Text" and _name(node.get("name"))]
    fields = [node for node in visible if _is_form_field(node) and _rid(node.get("runtime_id"))]
    counts = Counter(_name(label.get("name")) for label in labels)
    proposals = []
    for label in labels:
        name = _name(label.get("name"))
        if counts[name] != 1:
            continue
        label_rid = _rid(label.get("runtime_id"))
        explicit = [field for field in fields if label_rid is not None
                    and _rid(field.get("labeled_by")) == label_rid]
        if explicit:
            if len(explicit) == 1:
                proposals.append((explicit[0], name, "labeled_by"))
            continue
        nearby = [field for field in fields if _same_parent(label, field)
                  and _near_above(_box(label.get("bbox")), _box(field.get("bbox")))]
        if len(nearby) != 1:
            continue
        chosen = nearby[0]
        if any(other is not chosen and _same_field_cluster(chosen, other) for other in fields):
            continue
        proposals.append((chosen, name, "visible_label_geometry"))
    rid_counts = Counter(_rid(field.get("runtime_id")) for field, _, _ in proposals)
    return [{"control_id": field.get("control_id"), "runtime_id": list(_rid(field.get("runtime_id"))),
             "label": label, "source": source}
            for field, label, source in proposals if rid_counts[_rid(field.get("runtime_id"))] == 1]


def bind_form_label(label: str, control_type: str, nodes: Sequence[Mapping]) -> tuple[int, ...] | None:
    """读控件入口：只有目标标签和类型共同指向唯一 RID 才返回。"""
    expected = _name(label)
    types = {_rid(node.get("runtime_id")): node.get("control_type") for node in nodes if isinstance(node, Mapping)}
    matches = [tuple(binding["runtime_id"]) for binding in infer_form_label_bindings(nodes)
               if binding["label"] == expected and types.get(tuple(binding["runtime_id"])) == control_type]
    return matches[0] if len(matches) == 1 else None


__all__ = ["bind_form_label", "infer_form_label_bindings"]
