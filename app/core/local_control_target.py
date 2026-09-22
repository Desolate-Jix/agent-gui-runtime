"""内部只读控件约束：缩小既有识别点击范围，不产生输入或授权。"""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from threading import get_ident
import math


_TARGET_SCOPE = ContextVar("local_control_target", default=None)


class LocalControlTargetError(ValueError):
    def __init__(self, reason_code):
        if (not isinstance(reason_code, str) or not 1 <= len(reason_code) <= 96
                or not reason_code.replace("_", "").isascii()
                or not reason_code.replace("_", "").isalnum()):
            reason_code = "local_control_target_unavailable"
        self.reason_code = reason_code
        super().__init__(reason_code)


def _fail(reason):
    raise LocalControlTargetError("local_control_target_" + reason)


def _box(value):
    if (not isinstance(value, dict) or any(type(value.get(key)) is not int for key in ("x", "y", "w", "h"))
            or value["x"] < 0 or value["y"] < 0 or value["w"] <= 0 or value["h"] <= 0):
        _fail("bbox_unavailable")
    return value


def _point(point, box):
    if (not isinstance(point, dict) or any(type(point.get(key)) is not int for key in ("x", "y"))
            or not box["x"] <= point["x"] < box["x"] + box["w"]
            or not box["y"] <= point["y"] < box["y"] + box["h"]):
        _fail("point_outside")


def _popup_association(value, current, box):
    if value is None:
        return
    identity = current["window_identity"]
    if (not isinstance(value, dict) or value.get("contract_version") != "form_option_native_popup_v1"
            or value.get("association") != "native_owner_and_geometry"
            or value.get("coordinate_space") != "screen_pixels" or value.get("rect_format") != "ltrb"
            or any(type(value.get(key)) is not int or value[key] <= 0
                for key in ("handle", "process_id", "owner_handle", "root_owner_handle"))
            or value["handle"] == identity.get("target_window_handle")
            or value["process_id"] != identity.get("process_id")
            or value["root_owner_handle"] != identity.get("target_window_handle")
            or not isinstance(value.get("class_name"), str) or not value["class_name"]):
        _fail("option_popup_unavailable")
    created = value.get("bound_process_create_time")
    rect = value.get("rect")
    left, top = current["window_rect"][0] + box["x"], current["window_rect"][1] + box["y"]
    if (type(created) not in (int, float) or not math.isfinite(created) or created <= 0
            or created != identity.get("process_create_time")
            or type(rect) is not list or len(rect) != 4 or any(type(item) is not int for item in rect)
            or not (rect[0] <= left < left + box["w"] <= rect[2]
                    and rect[1] <= top < top + box["h"] <= rect[3])):
        _fail("option_popup_unavailable")


class LocalControlTarget:
    def __init__(self, read_current, expected_control, *, expected_option=None):
        if not callable(read_current) or not isinstance(expected_control, dict):
            _fail("request_invalid")
        self._read_current = read_current
        self._expected = deepcopy(expected_control)
        self._option = deepcopy(expected_option)
        self._validate(self._expected)

    def _validate(self, current):
        if not isinstance(current, dict) or current.get("source") != "windows_uia":
            _fail("source_unavailable")
        runtime = current.get("runtime_id")
        if (not isinstance(runtime, list) or not runtime
                or any(type(item) is not int for item in runtime)):
            _fail("runtime_id_unavailable")
        for key in ("window_identity", "window_rect", "runtime_id", "kind", "label", "bbox"):
            if current.get(key) != self._expected.get(key):
                _fail(key + "_changed")
        if (not isinstance(current.get("window_identity"), dict) or not current["window_identity"]
                or not isinstance(current.get("window_rect"), list) or len(current["window_rect"]) != 4
                or any(type(item) is not int for item in current["window_rect"])
                or current["kind"] not in {"dropdown", "checkbox", "radio"}
                or not isinstance(current.get("label"), str) or not current["label"].strip()):
            _fail("identity_unavailable")
        box = _box(current.get("bbox"))
        if (box["x"] + box["w"] > current["window_rect"][2]
                or box["y"] + box["h"] > current["window_rect"][3]):
            _fail("bbox_unavailable")
        if current["kind"] in {"checkbox", "radio"}:
            if current.get("state_available") is not True or type(current.get("checked")) is not bool:
                _fail("state_unavailable")
            if current["checked"] is not self._expected.get("checked"):
                _fail("state_changed")
        else:
            if type(current.get("expanded")) is not bool:
                _fail("expansion_unavailable")
            if current["expanded"] is not self._expected.get("expanded"):
                _fail("expansion_changed")
            if current.get("value") != self._expected.get("value"):
                _fail("state_changed")
        if self._option is not None:
            if current["kind"] != "dropdown" or not isinstance(self._option, dict):
                _fail("request_invalid")
            if current["expanded"] is not True:
                _fail("not_expanded")
            owned = [item for item in current.get("options", [])
                if isinstance(item, dict) and item.get("label") == self._option.get("label")]
            if len(owned) != 1:
                _fail("option_not_visible" if not owned else "option_ambiguous")
            for key in ("runtime_id", "bbox"):
                if owned[0].get(key) != self._option.get(key):
                    _fail("option_" + key + "_changed")
            option_runtime = owned[0].get("runtime_id")
            if (not isinstance(option_runtime, list) or not option_runtime
                    or any(type(item) is not int for item in option_runtime)):
                _fail("option_runtime_id_unavailable")
            box = _box(owned[0].get("bbox"))
            if (box["x"] + box["w"] > current["window_rect"][2]
                    or box["y"] + box["h"] > current["window_rect"][3]):
                _fail("option_bbox_unavailable")
            popup = owned[0].get("native_popup")
            if popup != self._option.get("native_popup"):
                _fail("option_popup_changed")
            _popup_association(popup, current, box)
        return box

    def __call__(self, point):
        try:
            current = self._read_current()
            box = self._validate(current)
            _point(point, box)
            popup = self._option.get("native_popup") if self._option is not None else None
            return {"contract_version": "local_control_target_check_v1", "status": "matched",
                "source": "windows_uia", "runtime_id": deepcopy(current["runtime_id"]),
                "option_runtime_id": deepcopy(self._option["runtime_id"]) if self._option is not None else None,
                "window_identity": deepcopy(current["window_identity"]),
                "window_rect": deepcopy(current["window_rect"]), "bbox": deepcopy(box),
                **({"expanded": current["expanded"]} if current["kind"] == "dropdown" else {}),
                **({"expected_owned_popup_handle": popup["handle"],
                    "native_popup_association": deepcopy(popup)} if popup is not None else {}),
                "point": deepcopy(point), "action_executed": False}
        except LocalControlTargetError:
            raise
        except Exception as error:
            raise LocalControlTargetError(getattr(error, "reason_code", "local_control_target_read_failed")) from None

    def verify_receipt(self, point, coordinate_space):
        # 事后回执校验只作纵深防御，不能替代输入前当前 UIA 约束。
        if coordinate_space != "capture_image_pixels":
            _fail("coordinate_space_unavailable")
        box = self._option["bbox"] if self._option is not None else self._expected["bbox"]
        _point(point, box)


@contextmanager
def local_control_target_scope(target):
    if _TARGET_SCOPE.get() is not None:
        _fail("scope_overlap")
    if target is not None and not isinstance(target, LocalControlTarget):
        _fail("request_invalid")
    scope = {"target": target, "active": True, "owner": get_ident()}
    token = _TARGET_SCOPE.set(scope)
    try:
        yield
    finally:
        # 撤销复制出的 Context，异常和后续单步均不能复用旧约束。
        scope["active"] = False
        _TARGET_SCOPE.reset(token)


def check_local_control_target(point):
    scope = _TARGET_SCOPE.get()
    if scope is None:
        return None
    if not scope["active"]:
        _fail("scope_expired")
    if scope["owner"] != get_ident():
        _fail("wrong_owner")
    return None if scope["target"] is None else scope["target"](point)
