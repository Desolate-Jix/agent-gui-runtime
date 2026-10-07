import importlib.util
from hashlib import sha256
import json
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QPushButton, QWidget


def fixture_class():
    path = Path(__file__).parent / "fixtures" / "learning_workflow_app.py"
    spec = importlib.util.spec_from_file_location("learning_workflow_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.LearningWorkflowWindow


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_fresh_native_fixture_reorders_and_reads_current_detail(qapp):
    expected = {"R-101": "first result", "R-202": "second result"}
    window = fixture_class()([
        {"id": "R-101", "name": "Same title", "detail": expected["R-101"]},
        {"id": "R-202", "name": "Same title", "detail": expected["R-202"]},
    ])
    window.show()
    window.reorder_rows(["R-202", "R-101"])
    row = window.findChild(QWidget, "recordRow_R-101")
    assert row is not None
    row.findChild(QPushButton, "openDetailButton").click()
    assert window.detail_output.text() == f"ID: R-101 | Detail: {expected['R-101']}"
    window.query_field.setText("R-202")
    window.search_button.click()
    assert window.findChild(QWidget, "recordRow_R-101") is None
    assert window.findChild(QWidget, "recordRow_R-202") is not None
    window.notice_button.click()
    assert window.notice_dialog.isVisible()
    window.notice_dialog.findChild(QPushButton, "closeNoticeButton").click()
    assert not window.notice_dialog.isVisible()
    window.close()


def test_current_detail_flows_only_through_observed_controlled_field(qapp):
    events = []
    window = fixture_class()([
        {"id": "R-101", "name": "Same title", "detail": "old-current-value"},
        {"id": "R-202", "name": "Same title", "detail": "another-value"},
    ], event_sink=events.append)
    window.show()
    row = window.findChild(QWidget, "recordRow_R-101")
    row.findChild(QPushButton, "openDetailButton").click()
    assert window.controlled_field.objectName() == "controlledField"
    assert window.controlled_field.accessibleName() == "Controlled value field"
    assert window.controlled_field.text() == ""
    window.controlled_field.setText("old-current-value")
    window.verify_button.click()
    assert window.verification_output.text() == "Matches current detail"
    window.update_detail("R-101", "new-current-value")
    assert window.detail_output.text() == "ID: R-101 | Detail: new-current-value"
    assert window.controlled_field.text() == "old-current-value"
    assert window.verification_output.text() == "Not verified"
    window.verify_button.click()
    assert events[-1]["matched"] is False
    window.controlled_field.setText("new-current-value")
    window.verify_button.click()
    assert {key: events[-2][key] for key in ("action", "actual_value")} == {
        "action": "controlled_field_changed", "actual_value": "new-current-value"}
    assert events[-1]["action"] == "verify_field"
    assert events[-1]["record_id"] == "R-101"
    assert events[-1]["actual_value"] == "new-current-value"
    assert events[-1]["expected_detail"] == "new-current-value"
    assert events[-1]["matched"] is True
    assert window.verification_output.text() == "Matches current detail"
    other = window.findChild(QWidget, "recordRow_R-202")
    other.findChild(QPushButton, "openDetailButton").click()
    assert window.verification_output.text() == "Not verified"
    assert window.detail_output.text() == "ID: R-202 | Detail: another-value"
    assert window.controlled_field.text() == "new-current-value"
    window.close()


def test_reset_case_clears_old_success_and_repositions_real_widgets(qapp):
    events = []
    window = fixture_class()([
        {"id": "R-101", "name": "Old", "detail": "old-value"},
        {"id": "R-202", "name": "Old", "detail": "other-value"},
    ], event_sink=events.append)
    window.show()
    handle = int(window.winId())
    window.findChild(QWidget, "recordRow_R-101").findChild(QPushButton, "openDetailButton").click()
    window.controlled_field.setText("old-value")
    window.verify_button.click()
    window.notice_button.click()
    assert window.verification_output.text() == "Matches current detail"
    assert window.notice_dialog.isVisible()
    prior_index = events[-1]["event_index"]
    new_records = [
        {"id": "R-303", "name": "Same", "detail": "current-3"},
        {"id": "R-404", "name": "Same", "detail": "current-4"},
    ]
    window.reset_case(case_id="case-2", records=new_records,
                      ordered_ids=["R-404", "R-303"], layout_variant="search_below_rows")
    assert int(window.winId()) == handle
    assert not window.notice_dialog or not window.notice_dialog.isVisible()
    snapshot = window.state_snapshot()
    assert snapshot == {"case_id": "case-2", "event_index": prior_index + 1,
                        "reset_event_index": prior_index + 1,
                        "records": [new_records[1], new_records[0]], "visible_ids": ["R-404", "R-303"],
                        "selected_id": None, "query": "", "detail_text": "No record selected",
                        "controlled_value": "", "verification_text": "Not verified",
                        "layout_variant": "search_below_rows", "notice_visible": False}
    assert events[-1]["action"] == "case_reset"
    assert events[-1]["case_id"] == "case-2"
    assert events[-1]["event_index"] == prior_index + 1
    assert events[-1]["order"] == ["R-404", "R-303"]
    assert events[-1]["layout_variant"] == "search_below_rows"
    assert events[-1]["records_sha256"] == sha256(json.dumps(snapshot["records"], ensure_ascii=False,
        sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    layout = window.layout()
    assert layout.indexOf(window.rows_container) < layout.indexOf(window.search_area)
    assert layout.indexOf(window.search_area) < layout.indexOf(window.detail_output)
    snapshot["records"][0]["detail"] = "mutated-copy"
    snapshot["visible_ids"].reverse()
    assert window.state_snapshot()["records"][0]["detail"] == "current-4"
    assert window.state_snapshot()["visible_ids"] == ["R-404", "R-303"]
    window.query_field.setText("R-303")
    assert events[-1]["case_id"] == "case-2"
    assert events[-1]["event_index"] == prior_index + 2
    window.reset_case(case_id="case-2", records=new_records,
                      ordered_ids=["R-303", "R-404"], layout_variant="detail_above_rows")
    assert window.state_snapshot()["reset_event_index"] == prior_index + 3
    assert layout.indexOf(window.search_area) < layout.indexOf(window.detail_output)
    assert layout.indexOf(window.detail_output) < layout.indexOf(window.rows_container)
    window.close()


def test_invalid_reset_is_atomic_and_reorder_survives_filter(qapp):
    events = []
    records = [{"id": "R-101", "name": "A", "detail": "one"},
               {"id": "R-202", "name": "B", "detail": "two"}]
    window = fixture_class()(records, event_sink=events.append)
    window.show()
    window.reorder_rows(["R-202", "R-101"])
    window.query_field.setText("R-")
    window.search_button.click()
    assert window.state_snapshot()["visible_ids"] == ["R-202", "R-101"]
    before = window.state_snapshot()
    before_events = len(events)
    bad_calls = [
        {"case_id": "", "records": records, "ordered_ids": ["R-101", "R-202"], "layout_variant": "default"},
        {"case_id": "case-é", "records": records, "ordered_ids": ["R-101", "R-202"], "layout_variant": "default"},
        {"case_id": "case", "records": [records[0], records[0]],
         "ordered_ids": ["R-101", "R-101"], "layout_variant": "default"},
        {"case_id": "case", "records": records, "ordered_ids": ["R-101", "R-101"], "layout_variant": "default"},
        {"case_id": "case", "records": records, "ordered_ids": ["R-101", "R-202"], "layout_variant": "fake"},
    ]
    for arguments in bad_calls:
        with pytest.raises(ValueError):
            window.reset_case(**arguments)
        assert window.state_snapshot() == before
        assert len(events) == before_events
    window.close()
