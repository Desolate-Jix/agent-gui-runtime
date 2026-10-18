"""执行前文本输入仅驱动离屏 Qt，不创建 Runtime 或接触真实剪贴板。"""
import pytest
from PySide6.QtWidgets import QDialog

from app.agent.text_parameters import ReviewedTextParameters, ReviewedTextSource
from app.desktop_review.window import ensure_application


def parameters(kind="variable", value="query", *, clear=True):
    return ReviewedTextParameters("query-field", ReviewedTextSource(kind, value), clear, False)


@pytest.mark.parametrize("text", ["", "中文\r\n第二行\r第三行", "<b>literal</b>"])
def test_fixed_dialog_preserves_exact_reviewed_text_without_editing(text):
    from app.desktop_review.text_input_dialog import TextInputDialog

    ensure_application()
    dialog = TextInputDialog(parameters("literal", text))
    assert dialog.text_editor.isReadOnly()
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.resolved.text == text
    assert dialog.text_values == {}
    dialog.close()


def test_variable_input_freezes_actual_value_and_never_reuses_prior_input():
    from app.desktop_review.text_input_dialog import TextInputDialog

    ensure_application()
    dialog = TextInputDialog(parameters())
    assert not dialog.text_editor.isReadOnly()
    dialog.text_editor.setPlainText("本次输入\n下一行")
    dialog.accept()
    assert dialog.resolved.text == "本次输入\n下一行"
    exposed = dialog.text_values
    exposed["query"] = "mutated"
    dialog.text_editor.setPlainText("later")
    assert dialog.text_values == {"query": "本次输入\n下一行"}
    fresh = TextInputDialog(parameters())
    assert fresh.text_editor.toPlainText() == ""
    fresh.accept()
    assert fresh.text_values == {"query": ""}
    dialog.close()
    fresh.close()


def test_cancel_has_no_usable_value_and_invalid_input_does_not_accept():
    from app.desktop_review.text_input_dialog import TextInputDialog

    ensure_application()
    dialog = TextInputDialog(parameters(clear=False))
    assert "插入" in dialog.mode_label.text()
    assert "追加" not in dialog.mode_label.text()
    dialog.text_editor.setPlainText("x" * 32769)
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.error_label.text()
    dialog.reject()
    with pytest.raises(ValueError):
        _ = dialog.text_values
    dialog.close()
