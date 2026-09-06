from __future__ import annotations
import importlib.util
import json
from hashlib import sha256
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("selection_export",ROOT/"scripts/export_learning_selection_acceptance_review.py")
exporter=importlib.util.module_from_spec(SPEC); assert SPEC.loader is not None; SPEC.loader.exec_module(exporter)

def test_export_uses_finalized_receipt_without_mutating_source(tmp_path,monkeypatch):
    run=tmp_path/"run"; case=run/"cases"/"case"; case.mkdir(parents=True)
    selection={"selection":{"selection_status":"selected","model_proposal":{"canonical_capture_pixel_point":[4,5],"binding_status":"BOUND","binding_reason":None}},"refinement":{"status":"skipped","provider_result":None}}
    selection_path=case/"selection-result.json"; selection_path.write_text(json.dumps(selection),encoding="utf-8")
    receipt={"contract_version":"learning_selection_acceptance_case_receipt_v1","key":["fixed25","case-001","target-01"],"refinement_mode":"never","validation_error":None,"selection_result_file_ref":{"path":"selection-result.json","sha256":sha256(selection_path.read_bytes()).hexdigest()},"actual_result":{"outcome":"completed","trial_path":"trial.json"},"score":{"outcome":"correct"}}
    receipt_path=case/"acceptance-receipt.json"; receipt_path.write_text(json.dumps(receipt),encoding="utf-8")
    (run/"run-identity.json").write_text("{}",encoding="utf-8")
    source_hash=sha256(receipt_path.read_bytes()+selection_path.read_bytes()).hexdigest()
    projection={"execution_origin":"actual_model","parent_refs":{"native_output_ref":{"sha256":"a"*64}},"selection":selection["selection"],"refinement":selection["refinement"],"candidates":[{"candidate_id":None,"reviewed_semantics":{"status":"missing"}}]}
    monkeypatch.setattr(exporter,"ROOT",tmp_path)
    monkeypatch.setattr(exporter.acceptance,"_catalog",lambda _: {"inference_rows":[{"suite":"fixed25","case_id":"case-001","target_id":"target-01","target_text":"target"}],"scoring_rows":[{"suite":"fixed25","case_id":"case-001","target_id":"target-01","baseline_outcome":"correct"}]})
    verified = dict(receipt, score={"outcome":"wrong"}, resource_cleanup_verified=True)
    monkeypatch.setattr(exporter.acceptance,"_reuse",lambda *args: verified)
    monkeypatch.setattr(exporter,"load_learning_draft_review",lambda *args,**kwargs:{"draft":{},"hybrid_review_projection":projection})
    monkeypatch.setattr(exporter,"selection_review_regions",lambda _:[])
    def render(draft,*,root,out_dir,revision):
        path=out_dir/"human_review_overlay_legacy.png"; path.write_bytes(b"png"); return path
    monkeypatch.setattr(exporter,"_render_human_review_overlay",render)
    disk=exporter._read(receipt_path); disk["_receipt_path"]="cases/case/acceptance-receipt.json"
    assert exporter._record(case,disk,tmp_path/"debug-export",{"target_text":"target"},{"baseline_outcome":"correct"},"identity") is not None
    result=exporter.export(run,tmp_path/"export")
    assert result["record_count"]==1, result
    row=result["records"][0]
    assert row["semantic_review_missing"] is True
    assert row["actual_outcome"] == "wrong"
    assert row["raw_binding_status"] == "BOUND"
    assert row["resource_cleanup_verified"] is True
    assert row["original_capture_pixel_point"]==[4,5]
    assert row["validated_refiner_capture_pixel_point"] is None
    assert sha256(receipt_path.read_bytes()+selection_path.read_bytes()).hexdigest()==source_hash
    assert (tmp_path/"export/index.html").is_file()

def test_export_omits_incomplete_case(tmp_path, monkeypatch):
    run=tmp_path/"run"; (run/"cases"/"incomplete").mkdir(parents=True)
    (run/"run-identity.json").write_text("{}",encoding="utf-8")
    monkeypatch.setattr(exporter.acceptance, "_catalog", lambda _: {"inference_rows":[],"scoring_rows":[]})
    result=exporter.export(run,tmp_path/"export")
    assert result["record_count"]==0
    assert result["incomplete_case_directories"]==["incomplete"]


def test_export_rejects_unverifiable_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr(exporter.acceptance, "_reuse", lambda *args: None)
    receipt = {"contract_version":"learning_selection_acceptance_case_receipt_v1", "refinement_mode":"never"}
    assert exporter._record(tmp_path, receipt, tmp_path / "out", {}, {}, "identity") is None


def test_export_keeps_finalized_failure_separate_from_incomplete(tmp_path, monkeypatch):
    receipt = {"contract_version":"learning_selection_acceptance_case_receipt_v1", "refinement_mode":"never",
               "actual_result":{"outcome":"safe_stopped", "reason":"model_timeout"},
               "score":{"outcome":"abstained"}, "resource_cleanup_verified":True}
    monkeypatch.setattr(exporter.acceptance, "_reuse", lambda *args: receipt)
    result = exporter._record(tmp_path, receipt, tmp_path / "out", {"target_text":"target"}, {"baseline_outcome":"correct"}, "identity")
    assert result["finalized_failure"] is True
    assert result["actual_outcome"] == "abstained"
    assert result["overlay_path"] is None


def test_export_does_not_present_human_geometry_as_raw(tmp_path, monkeypatch):
    import pytest
    receipt = {"contract_version":"learning_selection_acceptance_case_receipt_v1", "refinement_mode":"never",
               "actual_result":{"outcome":"completed", "trial_path":"trial.json"}}
    monkeypatch.setattr(exporter.acceptance, "_reuse", lambda *args: receipt)
    monkeypatch.setattr(exporter, "load_learning_draft_review", lambda *args, **kwargs: {
        "hybrid_review_projection":{"execution_origin":"actual_model", "review_decisions":[{"kind":"human_rebox"}]}})
    with pytest.raises(ValueError, match="raw model"):
        exporter._record(tmp_path, receipt, tmp_path / "out", {}, {}, "identity")
