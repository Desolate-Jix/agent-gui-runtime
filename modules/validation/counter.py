from __future__ import annotations

from typing import Optional


def counter_value(texts: list[str]) -> Optional[int]:
    values: list[int] = []
    for text in texts:
        normalized = text.strip()
        if normalized.isdigit():
            values.append(int(normalized))
    if not values:
        return None
    return max(values)


def evaluate_counter_result(before_numeric_texts: list[str], after_numeric_texts: list[str]) -> dict[str, object]:
    before_val = counter_value(before_numeric_texts)
    after_val = counter_value(after_numeric_texts)
    counter_changed = before_numeric_texts != after_numeric_texts
    strict_score = 0
    if before_val is not None and after_val is not None and after_val > before_val:
        strict_score += 3
    if counter_changed:
        strict_score += 1
    return {
        "target_counter_before": before_val,
        "target_counter_after": after_val,
        "strict_success": strict_score >= 3,
        "weak_success": counter_changed,
        "counter_changed": counter_changed,
        "strict_score": strict_score,
    }
