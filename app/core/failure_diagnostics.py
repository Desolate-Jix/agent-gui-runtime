"""只记录异常位置，不写入字段内容、凭证或异常原文。"""
import logging
import traceback


def log_failure_structure(error: BaseException, operation: str) -> None:
    causes = []
    seen = set()
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        causes.append({"type": type(current).__name__, "frames": [
            {"file": item.filename, "line": item.lineno, "function": item.name}
            for item in traceback.extract_tb(current.__traceback__)]})
        # 即使公开边界使用 from None 隐去供应方原文，也只保留其安全位置。
        current = current.__cause__ if current.__cause__ is not None else current.__context__
    logging.getLogger(__name__).warning("runtime_failure_structure %s %s", operation, causes)
