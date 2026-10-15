"""离线构建器验证分组、原图冻结、真实生产 wire 与真值隔离。"""
from copy import deepcopy
import base64
from hashlib import sha256
from io import BytesIO
import json

import httpx
from PIL import Image
import pytest

from scripts.decision_benchmark import load_suite, request_body


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def inputs(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGB", (160, 90), "white").save(source)
    case = {"id": "wrong-field", "category": "input_field", "target": "Address input",
        "point": {"x": 25, "y": 25}, "candidate_bbox": {"x": 10, "y": 10, "w": 50, "h": 40},
        "target_bbox": {"x": 100, "y": 10, "w": 50, "h": 40},
        "expected": "condition_not_met", "reason": "TRUTH_ONLY_WRONG_CONTROL",
        "appearance": "Small white input", "container": "Toolbar"}
    image = {"source_path": str(source), "source_sha256": sha256(source.read_bytes()).hexdigest(),
        "original_size": [160, 90], "session_id": "session-real-source", "capture_id": "capture-1",
        "group_id": "scene-a", "cases": [case]}
    annotation = {"suite_id": "offline-fixture", "annotator": "AI initial / Main AI review", "images": [image]}
    annotation_path, splits_path = tmp_path / "annotations.json", tmp_path / "splits.json"
    save(annotation_path, annotation)
    save(splits_path, {"scene-a": "train"})
    return annotation, annotation_path, splits_path


def build(inputs, output):
    from scripts.build_decision_benchmark import build_suite
    annotation, annotation_path, splits_path = inputs
    save(annotation_path, annotation)
    return build_suite(annotation_path, splits_path, output)


def raw_wire(case):
    return httpx.Request("POST", "https://api.openai.com/v1/decisions", json=request_body(case)).content


def test_original_png_is_copied_unchanged_and_negative_point_stays_in_candidate(inputs, tmp_path):
    suite_path = build(inputs, tmp_path / "out")
    case = load_suite(suite_path)["cases"][0]
    source = tmp_path / "source.png"
    assert (suite_path.parent / case["source"]["path"]).read_bytes() == source.read_bytes()
    assert case["source"]["sha256"] == sha256(source.read_bytes()).hexdigest()
    assert case["expected"] == "condition_not_met"
    assert case["truth"]["reason"] == "TRUTH_ONLY_WRONG_CONTROL"
    stored = (suite_path.parent / case["request"]["path"]).read_text(encoding="utf-8")
    assert "base64" not in stored
    assert case["image"]["path"] in stored


def test_group_mapping_applies_to_every_case_without_random_capture_split(inputs, tmp_path):
    annotation, _, splits = inputs
    another = deepcopy(annotation["images"][0]["cases"][0])
    another.update(id="same-scene-graphic", category="graphic")
    annotation["images"][0]["cases"].append(another)
    save(splits, {"scene-a": "validation", "unused-group": "test"})
    cases = load_suite(build(inputs, tmp_path / "out"))["cases"]
    assert [(case["group_id"], case["split"]) for case in cases] == [("scene-a", "validation")] * 2


def test_same_capture_or_source_cannot_cross_groups_splits(inputs, tmp_path):
    annotation, _, splits = inputs
    other = deepcopy(annotation["images"][0])
    other["group_id"] = "scene-b"
    other["cases"][0]["id"] = "heldout"
    annotation["images"].append(other)
    save(splits, {"scene-a": "train", "scene-b": "test"})
    with pytest.raises(ValueError, match="split_leakage"):
        build(inputs, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_source_hash_mismatch_is_rejected_before_output(inputs, tmp_path):
    inputs[0]["images"][0]["source_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="source_hash_mismatch"):
        build(inputs, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_negative_label_never_excuses_point_outside_candidate_bbox(inputs, tmp_path):
    inputs[0]["images"][0]["cases"][0]["point"] = {"x": 95, "y": 25}
    with pytest.raises(ValueError, match="coordinates_outside"):
        build(inputs, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_truth_label_reason_and_target_bbox_never_change_model_wire(inputs, tmp_path):
    first = load_suite(build(inputs, tmp_path / "first"))["cases"][0]
    case = inputs[0]["images"][0]["cases"][0]
    case.update(expected="condition_met", reason="TRUTH_ONLY_CHANGED",
                target_bbox={"x": 0, "y": 0, "w": 1, "h": 1})
    second = load_suite(build(inputs, tmp_path / "second"))["cases"][0]
    assert raw_wire(first) == raw_wire(second)
    wire = raw_wire(first).decode("utf-8")
    for forbidden in ["TRUTH_ONLY", "target_bbox", "expected", "annotator", "truth"]:
        assert forbidden not in wire


def test_provider_request_bytes_are_reproducible_and_recorded(inputs, tmp_path):
    first_path, second_path = build(inputs, tmp_path / "one"), build(inputs, tmp_path / "two")
    first, second = load_suite(first_path)["cases"][0], load_suite(second_path)["cases"][0]
    assert raw_wire(first) == raw_wire(second)
    assert first_path.read_bytes() == second_path.read_bytes()
    provenance = json.loads((first_path.parent / "build-provenance.json").read_text(encoding="utf-8"))
    record = provenance["cases"][0]
    assert record["wire_sha256"] == sha256(raw_wire(first)).hexdigest()
    assert record["wire_scope"] == "production_provider_request_only_no_action_receipt"
    assert record["truth"]["target_bbox"] == inputs[0]["images"][0]["cases"][0]["target_bbox"]
    assert provenance["truth_review"]["human_reviewed"] is False
    assert provenance["truth_review"]["general_accuracy_guaranteed"] is False
    assert all(len(value) == 64 for value in provenance["production_sha256"].values())


def test_candidates_use_actual_provider_once_with_bound_metadata(inputs, tmp_path, monkeypatch):
    from app.judgment.openai_decisions import OpenAIDecisionsProvider
    original, calls = OpenAIDecisionsProvider.judge, []

    def checked(self, payload):
        metadata = payload["frames"][0]["candidate_annotation"]["metadata"]
        assert metadata["source_sha256"] == inputs[0]["images"][0]["source_sha256"]
        assert metadata["click_point"] == {"x": 25, "y": 25}
        assert "window_identity" not in payload["frames"][0]
        assert "executed_click" not in payload["action"]
        calls.append(deepcopy(payload))
        return original(self, payload)

    monkeypatch.setattr(OpenAIDecisionsProvider, "judge", checked)
    build(inputs, tmp_path / "out")
    assert len(calls) == 1


def test_page_result_uses_production_result_question_and_exact_full_image(inputs, tmp_path):
    from app.judgment.choice_contract import result_choice_question
    case = inputs[0]["images"][0]["cases"][0]
    case.update(category="page_result", point=None, candidate_bbox=None, condition="The MDN page title is visible.")
    for key in ["target_bbox", "appearance", "container"]:
        case.pop(key)
    built = load_suite(build(inputs, tmp_path / "out"))["cases"][0]
    assert built["_body"]["questions"] == [result_choice_question(case["condition"])]
    assert built["image"] == built["source"]


def test_text_value_is_explicit_prompt_protocol_only_without_fake_action_evidence(inputs, tmp_path):
    from app.judgment.choice_contract import text_value_choice_question
    case = inputs[0]["images"][0]["cases"][0]
    case.update(category="text_value", point=None, expected_text="\u4e2d\u6587 value")
    path = build(inputs, tmp_path / "out")
    built = load_suite(path)["cases"][0]
    assert built["_body"]["questions"] == [text_value_choice_question(field_crop=True, expected_text=case["expected_text"])]
    image_url = request_body(built)["input"][0]["content"][1]["image_url"]
    with Image.open(BytesIO(base64.b64decode(image_url.split(",", 1)[1]))) as image:
        assert image.size == (50, 40)
    provenance = json.loads((path.parent / "build-provenance.json").read_text(encoding="utf-8"))
    assert provenance["cases"][0]["wire_scope"] == "production_text_question_and_image_protocol_only_no_runtime_receipt"
    assert "executed_click" not in raw_wire(built).decode("utf-8")


@pytest.mark.parametrize("category", ["graphic", "page_result", "text_value"])
def test_each_protocol_rehydrates_to_its_recorded_actual_body_bytes(inputs, tmp_path, category):
    case = inputs[0]["images"][0]["cases"][0]
    case["category"] = category
    if category == "page_result":
        case.update(condition="The page title is visible.", point=None, candidate_bbox=None)
    elif category == "text_value":
        case.update(point=None, expected_text="value")
    path = build(inputs, tmp_path / "out")
    built = load_suite(path)["cases"][0]
    record = json.loads((path.parent / "build-provenance.json").read_text(encoding="utf-8"))["cases"][0]
    assert sha256(raw_wire(built)).hexdigest() == record["wire_sha256"]


def test_missing_original_capture_id_is_explicitly_derived_not_fabricated(inputs, tmp_path):
    image = inputs[0]["images"][0]
    image.update(capture_id=None, original_size={"width": 160, "height": 90})
    path = build(inputs, tmp_path / "out")
    built = load_suite(path)["cases"][0]
    derived = "benchmark-source-sha256-" + image["source_sha256"]
    assert built["provenance"]["capture_id"] == derived
    record = json.loads((path.parent / "build-provenance.json").read_text(encoding="utf-8"))["cases"][0]
    assert record["original_capture_id"] is None
    assert record["benchmark_capture_id"] == derived
    assert "sha256" in record["capture_id_derivation"]


@pytest.mark.parametrize("fault", ["missing_split", "size_mismatch", "unknown_category", "bool_point", "missing_hint"])
def test_invalid_annotations_fail_before_creating_suite(inputs, tmp_path, fault):
    image = inputs[0]["images"][0]
    if fault == "missing_split":
        save(inputs[2], {})
    elif fault == "size_mismatch":
        image["original_size"][0] += 1
    elif fault == "unknown_category":
        image["cases"][0]["category"] = "unknown"
    elif fault == "bool_point":
        image["cases"][0]["point"]["x"] = True
    else:
        image["cases"][0].pop("appearance")
    with pytest.raises(ValueError):
        build(inputs, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_existing_output_is_not_overwritten(inputs, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    protected = out / "protected.txt"
    protected.write_bytes(b"keep")
    with pytest.raises(ValueError, match="output_exists"):
        build(inputs, out)
    assert protected.read_bytes() == b"keep"
