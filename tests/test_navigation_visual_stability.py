"""仅用本轮合成 PNG 和完整结构化替身验证导航视觉证明。"""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO

import pytest
from PIL import Image

from app.agent.fresh_learning_action_contracts import FreshLearningIntent, canonical_json_bytes, payload_sha256
from app.agent.fresh_learning_action_preview import FreshLearningActionPreview, _decision_and_risk
from app.agent.learned_control_reference import recognition_target_from_learned_control
from app.agent.navigation_visual_stability import (
    NavigationVisualPixelsChanged,
    NavigationVisualStabilityAttestation,
    NavigationVisualStabilityScope,
    navigation_visual_expectation,
    verify_navigation_visual_stability_reference,
)
from app.operation.recognition.schemas import CandidateRankResult, LocalGroundingResult, ScoreBreakdown
from app.vision.schemas import BBox
from tests.test_fresh_action_risk import _candidate, _control, _local, _uia


SIZE = (360, 260)
BOX = {"x": 80, "y": 60, "w": 100, "h": 30}
POINT = {"x": 130, "y": 75}


def _png(changes=(), *, size=SIZE):
    image = Image.new("RGB", size, "white")
    for point in changes:
        image.putpixel(point, (0, 0, 0))
    stream = BytesIO()
    image.save(stream, "PNG")
    return stream.getvalue()


def _rehash(data):
    evidence = data["observation_evidence"]
    data["capture_source"]["capture_id"] = evidence["capture"]["capture_id"]
    data["capture_source"]["screenshot_sha256"] = evidence["capture"]["screenshot_sha256"]
    data["capture_source"]["content_sha256"] = payload_sha256({
        "evidence_json": canonical_json_bytes(evidence).decode("utf-8"),
        "screenshot_sha256": evidence["capture"]["screenshot_sha256"],
    })
    data["preview_sha256"] = payload_sha256({key: value for key, value in data.items() if key != "preview_sha256"})
    return data


def _fixture(tmp_path=None):
    original_png = _png()
    binding = {
        "contract_version": "learned_control_binding_v1",
        "reference": {"interface_id": "interface-details", "version_id": "interface-version-" + "a" * 64,
                      "region_id": "region-details"},
        "task_id": "task-details", "content_sha256": "a" * 64,
        "region": {"region_id": "region-details", "name": "Details", "kind": "button", "meaning": "Open details",
                   "recognition_text": "View details", "bbox": [80, 60, 100, 30]},
        "application_identity": {"kind": "native", "executable_path": r"c:\example\demo.exe"},
        "source_screenshot_sha256": sha256(original_png).hexdigest(),
    }
    binding["binding_sha256"] = payload_sha256(binding)
    intent = FreshLearningIntent.from_dict({
        "contract_version": "fresh_learning_action_intent_v1", "intent_id": "intent-details",
        "session_id": "session-details", "observation_id": "observation-details", "source_sha256": "d" * 64,
        "action_id": "action-details", "semantic_action": "open_detail", "goal": "View details",
        "learned_control": binding,
    })
    target = recognition_target_from_learned_control(binding, semantic_action="open_detail")
    candidate = _candidate("View details")
    candidate.element.bbox = BBox(**BOX)
    candidate.element.click_point = dict(POINT)
    candidate.refined_bbox = dict(BOX)
    candidate.score_breakdown = ScoreBreakdown(text_similarity=1, policy_score=1, role_score=1,
        confidence_score=1, screen_reading_score=0.4)
    local = _local(candidate)
    local.crop_bbox = dict(BOX)
    local.matched_text_bbox = dict(BOX)
    local.refined_click_point = dict(POINT)
    projection = {
        "contract_version": "recognition_plan_v1", "goal": intent.goal,
        "candidate_result": CandidateRankResult(goal=intent.goal, candidates=[candidate],
            recommended_candidate_id=candidate.candidate_id, summary={"control_target": target}).to_dict(),
        "narrow_search_result": LocalGroundingResult(goal=intent.goal, results=[local],
            recommended_candidate_id=candidate.candidate_id).to_dict(),
    }
    projection["narrow_search_result"]["results"][0].pop("crop_path")
    control = {**_control("details-control", "View details", dict(BOX)), "runtime_id": [42, 7, 9]}
    uia = _uia(control)
    uia["window"]["bbox"] = {"x": 0, "y": 0, "w": SIZE[0], "h": SIZE[1]}
    evidence = {
        "contract_version": "fresh_learning_observation_v1",
        "target": {"window_handle": 4242, "process_id": 9001,
                   "rect": {"x": 0, "y": 0, "width": SIZE[0], "height": SIZE[1]}},
        "application": {**binding["application_identity"], "process_create_time": 33.5},
        "uia": {key: uia[key] for key in ("provider", "provider_version", "status", "control_count")},
        "capture": {"capture_id": "capture-before", "capture_started_ns": 100,
                    "captured_at_ns": 110, "observed_at_ns": 120, "capture_clock_id": "windows-perf-counter-v1",
                    "viewport_size": {"width": SIZE[0], "height": SIZE[1]},
                    "screenshot_sha256": sha256(original_png).hexdigest()},
        "recognition": {"status": "completed", "goal": intent.goal, "result_sha256": payload_sha256(projection),
                        "result_projection_contract": "fresh_read_only_recognition_projection_v1",
                        "result_is_original": False, "result": projection},
        "artifact_is_authorization": False, "execute_binding_enabled": False, "action_executed": False,
    }
    evidence["uia"]["snapshot_sha256"] = payload_sha256(uia)
    decision, risk = _decision_and_risk(evidence, uia, intent, require_control_target=True)
    data = {
        "contract_version": "fresh_learning_action_preview_v2", "session_id": intent.session_id,
        "observation_id": intent.observation_id, "intent": intent.to_dict(), "source_sha256": intent.source_sha256,
        "capture_source": {"contract_version": "fresh_learning_source_ref_v1", "source_id": "c" * 64},
        "observation_evidence": evidence, "uia_snapshot": uia, "pre_click_decision": decision, "risk": risk,
        "artifact_is_authorization": False, "execute_binding_enabled": False, "action_executed": False,
    }
    return FreshLearningActionPreview.from_dict(_rehash(data)), original_png


def _current(preview, png, *, passive=False):
    evidence = preview.to_dict()["observation_evidence"]
    evidence["capture"].update(capture_id="capture-after", capture_started_ns=200, captured_at_ns=210,
                               observed_at_ns=220, screenshot_sha256=sha256(png).hexdigest())
    if passive:
        evidence["recognition"].update(status="not_requested", goal=None, result_sha256=None, result=None)
    return evidence


def _far_pixels(count=68):
    return tuple((260 + index % 10, 180 + index // 10) for index in range(count))


@pytest.mark.parametrize("passive", [False, True])
def test_small_far_animation_preserves_exact_target_and_readonly_reopen(passive):
    preview, png = _fixture()
    before = preview.to_dict()["observation_evidence"]
    scope = NavigationVisualStabilityScope(preview, png)
    current_png = _png(_far_pixels())
    current = _current(preview, current_png, passive=passive)
    proof = scope.validate(current, current_png)
    reference = proof.to_reference()
    assert type(proof) is NavigationVisualStabilityAttestation
    assert reference["protected_bbox"] == [72, 52, 116, 46]
    assert reference["changed_pixels"] == 68 and reference["changed_bbox"] == [260, 180, 10, 7]
    assert reference["recognition_status"] == ("not_requested" if passive else "completed")
    assert scope.expectation_reference == navigation_visual_expectation(preview)
    proof.validate_binding(before, current, scope.expectation_reference)
    assert verify_navigation_visual_stability_reference(reference, before, current, scope.expectation_reference,
        png, current_png) is None


def test_identical_png_still_requires_new_capture():
    preview, png = _fixture()
    scope = NavigationVisualStabilityScope(preview, png)
    assert scope.validate(_current(preview, png), png).to_reference()["changed_pixels"] == 0
    with pytest.raises(ValueError):
        scope.validate(preview.to_dict()["observation_evidence"], png)


@pytest.mark.parametrize("changes", [
    ((80, 60),),  # 控件内部。
    ((72, 52),),  # 八像素保护边缘。
    ((251, 75),),  # 距保护框不足 64px。
    ((260, 180), (275, 190)),  # 同 extent 内仍不允许多个区域。
    tuple((260 + x, 180) for x in range(25)),  # extent 超过 24px。
    tuple((260 + x, 180 + y) for y in range(11) for x in range(12)),  # 132px。
    tuple((x, y) for y in range(150, 230) for x in range(230, 330)),
])
def test_target_border_near_disconnected_and_large_deltas_fail_closed(changes):
    preview, png = _fixture()
    changed = _png(changes)
    with pytest.raises(NavigationVisualPixelsChanged):
        NavigationVisualStabilityScope(preview, png).validate(_current(preview, changed), changed)


def test_scope_does_not_advance_baseline_between_frames():
    preview, png = _fixture()
    scope = NavigationVisualStabilityScope(preview, png)
    first_png = _png(_far_pixels(100))
    scope.validate(_current(preview, first_png), first_png)
    second_png = _png(_far_pixels(129))
    second = _current(preview, second_png)
    second["capture"].update(capture_id="capture-third", capture_started_ns=300, captured_at_ns=310, observed_at_ns=320)
    with pytest.raises(NavigationVisualPixelsChanged):
        scope.validate(second, second_png)


@pytest.mark.parametrize("section,key,value", [
    ("target", "window_handle", 4243), ("target", "process_id", 9002),
    ("application", "process_create_time", 34.5), ("application", "executable_path", r"c:\other\demo.exe"),
    ("uia", "snapshot_sha256", "f" * 64), ("uia", "control_count", 2),
    ("capture", "capture_id", "capture-before"), ("capture", "capture_started_ns", 120),
    ("capture", "capture_clock_id", "other-clock"), ("capture", "screenshot_sha256", "0" * 64),
    ("recognition", "status", "failed"),
])
def test_identity_chronology_recognition_and_forged_hash_are_rejected(section, key, value):
    preview, png = _fixture()
    current = _current(preview, png)
    current[section][key] = value
    with pytest.raises(ValueError):
        NavigationVisualStabilityScope(preview, png).validate(current, png)


@pytest.mark.parametrize("mutation", [
    lambda value: value["candidate_result"]["candidates"][0].update(label="Other"),
    lambda value: value["candidate_result"]["candidates"][0].update(role="link"),
    lambda value: value["candidate_result"]["candidates"][0]["refined_bbox"].update(x=81),
    lambda value: value["candidate_result"]["candidates"][0]["element"]["bbox"].update(x=81),
    lambda value: value["candidate_result"]["candidates"].append(deepcopy(value["candidate_result"]["candidates"][0])),
    lambda value: value["narrow_search_result"]["results"][0].update(refined_click_point={"x": 180, "y": 75}),
])
def test_current_target_label_role_bbox_uniqueness_and_point_must_remain_safe(mutation):
    preview, png = _fixture()
    current = _current(preview, png)
    mutation(current["recognition"]["result"])
    with pytest.raises(ValueError):
        NavigationVisualStabilityScope(preview, png).validate(current, png)


def test_different_safe_point_is_bound_without_deciding_execution_equivalence():
    preview, png = _fixture()
    current = _current(preview, png)
    current["recognition"]["result"]["narrow_search_result"]["results"][0]["refined_click_point"]["x"] += 1
    scope = NavigationVisualStabilityScope(preview, png)
    proof = scope.validate(current, png)
    proof.validate_binding(preview.to_dict()["observation_evidence"], current, scope.expectation_reference)
    changed_point = deepcopy(current)
    changed_point["recognition"]["result"]["narrow_search_result"]["results"][0]["refined_click_point"]["x"] += 1
    with pytest.raises(ValueError):
        proof.validate_binding(preview.to_dict()["observation_evidence"], changed_point, scope.expectation_reference)


@pytest.mark.parametrize("mutation", [
    lambda uia: uia["controls"][0].pop("runtime_id"),
    lambda uia: uia["controls"][0].update(runtime_id=[True]),
    lambda uia: uia["controls"][0].update(runtime_id=[]),
    lambda uia: uia["controls"][0].update(provider="generated"),
    lambda uia: uia["controls"][0].update(enabled=False),
])
def test_missing_or_non_real_uia_identity_cannot_create_scope(mutation):
    preview, png = _fixture()
    data = preview.to_dict()
    mutation(data["uia_snapshot"])
    data["observation_evidence"]["uia"]["snapshot_sha256"] = payload_sha256(data["uia_snapshot"])
    with pytest.raises(ValueError):
        NavigationVisualStabilityScope(FreshLearningActionPreview(canonical_json_bytes(_rehash(data))), png)


def test_original_hash_and_typed_v2_preview_are_required():
    preview, png = _fixture()
    with pytest.raises(TypeError):
        NavigationVisualStabilityScope(preview.to_dict(), png)
    with pytest.raises(ValueError):
        NavigationVisualStabilityScope(preview, _png(_far_pixels()))
    data = preview.to_dict()
    data["contract_version"] = "fresh_learning_action_preview_v1"
    with pytest.raises(ValueError, match="v2"):
        NavigationVisualStabilityScope(FreshLearningActionPreview.from_dict(_rehash(data)), png)


def test_seal_rejects_direct_construction_new_forgery_mutation_and_wrong_binding():
    preview, png = _fixture()
    scope = NavigationVisualStabilityScope(preview, png)
    before = preview.to_dict()["observation_evidence"]
    current = _current(preview, png)
    proof = scope.validate(current, png)
    with pytest.raises(TypeError):
        NavigationVisualStabilityAttestation(**proof.to_reference())
    with pytest.raises(AttributeError):
        proof._reference_json = b"{}"
    forged = object.__new__(NavigationVisualStabilityAttestation)
    object.__setattr__(forged, "_reference_json", proof._reference_json)
    object.__setattr__(forged, "_sealed", proof._sealed)
    with pytest.raises(TypeError):
        forged.to_reference()
    for section in ("before", "after", "expectation"):
        original_copy, current_copy, expectation = deepcopy(before), deepcopy(current), scope.expectation_reference
        if section == "expectation":
            expectation["selected_target"]["runtime_id"][-1] += 1
        else:
            evidence = original_copy if section == "before" else current_copy
            evidence["recognition"]["result_sha256"] = "a" * 64
        with pytest.raises(ValueError):
            proof.validate_binding(original_copy, current_copy, expectation)
    object.__setattr__(proof, "_reference_json", b"{}")
    with pytest.raises(TypeError):
        proof.to_reference()


@pytest.mark.parametrize("key,value", [
    ("changed_pixels", 67), ("policy", "open_detail_unbounded_v2"),
    ("after_evidence_sha256", "0" * 64), ("navigation_expectation_sha256", "0" * 64),
    ("recognition_status", "not_requested"), ("protected_bbox", [80, 60, 100, 30]),
])
def test_persisted_reference_tampering_is_rejected(key, value):
    preview, png = _fixture()
    scope = NavigationVisualStabilityScope(preview, png)
    changed = _png(_far_pixels())
    current = _current(preview, changed)
    reference = scope.validate(current, changed).to_reference()
    reference[key] = value
    with pytest.raises(ValueError):
        verify_navigation_visual_stability_reference(reference, preview.to_dict()["observation_evidence"],
            current, scope.expectation_reference, png, changed)


def test_wrong_persisted_expectation_and_png_are_rejected_without_issuing_proof():
    preview, png = _fixture()
    scope = NavigationVisualStabilityScope(preview, png)
    current_png = _png(_far_pixels())
    current = _current(preview, current_png)
    reference = scope.validate(current, current_png).to_reference()
    altered_expectation = scope.expectation_reference
    altered_expectation["selected_target"]["candidate_bbox"][0] += 1
    with pytest.raises(ValueError):
        verify_navigation_visual_stability_reference(reference, preview.to_dict()["observation_evidence"],
            current, altered_expectation, png, current_png)
    different_png = _png(_far_pixels(67))
    other = _current(preview, different_png)
    with pytest.raises(ValueError):
        verify_navigation_visual_stability_reference(reference, preview.to_dict()["observation_evidence"],
            other, scope.expectation_reference, png, different_png)


def _revalidate_preview(data):
    data["observation_evidence"]["uia"]["snapshot_sha256"] = payload_sha256(data["uia_snapshot"])
    decision, risk = _decision_and_risk(data["observation_evidence"], data["uia_snapshot"],
        FreshLearningIntent.from_dict(data["intent"]), require_control_target=True)
    data.update(pre_click_decision=decision, risk=risk)
    return FreshLearningActionPreview.from_dict(_rehash(data))


def test_pinned_link_uses_the_same_strict_pixel_policy():
    preview, png = _fixture()
    data = preview.to_dict()
    binding = data["intent"]["learned_control"]
    binding["region"]["kind"] = "link"
    binding["binding_sha256"] = payload_sha256({key: value for key, value in binding.items() if key != "binding_sha256"})
    projection = data["observation_evidence"]["recognition"]["result"]
    projection["candidate_result"]["summary"]["control_target"] = recognition_target_from_learned_control(
        binding, semantic_action="open_detail")
    candidate = projection["candidate_result"]["candidates"][0]
    candidate["role"] = candidate["element"]["role"] = "link"
    data["uia_snapshot"]["controls"][0]["control_type"] = "Hyperlink"
    preview = _revalidate_preview(data)
    current_png = _png(_far_pixels())
    assert NavigationVisualStabilityScope(preview, png).validate(
        _current(preview, current_png), current_png).to_reference()["changed_pixels"] == 68


@pytest.mark.parametrize("semantic", ["back", "close_modal"])
def test_other_low_risk_navigation_semantics_are_not_in_scope(semantic):
    preview, png = _fixture()
    data = preview.to_dict()
    data["intent"]["semantic_action"] = semantic
    with pytest.raises(ValueError, match="requires open_detail"):
        NavigationVisualStabilityScope(_revalidate_preview(data), png)


@pytest.mark.parametrize("mutation", [
    lambda data: data["uia_snapshot"]["window"].update(handle=4242.0),
    lambda data: data["uia_snapshot"]["window"]["bbox"].update(x=0.0),
    lambda data: data["uia_snapshot"]["controls"][0]["screen_bbox"].update(x=81),
    lambda data: data["uia_snapshot"]["controls"][0]["screen_bbox"].update(x=80.0),
])
def test_real_uia_identity_and_screen_geometry_reject_coercion_and_drift(mutation):
    preview, png = _fixture()
    data = preview.to_dict()
    mutation(data)
    with pytest.raises(ValueError):
        NavigationVisualStabilityScope(_revalidate_preview(data), png)


def test_passive_frame_cannot_smuggle_model_results_and_scope_cannot_be_rebased():
    preview, png = _fixture()
    scope = NavigationVisualStabilityScope(preview, png)
    malformed = _current(preview, png, passive=True)
    malformed["recognition"]["result"] = {}
    with pytest.raises(ValueError):
        scope.validate(malformed, png)
    with pytest.raises(AttributeError):
        scope._original_png_bytes = b"different"
    reference = scope.expectation_reference
    reference["selected_target"]["click_point"]["x"] += 1
    assert scope.expectation_reference != reference
    object.__setattr__(scope, "_expectation_json", canonical_json_bytes(reference))
    with pytest.raises(TypeError):
        scope.validate(_current(preview, png), png)


def test_non_rgb_or_wrong_size_images_do_not_lose_channels_during_comparison():
    preview, png = _fixture()
    scope = NavigationVisualStabilityScope(preview, png)
    for image in (Image.new("RGBA", SIZE, (255, 255, 255, 0)), Image.new("RGB", (361, 260), "white")):
        stream = BytesIO()
        image.save(stream, "PNG")
        different = stream.getvalue()
        with pytest.raises(ValueError):
            scope.validate(_current(preview, different), different)


@pytest.mark.parametrize("changes", [_far_pixels(128), tuple((260 + x, 180) for x in range(24)), ((252, 75),)])
def test_original_strict_limits_are_preserved_including_exact_boundaries(changes):
    preview, png = _fixture()
    current_png = _png(changes)
    assert NavigationVisualStabilityScope(preview, png).validate(
        _current(preview, current_png), current_png).to_reference()["changed_pixels"] == len(changes)
