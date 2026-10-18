"""仅用合成原图验证导航点微抖等价边界，不执行输入或调用模型。"""
from hashlib import sha1
import re
from types import SimpleNamespace

import pytest

from app.agent.fresh_learning_action_preview import (
    FreshLearningActionPreview,
    validate_fresh_execution_preview,
    validate_navigation_execution_equivalence,
)
from app.agent.navigation_visual_stability import NavigationVisualStabilityAttestation, NavigationVisualStabilityScope
from app.api.vision import _recognition_candidate_from_vista_direct
from app.operation.recognition.schemas import ScoreBreakdown
from app.vision.schemas import ImageSize
from tests.test_navigation_visual_stability import (
    POINT, SIZE, _current, _far_pixels, _fixture, _png, _rehash, _revalidate_preview,
)


def _source_id(goal, point):
    # 复用生产纯构造器验证来源 ID，不以测试内复制公式替代兼容性证据。
    return _recognition_candidate_from_vista_direct(goal=goal, point=point,
        image_size=ImageSize(width=SIZE[0], height=SIZE[1]), bbox_size=64).candidate_id


def _direct(data, point):
    projection = data["observation_evidence"]["recognition"]["result"]
    candidate = projection["candidate_result"]["candidates"][0]
    candidate["element"].setdefault("evidence", {})["vista_direct_identity"] = {
        "source": "vista_direct_point_grounding", "point": dict(point),
        "source_candidate_id": _source_id(data["intent"]["goal"], point),
    }
    projection["narrow_search_result"]["results"][0].update(
        refined_click_point=dict(point), coordinate_source="vista_point_v1_corroborated_by_local_ocr")


def _previews(offset=(1, 0), *, goal="View details", direct=True):
    original, original_png = _fixture()
    data = original.to_dict()
    evidence = data["observation_evidence"]
    projection = evidence["recognition"]["result"]
    data["intent"]["goal"] = evidence["recognition"]["goal"] = goal
    projection["goal"] = projection["candidate_result"]["goal"] = projection["narrow_search_result"]["goal"] = goal
    if direct:
        _direct(data, POINT)
    original = _revalidate_preview(data)
    current_png = _png(_far_pixels())
    current_data = original.to_dict()
    current_data["observation_evidence"] = _current(original, current_png)
    current_data["capture_source"]["source_id"] = "e" * 64
    point = {"x": POINT["x"] + offset[0], "y": POINT["y"] + offset[1]}
    current_data["observation_evidence"]["recognition"]["result"]["narrow_search_result"]["results"][0]["refined_click_point"] = point
    if direct:
        _direct(current_data, point)
    return original, _revalidate_preview(current_data), original_png, current_png


def _proof(original, current, original_png, current_png):
    return NavigationVisualStabilityScope(original, original_png).validate(
        current.to_dict()["observation_evidence"], current_png)


@pytest.mark.parametrize("offset", [(0, 0), (1, 0), (-1, 0), (2, 0), (-2, 0), (0, 2), (0, -2), (1, 1), (-1, -1), (16, 0), (2, 2), (16, 7)])
def test_axis_bounded_independent_safe_direct_points_are_equivalent(offset):
    original, current, original_png, current_png = _previews(offset)
    assert validate_navigation_execution_equivalence(original, current) is None
    proof = _proof(original, current, original_png, current_png)
    assert validate_fresh_execution_preview(original, current, navigation_visual_proof=proof) is None
    assert original.to_dict()["pre_click_decision"]["selected_click_point"] == POINT
    assert current.to_dict()["pre_click_decision"]["selected_click_point"] == {
        "x": POINT["x"] + offset[0], "y": POINT["y"] + offset[1]}


@pytest.mark.parametrize("offset", [(17, 0), (-17, 0), (0, 8), (2, 8), (16, 8), (-16, -8)])
def test_points_beyond_either_adaptive_axis_are_rejected(offset):
    original, current, original_png, current_png = _previews(offset)
    proof = _proof(original, current, original_png, current_png)
    with pytest.raises(ValueError, match="axis bound"):
        validate_navigation_execution_equivalence(original, current)
    with pytest.raises(ValueError, match="axis bound"):
        validate_fresh_execution_preview(original, current, navigation_visual_proof=proof)


def test_semantic_equivalence_cannot_replace_local_png_proof():
    original, current, original_png, current_png = _previews()
    assert validate_navigation_execution_equivalence(original, current) is None
    with pytest.raises(ValueError, match="drifted"):
        validate_fresh_execution_preview(original, current)
    assert validate_fresh_execution_preview(original, current,
        navigation_visual_proof=_proof(original, current, original_png, current_png)) is None


def test_non_direct_point_motion_is_rejected_even_with_a_real_visual_attestation():
    original, current, original_png, current_png = _previews(direct=False)
    proof = _proof(original, current, original_png, current_png)
    with pytest.raises(ValueError, match="independent direct grounding"):
        validate_fresh_execution_preview(original, current, navigation_visual_proof=proof)


@pytest.mark.parametrize("kind", ["label", "role", "candidate_id", "runtime_id", "bbox", "score", "score_breakdown"])
def test_other_valid_preview_evidence_is_not_normalized_by_point_equivalence(kind):
    original, current, _, _ = _previews()
    data = current.to_dict()
    projection = data["observation_evidence"]["recognition"]["result"]
    ranked = projection["candidate_result"]
    candidate = ranked["candidates"][0]
    grounded = projection["narrow_search_result"]
    if kind == "label":
        candidate["label"] = "View details now"
    elif kind == "role":
        candidate["role"] = "link"
    elif kind == "candidate_id":
        candidate["candidate_id"] = "candidate.other"
        ranked["recommended_candidate_id"] = "candidate.other"
        grounded["recommended_candidate_id"] = "candidate.other"
        grounded["results"][0]["candidate_id"] = "candidate.other"
    elif kind == "runtime_id":
        data["uia_snapshot"]["controls"][0]["runtime_id"][-1] += 1
    elif kind == "bbox":
        candidate["refined_bbox"]["x"] += 1
    elif kind == "score":
        candidate["score_breakdown"]["state_score"] = 0.125
    else:
        candidate["score_breakdown"]["text_similarity"] = 0.99
        candidate["score_breakdown"]["state_score"] = 0.0475
    if kind in {"score", "score_breakdown"}:
        breakdown = ScoreBreakdown(**{key: value for key, value in candidate["score_breakdown"].items() if key != "total"})
        candidate["score_breakdown"] = breakdown.to_dict()
        candidate["score"] = breakdown.total()
    changed = _revalidate_preview(data)
    assert FreshLearningActionPreview.from_dict(changed).to_dict() == changed.to_dict()
    with pytest.raises(ValueError, match="drifted"):
        validate_navigation_execution_equivalence(original, changed)


@pytest.mark.parametrize("key,value", [("risk_class", "low_risk_text_input"), ("hard_blocked", True), ("reasons", ["unverified_reason"])])
def test_changed_risk_is_rejected_even_when_preview_digest_is_recomputed(key, value):
    original, current, _, _ = _previews()
    data = current.to_dict()
    data["risk"][key] = value
    with pytest.raises(ValueError, match="gate or risk"):
        validate_navigation_execution_equivalence(original, _rehash(data))


@pytest.mark.parametrize("kind", ["mapping", "duck_type", "unissued", "copied_seal"])
def test_forged_or_dictionary_proof_cannot_enter_execution_comparison(kind):
    original, current, original_png, current_png = _previews()
    proof = _proof(original, current, original_png, current_png)
    if kind == "mapping":
        invalid = proof.to_reference()
    elif kind == "duck_type":
        invalid = SimpleNamespace(validate_binding=lambda *args: None)
    else:
        invalid = object.__new__(NavigationVisualStabilityAttestation)
        if kind == "copied_seal":
            object.__setattr__(invalid, "_sealed", proof._sealed)
            object.__setattr__(invalid, "_reference_json", proof._reference_json)
    with pytest.raises((TypeError, ValueError)):
        validate_fresh_execution_preview(original, current, navigation_visual_proof=invalid)


def test_navigation_and_text_proofs_are_exclusive_and_wrong_capture_binding_is_rejected():
    original, current, original_png, current_png = _previews()
    proof = _proof(original, current, original_png, current_png)
    with pytest.raises(ValueError, match="exclusive"):
        validate_fresh_execution_preview(original, current, text_visual_proof=object(), navigation_visual_proof=proof)
    data = current.to_dict()
    data["observation_evidence"]["recognition"]["result_sha256"] = "a" * 64
    changed = FreshLearningActionPreview.from_dict(_rehash(data))
    with pytest.raises(ValueError, match="evidence binding changed"):
        validate_fresh_execution_preview(original, changed, navigation_visual_proof=proof)


@pytest.mark.parametrize("mutation", [
    lambda direct: direct.update(source_candidate_id="vista_direct_0000000000"),
    lambda direct: direct.update(source_candidate_id=_source_id("View details", POINT)),
    lambda direct: direct.update(source="unverified_model_source"),
    lambda direct: direct["point"].update(x=132),
    lambda direct: direct.update(extra="not-in-contract"),
])
def test_direct_source_candidate_id_and_point_provenance_are_recomputed(mutation):
    original, current, original_png, current_png = _previews()
    data = current.to_dict()
    direct = data["observation_evidence"]["recognition"]["result"]["candidate_result"]["candidates"][0]["element"]["evidence"]["vista_direct_identity"]
    mutation(direct)
    changed = _revalidate_preview(data)
    proof = _proof(original, changed, original_png, current_png)
    with pytest.raises(ValueError, match="direct grounding provenance"):
        validate_navigation_execution_equivalence(original, changed)
    with pytest.raises(ValueError, match="direct grounding provenance"):
        validate_fresh_execution_preview(original, changed, navigation_visual_proof=proof)


def test_more_than_160_character_goal_uses_production_compacted_hash_without_losing_goal():
    goal = ("View details\t for the current result " + "with exact observed identity " * 8).rstrip()
    assert 160 < len(goal) <= 512
    original, current, original_png, current_png = _previews(goal=goal)
    for preview in (original, current):
        data = preview.to_dict()
        assert data["intent"]["goal"] == goal
        direct = data["observation_evidence"]["recognition"]["result"]["candidate_result"]["candidates"][0]["element"]["evidence"]["vista_direct_identity"]
        point = direct["point"]
        compact = re.sub(r"\s+", " ", goal).strip()[:160]
        assert direct["source_candidate_id"] == "vista_direct_" + sha1(
            f"{compact}|{point['x']}|{point['y']}".encode("utf-8")).hexdigest()[:10]
    assert validate_fresh_execution_preview(original, current,
        navigation_visual_proof=_proof(original, current, original_png, current_png)) is None


def test_untruncated_long_goal_digest_is_not_accepted_as_direct_provenance():
    goal = ("View details " + "with exact observed identity " * 8).rstrip()
    original, current, _, _ = _previews(goal=goal)
    data = current.to_dict()
    direct = data["observation_evidence"]["recognition"]["result"]["candidate_result"]["candidates"][0]["element"]["evidence"]["vista_direct_identity"]
    point = direct["point"]
    untruncated = re.sub(r"\s+", " ", goal).strip()
    direct["source_candidate_id"] = "vista_direct_" + sha1(
        f"{untruncated}|{point['x']}|{point['y']}".encode("utf-8")).hexdigest()[:10]
    with pytest.raises(ValueError, match="direct grounding provenance"):
        validate_navigation_execution_equivalence(original, _revalidate_preview(data))
