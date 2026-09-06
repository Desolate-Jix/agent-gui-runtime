"""Export read-only visual review pages from finalized selection acceptance receipts."""
from __future__ import annotations
import argparse
from copy import deepcopy
from hashlib import sha256
from html import escape
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.learn.draft_review import _render_human_review_overlay, load_learning_draft_review
from app.learn.hybrid.selection_persistence import selection_review_regions
if __name__ == "__main__":
    # 导出进程不运行工作流；隔离导入期间的全局存储，不争用正在推理的持久锁。
    os.environ["AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH"] = ":memory:"
from scripts import run_learning_selection_acceptance as acceptance


def _read(path: Path) -> dict[str, Any]:
    value=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value,dict): raise ValueError(f"JSON object required: {path}")
    return value

def _ref_ok(case: Path, value: object) -> bool:
    if not isinstance(value,Mapping): return False
    name=value.get("path"); digest=value.get("sha256")
    path=case/str(name)
    return isinstance(name,str) and isinstance(digest,str) and path.is_file() and sha256(path.read_bytes()).hexdigest()==digest

def _point(value: object) -> list[float|int] | None:
    return list(value) if isinstance(value,list) and len(value)==2 and all(isinstance(x,(int,float)) and not isinstance(x,bool) for x in value) else None

def _record(case: Path, receipt: Mapping[str,Any], out: Path, row: Mapping[str,Any], gold: Mapping[str,Any], identity_sha: str) -> dict[str,Any] | None:
    if receipt.get("contract_version")!="learning_selection_acceptance_case_receipt_v1" or receipt.get("validation_error") is not None: return None
    verified=acceptance._reuse(case/"acceptance-receipt.json",row,str(receipt.get("refinement_mode") or ""),gold,identity_sha)
    if verified is None: return None
    receipt=dict(verified, _receipt_path=str(case / "acceptance-receipt.json")); actual=receipt.get("actual_result")
    if not isinstance(actual,Mapping): return None
    if actual.get("outcome") != "completed":
        return {"key":receipt.get("key"),"refinement_mode":receipt.get("refinement_mode"),"target_text":row["target_text"],"raw_binding_status":None,"raw_binding_reason":None,"original_capture_pixel_point":None,"validated_refiner_capture_pixel_point":None,"refinement_status":None,"refusal_or_abstention_reason":actual.get("reason"),"semantic_review_missing":True,"trial_path":None,"parent_evidence_hashes":{},"overlay_path":None,"receipt_path":receipt.get("_receipt_path"),"baseline_outcome":gold["baseline_outcome"],"actual_outcome":receipt["score"]["outcome"],"finalized_failure":True}
    trial=actual.get("trial_path")
    if not isinstance(trial,str) or not trial: return None
    review=load_learning_draft_review(trial,project_root=ROOT)
    projection=review.get("hybrid_review_projection")
    if not isinstance(projection,Mapping) or projection.get("execution_origin")!="actual_model": return None
    if projection.get("review_decisions"):
        raise ValueError("reviewed geometry cannot be shown as raw model output")
    key=receipt.get("key")
    if not isinstance(key,list) or len(key)!=3: return None
    token=sha256("|".join(str(x) for x in key+[receipt.get("refinement_mode")]).encode("utf-8")).hexdigest()
    overlay_draft=deepcopy(review["draft"]); overlay_draft["regions"]=selection_review_regions(dict(projection))
    overlay_dir=out/"overlays"/token; overlay_dir.mkdir(parents=True,exist_ok=False)
    overlay=_render_human_review_overlay(overlay_draft,root=ROOT,out_dir=overlay_dir,revision=0)
    selection=projection.get("selection") if isinstance(projection.get("selection"),Mapping) else {}
    refinement=projection.get("refinement") if isinstance(projection.get("refinement"),Mapping) else {}
    proposal=selection.get("model_proposal") if isinstance(selection.get("model_proposal"),Mapping) else {}
    provider=refinement.get("provider_result") if isinstance(refinement.get("provider_result"),Mapping) else {}
    selected=next((item for item in projection.get("candidates",[]) if isinstance(item,Mapping) and item.get("candidate_id")==selection.get("candidate_id")),None)
    semantic=(selected or {}).get("reviewed_semantics") if isinstance(selected,Mapping) else {}
    return {"resource_cleanup_verified":receipt.get("resource_cleanup_verified"),"source_score":proposal.get("source_score"),"learning_state":projection.get("learning_state"),"key":key,"refinement_mode":receipt.get("refinement_mode"),"target_text":selection.get("target_text"),"raw_binding_status":proposal.get("binding_status"),"raw_binding_reason":proposal.get("binding_reason"),"original_capture_pixel_point":_point(proposal.get("canonical_capture_pixel_point")),"validated_refiner_capture_pixel_point":_point(provider.get("canonical_capture_pixel_point")) if refinement.get("status")=="validated" else None,"refinement_status":refinement.get("status"),"refusal_or_abstention_reason":actual.get("reason") or refinement.get("reason"),"semantic_review_missing":not isinstance(semantic,Mapping) or semantic.get("status")!="human_supplied","trial_path":trial,"parent_evidence_hashes":deepcopy(projection.get("parent_refs") or {}),"overlay_path":overlay.relative_to(out).as_posix() if overlay else None,"receipt_path":receipt.get("_receipt_path"),"baseline_outcome":gold["baseline_outcome"],"actual_outcome":receipt["score"]["outcome"],"finalized_failure":False}

def export(run: Path, out: Path) -> dict[str,Any]:
    run=run.resolve(); out=out.resolve()
    if not run.is_dir(): raise ValueError("run directory is unavailable")
    if out.exists() or out.is_relative_to(run): raise ValueError("export output must be a new directory outside the source run")
    catalog=acceptance._catalog(ROOT/"configs/benchmarks/learning_selection_acceptance_v1.json")
    score_by_key={acceptance._key(item):item for item in catalog["scoring_rows"]}; input_by_key={acceptance._key(item):item for item in catalog["inference_rows"]}
    identity_path=run/"run-identity.json"
    if not identity_path.is_file() or sha256(identity_path.read_bytes()).hexdigest() == "": raise ValueError("frozen run identity is unavailable")
    identity_sha=sha256(identity_path.read_bytes()).hexdigest()
    out.mkdir(parents=True)
    records=[]; incomplete=[]; invalid=[]
    for case in sorted((run/"cases").glob("*")):
        if not case.is_dir(): continue
        path=case/"acceptance-receipt.json"
        if not path.is_file(): incomplete.append(case.name); continue
        try:
            receipt=_read(path); receipt["_receipt_path"]=path.relative_to(run).as_posix(); raw_key=receipt.get("key")
            if not isinstance(raw_key,list) or len(raw_key)!=3 or not all(isinstance(item,str) and item for item in raw_key): raise ValueError("invalid receipt key")
            key=tuple(raw_key); record=_record(case,receipt,out,input_by_key[key],score_by_key[key],identity_sha)
        except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError) as error:
            invalid.append({"case":case.name,"reason":type(error).__name__+":"+str(error)}); continue
        if record is None: invalid.append({"case":case.name,"reason":"receipt_or_model_evidence_not_verified"})
        else: records.append(record)
    records.sort(key=lambda item: (item["key"], acceptance.POLICIES.index(item["refinement_mode"])))
    index={"contract_version":"learning_selection_acceptance_visual_export_v1","source_run":str(run),"record_count":len(records),"incomplete_case_directories":incomplete,"records":records,"artifact_is_authorization":False,"execute_binding_enabled":False}
    index.update(invalid_cases=invalid, full_denominator=105, run_identity_sha256=identity_sha)
    (out/"index.json").write_text(json.dumps(index,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    cards=[]
    for row in records:
        image=f'<img src="{escape(str(row["overlay_path"] or ""),quote=True)}" alt="overlay">' if row["overlay_path"] else "<p>overlay unavailable</p>"
        visible = {
            "原基线 → 本次模型评分": str(row["baseline_outcome"]) + " → " + str(row["actual_outcome"]),
            "选择绑定 / 拒绝原因": [row["raw_binding_status"], row["raw_binding_reason"]],
            "GUIActor 原始点（仅诊断）": row["original_capture_pixel_point"],
            "已验证的精修点": row["validated_refiner_capture_pixel_point"],
            "精修状态": [row["refinement_status"], row["refusal_or_abstention_reason"]],
            "模型分数": row.get("source_score") if row.get("source_score") is not None else "未提供",
            "尚缺语义 / 学习状态": [row["semantic_review_missing"], row.get("learning_state")],
        }
        fields="".join(f"<dt>{escape(name)}</dt><dd>{escape(json.dumps(value,ensure_ascii=False))}</dd>" for name,value in visible.items())
        technical=escape(json.dumps(row,ensure_ascii=False,indent=2))
        cards.append(f'<article><h2>{escape(str(row["target_text"]))}</h2><p>{escape(" / ".join(row["key"]))} · {escape(row["refinement_mode"])}</p>{image}<dl>{fields}</dl><details><summary>原始字段和证据引用</summary><pre>{technical}</pre></details></article>')
    html="<!doctype html><meta charset=\"utf-8\"><title>选择验收审核</title><style>article{margin:20px;padding:12px;border:1px solid #aaa}img{max-width:900px}dt{font-weight:bold}dd{white-space:pre-wrap}</style><h1>选择验收审核</h1><p>蓝框=候选 / 红框=当前所选。分数未提供≠低分；人工修订不计模型成绩。</p>"+"".join(cards)
    html += f'<p>已导出 {len(records)} / 105 条；运行中目录 {len(incomplete)} 个；证据未通过复验 {len(invalid)} 个。未运行项目不算完成。</p>'
    (out/"index.html").write_text(html,encoding="utf-8")
    return index

def main()->int:
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--run",required=True,type=Path); parser.add_argument("--out",required=True,type=Path); args=parser.parse_args()
    result = export(args.run,args.out)
    print(json.dumps({key:value for key,value in result.items() if key != "records"},ensure_ascii=False,indent=2))
    return 1 if result["invalid_cases"] else 0
if __name__=="__main__": raise SystemExit(main())
