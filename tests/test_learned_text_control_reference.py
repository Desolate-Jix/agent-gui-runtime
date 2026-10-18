from __future__ import annotations

from types import SimpleNamespace

import pytest


def _binding():
    from app.agent.fresh_learning_action_contracts import payload_sha256
    value = {"contract_version": "learned_control_binding_v1", "reference": {"interface_id": "interface-search", "version_id": "interface-version-" + "a" * 64, "region_id": "region-search"}, "task_id": "task-map", "content_sha256": "a" * 64, "region": {"region_id": "region-search", "name": "Search", "kind": "textbox", "meaning": "search map", "recognition_text": "Search maps", "bbox": [10, 10, 120, 40]}, "application_identity": {"kind": "native", "executable_path": "c:\\map\\demo.exe"}, "source_screenshot_sha256": "b" * 64}
    value["binding_sha256"] = payload_sha256(value)
    return value


def _current(control):
    candidate = SimpleNamespace(text="Search maps", label="Search maps", element=SimpleNamespace(text="Search maps", label="Search maps"))
    local = SimpleNamespace(matched_text="Search maps", refined_click_point={"x": 20, "y": 20})
    uia = {"controls": [control]}
    application = {"kind": "native", "executable_path": "c:\\map\\demo.exe", "process_create_time": 1.0}
    return candidate, local, uia, application


def _edit(**changes):
    value = {"control_id": "map-search", "name": "Search maps", "control_type": "Edit", "bbox": {"x": 10, "y": 10, "w": 120, "h": 40}, "enabled": True, "visible": True, "patterns": ["Value", "Text"]}
    value.update(changes)
    return value


def test_learned_edit_is_reusable_only_for_fill_field():
    from app.agent.learned_control_reference import validate_current_learned_control
    candidate, local, uia, application = _current(_edit())
    assert validate_current_learned_control(_binding(), candidate, local, uia, application, semantic_action="fill_field") is None
    with pytest.raises(ValueError, match="target"):
        validate_current_learned_control(_binding(), candidate, local, uia, application, semantic_action="open_detail")


@pytest.mark.parametrize("control", [_edit(is_password=True), _edit(readonly=True), _edit(name="Other"), _edit(enabled=False)])
def test_learned_fill_rejects_unsafe_or_wrong_edit(control):
    from app.agent.learned_control_reference import validate_current_learned_control
    candidate, local, uia, application = _current(control)
    with pytest.raises(ValueError):
        validate_current_learned_control(_binding(), candidate, local, uia, application, semantic_action="fill_field")


def test_learned_fill_rejects_duplicate_and_wrong_version():
    from app.agent.learned_control_reference import validate_current_learned_control
    candidate, local, uia, application = _current(_edit())
    uia["controls"].append(_edit(control_id="map-search-2"))
    with pytest.raises(ValueError):
        validate_current_learned_control(_binding(), candidate, local, uia, application, semantic_action="fill_field")
    binding = _binding(); binding["reference"]["version_id"] = "interface-version-" + "c" * 64
    with pytest.raises(ValueError):
        validate_current_learned_control(binding, candidate, local, _current(_edit())[2], application, semantic_action="fill_field")


@pytest.mark.parametrize('source', ['vista_point_v1_corroborated_by_local_ocr', 'local_ocr_text_center'])
def test_visible_placeholder_uses_current_ocr_box_inside_unique_editable_field(source):
    from app.agent.learned_control_reference import validate_current_learned_control
    candidate, local, uia, application = _current(_edit(name='Accessible search label', control_type='ComboBox'))
    local.status = 'grounded'
    local.coordinate_source = source
    local.crop_bbox = {'x': 10, 'y': 10, 'w': 120, 'h': 40}
    local.matched_text_bbox = ({'x': 15, 'y': 15, 'w': 60, 'h': 20} if source.startswith('vista')
                               else {'x': 5, 'y': 5, 'width': 60, 'height': 20})
    assert validate_current_learned_control(_binding(), candidate, local, uia, application,
                                          semantic_action='fill_field') is None
    with pytest.raises(ValueError):
        validate_current_learned_control(_binding(), candidate, local, uia, application, semantic_action='open_detail')


@pytest.mark.parametrize('mutation', ['outside', 'partial', 'unknown_space', 'fallback', 'no_box',
                                    'duplicate', 'wrong_text', 'bool', 'negative', 'crop_outside'])
def test_placeholder_association_rejects_unproven_or_ambiguous_geometry(mutation):
    from app.agent.learned_control_reference import validate_current_learned_control
    candidate, local, uia, application = _current(_edit(name='Accessible search label'))
    local.status = 'grounded'
    local.coordinate_source = 'vista_point_v1_corroborated_by_local_ocr'
    local.crop_bbox = {'x': 10, 'y': 10, 'w': 120, 'h': 40}
    local.matched_text_bbox = {'x': 15, 'y': 15, 'w': 60, 'h': 20}
    if mutation == 'outside': local.matched_text_bbox['x'] = 150
    elif mutation == 'partial': local.matched_text_bbox['x'] = 0
    elif mutation == 'unknown_space': local.coordinate_source = 'unverified'
    elif mutation == 'fallback': local.status = 'fallback'
    elif mutation == 'no_box': local.matched_text_bbox = None
    elif mutation == 'duplicate': uia['controls'].append(_edit(control_id='duplicate'))
    elif mutation == 'wrong_text': local.matched_text = 'Other value'
    elif mutation == 'bool': local.matched_text_bbox['w'] = True
    elif mutation == 'negative': local.matched_text_bbox['w'] = -1
    elif mutation == 'crop_outside': local.crop_bbox['x'] = 200
    with pytest.raises(ValueError):
        validate_current_learned_control(_binding(), candidate, local, uia, application, semantic_action='fill_field')


def test_native_fill_preview_uses_resolved_learned_edit_binding(tmp_path):
    import time
    from uuid import uuid4
    from app.agent.fresh_learning_action_contracts import FreshLearningIntent
    from app.agent.fresh_learning_action_preview import build_fresh_learning_action_preview
    from app.agent.learned_control_reference import resolve_learned_control
    from app.agent.text_field_evidence import TextFieldIdentity, TextFieldSnapshot, prepare_text_field_expectation
    from tests.test_fresh_text_preview import _native_owner, _parameters, _intent_payload
    from tests.test_formal_fresh_graph_source import _stage
    from tests.test_formal_fresh_runtime_session import _runtime

    owner = _native_owner(tmp_path / "capture")
    packet = owner.observe(target_window_handle=4242, target_process_id=9001)
    host, connection, segment, _packet, _args, staged = _stage(tmp_path, packet)
    owner.project_root = host.fresh_learning.archive.project_root
    runtime, backend, _claims, source = _runtime(host, connection, segment, staged, observation_owner=owner)
    session = runtime.start_session_preparation(preparation_id="learned.native.fill")
    try:
        first = host.facade.import_interface_content(source.reference()["task_id"], source.reference()["batch_id"], "observed-screen")
        region = {"region_id": "region-user-" + str(uuid4()), "bbox": [0, 0, 1, 1], "name": "Search field", "kind": "input", "meaning": "map search", "recognition_text": "Search field"}
        saved = host.facade.save_interface_content(first["interface_id"], first["revision"], first["content_sha256"], {"regions": [region]}, "native-search-region")
        selection = {"interface_id": saved["interface_id"], "version_id": saved["version_id"], "region_id": region["region_id"]}
        binding = resolve_learned_control(host.fresh_learning, source.reference(), selection)
        params = _parameters()
        intent = FreshLearningIntent.from_dict({**_intent_payload(params), "session_id": session.session_id, "observation_id": session.current_observation.observation_id, "source_sha256": source.reference()["source_sha256"], "learned_control": binding})
        bundle = owner.observe_for_action(target_window_handle=4242, target_process_id=9001, goal=intent.goal)
        evidence = bundle.packet.evidence()
        identity = TextFieldIdentity("fresh.search", 4242, 9001, 100.5, (42, 12), (10, 20, 160, 100), (10, 10, 120, 40))
        field = TextFieldSnapshot(identity, evidence["capture"]["capture_id"], "learned-read", time.perf_counter_ns(), "uia_value", "old", (0, 0))
        expectation = prepare_text_field_expectation(field, params)
        reference = source.reference(); scope = {key: reference[key] for key in ("connection_id", "task_id", "segment_id")}
        capture_source = host.fresh_learning.archive.record(bundle.packet, **scope)
        preview = build_fresh_learning_action_preview(bundle=bundle, capture_source=capture_source, observation=session.current_observation.to_dict(), intent=intent, source_reference=reference, text_field_expectation=expectation)
        assert preview.to_dict()["risk"]["risk_class"] == "low_risk_text_input"
        assert preview.to_dict()["intent"]["learned_control"] == binding
        assert backend.commands == [] and backend.attempt_count == 0
        wrong = intent.to_dict(); wrong["learned_control"]["region"]["recognition_text"] = "Wrong field"
        from app.agent.fresh_learning_action_contracts import payload_sha256
        wrong["learned_control"]["binding_sha256"] = payload_sha256({key: value for key, value in wrong["learned_control"].items() if key != "binding_sha256"})
        with pytest.raises(ValueError, match="recognition"):
            build_fresh_learning_action_preview(bundle=bundle, capture_source=capture_source, observation=session.current_observation.to_dict(), intent=FreshLearningIntent.from_dict(wrong), source_reference=reference, text_field_expectation=expectation)
    finally:
        runtime.abandon_session(session_id=session.session_id)
        host.close()
