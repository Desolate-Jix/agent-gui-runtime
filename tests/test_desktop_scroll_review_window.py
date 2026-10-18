from __future__ import annotations

import copy

from PySide6.QtTest import QTest

from app.desktop_review.window import ReviewMainWindow, ensure_application
from test_desktop_review_window import _Facade, _batch, _wait_loaded, _wait_workers


PARAMETERS = {
    "contract_version": "reviewed_scroll_parameters_v1",
    "target_container_id": "apply",
    "axis": "vertical",
    "direction": "down",
    "wheel_clicks": 3,
    "unit": "wheel_detent",
}


def test_native_scroll_controls_edit_save_and_clear_non_scroll_parameters():
    application = ensure_application()
    batch = _batch()
    batch["steps"][0].update(action_type="scroll_region", scroll_parameters=copy.deepcopy(PARAMETERS))
    facade = _Facade([batch])
    window = ReviewMainWindow(facade)
    window.show()
    window.load_batch("task-1", "batch-1")
    try:
        _wait_loaded(window)
        _wait_workers(window)
        window.step_table.selectRow(0)
        application.processEvents()
        assert window.scroll_direction.currentData() == "down"
        assert window.scroll_wheel_clicks.value() == 3
        window.scroll_direction.setCurrentIndex(window.scroll_direction.findData("up"))
        window.scroll_wheel_clicks.setValue(4)
        assert window.workspace["batch"]["steps"][0]["scroll_parameters"] == {**PARAMETERS, "direction": "up", "wheel_clicks": 4}
        window.save_current()
        _wait_workers(window)
        assert facade.saved[-1]["steps"][0]["scroll_parameters"]["direction"] == "up"
        window.step_action.setText("open_detail")
        assert "scroll_parameters" not in window.workspace["batch"]["steps"][0]
    finally:
        _wait_workers(window)
        window._dirty = False
        window.close()
        application.processEvents()
