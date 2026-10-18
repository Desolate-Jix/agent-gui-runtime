"""网页首次填写贯穿确切控件引用、人工确认、门控派发与持久回执。"""

from contextlib import contextmanager
from copy import deepcopy
from uuid import uuid4

import pytest

from app.agent.desktop_backend import ExistingWindowsBackendAdapter
from app.agent.fresh_learning_action_contracts import FreshLearningIntent
from app.agent.learned_control_reference import resolve_learned_control
from app.agent.live_controller import LiveControllerDecision
from app.agent.text_parameters import (
    ReviewedTextParameters,
    ReviewedTextSource,
    resolve_text_parameters,
    text_parameter_reference,
)
from tests.test_fresh_action_risk import _control
from tests.test_fresh_dispatch_graph import _Visible
from tests.test_fresh_learning_action_preview import _recognize
from tests.test_fresh_text_dispatch import _Input
from tests.test_formal_fresh_graph_source import _stage
from tests.test_formal_fresh_learning_observation import (
    _NativeReader,
    _OriginReader,
    _UIAProvider,
    _WindowManager,
    _bound,
    _owner,
)
from tests.test_formal_fresh_runtime_session import _runtime
from tests.text_field_fixture_support import SyntheticTextFieldReader


class _WebComboUIA(_UIAProvider):
    def __init__(self, field_id):
        super().__init__()
        self.field_id = field_id

    def snapshot_window(self, bound):
        result = super().snapshot_window(bound)
        wrapper = _control(
            "page-wrapper", "__next", {"x": 0, "y": 0, "w": 160, "h": 100},
            control_type="Group",
        )
        wrapper["ancestor_control_ids"] = []
        field = _control(
            self.field_id, "Search field", {"x": 10, "y": 10, "w": 120, "h": 40},
            control_type="ComboBox",
        )
        field.update(
            patterns=["Value", "Text", "ExpandCollapse"],
            class_name="search-input",
            runtime_id=[42, 12],
            ancestor_control_ids=[wrapper["control_id"]],
        )
        result["controls"] = [wrapper, field]
        result["control_count"] = 2
        return result


def _web_recognize(**kwargs):
    result = _recognize(**kwargs)
    candidate = result["candidate_result"]["candidates"][0]
    # 模拟视觉模型的小框；字段身份必须来自当前唯一 UIA ComboBox 的完整矩形。
    visual_box = {"x": 36, "y": 14, "w": 48, "h": 32}
    candidate["element"]["bbox"] = dict(visual_box)
    candidate["element"]["click_point"] = {"x": 60, "y": 30}
    candidate["refined_bbox"] = dict(visual_box)
    candidate["role"] = candidate["element"]["role"] = "textbox"
    local = result["narrow_search_result"]["results"][0]
    local["crop_bbox"] = dict(visual_box)
    local["matched_text_bbox"] = dict(visual_box)
    local["refined_click_point"] = {"x": 60, "y": 30}
    return result


def _parameters(field_id, *, variable=False):
    return resolve_text_parameters(
        ReviewedTextParameters(
            field_id,
            ReviewedTextSource("variable", "place") if variable else ReviewedTextSource("literal", "OpenStreetMap"),
            True,
            False,
        ),
        {"place": "奥克兰博物馆"} if variable else {},
    )


def _saved_control(host, source, field_id):
    reference = source.reference()
    imported = host.facade.import_interface_content(
        reference["task_id"], reference["batch_id"], "observed-screen",
    )
    region = {
        "region_id": field_id,
        # 历史审核框故意不同；本次执行不得把它当成当前字段矩形。
        "bbox": [1, 1, 20, 10],
        "name": "Private search",
        "kind": "input",
        "meaning": "Enter a private search query",
        "recognition_text": "Search field",
    }
    saved = host.facade.save_interface_content(
        imported["interface_id"], imported["revision"], imported["content_sha256"],
        {"regions": [region]}, "save-web-field",
    )
    selection = {
        "interface_id": saved["interface_id"],
        "version_id": saved["version_id"],
        "region_id": field_id,
    }
    binding = resolve_learned_control(host.fresh_learning, reference, selection)
    latest_region = {**deepcopy(region), "recognition_text": "Different latest field"}
    latest = host.facade.save_interface_content(
        saved["interface_id"], saved["revision"], saved["content_sha256"],
        {"regions": [latest_region]}, "newer-web-field-version",
    )
    assert latest["version_id"] != selection["version_id"]
    return binding, selection, latest


@contextmanager
def _ready_web_fill(root, *, variable=False):
    field_id = "region-user-" + str(uuid4())
    owner = _owner(
        root / "capture",
        manager=_WindowManager(*[_bound() for _ in range(500)]),
        native=_NativeReader(*([100.5] * 500), path=r"c:\program files (x86)\microsoft\edge\application\msedge.exe"),
        origin=_OriginReader(*(["https://fresh.example"] * 500)),
        uia=_WebComboUIA(field_id),
        runner=_web_recognize,
    )
    owner._text_field_reader = SyntheticTextFieldReader()
    packet = owner.observe(target_window_handle=4242, target_process_id=9001)
    host, connection, segment, _packet, _arguments, staged = _stage(root, packet)
    runtime = session = None
    try:
        owner.project_root = host.fresh_learning.archive.project_root
        runtime, _backend, claims, source = _runtime(
            host, connection, segment, staged, observation_owner=owner,
        )
        runtime.set_action_learning_recorder(host.fresh_learning.segments.recorder)
        runtime._window_visibility_checker = _Visible()
        native_input = _Input(owner._text_field_reader)
        runtime._backend = ExistingWindowsBackendAdapter(
            input_controller=native_input,
            window_manager=owner._window_manager,
            post_dispatch_settle_seconds=0,
        )
        binding, selection, latest = _saved_control(host, source, field_id)
        session = runtime.start_session()
        scope = {
            key: source.reference()[key]
            for key in ("connection_id", "task_id", "segment_id")
        }
        host.fresh_learning.segments.attach_runtime(
            **scope, runtime_session_id=session.session_id,
        )
        parameters = _parameters(field_id, variable=variable)
        intent = FreshLearningIntent.from_dict({
            "contract_version": "fresh_learning_action_intent_v1",
            "intent_id": "intent.web.fill",
            "session_id": session.session_id,
            "observation_id": session.current_observation.observation_id,
            "source_sha256": source.reference()["source_sha256"],
            "action_id": "action.web.fill",
            "semantic_action": "fill_field",
            "goal": "Search field",
            "text_parameters_ref": text_parameter_reference(parameters.reviewed),
            "learned_control": binding,
        })
        claim = runtime.request_grounded_confirmation(
            intent.to_dict(), target_process_id=9001, text_input=parameters,
        )
        assert not isinstance(claim, LiveControllerDecision), claim
        confirmation_id = claim.grounded_confirmation.confirmation_id
        approved = runtime.record_grounded_confirmation_decision(
            confirmation_id=confirmation_id, decision="approved",
        )
        assert approved.phase == "grounded_confirmation_approved"
        yield {
            "host": host,
            "owner": owner,
            "runtime": runtime,
            "input": native_input,
            "claims": claims,
            "session": session,
            "scope": scope,
            "confirmation_id": confirmation_id,
            "claim": claim,
            "parameters": parameters,
            "selection": selection,
            "latest": latest,
        }
    finally:
        if runtime is not None and session is not None:
            if session.session_id in runtime._grounded_publications:
                runtime.cancel_grounded_review(session_id=session.session_id)
            elif session.session_id in runtime._sessions:
                runtime.abandon_session(session_id=session.session_id)
        host.close()


def test_web_combo_fill_keeps_exact_version_and_records_one_verified_dispatch(tmp_path):
    with _ready_web_fill(tmp_path) as rig:
        preview = rig["claim"].grounded_confirmation.preview.to_dict()
        assert preview["intent"]["learned_control"]["reference"] == rig["selection"]
        assert preview["intent"]["learned_control"]["reference"]["version_id"] != rig["latest"]["version_id"]
        assert preview["observation_evidence"]["application"] == {
            "kind": "web",
            "canonical_origin": "https://fresh.example",
            "executable_path": r"c:\program files (x86)\microsoft\edge\application\msedge.exe",
            "process_create_time": 100.5,
        }
        field = preview["text_field_expectation_ref"]["before"]["identity"]
        assert field["control_bbox"] == [10, 10, 120, 40]
        assert preview["pre_click_decision"]["selected_click_point"] == {"x": 60, "y": 30}
        assert preview["risk"]["risk_class"] == "low_risk_text_input"

        result = rig["runtime"].consume_grounded_confirmation(
            confirmation_id=rig["confirmation_id"],
        )
        assert not isinstance(result, LiveControllerDecision), result
        assert result.outcome == "ACTION_RECORDED"
        assert result.effect_status == "verified"
        assert len(rig["input"].calls) == 1
        assert rig["input"].calls[0]["field_guard"].expectation.before.identity.control_bbox == (
            10, 10, 120, 40,
        )
        record = rig["claims"].load_terminal_receipt_record(
            session_id=rig["session"].session_id,
            observation_id=result.observation_id,
        )
        assert record.runtime_receipt == result
        assert rig["runtime"].consume_grounded_confirmation(
            confirmation_id=rig["confirmation_id"],
        ) == result
        assert len(rig["input"].calls) == 1


@pytest.mark.parametrize("drift", ["origin", "process", "executable", "window"])
def test_web_combo_fill_identity_drift_after_approval_never_dispatches(tmp_path, drift):
    with _ready_web_fill(tmp_path) as rig:
        owner = rig["owner"]
        if drift == "origin":
            owner._origin_reader = _OriginReader(*(["https://elsewhere.example"] * 20))
        elif drift == "process":
            owner._native_identity_reader = _NativeReader(*([101.0] * 20))
        elif drift == "executable":
            owner._native_identity_reader = _NativeReader(
                *([100.5] * 20), path=r"c:\different\browser.exe",
            )
        else:
            owner._window_manager = _WindowManager(*[_bound(pid=9002) for _ in range(20)])

        result = rig["runtime"].consume_grounded_confirmation(
            confirmation_id=rig["confirmation_id"],
        )

        assert isinstance(result, LiveControllerDecision)
        assert result.reason_code == "grounded_confirmation_stale"
        assert rig["input"].calls == []
