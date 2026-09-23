from __future__ import annotations

import re
import unicodedata
from typing import Mapping

ROLES = frozenset({"button", "link", "input", "menu_item", "tab", "checkbox", "radio", "control"})

def validate_control_target(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != {"contract_version", "label", "role", "source_binding_sha256"}:
        raise ValueError("control target schema is invalid")
    raw_label = value.get("label")
    role = value.get("role")
    digest = value.get("source_binding_sha256")
    if not isinstance(raw_label, str) or not isinstance(role, str):
        raise ValueError("control target is invalid")
    label = " ".join(unicodedata.normalize("NFC", raw_label).split())
    if value.get("contract_version") != "recognition_control_target_v1" or not label or role not in ROLES or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("control target is invalid")
    return {"contract_version": "recognition_control_target_v1", "label": label, "role": role, "source_binding_sha256": digest}

def control_target_matches(label: object, role: object, target: Mapping[str, object]) -> bool:
    return (isinstance(label, str) and isinstance(role, str)
        and " ".join(unicodedata.normalize("NFC", label).split()).casefold() == str(target["label"]).casefold()
        and (role == target["role"] or target["role"] == "control" and role in ROLES))

def control_target_ocr_matches(label: object, role: object, target: Mapping[str, object], *, candidate_label: object) -> bool:
    # 精确文字也不能代替候选身份；先绑定控件，再容忍 OCR 丢失空白。
    if not isinstance(label, str) or not control_target_matches(candidate_label, role, target):
        return False
    if control_target_matches(label, role, target):
        return True
    observed = "".join(unicodedata.normalize("NFC", label).split()).casefold()
    expected = "".join(unicodedata.normalize("NFC", str(target["label"])).split()).casefold()
    return bool(observed) and observed == expected

def uia_control_matches(control: Mapping[str, object], target: Mapping[str, object]) -> bool:
    kind = {"Button":"button","Hyperlink":"link","Edit":"input","MenuItem":"menu_item","TabItem":"tab","CheckBox":"checkbox","RadioButton":"radio","Control":"control","ListItem":"control","ComboBox":"input"}.get(str(control.get("control_type")))
    if kind is None:
        return False
    if target.get("role") == "control" and not (control.get("enabled") is True and control.get("visible") is True and set(control.get("patterns") or []) & {"Invoke", "Value", "Selection", "ExpandCollapse", "Toggle"}):
        return False
    return control_target_matches(control.get("name"), kind, target)


def uia_control_is_action_identity(control: Mapping[str, object]) -> bool:
    """身份候选只含直接动作控件或真实动作 pattern；可见性和启用状态另行核验。"""
    from app.gate.fresh_action_risk import _actionable
    from app.operation.screen_inventory.builder import CLICKABLE_UIA_TYPES

    if not isinstance(control, Mapping):
        return False
    kind = str(control.get("control_type") or "").strip().casefold()
    # Value/Text/Scroll 可只是页面只读能力，不能把整页容器提升为点击身份。
    return _actionable(control) or kind in CLICKABLE_UIA_TYPES or kind in {
        "textbox", "text box", "treeitem", "tree item", "splitbutton", "split button",
    }


def explicit_browser_navigation_goal(goal: str) -> bool:
    """只识别明确点浏览器导航按钮的单步目标，不把正文提及当目标。"""
    return bool(re.match(
        r"\s*(?:(?:left|single)[ -]?)?click\s+(?:the\s+)?browser(?:'s)?\s+"
        r"(?:back|forward|refresh|reload)\s+button\b", goal, re.I)
        or re.match(r"\s*点击浏览器(?:工具栏(?:的)?)?(?:返回|后退|前进|刷新)按钮", goal))


def explicit_menu_item_goal(goal: str) -> bool:
    """识别菜单项为动作目标，不能因上下文提到菜单就改用菜单子树。"""
    action = re.match(r"\s*(?:(?:(?:left|right|double|single)[ -]?)?click|select|choose)\s+(?:the\s+)?", goal, re.I)
    if action is None:
        return False
    tail = goal[action.end():]
    menu = r"(?:right[ -]click\s+)?(?:context\s+)?menu"
    if re.match(menu + r"\s+(?:item|option)\b", tail, re.I):
        return True
    # 标签在前的同义语序；排除先操作字段、随后再选菜单的多步指令。
    target = re.match(r"(?P<label>[^,;.!?\n]+?)\s+(?:item|option)\s+(?:in|on|from)\s+(?:the\s+)?" + menu + r"\b", tail, re.I)
    return bool(target and not re.search(r"\b(?:then|inside|within|button|input|field|box|word)\b", target.group("label"), re.I))


def _field_target_label(goal):
    """空标签表示泛型字段；字段前的限定词必须保留为完整名称。"""
    field_pattern = r"\b(?:(?:search\s+)?input\s+(?:box|field)|search\s+(?:box|field)|text\s+(?:box|field|area)|textbox|textarea|combobox)\b"
    # 动作后的方位介词仍指字段本身；框内单词/按钮由下方目标边界排除。
    action = re.match(r"\s*(?:right[ -]?click|double[ -]?click|click|focus|locate)\b\s*(?:(?:on|inside|within|in)\s+)?", goal, re.I)
    if action is None:
        # 裸名词只能由字段角色起头；后缀仅作方位或明确标签，不吞掉按钮、单词或导航目标。
        bare = re.match(r"\s*(?:(?:the|an?)\s+)?" + field_pattern, goal, re.I)
        if bare is not None:
            suffix = goal[bare.end():].strip()
            if (not suffix or re.match(r"(?:labelled|labeled|named)\s+", suffix, re.I)
                    or re.match(r"(?:at|in|on|inside|within|near|above|below|beside|next\s+to)\b", suffix, re.I)
                    and not re.search(r"[,;\n]|\b(?:then|and)\s+(?:click|focus|locate|select|open|navigate)\b", suffix, re.I)):
                return ""
        return None
    tail = goal[action.end():]
    field = re.search(field_pattern, tail, re.I)
    if field is None:
        return None
    prefix = re.sub(r"^\s*(?:the|an?)\s+", "", tail[:field.start()], count=1, flags=re.I).strip()
    if re.search(r"\b(?:inside|within|in|on|word|button|link|label|icon|menu|checkbox|radio)\b|[,;.!?\n]", prefix, re.I):
        return None
    # Quick search input box 的 search 属于名称，不能只留下 Quick。
    if prefix and re.match(r"search\b", field.group(), re.I):
        prefix += " search"
    return " ".join(unicodedata.normalize("NFC", prefix).split())


def generic_field_target(goal, *, control_target=None, target_text=None):
    """只识别直接指向字段的动作，不把框内单词、按钮或明确标签泛化。"""
    from app.operation.recognition.text_match import explicit_target_marker
    if control_target is not None or target_text or explicit_target_marker(goal):
        return False
    return _field_target_label(goal) == ""


def uia_control_has_text_entry_patterns(control):
    """模式仅证明字段候选能力；只读、密码和焦点仍由现场读取器核验。"""
    kind = str(control.get("control_type") or "").casefold()
    patterns = {str(item).casefold() for item in control.get("patterns") or []}
    return (kind in {"edit", "textbox", "text box"} and bool(patterns & {"value", "text"})
            or kind in {"combobox", "combo box"} and {"value", "text"} <= patterns)


def uia_form_label(control):
    """标签关联必须仍属于同一当前控件与矩形，不能移植到另一候选。"""
    binding = control.get("form_label_binding")
    if (isinstance(binding, Mapping) and binding.get("source") in {"labeled_by", "visible_label_geometry"}
            and binding.get("control_id") and binding.get("control_id") == control.get("control_id")
            and binding.get("runtime_id") and binding.get("runtime_id") == control.get("runtime_id")
            and binding.get("bbox") and binding.get("bbox") == control.get("bbox")):
        return str(binding.get("label") or "") or None
    return None


def uia_point_form_role_matches(control, *, goal, control_target=None, target_text=None):
    """仅在未指定标签时，让模型点位与同帧真实表单控件类型互证。"""
    from app.operation.recognition.text_match import explicit_target_marker

    if control_target is not None or target_text or explicit_target_marker(goal):
        return False
    if not isinstance(control, Mapping) or not uia_control_is_action_identity(control):
        return False
    kind = re.sub(r"\s+", "", str(control.get("control_type") or "").casefold())
    patterns = {str(item).casefold() for item in control.get("patterns") or []}
    if kind != "combobox" or not patterns & {"expandcollapse", "selection"}:
        return False
    return bool(re.match(
        r"\s*(?:(?:left|single|double)[ -]?)?(?:click|open|focus|locate|select|choose)\s+"
        r"(?:(?:the|an?)\s+)?(?:(?:empty|blank|visible|current)\s+)*"
        r"(?:multi[ -]?select(?:\s+(?:box|control|dropdown))?|"
        r"select(?:ion)?\s+(?:box|control)|dropdown|combo\s*box)\b",
        goal, re.I))


def uia_action_identity_matches(control, *, goal, control_target=None, target_text=None):
    """生产者与消歧消费者共用原始匹配集合，不用选中标签缩小候选集合。"""
    from app.operation.recognition.candidate_ranker import _goal_label_match

    if not isinstance(control, Mapping) or not uia_control_is_action_identity(control):
        return False
    if control_target is not None:
        return uia_control_matches(control, control_target)
    from app.operation.recognition.text_match import explicit_target_role, explicit_target_marker
    requested_role = explicit_target_role(goal)
    if requested_role is not None:
        expected = {"menu item": {"menuitem"}, "radio button": {"radiobutton"},
                    "hyperlink": {"hyperlink"}, "link": {"hyperlink"}, "button": {"button", "splitbutton"},
                    "tab": {"tabitem"}, "checkbox": {"checkbox"},
                    "dropdown": {"combobox"}, "option": {"listitem", "menuitem"},
                    "input": {"edit", "textbox", "combobox"}, "field": {"edit", "textbox", "combobox"}}
        if re.sub(r"\s+", "", str(control.get("control_type") or "").casefold()) not in expected[requested_role]:
            return False
        if requested_role in {"input", "field"} and not uia_control_has_text_entry_patterns(control):
            return False
    field_label = _field_target_label(goal) if explicit_target_marker(goal) is None else None
    if generic_field_target(goal, target_text=target_text) or field_label:
        # 动态值不是字段标签；这里只限定角色，唯一几何与状态由当前树消费者核验。
        editable = uia_control_has_text_entry_patterns(control)
        if field_label:
            label = " ".join(unicodedata.normalize("NFC", str(control.get("name") or "")).split()).casefold()
            requested = field_label.casefold()
            # 普通字段语句容忍标签末尾的单个冒号；不删内部文字或显式结构化身份。
            if label.endswith((":", "：")) and not label[:-1].rstrip().endswith((":", "：")):
                label = label[:-1].rstrip()
            if requested.endswith((":", "：")) and not requested[:-1].rstrip().endswith((":", "：")):
                requested = requested[:-1].rstrip()
            labels = {label}
            alias = uia_form_label(control)
            if alias:
                labels.add(" ".join(unicodedata.normalize("NFC", alias).split()).casefold().rstrip(":：").rstrip())
            return editable and requested in labels and (not target_text or requested == " ".join(str(target_text).split()).casefold())
        return editable
    target_key = re.sub(r'\s+', ' ', str(target_text or '').strip().casefold())
    label_key = re.sub(r'\s+', ' ', str(control.get('name') or '').strip().casefold())
    if requested_role in {"input", "field", "dropdown", "checkbox", "radio button", "button"}:
        from app.operation.recognition.text_match import explicit_target_label
        alias = uia_form_label(control)
        requested = explicit_target_label(goal)
        if alias and requested and " ".join(alias.split()).casefold() == " ".join(requested.split()).casefold():
            return not target_key or target_key == " ".join(alias.split()).casefold()
    return ((not target_key or label_key == target_key)
            and _goal_label_match(goal, [str(control.get('name') or '')], negated=False))
