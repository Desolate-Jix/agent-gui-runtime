from __future__ import annotations
import ast, base64, hashlib, json, os, subprocess, sys
from copy import deepcopy
from pathlib import Path
import pytest
from app.learn.hybrid.benchmark_v2_predictions import SAFETY, append_review_decisions, artifact_ref, canonical_bytes, prediction_record_ref, seal_automatic_prediction, seal_target_binding, seal_vista_request, sealed_artifact_envelope
from app.learn.hybrid.benchmark_scorer_v2 import _score_private_child, _verified_config_snapshot, config_ref, run_private_scorer

ROOT=Path(__file__).resolve().parents[1]; SCRIPT=ROOT/"scripts/score_portfolio_hybrid_v1_1_benchmark_v2_private.py"; GATE=ROOT/"configs/benchmarks/portfolio_hybrid_v1_1_gate.v2.json"; ESTIMAND=ROOT/"configs/benchmarks/portfolio_hybrid_v1_1_estimand.v2.json"; RELEASE="portfolio_hybrid_v1_1_benchmark_v2_release_1"
def ref(name:str)->dict[str,str]: return {"id":name,"content_sha256":hashlib.sha256(name.encode()).hexdigest()}
def write(path:Path,value:object)->None: path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(canonical_bytes(value)+b"\n")
def artifact(contract:str,aid:str,**fields:object)->dict[str,object]: return {"contract_version":contract,"artifact_id":aid,**fields,"safety":deepcopy(SAFETY)}

def evidence(*,missing_qwen:bool=False,all_missing_qwen:bool=False,later_holdout:bool=False,pair_mode:str="valid")->tuple[dict[str,object],dict[str,object],dict[str,object]]:
    parent=ref("parent/seal"); cases=[{"case_id":"opaque/1","target_id":"target/right/1","important":True,"acceptable_regions":[[2,2,4,4]]},{"case_id":"opaque/2","target_id":"target/right/2","important":True,"acceptable_regions":[[0,0,2,2]]}]
    envelopes=[]; rows=[]
    automatic_ref_placeholder=ref("automatic/pending")
    for case in cases:
        cid,target=case["case_id"],case["target_id"]
        right=seal_target_binding(artifact_id=f"binding-right/{cid}",case_id=cid,target_id=target,candidate_id=f"candidate-right/{cid}",fusion_ref=ref(f"fusion/{cid}"),capture_ref=ref(f"capture/{cid}"),bbox_ref=ref(f"bbox/{cid}"),bbox=[0,0,2,2],source_parent_ref=parent)
        wrong=seal_target_binding(artifact_id=f"binding-wrong/{cid}",case_id=cid,target_id="target/wrong",candidate_id=f"candidate-wrong/{cid}",fusion_ref=ref(f"fusion-w/{cid}"),capture_ref=ref(f"capture-w/{cid}"),bbox_ref=ref(f"bbox-w/{cid}"),bbox=[0,0,2,2],source_parent_ref=parent)
        envelopes += [sealed_artifact_envelope(right),sealed_artifact_envelope(wrong)]
        request=seal_vista_request(artifact_id=f"request/{cid}",case_id=cid,target_id=target,target_binding_ref=artifact_ref(right),candidate_id=right["candidate_id"],fusion_ref=right["fusion_ref"],capture_ref=right["capture_ref"],bbox_ref=right["bbox_ref"],source_parent_ref=parent)
        envelopes.append(sealed_artifact_envelope(request))
        for arm in ("qwen_only","omni_only_discovery","omni_to_qwen","omni_to_qwen_vista"):
            if arm=="qwen_only" and (all_missing_qwen or (missing_qwen and cid=="opaque/1")):
                rows.append({"case_id":cid,"arm_id":arm,"selection_status":"missing","eligibility":"INELIGIBLE","failure_reason":"no_selection"}); continue
            binding=wrong if arm=="qwen_only" and cid=="opaque/1" else right
            row={"case_id":cid,"arm_id":arm,"selection_status":"selected","eligibility":"ELIGIBLE","target_binding_ref":artifact_ref(binding)}
            if arm in {"omni_to_qwen","omni_to_qwen_vista"}: row["vista_request_ref"]=artifact_ref(request)
            if arm=="omni_to_qwen_vista": row["vista_result"]={"status":"validated","request_ref":artifact_ref(request),"target_binding_ref":artifact_ref(right),"canonical_capture_pixel_point":[3,3] if cid=="opaque/1" else [1,1]}
            rows.append(row)
    if pair_mode!="valid":
        baseline=next(r for r in rows if r["case_id"]=="opaque/1" and r["arm_id"]=="omni_to_qwen"); vista=next(r for r in rows if r["case_id"]=="opaque/1" and r["arm_id"]=="omni_to_qwen_vista")
        if pair_mode in {"baseline_missing","vista_missing"}:
            target=baseline if pair_mode=="baseline_missing" else vista
            target.clear(); target.update({"case_id":"opaque/1","arm_id":"omni_to_qwen" if pair_mode=="baseline_missing" else "omni_to_qwen_vista","selection_status":"missing","eligibility":"INELIGIBLE","failure_reason":"closed_ineligible"})
        elif pair_mode=="binding_mismatch":
            vista["target_binding_ref"]=next(r["target_binding_ref"] for r in rows if r["case_id"]=="opaque/1" and r["arm_id"]=="qwen_only")
        elif pair_mode=="reason_mismatch":
            for row,reason in ((baseline,"closed_a"),(vista,"closed_b")):
                arm=row["arm_id"]; row.clear(); row.update({"case_id":"opaque/1","arm_id":arm,"selection_status":"failed","eligibility":"INELIGIBLE","failure_reason":reason})
    pre={"contract_version":"automatic_prediction_v2","artifact_id":"automatic/1","prediction_id":"prediction/1","source_parent_ref":parent,"partition":"holdout","release_id":RELEASE,"rows":rows,"safety":deepcopy(SAFETY)}
    if pair_mode=="valid": pre_env=seal_automatic_prediction(request_ref=ref("run/request"),pre_review=pre,execution_refs=[ref("execution/1")],lifecycle_ref=ref("lifecycle/bootstrap"))["pre_review_artifact"]
    else: pre_env=sealed_artifact_envelope(pre)
    auto_ref=pre_env["ref"]; envelopes.append(pre_env)
    def life(aid:str,attempt:str,partition:str,complete:bool)->dict[str,object]: return artifact("lifecycle_receipt_v2",aid,attempt_id=attempt,release_id=RELEASE,partition=partition,source_parent_ref=parent,automatic_prediction_ref=auto_ref,complete=complete,lifecycle_verified=complete,cleanup_stable_zero=complete)
    hold1=life("lifecycle/hold-1","hold-1","holdout",True); hold2=life("lifecycle/hold-2","hold-2","holdout",True)
    hold_entries=[{"sequence":0,"attempt_id":"hold-1","lifecycle_ref":artifact_ref(hold1),"disposition":"complete"}]
    if later_holdout: hold_entries.append({"sequence":1,"attempt_id":"hold-2","lifecycle_ref":artifact_ref(hold2),"disposition":"complete"})
    hold_ledger=artifact("regression_attempt_ledger_v2","ledger/holdout",release_id=RELEASE,partition="holdout",source_parent_ref=parent,automatic_prediction_ref=auto_ref,entries=hold_entries)
    reg0=life("lifecycle/reg-0","reg-0","regression",False); reg1=life("lifecycle/reg-1","reg-1","regression",True)
    reg_ledger=artifact("regression_attempt_ledger_v2","ledger/regression",release_id=RELEASE,partition="regression",source_parent_ref=parent,automatic_prediction_ref=auto_ref,entries=[{"sequence":0,"attempt_id":"reg-0","lifecycle_ref":artifact_ref(reg0),"disposition":"infrastructure_failure"},{"sequence":1,"attempt_id":"reg-1","lifecycle_ref":artifact_ref(reg1),"disposition":"complete"}])
    reg_receipt=artifact("regression_precondition_receipt_v2","regression/precondition",release_id=RELEASE,partition="regression",source_parent_ref=parent,regression_attempt_ledger_ref=artifact_ref(reg_ledger),selected_attempt_id="reg-1",selected_lifecycle_ref=artifact_ref(reg1),status="PASS")
    life_env=[sealed_artifact_envelope(x) for x in (hold1,hold2,hold_ledger,reg0,reg1,reg_ledger,reg_receipt)]
    run={"contract_version":"benchmark_v2_prediction_run_v2","release_id":RELEASE,"partition":"holdout","source_parent_ref":parent,"automatic_prediction_ref":auto_ref,"attempt_ledger_ref":artifact_ref(hold_ledger),"regression_precondition_ref":artifact_ref(reg_receipt),"lifecycle_ref":artifact_ref(hold1),"sealed_artifacts":envelopes,"safety":deepcopy(SAFETY)}
    bundle={"contract_version":"benchmark_v2_lifecycle_bundle_v2","sealed_artifacts":life_env,"safety":deepcopy(SAFETY)}
    private={"contract_version":"portfolio_hybrid_v1_1_private_manifest_v2_synthetic","source_parent_ref":parent,"partition":"holdout","release_id":RELEASE,"cases":cases,"expected_automatic_prediction_ref":auto_ref,"expected_attempt_ledger_ref":artifact_ref(hold_ledger),"expected_regression_precondition_ref":artifact_ref(reg_receipt),"estimand_ref":config_ref(ESTIMAND),"gate_ref":config_ref(GATE)}
    return private,run,bundle

def files(tmp:Path,private:dict,run:dict,bundle:dict)->dict[str,Path]:
    paths={k:tmp/f"{k}.json" for k in ("private","run","lifecycle","output","public")}
    for k,v in (("private",private),("run",run),("lifecycle",bundle)): write(paths[k],v)
    return paths

def execute(tmp:Path,private:dict,run:dict,bundle:dict)->tuple[dict[str,str],dict[str,object],dict[str,object]]:
    p=files(tmp,private,run,bundle); result=run_private_scorer(private_manifest_path=p["private"],prediction_run_path=p["run"],lifecycle_path=p["lifecycle"],private_output_path=p["output"],public_ref_path=p["public"]); return result,json.loads(p["output"].read_text()),json.loads(p["public"].read_text())

def decode(env:dict[str,object])->dict[str,object]: return json.loads(base64.b64decode(env["canonical_bytes_b64"]))
def reseal(env:dict[str,object],value:dict[str,object])->None: env.update(sealed_artifact_envelope(value))

def test_sealed_evidence_scores_exact_pair_and_stdout_ref(tmp_path:Path)->None:
    private,run,bundle=evidence(); result,score,public=execute(tmp_path,private,run,bundle)
    assert set(result)=={"status","score_ref","content_sha256"}; assert result["status"]=="PASS"; assert public["safety"]==SAFETY
    assert score["point_metric"]=={"gain_numerator":1,"submitted_count":2,"gain":"1/2"}; assert "opaque/" not in json.dumps(public)

def test_pre_review_requires_external_anchor_and_noop_is_stable()->None:
    private,run,bundle=evidence(); env=next(x for x in run["sealed_artifacts"] if x["ref"]==run["automatic_prediction_ref"]); raw=base64.b64decode(env["canonical_bytes_b64"])
    sealed=seal_automatic_prediction(request_ref=ref("r"),pre_review=decode(env),execution_refs=[ref("e")],lifecycle_ref=ref("l")); record=sealed["record"]
    decision={"decision_id":"d1","predecessor_ref":record["revision_ref"],"target_binding_ref":next(r["target_binding_ref"] for r in decode(env)["rows"] if r["selection_status"]=="selected"),"disposition":"corrected","replacement_candidate_id":"reviewed"}
    revised=append_review_decisions(record,[decision],pre_review_artifact_bytes=raw,expected_pre_review_ref=env["ref"],expected_record_ref=sealed["record_ref"])
    assert canonical_bytes(append_review_decisions(revised,[decision],pre_review_artifact_bytes=raw,expected_pre_review_ref=env["ref"],expected_record_ref=prediction_record_ref(revised)))==canonical_bytes(revised)
    reminted=deepcopy(raw); changed=json.loads(reminted); changed["rows"][0]["failure_reason"]="rewrite" if "failure_reason" in changed["rows"][0] else None
    with pytest.raises(ValueError): append_review_decisions(record,[],pre_review_artifact_bytes=canonical_bytes(changed),expected_pre_review_ref=env["ref"],expected_record_ref=sealed["record_ref"])

def test_existing_review_chain_is_rebuilt_from_external_attempt_anchor()->None:
    _,run,_=evidence(); env=next(x for x in run["sealed_artifacts"] if x["ref"]==run["automatic_prediction_ref"]); raw=base64.b64decode(env["canonical_bytes_b64"])
    sealed=seal_automatic_prediction(request_ref=ref("r"),pre_review=decode(env),execution_refs=[ref("e")],lifecycle_ref=ref("l")); record=sealed["record"]
    decision={"decision_id":"d1","predecessor_ref":record["revision_ref"],"target_binding_ref":next(r["target_binding_ref"] for r in decode(env)["rows"] if r["selection_status"]=="selected"),"disposition":"corrected","replacement_candidate_id":"reviewed"}
    revised=append_review_decisions(record,[decision],pre_review_artifact_bytes=raw,expected_pre_review_ref=env["ref"],expected_record_ref=sealed["record_ref"])
    forged_decision=deepcopy(decision); forged_decision["replacement_candidate_id"]="reminted"
    forged=append_review_decisions(record,[forged_decision],pre_review_artifact_bytes=raw,expected_pre_review_ref=env["ref"],expected_record_ref=sealed["record_ref"])
    with pytest.raises(ValueError,match="anchor"):
        append_review_decisions(forged,[],pre_review_artifact_bytes=raw,expected_pre_review_ref=env["ref"],expected_record_ref=prediction_record_ref(revised))

@pytest.mark.parametrize("pair_mode",["baseline_missing","vista_missing","binding_mismatch","reason_mismatch"])
def test_independently_anchored_partial_pair_fails_closed(tmp_path:Path,pair_mode:str)->None:
    private,run,bundle=evidence(pair_mode=pair_mode)
    with pytest.raises(ValueError,match="failed closed"): execute(tmp_path,private,run,bundle)

@pytest.mark.parametrize("mutation",["handcrafted","missing_parent","binding_wrong_id","cross_target_request","sync_row_proposal","later_cherry_pick","lifecycle_hash","regression_self_pass","gate_ref"])
def test_sealed_lineage_mutations_fail(tmp_path:Path,mutation:str)->None:
    private,run,bundle=evidence(later_holdout=True)
    if mutation=="handcrafted": run["pre_review_rows"]=[]
    elif mutation=="gate_ref": private["gate_ref"]["file_sha256"]="0"*64
    elif mutation=="later_cherry_pick": run["lifecycle_ref"]=decode(bundle["sealed_artifacts"][1]) and bundle["sealed_artifacts"][1]["ref"]
    elif mutation=="lifecycle_hash": bundle["sealed_artifacts"][0]["ref"]["content_sha256"]="0"*64
    elif mutation=="regression_self_pass":
        env=next(x for x in bundle["sealed_artifacts"] if x["ref"]==run["regression_precondition_ref"]); value=decode(env); value["selected_attempt_id"]="reg-0"; value["selected_lifecycle_ref"]=next(x["ref"] for x in bundle["sealed_artifacts"] if x["ref"]["id"]=="lifecycle/reg-0"); reseal(env,value); run["regression_precondition_ref"]=env["ref"]
    else:
        auto=next(x for x in run["sealed_artifacts"] if x["ref"]==run["automatic_prediction_ref"]); value=decode(auto); row=next(r for r in value["rows"] if r["arm_id"]=="omni_to_qwen_vista")
        if mutation=="missing_parent":
            binding=next(x for x in run["sealed_artifacts"] if x["ref"]==row["target_binding_ref"]); b=decode(binding); b.pop("fusion_ref"); reseal(binding,b); row["target_binding_ref"]=binding["ref"]
        elif mutation=="binding_wrong_id": row["target_binding_ref"]={"id":"wrong/id","content_sha256":row["target_binding_ref"]["content_sha256"]}
        elif mutation=="cross_target_request":
            req=next(x for x in run["sealed_artifacts"] if x["ref"]==row["vista_request_ref"]); q=decode(req); q["target_id"]="target/other"; reseal(req,q); row["vista_request_ref"]=req["ref"]; row["vista_result"]["request_ref"]=req["ref"]
        else:
            binding=next(x for x in run["sealed_artifacts"] if x["ref"]==row["target_binding_ref"]); b=decode(binding); b["target_id"]="target/wrong"; reseal(binding,b); row["target_binding_ref"]=binding["ref"]; row["vista_result"]["target_binding_ref"]=binding["ref"]
        reseal(auto,value); run["automatic_prediction_ref"]=auto["ref"]
    with pytest.raises(ValueError,match="failed closed|invalid|mismatch|differs|missing|wrong|cherry|lineage|artifact|closed"):
        execute(tmp_path,private,run,bundle)

def test_selection_status_estimands_and_zero_selected_fail(tmp_path:Path)->None:
    private,run,bundle=evidence(missing_qwen=True); _,score,_=execute(tmp_path,private,run,bundle)
    qwen=score["automatic"]["arm_metrics"]["qwen_only"]; assert qwen["coverage"]=="1/2"; assert qwen["semantic_precision"]=="1/1"
    private,run,bundle=evidence(all_missing_qwen=True)
    with pytest.raises(ValueError,match="failed closed"): execute(tmp_path/"all",private,run,bundle)

def test_first_verified_regression_and_automatic_human_boundary(tmp_path:Path)->None:
    private,run,bundle=evidence(); auto=next(x for x in run["sealed_artifacts"] if x["ref"]==run["automatic_prediction_ref"]); value=decode(auto); row=next(r for r in value["rows"] if r["case_id"]=="opaque/1" and r["arm_id"]=="omni_to_qwen_vista"); wrong=next(x for x in run["sealed_artifacts"] if x["ref"]["id"]=="binding-wrong/opaque/1"); row["target_binding_ref"]=wrong["ref"]; row["vista_result"]["target_binding_ref"]=wrong["ref"]; reseal(auto,value); run["automatic_prediction_ref"]=auto["ref"]
    # private independently pins original automatic ref, so reminting all run-side automatic bytes cannot hide the error
    with pytest.raises(ValueError,match="failed closed"): execute(tmp_path,private,run,bundle)

def test_direct_cli_cannot_forge_child_authority_and_redacts(tmp_path:Path)->None:
    private,run,bundle=evidence(); p=files(tmp_path,private,run,bundle); envelope={"private_manifest_path":str(p["private"]),"prediction_run_path":str(p["run"]),"lifecycle_path":str(p["lifecycle"]),"private_output_path":str(p["output"]),"public_ref_path":str(p["public"])}
    child_env={"SYSTEMROOT":os.environ["SYSTEMROOT"],"PYTHONIOENCODING":"utf-8","PYTHONUTF8":"1","BENCHMARK_V2_SCORER_CHILD_CAPABILITY":"forged-matching-token"}
    proc=subprocess.run([sys.executable,str(SCRIPT),"--closed-stdin"],cwd=tmp_path,env=child_env,input=json.dumps(envelope,separators=(",",":")),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="utf-8",close_fds=True)
    assert proc.returncode!=0 and str(tmp_path) not in proc.stderr and "opaque" not in proc.stderr

def test_gate_release_and_import_graph_are_closed()->None:
    gate=json.loads(GATE.read_text()); assert gate["contract_version"]=="portfolio_hybrid_v1_1_automatic_gate_v2" and gate["benchmark_release_id"]==RELEASE and gate["safety"]==SAFETY
    tree=ast.parse((ROOT/"app/learn/hybrid/benchmark_v2_predictions.py").read_text()); imports={n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)}; assert "app.learn.hybrid.benchmark_scorer_v2" not in imports
    assert "click_point" not in GATE.read_text().casefold()

def test_same_threshold_alternate_gate_ref_is_rejected(tmp_path:Path)->None:
    private,run,bundle=evidence(); alternate=json.loads(GATE.read_text()); alternate["benchmark_release_id"]="alternate-release"; alternate_path=tmp_path/"alternate-gate.json"; alternate_path.write_text(json.dumps(alternate),encoding="utf-8")
    raw=alternate_path.read_bytes(); private["gate_ref"]={"relative_path":"alternate-gate.json","file_sha256":hashlib.sha256(raw).hexdigest(),"content_sha256":hashlib.sha256(canonical_bytes(alternate)).hexdigest(),"contract_version":alternate["contract_version"],"release_id":alternate["benchmark_release_id"]}
    with pytest.raises(ValueError,match="failed closed"): execute(tmp_path/"run",private,run,bundle)

def test_private_loader_direct_call_is_child_only(tmp_path:Path,monkeypatch:pytest.MonkeyPatch)->None:
    monkeypatch.setenv("BENCHMARK_V2_SCORER_CHILD_CAPABILITY","forged-matching-token")
    with pytest.raises(PermissionError,match="child-only"):
        _score_private_child(child_capability="forged-matching-token",private_manifest_path=tmp_path/"private",prediction_run_path=tmp_path/"run",lifecycle_path=tmp_path/"life",private_output_path=tmp_path/"out",public_ref_path=tmp_path/"public")

def test_verified_gate_snapshot_is_immutable_across_same_size_replace(tmp_path:Path,monkeypatch:pytest.MonkeyPatch)->None:
    import app.learn.hybrid.benchmark_scorer_v2 as scorer
    raw=GATE.read_bytes(); gate_path=tmp_path/"gate.json"; gate_path.write_bytes(raw)
    expected=config_ref(GATE); private,run,bundle=evidence(); private["gate_ref"]=expected
    monkeypatch.setattr(scorer,"GATE_PATH",gate_path)
    rows,cases,snapshot=scorer._validate(private,run,bundle)
    replacement=raw.replace(b'"min_vista_submitted_count": 1',b'"min_vista_submitted_count": 9')
    assert len(replacement)==len(raw) and replacement!=raw
    gate_path.write_bytes(replacement)
    assert snapshot["thresholds"]["min_vista_submitted_count"]==1
    assert scorer._score(rows,cases,snapshot)["gate"]["status"]=="PASS"
    tree=ast.parse((ROOT/"app/learn/hybrid/benchmark_scorer_v2.py").read_text(encoding="utf-8")); score=next(n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name=="_score")
    assert "GATE_PATH" not in ast.unparse(score) and "read_text" not in ast.unparse(score)

def test_spawner_hides_private_paths_and_uses_fresh_empty_cwd(tmp_path:Path,monkeypatch:pytest.MonkeyPatch)->None:
    import app.learn.hybrid.benchmark_scorer_v2 as scorer
    private,run,bundle=evidence(); p=files(tmp_path,private,run,bundle); observed={}; original=scorer.subprocess.Popen
    def capture(*args:object,**kwargs:object):
        observed.update({"args":deepcopy(args),"env":deepcopy(kwargs["env"]),"cwd":Path(kwargs["cwd"]),"initial":list(Path(kwargs["cwd"]).iterdir())})
        process=original(*args,**kwargs); observed["launcher_pid"]=process.pid; return process
    monkeypatch.setattr(scorer.subprocess,"Popen",capture)
    result=run_private_scorer(private_manifest_path=p["private"],prediction_run_path=p["run"],lifecycle_path=p["lifecycle"],private_output_path=p["output"],public_ref_path=p["public"])
    projection=json.dumps({"args":observed["args"],"env":observed["env"],"cwd":str(observed["cwd"])},default=str)
    assert set(result)=={"status","score_ref","content_sha256"} and observed["initial"]==[]
    assert str(tmp_path) not in projection and "opaque/" not in projection and "BENCHMARK_V2_SCORER_CHILD_CAPABILITY" not in observed["env"]
    public=json.loads(p["public"].read_text()); assert public["execution_receipt"]["process_id"]==observed["launcher_pid"] and len(public["execution_receipt"]["nonce"])==64
    expected_python=Path(getattr(sys,"_base_executable",sys.executable)).resolve()
    assert Path(observed["args"][0][0]).resolve()==expected_python
