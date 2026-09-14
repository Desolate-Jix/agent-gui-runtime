from __future__ import annotations

import math
import time
import hashlib
import json
import ntpath
from dataclasses import dataclass
from typing import Any, Callable, Mapping


def _integer(value: object, name: str, *, positive: bool = False) -> int:
    if type(value) is not int or (positive and value <= 0):
        raise ValueError(f"taskbar activation {name} is invalid")
    return value


def _point(value: object, name: str) -> tuple[int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"taskbar activation {name} is invalid")
    return (_integer(value[0], name), _integer(value[1], name))


@dataclass(frozen=True)
class TaskbarActivationExpectation:
    capture_id: str
    source_sha256: str
    candidate_id: str
    taskbar_handle: int
    destination_handle: int
    window_point: tuple[int, int]
    screen_point: tuple[int, int]
    _frozen_json: str

    @classmethod
    def from_dict(cls, value: dict) -> "TaskbarActivationExpectation":
        if not isinstance(value, dict):
            raise ValueError("taskbar activation evidence is invalid")
        if value.get("schema") != "taskbar_activation_evidence_v1":
            raise ValueError("taskbar activation schema is invalid")
        for key in ("capture_id", "source_sha256", "candidate_id"):
            if not isinstance(value.get(key), str) or not value[key]:
                raise ValueError(f"taskbar activation {key} is invalid")
        taskbar, destination, button = value.get("taskbar"), value.get("destination"), value.get("selected_button")
        if not all(isinstance(x, Mapping) for x in (taskbar, destination, button)):
            raise ValueError("taskbar activation identities are invalid")
        handle = _integer(taskbar.get("handle"), "taskbar_handle", positive=True)
        dest = _integer(destination.get("handle"), "destination_handle", positive=True)
        for identity in (taskbar, destination, value.get("source_foreground")):
            if not isinstance(identity, dict):
                raise ValueError("taskbar activation identity is missing")
            _integer(identity.get("handle"), "identity handle", positive=True)
            _integer(identity.get("pid"), "identity pid", positive=True)
            created = identity.get("create_time")
            if type(created) not in (int, float) or not math.isfinite(created) or created <= 0:
                raise ValueError("taskbar activation process creation time is invalid")
            if not isinstance(identity.get("exe"), str) or not ntpath.isabs(identity["exe"]):
                raise ValueError("taskbar activation executable identity is invalid")
        if not isinstance(destination.get("title"), str) or not destination["title"] or dest == handle:
            raise ValueError("taskbar activation destination title is invalid")
        if value['source_foreground']['handle'] == dest:
            raise ValueError('taskbar activation destination is already foreground; do not toggle it')
        if taskbar.get("class_name") not in {"Shell_TrayWnd", "Shell_SecondaryTrayWnd"}:
            raise ValueError("taskbar activation taskbar class is invalid")
        if not str(taskbar.get("exe", "")).replace("/", chr(92)).casefold().endswith(chr(92) + "explorer.exe"):
            raise ValueError("taskbar activation taskbar executable is invalid")
        if type(value.get("running_window_count")) is not int or type(value.get("matched_button_count")) is not int or value.get("running_window_count") != 1 or value.get("matched_button_count") != 1:
            raise ValueError("taskbar activation target is ambiguous")
        visibility = button.get("point_visibility")
        if not isinstance(visibility, Mapping) or visibility.get("kind") != "taskbar_button" or visibility.get("hit_handle") not in {handle, button.get("toolbar_handle")} or visibility.get("hit_root_handle") != handle or visibility.get("owner_handle") != handle:
            raise ValueError("taskbar activation point is not visible")
        for field in ('hit_handle', 'hit_root_handle', 'owner_handle'):
            _integer(visibility.get(field), field, positive=True)
        _integer(button.get('toolbar_handle'), 'toolbar handle', positive=True)
        if button.get('toolbar_class_name') != 'MSTaskListWClass':
            raise ValueError('taskbar activation toolbar class is invalid')
        ancestors = button.get("ancestor_control_ids")
        if not isinstance(ancestors, list) or not ancestors or button.get("toolbar_control_id") not in ancestors:
            raise ValueError("taskbar activation toolbar ancestry is invalid")
        if button.get("control_type") not in (None, "Button") or button.get("enabled") is not True or button.get("visible") is not True or "Invoke" not in button.get("patterns", []):
            raise ValueError("taskbar activation button is invalid")
        runtime = button.get("runtime_id")
        if not isinstance(runtime, list) or not runtime or any(type(x) is not int for x in runtime):
            raise ValueError("taskbar activation runtime identity is invalid")
        captured = value.get("captured_at_monotonic")
        if not isinstance(captured, (int, float)) or isinstance(captured, bool) or not math.isfinite(captured):
            raise ValueError("taskbar activation capture time is invalid")
        window_point, screen_point = _point(value.get('window_point'), 'window_point'), _point(value.get('screen_point'), 'screen_point')
        def rectangle(raw, keys):
            if not isinstance(raw, dict):
                raise ValueError('taskbar activation rectangle is missing')
            result = tuple(_integer(raw.get(key), key, positive=index >= 2) for index, key in enumerate(keys))
            return result
        bar_rect = rectangle(taskbar.get('screen_rect'), ('left', 'top', 'width', 'height'))
        desktop = rectangle(value.get('desktop_rect'), ('left', 'top', 'width', 'height'))
        bbox = rectangle(button.get('bbox'), ('x', 'y', 'w', 'h'))
        screen_bbox = rectangle(button.get('screen_bbox'), ('x', 'y', 'w', 'h'))
        if (screen_bbox != (bar_rect[0] + bbox[0], bar_rect[1] + bbox[1], bbox[2], bbox[3])
                or screen_point != (bar_rect[0] + window_point[0], bar_rect[1] + window_point[1])
                or not (bbox[0] <= window_point[0] < bbox[0] + bbox[2] and bbox[1] <= window_point[1] < bbox[1] + bbox[3])
                or not (0 <= bbox[0] and 0 <= bbox[1] and bbox[0] + bbox[2] <= bar_rect[2] and bbox[1] + bbox[3] <= bar_rect[3])
                or not (desktop[0] <= screen_point[0] < desktop[0] + desktop[2] and desktop[1] <= screen_point[1] < desktop[1] + desktop[3])):
            raise ValueError('taskbar activation geometry is inconsistent')
        candidate = {k: value[k] for k in ("taskbar", "destination", "selected_button", "window_point", "screen_point")}
        if _digest(candidate) != value["candidate_id"]:
            raise ValueError("taskbar activation candidate hash is invalid")
        unhashed = dict(value); unhashed.pop("source_sha256")
        if _digest(unhashed) != value["source_sha256"]:
            raise ValueError("taskbar activation source hash is invalid")
        return cls(value["capture_id"], value["source_sha256"], value["candidate_id"], handle, dest,
                   _point(value.get("window_point"), "window_point"), _point(value.get("screen_point"), "screen_point"),
                   json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False))

    def to_dict(self) -> dict:
        return json.loads(self._frozen_json)

    @property
    def _evidence(self) -> dict[str, Any]:
        return self.to_dict()


class TaskbarActivationGuard:
    __slots__ = ('expectation', '_reader', '_clock', '_max_age')

    def __init__(self, expectation: TaskbarActivationExpectation, reader: Callable[[], dict], *, clock=time.monotonic, max_age_seconds: float = 15) -> None:
        if not isinstance(max_age_seconds, (int, float)) or isinstance(max_age_seconds, bool) or not math.isfinite(max_age_seconds) or max_age_seconds <= 0:
            raise ValueError("taskbar activation maximum age is invalid")
        if (type(expectation) is not TaskbarActivationExpectation
                or TaskbarActivationExpectation.from_dict(expectation.to_dict()) != expectation
                or not callable(reader) or not callable(clock)):
            raise ValueError('taskbar activation guard binding is invalid')
        for key, item in (('expectation', expectation), ('_reader', reader), ('_clock', clock), ('_max_age', float(max_age_seconds))):
            object.__setattr__(self, key, item)

    def __setattr__(self, name, value):
        raise AttributeError('taskbar activation guard binding is immutable')

    def __delattr__(self, name):
        raise AttributeError('taskbar activation guard binding is immutable')

    def validate_command(self, window_handle: int, click_point: tuple[int, int]) -> None:
        if window_handle != self.expectation.taskbar_handle or tuple(click_point) != self.expectation.window_point:
            raise ValueError("taskbar activation command does not match expectation")

    def verify_current(self) -> bool:
        now = self._clock()
        original = self.expectation._evidence["captured_at_monotonic"]
        if not isinstance(now, (int, float)) or isinstance(now, bool) or not math.isfinite(now) or original > now or now - original > self._max_age:
            raise ValueError("taskbar activation evidence is stale")
        current = TaskbarActivationExpectation.from_dict(self._reader())
        now = self._clock()
        captured = current._evidence["captured_at_monotonic"]
        if captured > now or now - captured > self._max_age or now - original > self._max_age:
            raise ValueError("taskbar activation current evidence is stale")
        expected, observed = self.expectation._evidence, current._evidence
        for key in ("taskbar", "destination", "selected_button", "window_point", "screen_point", "source_foreground", "candidate_id"):
            if observed.get(key) != expected.get(key):
                raise ValueError(f"taskbar activation {key} drifted")
        return True

    def verify_destination(self) -> bool:
        method = getattr(self._reader, "read_destination_foreground", None)
        if not callable(method):
            raise ValueError("taskbar activation reader lacks destination foreground check")
        fact = method()
        destination = self.expectation._evidence["destination"]
        if not isinstance(fact, Mapping) or any(fact.get(k) != destination.get(k) for k in ("handle", "pid", "exe", "create_time")):
            return False
        return fact.get("is_foreground") is True


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
