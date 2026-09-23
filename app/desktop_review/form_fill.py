"""有界表单编排：复用受控单步，逐字段验证；禁止自动提交和重放。"""
import json
import re
import unicodedata
from datetime import date
from time import perf_counter
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from .input_sequence import _action_data, run_input_sequence


def _nonblank(value):
    if not value.strip():
        raise ValueError("form field strings must not be blank")
    return value


Label = Annotated[str, Field(min_length=1, max_length=500), AfterValidator(_nonblank)]
Text = Annotated[str, Field(min_length=1, max_length=20000), AfterValidator(_nonblank)]
Goal = Annotated[str, Field(min_length=1, max_length=2000), AfterValidator(_nonblank)]


def _iso_date(value):
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        raise ValueError("date value must be ISO YYYY-MM-DD")
    try:
        date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("date value must be a real calendar date") from error
    return value


ISODate = Annotated[str, AfterValidator(_iso_date)]


class _StrictField(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class TextField(_StrictField):
    kind: Literal["text"]
    field_goal: Goal
    text: Text
    clear_existing: bool = True
    label: Label | None = None


class DateField(_StrictField):
    kind: Literal["date"]
    field_goal: Goal
    value: ISODate
    format: Literal["YYYY-MM-DD", "DD/MM/YYYY", "MM/DD/YYYY"]


class DropdownField(_StrictField):
    kind: Literal["dropdown"]
    label: Label
    option: Label


class CheckboxField(_StrictField):
    kind: Literal["checkbox"]
    label: Label
    checked: bool


class RadioField(_StrictField):
    kind: Literal["radio"]
    label: Label


FormField = Annotated[TextField | DateField | DropdownField | CheckboxField | RadioField,
    Field(discriminator="kind")]


class FormFillRequest(_StrictField):
    fields: list[FormField] = Field(min_length=1, max_length=32)
    text_navigation: Literal["recognize_each", "tab_sequence"] = "recognize_each"

    @model_validator(mode="after")
    def check_tab_group(self):
        if self.text_navigation == "tab_sequence":
            if any(not isinstance(item, TextField) or not item.label for item in self.fields):
                raise ValueError("tab_sequence requires only text fields with exact accessible labels")
            labels = [" ".join(item.label.split()).casefold() for item in self.fields]
            if len(labels) != len(set(labels)):
                raise ValueError("tab_sequence requires distinct field labels")
        return self


class FormFillInterrupted(ValueError):
    pass


def _option_matches(options, requested):
    """精确项优先；仅允许唯一大小写/空白等价项，不做子串或近似语义匹配。"""
    exact = [item for item in options if item.get("label") == requested]
    if exact:
        return exact, "exact"
    def normalized(value):
        return " ".join(unicodedata.normalize("NFC", value).split()).casefold() if isinstance(value, str) else None
    key = normalized(requested)
    return [item for item in options if normalized(item.get("label")) == key], "case_whitespace"


def run_form_fill(coordinator, target, request, *, persist=None):
    """串行执行已声明字段；状态未知即中断，保留最后尝试的原始回执。"""
    spec = FormFillRequest.model_validate(request)
    if target is None:
        raise ValueError("select a target window before form_fill")
    started = perf_counter()
    previous_text = None
    result = {"contract_version": "form_fill_v1", "status": "running", "phase": "starting",
        "fields": [], "completed_fields": [], "interrupted_at": None,
        "action_executed": False, "capture": None, "observation": {"status": "not_requested"},
        "task_effect_verified": None, "automatic_retry_allowed": False, "error": None}
    result.update(requested_fields=len(spec.fields), text_navigation=spec.text_navigation)

    def checkpoint():
        result["remaining_fields"] = [i for i in range(len(spec.fields)) if i not in result["completed_fields"]]
        result["total_ms"] = round((perf_counter() - started) * 1000, 3)
        if persist is not None:
            persist(result)

    def merge_action(value):
        if value is True:
            result["action_executed"] = True
        elif value is None and result["action_executed"] is not True:
            result["action_executed"] = None

    def frames(receipt):
        if result["capture"] is None:
            result["capture"] = receipt.get("capture")
        result["observation"] = receipt.get("observation") or {"status": "unavailable"}

    def action(row, name, goal, field, before, option=None):
        from app.agent.windows_form_control_reader import read_form_control
        from app.core.local_control_target import LocalControlTarget
        binding = LocalControlTarget(lambda: read_form_control(coordinator, target, field.label, field.kind,
            expected_runtime_id=before["runtime_id"]), before, expected_option=option)
        result["phase"] = name
        result["observation"] = {"status": "unavailable", "reason": "action_in_progress"}
        step = {"name": name, "operation": "execute_recognition_plan",
            "status": "dispatching", "action_executed": None}
        row["steps"].append(step)
        checkpoint()
        at = perf_counter()
        try:
            receipt = coordinator.execute_local_step(target_window_handle=target["handle"],
                target_process_id=target["process_id"], operation="execute_recognition_plan",
                request={"goal": goal, "click_kind": "single"},
                include_observation=True, observation_wait_ms=0, control_target=binding)
        except Exception:
            step["status"] = "result_unknown"
            merge_action(None)
            raise
        finally:
            step["elapsed_ms"] = round((perf_counter() - at) * 1000, 3)
        step.update(status=receipt.get("phase"), receipt=receipt)
        frames(receipt)
        data = _action_data(receipt)
        dispatched = (data.get("execution_path") or {}).get("action_executed", data.get("action_executed"))
        step["action_executed"] = dispatched if type(dispatched) is bool else None
        merge_action(step["action_executed"])
        checkpoint()
        if (receipt.get("response") or {}).get("success") is not True or dispatched is not True:
            reason = ((data.get("control_target_check") or {}).get("error_code")
                or ((receipt.get("response") or {}).get("error") or {}).get("code"))
            raise FormFillInterrupted(reason or "form_input_not_confirmed")
        binding.verify_receipt(data.get("selected_click_point"), data.get("selected_click_point_coordinate_space"))
        if not (result["observation"].get("capture") or {}).get("sha256"):
            raise FormFillInterrupted("form_observation_unavailable")
        return receipt

    def current_state_unavailable(row, reason):
        row["check"] = {"status": "unavailable", "reason": reason}
        # 读取异常和未知状态都不能用旧后图代表当前窗口；历史图留在原单步回执。
        result["observation"] = {"status": "unavailable", "error_code": reason,
            "reason": "current_form_state_unavailable",
            "next_action": "capture_current_state_without_replaying_input",
            "automatic_retry_allowed": False}

    def read(row, field, before=None, receipt=None):
        from app.agent.windows_form_control_reader import read_form_control
        result["phase"] = "read_control" if before is None else "check_control"
        checkpoint()
        try:
            snapshot = read_form_control(coordinator, target, field.label, field.kind,
                expected_runtime_id=None if before is None else before["runtime_id"])
            row.setdefault("reads", []).append(snapshot)
            if not snapshot.get("runtime_id"):
                raise FormFillInterrupted("form_control_runtime_id_unavailable")
            if before is not None:
                for key in ("runtime_id", "window_identity", "window_rect"):
                    if snapshot.get(key) != before.get(key):
                        raise FormFillInterrupted("form_control_" + key + "_changed")
                if receipt is not None and receipt.get("target_identity") != before.get("window_identity"):
                    raise FormFillInterrupted("form_control_window_identity_changed")
            return snapshot
        except Exception as error:
            current_state_unavailable(row, reason_code(error))
            from app.agent.windows_form_control_reader import FormControlReadError
            if isinstance(error, FormControlReadError) and getattr(error, "diagnostics", None):
                # 仅透传读取器白名单结构，不接受其他供应方异常自带的内容。
                row["check"]["diagnostics"] = error.to_reference()["diagnostics"]
                result["observation"]["diagnostics"] = error.to_reference()["diagnostics"]
            raise
        finally:
            checkpoint()

    def reason_code(error):
        return str(error) if isinstance(error, FormFillInterrupted) else getattr(error,
            "reason_code", "form_fill_failed")

    def matched(row, snapshot, *, already=False):
        row["check"] = {"status": "matched", "source": snapshot["source"],
            "runtime_id": snapshot["runtime_id"], "already_satisfied": already}

    def checked(snapshot):
        if snapshot.get("state_available") is not True or type(snapshot.get("checked")) is not bool:
            raise FormFillInterrupted("form_control_state_unavailable")
        return snapshot["checked"]

    def fill_control(row, field):
        before = read(row, field)
        quoted_label = json.dumps(field.label, ensure_ascii=False)
        if field.kind in ("checkbox", "radio"):
            desired = field.checked if field.kind == "checkbox" else True
            if checked(before) is desired:
                matched(row, before, already=True)
                return
            noun = "checkbox" if field.kind == "checkbox" else "radio button"
            receipt = action(row, "set_state", f"Click the {noun} labelled {quoted_label}", field, before)
            after = read(row, field, before, receipt)
            if checked(after) is not desired:
                row["check"] = {"status": "mismatch", "source": after["source"]}
                raise FormFillInterrupted("form_control_state_mismatch")
        else:
            if before.get("value") == field.option:
                matched(row, before, already=True)
                return
            if type(before.get("expanded")) is not bool:
                raise FormFillInterrupted("form_control_expansion_unavailable")
            opened = before
            if before["expanded"] is False:
                receipt = action(row, "open_dropdown", f"Click the dropdown labelled {quoted_label}", field, before)
                opened = read(row, field, before, receipt)
                if opened.get("expanded") is not True:
                    raise FormFillInterrupted("form_control_not_expanded")
            options, match_kind = _option_matches(opened.get("options", []), field.option)
            if len(options) != 1:
                row["available_options"] = [item.get("label") for item in opened.get("options", [])][:64]
                raise FormFillInterrupted("form_option_not_visible" if not options else "form_option_ambiguous")
            resolved_option = options[0]["label"]
            row["option_match"] = {"requested": field.option, "resolved": resolved_option, "method": match_kind}
            quoted_option = json.dumps(resolved_option, ensure_ascii=False)
            receipt = action(row, "select_option",
                f"Click the option {quoted_option} in the open dropdown labelled {quoted_label}",
                field, opened, options[0])
            after = read(row, field, before, receipt)
            selected = [item for item in after.get("options", []) if item.get("label") == resolved_option
                and item.get("selected") is True]
            if after.get("value") != resolved_option and len(selected) != 1:
                row["check"] = {"status": "mismatch", "source": after["source"]}
                raise FormFillInterrupted("form_control_value_mismatch")
        matched(row, after)

    def fill_text(row, field, text):
        nonlocal previous_text
        result["observation"] = {"status": "unavailable", "reason": "action_in_progress"}
        result["phase"] = "text"
        checkpoint()

        def progress(child):
            row["steps"] = child["steps"]
            row["check"] = child["input_check"]
            row["status"] = child["status"]
            row["error"] = child.get("error")
            row["input_sequence"] = child
            result["phase"] = child["phase"]
            frames(child)
            merge_action(child["action_executed"])
            checkpoint()

        def completed(snapshot, kind):
            nonlocal previous_text
            previous_text = (snapshot, kind)

        grouped = spec.text_navigation == "tab_sequence"
        # 显式标签优先，避免名称里的 input/field 被误当成语法而截断。
        goal = (f"Click the input labelled {json.dumps(field.label, ensure_ascii=False)}"
                if isinstance(field, TextField) and field.label else field.field_goal)
        child = run_input_sequence(coordinator, target, {"field_goal": goal,
            "text": text, "clear_existing": True if field.kind == "date" else field.clear_existing,
            "submit_search": False},
            persist=progress, _prefer_current_uia=isinstance(field, TextField) and bool(field.label),
            **({"_tab_from": previous_text, "_expected_label": field.label,
                "_on_field_complete": completed} if grouped else {}))
        progress(child)
        if child["status"] != "completed":
            raise FormFillInterrupted((child.get("error") or {}).get("code", "form_text_interrupted"))

    try:
        for index, field in enumerate(spec.fields):
            row = {"index": index, "kind": field.kind, "status": "running", "steps": [],
                "check": {"status": "not_checked"}, "error": None}
            result["fields"].append(row)
            checkpoint()
            if field.kind == "text":
                fill_text(row, field, field.text)
            elif field.kind == "date":
                year, month, day = field.value.split("-")
                display_text = {"YYYY-MM-DD": f"{year}-{month}-{day}",
                    "DD/MM/YYYY": f"{day}/{month}/{year}",
                    "MM/DD/YYYY": f"{month}/{day}/{year}"}[field.format]
                fill_text(row, field, display_text)
                if row["check"].get("status") != "matched":
                    raise FormFillInterrupted("form_date_readback_unmatched")
                row["check"].update(value=field.value, display_format=field.format,
                    display_text=display_text)
            else:
                fill_control(row, field)
            row["status"] = "completed"
            result["completed_fields"].append(index)
            checkpoint()
        result.update(status="completed", phase="returned",
            next_action="inspect_returned_image_and_judge_task_effect")
    except Exception as error:
        failure = {"code": reason_code(error), "type": type(error).__name__}
        if failure["code"] in {"form_control_state_unavailable", "form_control_expansion_unavailable"}:
            current_state_unavailable(row, failure["code"])
        row.update(status="interrupted", error=row.get("error") or failure)
        result.update(status="interrupted", interrupted_at=row["index"], error=row["error"],
            next_action="inspect_partial_fields_and_current_state_before_a_new_command")
    finally:
        checkpoint()
    return result
