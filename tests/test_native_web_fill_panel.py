"""网页当前字段、确切记忆版本和本地填写值经过真实原生预览校验。"""

from copy import deepcopy
from dataclasses import replace
import os
from pathlib import Path

import pytest

from app.desktop_review.grounded_preview_widget import GroundedPreviewWidget
from app.desktop_review.window import ensure_application
from tests.test_fresh_web_text_integration import _ready_web_fill
from tests.test_native_fresh_text_preview import _view


@pytest.mark.parametrize("variable", [False, True])
def test_web_fill_panel_preserves_version_values_and_clears_rejected_state(tmp_path, variable):
    application = ensure_application()
    with _ready_web_fill(tmp_path, variable=variable) as rig:
        view = _view(rig["runtime"], rig["claim"])
        view["phase"] = "approved"
        widget = GroundedPreviewWidget()
        try:
            widget.resize(1120, 840)
            widget.set_review(view)
            widget.show()
            application.processEvents()
            text = rig["parameters"].text
            assert widget.text_value_editor.toPlainText() == text
            assert widget.text_expected_editor.toPlainText() == text
            assert widget.text_before_editor.toPlainText() == rig["owner"]._text_field_reader.value
            assert widget.text_expected_editor.isReadOnly()
            assert widget.text_before_editor.isVisible()
            metadata = widget.metadata_text.toPlainText()
            assert "应用来源（Web）：https://fresh.example" in metadata
            assert rig["selection"]["version_id"] in metadata
            assert rig["latest"]["version_id"] not in metadata
            assert ("变量 place" if variable else "固定内容") in metadata
            assert "不按 Enter，不提交" in metadata
            assert widget.view.sceneRect().width() == 160
            assert widget.view.sceneRect().height() == 100
            output = Path(os.environ.get("AGENT_REVIEW_PANEL_EVIDENCE_DIR", str(tmp_path)))
            output.mkdir(parents=True, exist_ok=True)
            assert widget.grab().save(str(output / ("web-fill-variable.png" if variable else "web-fill-literal.png")))
            assert rig["input"].calls == []

            wrong = deepcopy(view)
            wrong["text_field_local"] = replace(view["text_field_local"],
                before=replace(view["text_field_local"].before, value="different"))
            with pytest.raises(ValueError):
                widget.set_review(wrong)
            assert widget.review is None
            assert widget.text_value_editor.toPlainText() == ""
            assert not widget.text_value_editor.isVisible()
            assert rig["input"].calls == []

            widget.set_review(view)
            bad_image = deepcopy(view)
            bad_image["png_bytes"] = b"not-the-bound-screenshot"
            with pytest.raises(ValueError):
                widget.set_review(bad_image)
            assert widget.review is None
            assert widget.view.scene().items() == []
            assert rig["input"].calls == []
        finally:
            widget.close()
            widget.deleteLater()
            application.processEvents()
