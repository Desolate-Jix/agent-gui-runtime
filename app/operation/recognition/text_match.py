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


def explicit_target_label(goal: str) -> str | None:
    # 仅抽取明确标记的标签，不猜测任意自然语言中的目标。
    marker = re.search(r"\b(labelled|labeled|named|titled)\s+", goal, re.I)
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
    boundary = r"\s+(?:whose|in|on)\b"
    if marker.group(1).casefold() != "titled":
        boundary += r"|\s*\("
    label = re.split(boundary, tail, maxsplit=1, flags=re.I)[0].strip()
    # 未加引号的多个备选标签不是单一身份，继续走原有多候选判断。
    if re.search(r"\s+or\s+", label, re.I):
        return None
    return label or None
