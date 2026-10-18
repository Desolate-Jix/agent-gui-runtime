"""区分空字段文字缺失与当前控件身份缺失；诊断不授予执行权限。"""
from collections.abc import Mapping

from app.operation.recognition.control_corroboration import _inside


def diagnose_unverified_editable_target(*, goal, point, uia_snapshot, semantic_action=None, control_target=None):
    from app.operation.recognition.candidate_ranker import _goal_requests_text_entry

    explicit_field = isinstance(control_target, Mapping) and control_target.get("role") == "input"
    if not (explicit_field or semantic_action == "fill_field" or _goal_requests_text_entry(goal)):
        return None
    uia = uia_snapshot if isinstance(uia_snapshot, Mapping) else {}
    controls = uia.get("controls")
    complete = (uia.get("status") == "ok" and uia.get("scan_complete") is True
                and uia.get("truncated") is False and isinstance(controls, list)
                and all(isinstance(control, Mapping) for control in controls))
    hits = [control for control in (controls if complete else [])
            if str(control.get("control_type") or "").casefold() in {"edit", "combobox", "combo box", "textbox", "text box"}
            and control.get("visible") is True and control.get("enabled") is True
            and _inside(control.get("bbox"), point)]
    status = ("current_editable_snapshot_unavailable" if not complete else
              "current_editable_control_missing" if not hits else "current_editable_control_unverified")
    return {"contract_version": "editable_target_diagnostic_v1", "status": status,
            "point": dict(point), "scan_complete": complete,
            "control_ids_at_point": [control.get("control_id") for control in hits],
            "next_action": "capture_fresh_target_and_inspect_current_controls",
            "automatic_retry_allowed": False, "artifact_is_authorization": False,
            "action_executed": False}
