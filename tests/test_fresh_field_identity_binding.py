"""新填写必须把捕获的 UIA 元素身份绑定到当前只读字段。"""

from dataclasses import replace

import pytest

from app.agent.fresh_learning_observation import FreshLearningObservationError
from tests.test_fresh_text_preview import _TextUIA
from tests.test_fresh_web_text_field import web_fixture


class _IdentityUIA(_TextUIA):
    def __init__(self, *states):
        super().__init__()
        self._states = list(states)

    def snapshot_window(self, bound):
        snapshot = super().snapshot_window(bound)
        runtime_id, control_type = self._states.pop(0) if self._states else ((42, 12), "Edit")
        field = snapshot["controls"][0]
        field["runtime_id"] = list(runtime_id) if runtime_id is not None else None
        field["control_type"] = control_type
        field["patterns"] = ["Text"] if control_type == "Document" else ["Value", "Text"]
        return snapshot


class _DuplicateRuntimeUIA(_IdentityUIA):
    def snapshot_window(self, bound):
        snapshot = super().snapshot_window(bound)
        field = snapshot["controls"][0]
        snapshot["controls"].append({
            "provider": "windows_uia",
            "control_id": "unrelated-control",
            "name": "Unrelated",
            "control_type": "Button",
            "automation_id": "unrelated-control",
            "class_name": "Button",
            "bbox": {"x": 140, "y": 70, "w": 10, "h": 10},
            "screen_bbox": {"x": 140, "y": 70, "w": 10, "h": 10},
            "enabled": True,
            "visible": True,
            "patterns": ["Invoke"],
            "runtime_id": list(field["runtime_id"]),
        })
        snapshot["control_count"] = len(snapshot["controls"])
        return snapshot


def test_same_bbox_and_name_with_different_reader_runtime_is_rejected(tmp_path):
    owner, reader, bundle, decision = web_fixture(
        tmp_path, uia=_IdentityUIA(((42, 12), "Edit")),
    )
    original = reader.read_field

    def changed_runtime(**request):
        result = original(**request)
        return replace(result, identity=replace(result.identity, runtime_id=(99, 1)))

    reader.read_field = changed_runtime
    with pytest.raises(FreshLearningObservationError, match="identity|binding"):
        owner.read_text_field(bundle=bundle, target_field_id="fresh.search", decision=decision)


def test_same_runtime_bbox_and_name_with_changed_control_type_is_rejected(tmp_path):
    owner, reader, bundle, decision = web_fixture(
        tmp_path,
        uia=_IdentityUIA(
            ((42, 12), "Edit"),
            ((42, 12), "Document"),
            ((42, 12), "Document"),
        ),
    )
    with pytest.raises(FreshLearningObservationError, match="identity"):
        owner.read_text_field(bundle=bundle, target_field_id="fresh.search", decision=decision)
    assert reader.calls == []


def test_runtime_identity_must_be_unique_across_the_whole_snapshot(tmp_path):
    owner, reader, bundle, decision = web_fixture(
        tmp_path, uia=_DuplicateRuntimeUIA(((42, 12), "Edit")),
    )
    with pytest.raises(FreshLearningObservationError, match="identity"):
        owner.read_text_field(bundle=bundle, target_field_id="fresh.search", decision=decision)
    assert reader.calls == []


def test_uia_runtime_change_during_reader_call_is_rejected_after_read(tmp_path):
    owner, reader, bundle, decision = web_fixture(
        tmp_path,
        uia=_IdentityUIA(
            ((42, 12), "Edit"),
            ((42, 12), "Edit"),
            ((99, 1), "Edit"),
        ),
    )
    with pytest.raises(FreshLearningObservationError, match="identity"):
        owner.read_text_field(bundle=bundle, target_field_id="fresh.search", decision=decision)
    assert len(reader.calls) == 1


def test_new_fill_rejects_capture_without_runtime_identity(tmp_path):
    owner, reader, bundle, decision = web_fixture(
        tmp_path, uia=_IdentityUIA((None, "Edit")),
    )
    with pytest.raises(FreshLearningObservationError, match="identity"):
        owner.read_text_field(bundle=bundle, target_field_id="fresh.search", decision=decision)
    assert reader.calls == []
