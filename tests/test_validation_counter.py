from __future__ import annotations

from modules.validation.counter import counter_value, evaluate_counter_result


def test_counter_value_returns_largest_numeric_token() -> None:
    assert counter_value(["abc", "62", "7"]) == 62


def test_counter_value_returns_none_without_digits() -> None:
    assert counter_value(["abc", "  "]) is None


def test_evaluate_counter_result_marks_strict_success_on_increase() -> None:
    result = evaluate_counter_result(["0", "62"], ["0", "63"])
    assert result["strict_success"] is True
    assert result["weak_success"] is True
    assert result["strict_score"] >= 3


def test_evaluate_counter_result_marks_weak_success_on_any_change() -> None:
    result = evaluate_counter_result(["0", "62"], ["0", "6"])
    assert result["strict_success"] is False
    assert result["weak_success"] is True
