"""局部识别与动作判断共用匹配规则；短中文只接受完整词段。"""
import json
import re
from difflib import SequenceMatcher


def normalize_text(value: str) -> str:
    return " ".join(re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", str(value or "").casefold()).split())


def text_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    short, long = sorted((left, right), key=len)
    if len(short) >= 3 and short in long:
        return 0.9
    if re.fullmatch(r"[\u4e00-\u9fff]{2}", short) and short in long.split():
        return 0.9
    a, b = set(left.split()), set(right.split())
    return max(len(a & b) / len(a | b), SequenceMatcher(None, left, right).ratio())


_FIELD_ROLE = r"(?:search\s+|text\s+)?input\s+(?:box|field)|text\s+(?:box|field|area)|search\s+(?:box|field)|textbox|textarea"
_TARGET_ROLE = rf"menu\s+item|radio\s+button|hyperlink|link|button|tab|checkbox|dropdown|option|{_FIELD_ROLE}|input|field"


def explicit_target_marker(goal: str):
    marker = re.search(
        r"\b(labelled|labeled|named|titled)\s+|"
        r"\b(?:double[ -]?click|click|select)\s+(?:the\s+)?(?P<word>word)\s+|"
        r"\b(?:double[ -]?click|click|select|choose|locate)\s+(?:the\s+)?"
        rf"(?:(?P<quoted_role>{_TARGET_ROLE})\s+)?"
        r"(?P<quoted>(?=[\"'“‘]))|"
        r"\A\s*(?:click|select|choose|locate)\s+(?:the\s+)?"
        r"(?=(?P<native_label>\w[\w .-]{0,80}?(?:\(&?[A-Za-z]\)|（&?[A-Za-z]）))\s+"
        r"(?P<native_role>button|tab|menu\s+item)\b(?P<native_suffix>[^\r\n]*$))",
        goal, re.I)
    if marker and marker.group("native_label") is not None:
        label, suffix = marker.group("native_label"), marker.group("native_suffix").strip()
        # 助记字母是原生控件名称的一部分；只认动作宾语，不把方位、备选或多步指令当名称。
        if (re.search(r"\b(?:or|and|not|then|inside|within|in|on|input|field|button|link)\b", label, re.I)
                or suffix and not re.match(r"(?:[.]?$|(?:at|in|on|to|for|near|above|below|beside)\b)", suffix, re.I)
                or re.search(r"[;；]|\b(?:or|and|not|never|then|click|press|select|choose|type)\b", suffix, re.I)
                or re.search(r"(?:\(&?[A-Za-z]\)|（&?[A-Za-z]）)", suffix)):
            return None
    return marker


def _quoted_label_end(tail: str) -> int:
    if tail.startswith('"'):
        try:
            # 结构化标签采用 JSON 引号；转义引号不能提前终止字段身份。
            _, end = json.JSONDecoder().raw_decode(tail)
            return end - 1
        except json.JSONDecodeError:
            # 保留自然语言中的未转义路径及历史引号写法。
            pass
    closing = {'"': '"', "'": "'", '“': '”', '‘': '’'}.get(tail[:1])
    return next((i for i in range(1, len(tail)) if tail[i] == closing
                 and not (closing == "'" and i + 1 < len(tail)
                          and tail[i - 1].isalnum() and tail[i + 1].isalnum())), -1)


def explicit_target_role(goal: str) -> str | None:
    marker = explicit_target_marker(goal)
    if marker is None:
        return None
    role = marker.group("quoted_role") or marker.group("native_role")
    if not role:
        prefix = re.search(rf"\b({_TARGET_ROLE})\s*$", goal[:marker.start()], re.I)
        role = prefix.group(1) if prefix else None
    if not role and marker.group("quoted") is not None:
        tail = goal[marker.end():].strip()
        end = _quoted_label_end(tail)
        # 只读取紧邻标签及可选翻译后的角色，不采纳后续位置说明中的控件名。
        suffix = re.match(rf"\s*(?:\([^()]*\)\s*)?({_TARGET_ROLE})\b", tail[end + 1:], re.I) if end > 0 else None
        role = suffix.group(1) if suffix else None
    if role and re.fullmatch(_FIELD_ROLE, role, re.I):
        return "input"
    return " ".join(role.casefold().split()) if role else None


def explicit_target_label(goal: str) -> str | None:
    # 仅抽取明确标记的标签，不猜测任意自然语言中的目标。
    marker = explicit_target_marker(goal)
    if marker is None:
        return None
    if marker.group("native_label") is not None:
        return marker.group("native_label").strip()
    tail = goal[marker.end():].strip()
    if not tail:
        return None
    # 引号内的括号、介词属于标签，不能按上下文分隔符截断。
    closing = {'"': '"', "'": "'", '“': '”', '‘': '’'}.get(tail[0])
    if closing is not None:
        # 单词内部的撇号不是标签结束；引号后的备选项仍是歧义目标。
        end = _quoted_label_end(tail)
        if end > 0 and re.match(rf"\s+(?:\([^()]*\)\s*)?(?:(?:{_TARGET_ROLE})\s+)?or\b", tail[end + 1:], re.I):
            return None
        if end > 0 and tail.startswith('"'):
            try:
                return json.loads(tail[:end + 1]).strip() or None
            except json.JSONDecodeError:
                pass
        return (tail[1:end].strip() or None) if end > 0 else None
    # titled 的括号可为正式标题缩写；保留 labelled 的历史括号说明语法。
    kind = (marker.group(1) or marker.group("word")).casefold()
    boundary = r"\s+(?:whose|in|on)\b"
    if kind == "word":
        boundary = r"\s+(?:inside|within|in|on|at|to|for)\b"
    # 逗号后明确的位置说明不属于标签；引号内的同样文字已在上方完整保留。
    boundary += r"|,\s*(?:(?:directly|immediately)\s+)?(?:above|below|beside|next\s+to|to\s+the\s+(?:left|right)\s+of)\b"
    if kind != "titled":
        boundary += r"|\s*\("
    label = re.split(boundary, tail, maxsplit=1, flags=re.I)[0].strip()
    # 未加引号的多个备选标签不是单一身份，继续走原有多候选判断。
    if re.search(r"\s+or\s+", label, re.I):
        return None
    # 未加引号的单词目标只接受一个明确词，不把容器描述当作标签。
    if kind == "word" and (not re.fullmatch(r"[\w'-]+", label)
                           or label.casefold() in {"in", "inside", "within", "on", "at", "to", "for"}):
        return None
    return label or None


def explicit_word_target(goal: str) -> str | None:
    marker = explicit_target_marker(goal)
    return explicit_target_label(goal) if marker and marker.group("word") else None
