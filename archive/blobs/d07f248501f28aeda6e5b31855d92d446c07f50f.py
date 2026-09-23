"""局部识别与动作判断共用匹配规则；短中文只接受完整词段。"""
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


def explicit_target_marker(goal: str):
    return re.search(
        r"\b(labelled|labeled|named|titled)\s+|"
        r"\b(?:double[ -]?click|click|select)\s+(?:the\s+)?(?P<word>word)\s+",
        goal, re.I)


def explicit_target_label(goal: str) -> str | None:
    # 仅抽取明确标记的标签，不猜测任意自然语言中的目标。
    marker = explicit_target_marker(goal)
    if marker is None:
        return None
    tail = goal[marker.end():].strip()
    if not tail:
        return None
    # 引号内的括号、介词属于标签，不能按上下文分隔符截断。
    closing = {'"': '"', "'": "'", '“': '”', '‘': '’'}.get(tail[0])
    if closing is not None:
        end = tail.find(closing, 1)
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
