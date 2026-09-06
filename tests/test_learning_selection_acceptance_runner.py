from __future__ import annotations
import importlib.util
import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("acceptance_runner", ROOT / "scripts/run_learning_selection_acceptance.py")
runner = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(runner)


def _catalog(tmp_path: Path) -> Path:
    rows=[]; scores=[]
    for index in range(2):
        row={"suite":"fixed25","case_id":f"case-{index}","target_id":f"target-{index}","target_text":"target","image_path":"unused.png","image_sha256":"a"*64,"image_size":[10,10],"source_manifest_refs":[]}
        rows.append(row); scores.append({"suite":row["suite"],"case_id":row["case_id"],"target_id":row["target_id"],"ground_truth":{"acceptable_regions":[[0,0,10,10]]},"baseline_outcome":"correct","human_correction_applied":False})
    path=tmp_path/"catalog.json";path.write_text(json.dumps({"contract_version":"learning_selection_acceptance_catalog_v1","inference_rows":rows,"scoring_rows":scores}),encoding="utf-8");return path


def _fake_actual(**kwargs):
    out=kwargs["out_dir"];out.mkdir(parents=True)
    mode=kwargs["refinement_mode"]
    refinement={"status":"skipped","provider_result":None}
    canonical=[5,5]
    if mode=="conditional": refinement={"status":"review_required","provider_result":None};canonical=None
    if mode=="always": refinement={"status":"validated","provider_result":{"canonical_capture_pixel_point":[6,6]}};canonical=[6,6]
    response={"selection":{"selection_status":"selected","model_proposal":{"canonical_capture_pixel_point":[5,5],"provider_id":"gui_actor"}},"refinement":refinement,"review_projection":{"execution_origin":"actual_model","artifact_is_authorization":False,"execute_binding_enabled":False}}
    (out/"selection-result.json").write_text(json.dumps(response),encoding="utf-8")
    (out/"result.json").write_text("{}",encoding="utf-8")
    return {"outcome":"completed","trial_path":"fixture-trial.json","original_capture_pixel_point":[5,5],"canonical_capture_pixel_point":canonical}


def test_limit_is_partial_and_preserves_every_policy_outcome(tmp_path, monkeypatch):
    monkeypatch.setattr(runner,"ROOT",tmp_path)
    monkeypatch.setattr(runner,"_source_identity",lambda: {"fixture": "a" * 64})
    monkeypatch.setattr(runner,"_verified_response",lambda *args: None)
    monkeypatch.setattr(runner,"_cleanup_verified",lambda *args: True)
    catalog=_catalog(tmp_path); monkeypatch.setattr(runner,"_catalog",lambda _:json.loads(catalog.read_text(encoding="utf-8"))); monkeypatch.setattr(runner,"_tree_bytes",lambda _:0)
    monkeypatch.setattr(runner,"_configuration",lambda _: object())
    monkeypatch.setattr(runner,"_static",lambda row,run_id:(tmp_path/"image.png",{"bundle_ref":{"id":"bundle"}}))
    monkeypatch.setattr(runner,"run_learning_selection_actual_no_action",_fake_actual)
    monkeypatch.setattr(runner.subprocess,"check_output",lambda *args,**kwargs:"GPU-test, 1024, 256, 768\n")
    report=runner.run_acceptance(catalog_path=catalog,out_dir=tmp_path/"out",limit=1,assets_root=tmp_path,artifact_root=tmp_path)
    assert report["partial"] is True
    assert report["full_acceptance_pass"] is False
    assert report["completed_denominator"] == 3
    assert report["per_policy"]["never"] == {"targets":1,"correct":1,"wrong":0,"abstained":0}
    assert report["per_policy"]["conditional"] == {"targets":1,"correct":0,"wrong":0,"abstained":1}
    assert len(report["original_correct_regressions"]) == 1
    assert report["runtime"]["never"]["startup_mode"] == "cold_per_case"
    assert report["runtime"]["never"]["peak_model_vram_bytes"] == "unmeasured"


def test_resume_requires_completed_receipt_and_model_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(runner,"ROOT",tmp_path); monkeypatch.setattr(runner,"_tree_bytes",lambda _:0)
    monkeypatch.setattr(runner,"_source_identity",lambda: {"fixture": "a" * 64})
    monkeypatch.setattr(runner,"_verified_response",lambda *args: None)
    monkeypatch.setattr(runner,"_cleanup_verified",lambda *args: True)
    monkeypatch.setattr(runner,"_configuration",lambda _: object())
    monkeypatch.setattr(runner,"_static",lambda row,run_id:(tmp_path/"image.png",{"bundle_ref":{"id":"bundle"}}))
    calls=[]
    def actual(**kwargs): calls.append(kwargs["refinement_mode"]);return _fake_actual(**kwargs)
    monkeypatch.setattr(runner,"run_learning_selection_actual_no_action",actual)
    monkeypatch.setattr(runner,"load_learning_draft_review",lambda *args,**kwargs:{"hybrid_review_projection":{"execution_origin":"actual_model"}})
    monkeypatch.setattr(runner.subprocess,"check_output",lambda *args,**kwargs:"GPU-test, 1024, 256, 768\n")
    catalog=_catalog(tmp_path); monkeypatch.setattr(runner,"_catalog",lambda _:json.loads(catalog.read_text(encoding="utf-8")));out=tmp_path/"out"
    runner.run_acceptance(catalog_path=catalog,out_dir=out,limit=1,assets_root=tmp_path,artifact_root=tmp_path)
    receipt=next((out/"cases").glob("*/acceptance-receipt.json")); value=json.loads(receipt.read_text(encoding="utf-8")); value["score"]["outcome"]="wrong"; receipt.write_text(json.dumps(value),encoding="utf-8")
    report=runner.run_acceptance(catalog_path=catalog,out_dir=out,limit=1,assets_root=tmp_path,artifact_root=tmp_path)
    assert calls == ["never","conditional","always"]
    assert report["per_policy"]["never"]["correct"] == 1
    actual_path = receipt.parent / "runner-result.json"
    value = json.loads(actual_path.read_text(encoding="utf-8"))
    value["canonical_capture_pixel_point"] = [9, 9]
    actual_path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="unverifiable"):
        runner.run_acceptance(catalog_path=catalog,out_dir=out,limit=1,assets_root=tmp_path,artifact_root=tmp_path)
    assert calls == ["never", "conditional", "always"]


def test_invalid_refinement_and_manual_results_are_not_scored_as_correct():
    gold={"ground_truth":{"acceptable_regions":[[0,0,10,10]]}}
    result={"outcome":"completed","original_capture_pixel_point":[5,5],"canonical_capture_pixel_point":None}
    response={"selection":{"selection_status":"selected","model_proposal":{"canonical_capture_pixel_point":[5,5]}},"refinement":{"status":"review_required","provider_result":None},"review_projection":{"execution_origin":"actual_model","artifact_is_authorization":False,"execute_binding_enabled":False}}
    assert runner._actual_score(result,response,gold)["outcome"] == "abstained"
    assert runner._score([0,5],gold) == "wrong"


def test_device_sampler_marks_unavailable_without_fabricating_model_peak(monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError("nvidia-smi unavailable")
    monkeypatch.setattr(runner.subprocess,"check_output",unavailable)
    sampler=runner._NvidiaSampler(); sampler.start()
    observed=sampler.stop()
    assert observed["measurement"] == "unmeasured"
    assert observed["peak_device_used_mib"] is None


def test_fixed_manifest_hash_matches_written_utf8_bytes_on_windows(tmp_path, monkeypatch):
    image = tmp_path / "fixture.png"
    image.write_bytes(b"offline image bytes")
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    def seal(**kwargs):
        asset = kwargs["static_asset"]
        manifest = tmp_path / asset["source_manifest_ref"]["relative_path"]
        assert sha256(manifest.read_bytes()).hexdigest() == asset["source_manifest_ref"]["sha256"]
        assert asset["dataset"] == "portfolio_hybrid_v1_1"
        return {"bundle_ref": {}}
    monkeypatch.setattr(runner, "seal_static_capture_bundle", seal)
    runner._static({"suite": "fixed25", "case_id": "case-001", "image_path": str(image),
        "image_sha256": sha256(image.read_bytes()).hexdigest(), "image_size": [10, 10]}, "test-manifest")


def test_verified_scoring_rejects_changed_points_even_when_top_result_agrees(tmp_path, monkeypatch):
    from tests.test_learning_selection_actual_flow import _fixture, _run
    _, payload, _ = _fixture(tmp_path, monkeypatch)
    result = _run(tmp_path, payload, refinement_mode="never")
    response = json.loads((tmp_path / "actual-run/selection-result.json").read_text(encoding="utf-8"))
    row = {"target_text": payload["target_text"], "image_sha256": payload["gui_actor_selection_input"]["image_sha256"]}
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    runner._verified_response(result, response, row, "never")
    response["selection"]["model_proposal"]["canonical_capture_pixel_point"] = [1, 1]
    result["original_capture_pixel_point"] = result["canonical_capture_pixel_point"] = [1, 1]
    with pytest.raises(ValueError, match="sealed"):
        runner._verified_response(result, response, row, "never")


def test_scoring_ignores_human_point_and_keeps_normal_abstention_separate():
    gold = {"ground_truth": {"acceptable_regions": [[0, 0, 10, 10]]}}
    response = {"selection": {"selection_status": "unbound", "model_proposal": {"canonical_capture_pixel_point": None}},
        "refinement": {"status": "not_requested"}, "review_projection": {"execution_origin": "actual_model", "artifact_is_authorization": False, "execute_binding_enabled": False},
        "human_corrected_point": [5, 5]}
    score = runner._actual_score({"outcome": "completed", "human_corrected_point": [5, 5]}, response, gold)
    assert score == {"outcome": "abstained", "point": None, "reason": "selection_unbound"}
    assert runner._point([float("nan"), 2]) is None


def test_catalog_duplicate_keys_cannot_become_full_acceptance(tmp_path, monkeypatch):
    value = json.loads(_catalog(tmp_path).read_text(encoding="utf-8"))
    value["inference_rows"] = [deepcopy(value["inference_rows"][0]) for _ in range(35)]
    value["scoring_rows"] = [deepcopy(value["scoring_rows"][0]) for _ in range(35)]
    path = tmp_path / "duplicate.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setattr(runner, "FROZEN_CATALOG_SHA256", sha256(path.read_bytes()).hexdigest())
    with pytest.raises(ValueError, match="joined35"):
        runner._catalog(path)


def test_missing_static_input_preserves_all_policy_denominators(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    catalog = _catalog(tmp_path)
    monkeypatch.setattr(runner, "_catalog", lambda _: json.loads(catalog.read_text(encoding="utf-8")))
    monkeypatch.setattr(runner, "_source_identity", lambda: {"fixture": "a" * 64})
    monkeypatch.setattr(runner, "_tree_bytes", lambda _: 0)
    monkeypatch.setattr(runner, "_configuration", lambda _: object())
    def missing(*args):
        raise FileNotFoundError("pinned input unavailable")
    monkeypatch.setattr(runner, "_static", missing)
    monkeypatch.setattr(runner, "run_learning_selection_actual_no_action", lambda **kwargs: pytest.fail("model must not run"))
    report = runner.run_acceptance(catalog_path=catalog, out_dir=tmp_path / "out", limit=None, assets_root=tmp_path, artifact_root=tmp_path)
    assert report["completed_denominator"] == 6
    assert all(report["per_policy"][mode]["abstained"] == 2 for mode in runner.POLICIES)
    assert report["full_acceptance_pass"] is False


def _fake_batch(tmp_path, monkeypatch, value, *, cleanup=True):
    path = tmp_path / "batch.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "_catalog", lambda _: value)
    monkeypatch.setattr(runner, "_source_identity", lambda: {"fixture": "a" * 64})
    monkeypatch.setattr(runner, "_verified_response", lambda *args: None)
    monkeypatch.setattr(runner, "_cleanup_verified", lambda *args: cleanup)
    monkeypatch.setattr(runner, "_tree_bytes", lambda _: 0)
    monkeypatch.setattr(runner, "_configuration", lambda _: object())
    monkeypatch.setattr(runner, "_static", lambda *args: (tmp_path / "image.png", {"bundle_ref": {}}))
    monkeypatch.setattr(runner.subprocess, "check_output", lambda *args, **kwargs: "GPU-test, 1024, 256, 768\n")
    return path


def test_unverified_cleanup_stops_next_model_but_keeps_full_denominator(tmp_path, monkeypatch):
    value = json.loads(_catalog(tmp_path).read_text(encoding="utf-8"))
    path = _fake_batch(tmp_path, monkeypatch, value, cleanup=False)
    calls = []
    def actual(**kwargs):
        calls.append(kwargs["refinement_mode"])
        return _fake_actual(**kwargs)
    monkeypatch.setattr(runner, "run_learning_selection_actual_no_action", actual)
    report = runner.run_acceptance(catalog_path=path, out_dir=tmp_path / "out", limit=None, assets_root=tmp_path, artifact_root=tmp_path)
    assert calls == ["never"]
    assert report["stopped_for_unverified_cleanup"] is True
    assert report["full_denominator"] == 6
    assert report["completed_denominator"] == 1
    assert report["not_run_per_policy"] == {"never": 1, "conditional": 2, "always": 2}


def test_full_score_cannot_hide_wrong_predictions_on_old_abstentions(tmp_path, monkeypatch):
    value = json.loads(_catalog(tmp_path).read_text(encoding="utf-8"))
    base_row, base_score = value["inference_rows"][0], value["scoring_rows"][0]
    value["inference_rows"], value["scoring_rows"] = [], []
    for index in range(35):
        identity = {"suite": "fixed25", "case_id": f"case-{index}", "target_id": f"target-{index}"}
        value["inference_rows"].append({**deepcopy(base_row), **identity})
        value["scoring_rows"].append({**deepcopy(base_score), **identity, "baseline_outcome": "correct" if index < 26 else "abstained",
            "ground_truth": {"acceptable_regions": [[0, 0, 10, 10]] if index < 26 else [[20, 20, 30, 30]]}})
    path = _fake_batch(tmp_path, monkeypatch, value)
    def actual(**kwargs):
        result = _fake_actual(**kwargs)
        response_path = kwargs["out_dir"] / "selection-result.json"
        response = json.loads(response_path.read_text(encoding="utf-8"))
        response["refinement"] = {"status": "skipped", "provider_result": None}
        response_path.write_text(json.dumps(response), encoding="utf-8")
        return {**result, "canonical_capture_pixel_point": [5, 5]}
    monkeypatch.setattr(runner, "run_learning_selection_actual_no_action", actual)
    report = runner.run_acceptance(catalog_path=path, out_dir=tmp_path / "out", limit=None, assets_root=tmp_path, artifact_root=tmp_path)
    assert report["per_policy"]["conditional"] == {"targets": 35, "correct": 26, "wrong": 9, "abstained": 0}
    assert report["original_correct_regressions"] == []
    assert report["full_acceptance_pass"] is False
