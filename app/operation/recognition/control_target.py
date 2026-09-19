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


def generic_field_target(goal, *, control_target=None, target_text=None):
    """只识别直接指向字段的动作，不把框内单词、按钮或明确标签泛化。"""
    from app.operation.recognition.text_match import explicit_target_marker
    if control_target is not None or target_text or explicit_target_marker(goal):
        return False
    # 动作后的方位介词仍指字段本身；框内单词/按钮由下方目标边界排除。
    action = re.match(r"\s*(?:right[ -]?click|double[ -]?click|click|focus|locate)\b\s*(?:(?:on|inside|within|in)\s+)?", goal, re.I)
    if action is None:
        return False
    tail = goal[action.end():]
    field = re.search(r"\b(?:input\s+(?:box|field)|search\s+(?:box|field)|text\s+(?:box|field|area)|textbox|textarea|combobox)\b", tail, re.I)
    if field is None:
        return False
    return re.search(r"\b(?:inside|within|in|on|word|button|link|label|icon|menu|checkbox|radio)\b", tail[:field.start()], re.I) is None


def uia_action_identity_matches(control, *, goal, control_target=None, target_text=None):
    """生产者与消歧消费者共用原始匹配集合，不用选中标签缩小候选集合。"""
    from app.operation.recognition.candidate_ranker import _goal_label_match

    if not isinstance(control, Mapping) or not uia_control_is_action_identity(control):
        return False
    if control_target is not None:
        return uia_control_matches(control, control_target)
    if generic_field_target(goal, target_text=target_text):
        # 动态值不是字段标签；这里只限定角色，唯一几何与状态由当前树消费者核验。
        kind = str(control.get("control_type") or "").casefold()
        patterns = {str(item).casefold() for item in control.get("patterns") or []}
        return (kind in {"edit", "textbox", "text box"} and bool(patterns & {"value", "text"})
                or kind in {"combobox", "combo box"} and {"value", "text"} <= patterns)
    target_key = re.sub(r'\s+', ' ', str(target_text or '').strip().casefold())
    label_key = re.sub(r'\s+', ' ', str(control.get('name') or '').strip().casefold())
    return ((not target_key or label_key == target_key)
            and _goal_label_match(goal, [str(control.get('name') or '')], negated=False))
