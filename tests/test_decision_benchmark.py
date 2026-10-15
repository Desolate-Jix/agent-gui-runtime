"""真实截图评测的分组、请求隔离和计分约束。"""
from copy import deepcopy
from hashlib import sha256
import json

from PIL import Image
import pytest

from scripts.decision_benchmark import load_suite, request_body, summarize, task_order


def _save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def suite_path(tmp_path):
    Image.new("RGB", (32, 24), "white").save(tmp_path / "source.png")
    Image.new("RGB", (32, 24), "cyan").save(tmp_path / "marked.png")
    body = {"model": "gpt-6-luna", "input": [{"role": "user", "content": [
        {"type": "input_text", "text": "The cyan marker is an annotation."},
        {"type": "input_image", "image_url": "marked.png", "detail": "high"}]}],
        "questions": [{"type": "choice", "name": "current_step", "instructions": "Original question",
            "choices": [{"value": x, "description": x} for x in
                ("condition_met", "condition_not_met", "evidence_insufficient")]}]}
    _save(tmp_path / "request.json", body)
    digest = lambda name: sha256((tmp_path / name).read_bytes()).hexdigest()
    case = {"id": "field", "group_id": "session-page-a", "split": "train", "category": "input_field",
        "expected": "condition_met", "truth": {"annotator": "Main", "reason": "Point inside boundary"},
        "provenance": {"capture_id": "real-capture-a", "session_id": "session-a", "kind": "real_capture"},
        "source": {"path": "source.png", "sha256": digest("source.png")},
        "image": {"path": "marked.png", "sha256": digest("marked.png")},
        "request": {"path": "request.json", "sha256": digest("request.json")},
        "question_data": {"target": "the address input"}}
    _save(tmp_path / "suite.json", {"schema": "decision_benchmark.v1", "suite_id": "test", "cases": [case]})
    return tmp_path / "suite.json"


def test_manifest_rejects_scene_group_leakage(suite_path):
    d = json.loads(suite_path.read_text(encoding="utf-8"))
    other = deepcopy(d["cases"][0])
    other.update(id="heldout", split="test")
    d["cases"].append(other)
    _save(suite_path, d)
    with pytest.raises(ValueError, match="split_leakage"):
        load_suite(suite_path)


def test_manifest_rejects_same_source_under_different_group(suite_path):
    d = json.loads(suite_path.read_text(encoding="utf-8"))
    other = deepcopy(d["cases"][0])
    other.update(id="heldout", group_id="claimed-different-scene", split="test")
    d["cases"].append(other)
    _save(suite_path, d)
    with pytest.raises(ValueError, match="split_leakage"):
        load_suite(suite_path)


def test_manifest_rejects_changed_image_before_request(suite_path):
    (suite_path.parent / "marked.png").write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash_mismatch"):
        load_suite(suite_path)


def test_manifest_rejects_unreviewed_or_nonreal_truth(suite_path):
    d = json.loads(suite_path.read_text(encoding="utf-8"))
    d["cases"][0]["provenance"]["kind"] = "synthetic_ui"
    _save(suite_path, d)
    with pytest.raises(ValueError, match="real_capture_required"):
        load_suite(suite_path)


def test_prompt_changes_only_question_instructions_and_never_sends_truth(suite_path):
    suite = load_suite(suite_path)
    case = suite["cases"][0]
    baseline = request_body(case)
    variant = request_body(case, {"input_field": "Is the point in {target}?"})
    expected = deepcopy(baseline)
    expected["questions"][0]["instructions"] = 'Is the point in "the address input"?'
    assert variant == expected
    assert "expected" not in variant and "truth" not in variant
    assert baseline["input"][0]["content"][1]["image_url"].startswith("data:image/png;base64,")


def test_run_order_is_reproducible_and_contains_each_trial(suite_path):
    suite = load_suite(suite_path)
    args = (suite, ["baseline", "short"], "train", 3, 42)
    assert task_order(*args) == task_order(*args)
    assert len(task_order(*args)) == 6
    assert len(set(task_order(*args))) == 6


def test_scoring_keeps_unknown_separate_and_never_credits_uncertain_negative():
    rows = [
        {"category": "graphic", "expected": "condition_met", "choice": "condition_met", "status": "completed", "http_elapsed_ms": 100, "usage": {"input_tokens": 10, "output_tokens": 0}},
        {"category": "graphic", "expected": "condition_not_met", "choice": "condition_met", "status": "completed", "http_elapsed_ms": 200, "usage": {"input_tokens": 20, "output_tokens": 0}},
        {"category": "graphic", "expected": "condition_not_met", "choice": "evidence_insufficient", "status": "completed", "http_elapsed_ms": 300, "usage": {"input_tokens": 30, "output_tokens": 0}},
        {"category": "input_field", "expected": "condition_met", "status": "unknown", "http_elapsed_ms": 8000},
        {"category": "input_field", "expected": "evidence_insufficient", "choice": "evidence_insufficient", "status": "completed", "http_elapsed_ms": 400, "usage": {"input_tokens": 40, "output_tokens": 0}},
    ]
    result = summarize(rows)
    assert result["cases"] == 5 and result["exact_correct"] == 2
    assert result["accuracy"] == .4
    assert result["false_accepts"] == 1
    assert result["false_rejects"] == 0
    assert result["errors"] == 1
    assert result["input_tokens"] == 100
    assert result["unknown_usage_requests"] == 1
    assert result["by_category"]["graphic"]["exact_correct"] == 1
    assert result["returned_nonpass_on_positive"] == 0
