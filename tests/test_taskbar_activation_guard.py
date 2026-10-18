import hashlib
import json

import pytest

from app.agent.taskbar_activation_guard import TaskbarActivationExpectation, TaskbarActivationGuard


def evidence(*, captured=100.0, foreground=88):
    raw = {
        "schema": "taskbar_activation_evidence_v1", "captured_at_monotonic": captured,
        "capture_id": "cap-1", "image_path": "x.png", "image_sha256": "a" * 64,
        "desktop_rect": {"left": -10, "top": -20, "width": 200, "height": 101},
        "taskbar": {"handle": 11, "class_name": "Shell_TrayWnd", "pid": 1, "exe": r"C:\Windows\explorer.exe", "create_time": 1.0, "screen_rect": {"left": -10, "top": 60, "width": 200, "height": 40}},
        "destination": {"handle": 77, "pid": 2, "exe": r"C:\Program Files\Demo\demo.exe", "create_time": 2.0, "title": "Demo"},
        "source_foreground": {"handle": foreground, "pid": 3, "exe": r"C:\x\source.exe", "create_time": 3.0},
        "selected_button": {"control_id": "uia_6_demo", "runtime_id": [42, -1, 7], "name": "Demo - 1 running window", "automation_id": "Demo", "control_type": "Button", "bbox": {"x": 20, "y": 0, "w": 30, "h": 40}, "screen_bbox": {"x": 10, "y": 60, "w": 30, "h": 40}, "enabled": True, "visible": True, "patterns": ["Invoke"], "ancestor_control_ids": ["toolbar", "taskbar"], "toolbar_control_id": "toolbar", "toolbar_runtime_id": [42, 5], "toolbar_handle": 12, "toolbar_class_name": "MSTaskListWClass", "point_visibility": {"kind": "taskbar_button", "hit_handle": 11, "hit_root_handle": 11, "owner_handle": 11}},
        "running_window_count": 1, "matched_button_count": 1, "window_point": [35, 20], "screen_point": [25, 80],
    }
    stable = {"taskbar": raw["taskbar"], "destination": raw["destination"], "selected_button": raw["selected_button"], "window_point": raw["window_point"], "screen_point": raw["screen_point"]}
    raw["candidate_id"] = hashlib.sha256(json.dumps(stable, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    raw["source_sha256"] = hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return raw


def rehash(raw):
    raw["source_sha256"] = hashlib.sha256(json.dumps({k: v for k, v in raw.items() if k != "source_sha256"}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def test_guard_accepts_current_equivalent_new_capture_and_destination():
    first = evidence()
    second = evidence(captured=101.0)
    second["capture_id"] = "cap-2"; second["image_sha256"] = "b" * 64
    rehash(second)
    expectation = TaskbarActivationExpectation.from_dict(first)
    class Reader:
        def __call__(self):
            return second
        def read_destination_foreground(self):
            return {**second["destination"], "is_foreground": True}
    guard = TaskbarActivationGuard(expectation, Reader(), clock=lambda: 102.0)
    assert guard.expectation.source_sha256 == first["source_sha256"]
    guard.validate_command(11, (35, 20))
    assert guard.verify_current() is True
    assert guard.verify_destination() is True


@pytest.mark.parametrize("mutate", [
    lambda e: e["selected_button"].update({"ancestor_control_ids": []}),
    lambda e: e["selected_button"]["screen_bbox"].update({"x": 99}),
    lambda e: e.update({"window_point": [51, 20]}),
])
def test_guard_rejects_drift(mutate):
    first = evidence(); current = evidence(); mutate(current)
    guard = TaskbarActivationGuard(TaskbarActivationExpectation.from_dict(first), lambda: current, clock=lambda: 101.0)
    with pytest.raises(ValueError):
        guard.verify_current()


def test_guard_rejects_stale_bool_and_wrong_command():
    old = evidence(captured=1.0)
    with pytest.raises(ValueError):
        TaskbarActivationExpectation.from_dict({**old, "taskbar": {**old["taskbar"], "handle": True}})
    guard = TaskbarActivationGuard(TaskbarActivationExpectation.from_dict(old), lambda: old, clock=lambda: 17.0, max_age_seconds=15)
    with pytest.raises(ValueError):
        guard.verify_current()
    with pytest.raises(ValueError):
        guard.validate_command(77, (35, 20))


def test_hash_and_snapshot_are_tamper_proof():
    raw = evidence()
    expectation = TaskbarActivationExpectation.from_dict(raw)
    copied = expectation.to_dict(); copied["taskbar"]["handle"] = 99
    assert expectation.taskbar_handle == 11
    with pytest.raises(ValueError):
        TaskbarActivationExpectation.from_dict(copied)


def test_original_ttl_replay_is_rejected_even_when_reader_is_fresh():
    old = evidence(captured=1.0); fresh = evidence(captured=100.0)
    guard = TaskbarActivationGuard(TaskbarActivationExpectation.from_dict(old), lambda: fresh, clock=lambda: 100.0)
    with pytest.raises(ValueError, match="stale"):
        guard.verify_current()


def rehash_all(raw):
    from app.agent.taskbar_activation_guard import _digest
    raw['candidate_id'] = _digest({k: raw[k] for k in ('taskbar', 'destination', 'selected_button', 'window_point', 'screen_point')})
    raw['source_sha256'] = _digest({k: v for k, v in raw.items() if k != 'source_sha256'})


@pytest.mark.parametrize('mutate', [
    lambda e: e.update(running_window_count=2),
    lambda e: e.update(running_window_count=True),
    lambda e: e.update(screen_point=[999, 80]),
    lambda e: e.update(window_point=[199, 20]),
    lambda e: e['selected_button']['point_visibility'].update(hit_root_handle=99),
    lambda e: e['selected_button']['screen_bbox'].update(x=99),
    lambda e: e['destination'].update(pid=True),
    lambda e: e['source_foreground'].update(handle=e['destination']['handle']),
])
def test_strict_evidence_rejects_invalid_facts_even_with_valid_hashes(mutate):
    raw = evidence()
    mutate(raw)
    rehash_all(raw)
    with pytest.raises(ValueError):
        TaskbarActivationExpectation.from_dict(raw)


def test_verified_toolbar_child_hit_is_valid_and_guard_is_immutable():
    raw = evidence()
    raw['selected_button']['point_visibility']['hit_handle'] = raw['selected_button']['toolbar_handle']
    rehash_all(raw)
    guard = TaskbarActivationGuard(TaskbarActivationExpectation.from_dict(raw), lambda: raw, clock=lambda: 101)
    assert guard.verify_current()
    with pytest.raises(AttributeError):
        guard.expectation = TaskbarActivationExpectation.from_dict(evidence())


def test_capture_during_reader_is_not_mistaken_for_future_time():
    clock = iter([101, 103])
    guard = TaskbarActivationGuard(TaskbarActivationExpectation.from_dict(evidence()),
        lambda: evidence(captured=102), clock=lambda: next(clock))
    assert guard.verify_current()
