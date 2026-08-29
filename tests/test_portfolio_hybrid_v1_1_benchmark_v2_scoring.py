from __future__ import annotations
import ast, base64, hashlib, importlib.util, json, os, subprocess, sys
from copy import deepcopy
import inspect
from pathlib import Path
import pytest
from app.learn.hybrid.benchmark_v2_predictions import SAFETY, append_review_decisions, artifact_ref, attach_vista_outcomes, canonical_bytes, parse_benchmark_v2_goal, prediction_record_ref, seal_automatic_prediction, seal_review_decision, seal_target_binding, seal_vista_request, sealed_artifact_envelope, select_pre_vista_prediction_rows
from app.learn.hybrid.benchmark_v2_contracts import PARENT_REF, content_sha256
from app.learn.hybrid.benchmark_v2_pathless import order_pathless_envelopes, pathless_artifact_ref, seal_pathless_envelope, seal_pathless_projection
import app.learn.hybrid.benchmark_scorer_v2 as scorer_v2
from app.learn.hybrid.benchmark_scorer_v2 import _score_private_child, _verified_config_snapshot, config_ref, run_private_scorer

ROOT=Path(__file__).resolve().parents[1]; SCRIPT=ROOT/"scripts/score_portfolio_hybrid_v1_1_benchmark_v2_private.py"; GATE=ROOT/"configs/benchmarks/portfolio_hybrid_v1_1_gate.v2.json"; ESTIMAND=ROOT/"configs/benchmarks/portfolio_hybrid_v1_1_estimand.v2.json"; RELEASE="portfolio_hybrid_v1_1_benchmark_v2_release_1"
PRIVATE_TARGET_MARKERS=tuple(f"private-target-{index:03d}" for index in range(1,6))
PRIVATE_LABEL_MARKERS=tuple(f"private-label-{index:03d}" for index in range(1,6))
PRIVATE_SCREEN_GROUP_MARKER="private-screen-group-marker/never-public"
def ref(name:str)->dict[str,str]: return {"id":name,"content_sha256":hashlib.sha256(name.encode()).hexdigest()}
def write(path:Path,value:object)->None: path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(canonical_bytes(value)+b"\n")
def artifact(contract:str,aid:str,**fields:object)->dict[str,object]: return {"contract_version":contract,"artifact_id":aid,**fields,"safety":deepcopy(SAFETY)}

def evidence(*,missing_qwen:bool=False,all_missing_qwen:bool=False,later_holdout:bool=False,pair_mode:str="valid")->tuple[dict[str,object],dict[str,object],dict[str,object]]:
    parent=ref("parent/seal"); cases=[{"case_id":f"opaque/{index}","screen_group":PRIVATE_SCREEN_GROUP_MARKER,"important_target":True,"acceptable_regions":[[10+(index-1)*20,10,14+(index-1)*20,14]]} for index in range(1,6)]
    envelopes=[]; rows=[]
    automatic_ref_placeholder=ref("automatic/pending")
    for case in cases:
        cid=case["case_id"]
        index=int(cid.rsplit("/",1)[1]); center=12+(index-1)*20
        right_bbox=[0,0,13,13] if index==1 else [center-3,9,center+3,15]
        wrong_bbox=[29,9,35,15] if index==1 else [0,0,13,13]
        right=seal_target_binding(artifact_id=f"binding-right/{cid}",case_id=cid,candidate_id=f"candidate-right/{cid}",fusion_ref=ref(f"fusion/{cid}"),capture_ref=ref(f"capture/{cid}"),bbox_ref=ref(f"bbox/{cid}"),bbox=right_bbox,source_parent_ref=parent)
        wrong=seal_target_binding(artifact_id=f"binding-wrong/{cid}",case_id=cid,candidate_id=f"candidate-wrong/{cid}",fusion_ref=ref(f"fusion-w/{cid}"),capture_ref=ref(f"capture-w/{cid}"),bbox_ref=ref(f"bbox-w/{cid}"),bbox=wrong_bbox,source_parent_ref=parent)
        envelopes += [sealed_artifact_envelope(right),sealed_artifact_envelope(wrong)]
        request=seal_vista_request(artifact_id=f"request/{cid}",case_id=cid,target_binding_ref=artifact_ref(right),candidate_id=right["candidate_id"],fusion_ref=right["fusion_ref"],capture_ref=right["capture_ref"],bbox_ref=right["bbox_ref"],source_parent_ref=parent)
        envelopes.append(sealed_artifact_envelope(request))
        for arm in ("qwen_only","omni_only_discovery","omni_to_qwen","omni_to_qwen_vista"):
            if arm=="qwen_only" and (all_missing_qwen or (missing_qwen and cid=="opaque/1")):
                rows.append({"case_id":cid,"arm_id":arm,"selection_status":"missing","eligibility":"INELIGIBLE","failure_reason":"no_selection"}); continue
            binding=wrong if arm=="qwen_only" and cid=="opaque/1" else right
            row={"case_id":cid,"arm_id":arm,"selection_status":"selected","eligibility":"ELIGIBLE","target_binding_ref":artifact_ref(binding)}
            if arm in {"omni_to_qwen","omni_to_qwen_vista"}: row["vista_request_ref"]=artifact_ref(request)
            if arm=="omni_to_qwen_vista": row["vista_result"]={"status":"validated","request_ref":artifact_ref(request),"target_binding_ref":artifact_ref(right),"canonical_capture_pixel_point":[center,12]}
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
    private={"contract_version":"portfolio_hybrid_v1_1_private_manifest_v2_1_synthetic","source_parent_ref":parent,"partition":"holdout","release_id":RELEASE,"cases":cases,"expected_automatic_prediction_ref":auto_ref,"expected_attempt_ledger_ref":artifact_ref(hold_ledger),"expected_regression_precondition_ref":artifact_ref(reg_receipt),"estimand_ref":config_ref(ESTIMAND),"gate_ref":config_ref(GATE)}
    return private,run,bundle


def task10_evidence(cases:list[dict[str,object]])->tuple[dict[str,object],dict[str,object]]:
    parent={"id":PARENT_REF["artifact_id"],"content_sha256":PARENT_REF["content_sha256"]}
    envelopes=[]; rows=[]
    for case in cases:
        cid=str(case["case_id"]); bbox=list(case["acceptable_regions"][0]); a,b,c,d=bbox; center=[(a+c)//2,(b+d)//2]
        binding=seal_target_binding(artifact_id=f"binding/{cid}",case_id=cid,candidate_id=f"candidate/{cid}",fusion_ref=ref(f"fusion/{cid}"),capture_ref=ref(f"capture/{cid}"),bbox_ref=ref(f"bbox/{cid}"),bbox=bbox,source_parent_ref=parent)
        envelopes.append(sealed_artifact_envelope(binding))
        request=seal_vista_request(artifact_id=f"request/{cid}",case_id=cid,target_binding_ref=artifact_ref(binding),candidate_id=binding["candidate_id"],fusion_ref=binding["fusion_ref"],capture_ref=binding["capture_ref"],bbox_ref=binding["bbox_ref"],source_parent_ref=parent)
        envelopes.append(sealed_artifact_envelope(request))
        for arm in ("qwen_only","omni_only_discovery","omni_to_qwen","omni_to_qwen_vista"):
            row={"case_id":cid,"arm_id":arm,"selection_status":"selected","eligibility":"ELIGIBLE","target_binding_ref":artifact_ref(binding)}
            if arm in {"omni_to_qwen","omni_to_qwen_vista"}: row["vista_request_ref"]=artifact_ref(request)
            if arm=="omni_to_qwen_vista": row["vista_result"]={"status":"validated","request_ref":artifact_ref(request),"target_binding_ref":artifact_ref(binding),"canonical_capture_pixel_point":center}
            rows.append(row)
    pre={"contract_version":"automatic_prediction_v2","artifact_id":"automatic/task10","prediction_id":"prediction/task10","source_parent_ref":deepcopy(parent),"partition":"holdout","release_id":RELEASE,"rows":rows,"safety":deepcopy(SAFETY)}
    pre_env=seal_automatic_prediction(request_ref=ref("run/task10"),pre_review=pre,execution_refs=[ref("execution/task10")],lifecycle_ref=ref("lifecycle/task10-bootstrap"))["pre_review_artifact"]
    auto_ref=pre_env["ref"]; envelopes.append(pre_env)
    def life(aid:str,attempt:str,partition:str,complete:bool)->dict[str,object]: return artifact("lifecycle_receipt_v2",aid,attempt_id=attempt,release_id=RELEASE,partition=partition,source_parent_ref=deepcopy(parent),automatic_prediction_ref=auto_ref,complete=complete,lifecycle_verified=complete,cleanup_stable_zero=complete)
    hold=life("lifecycle/task10-hold","task10-hold","holdout",True)
    hold_ledger=artifact("regression_attempt_ledger_v2","ledger/task10-hold",release_id=RELEASE,partition="holdout",source_parent_ref=deepcopy(parent),automatic_prediction_ref=auto_ref,entries=[{"sequence":0,"attempt_id":"task10-hold","lifecycle_ref":artifact_ref(hold),"disposition":"complete"}])
    regression=life("lifecycle/task10-regression","task10-regression","regression",True)
    regression_ledger=artifact("regression_attempt_ledger_v2","ledger/task10-regression",release_id=RELEASE,partition="regression",source_parent_ref=deepcopy(parent),automatic_prediction_ref=auto_ref,entries=[{"sequence":0,"attempt_id":"task10-regression","lifecycle_ref":artifact_ref(regression),"disposition":"complete"}])
    precondition=artifact("regression_precondition_receipt_v2","regression/task10-precondition",release_id=RELEASE,partition="regression",source_parent_ref=deepcopy(parent),regression_attempt_ledger_ref=artifact_ref(regression_ledger),selected_attempt_id="task10-regression",selected_lifecycle_ref=artifact_ref(regression),status="PASS")
    run={"contract_version":"benchmark_v2_prediction_run_v2","release_id":RELEASE,"partition":"holdout","source_parent_ref":deepcopy(parent),"automatic_prediction_ref":auto_ref,"attempt_ledger_ref":artifact_ref(hold_ledger),"regression_precondition_ref":artifact_ref(precondition),"lifecycle_ref":artifact_ref(hold),"sealed_artifacts":envelopes,"safety":deepcopy(SAFETY)}
    bundle={"contract_version":"benchmark_v2_lifecycle_bundle_v2","sealed_artifacts":[sealed_artifact_envelope(item) for item in (hold,hold_ledger,regression,regression_ledger,precondition)],"safety":deepcopy(SAFETY)}
    return run,bundle


def _selected_accepted_input(path:Path,provider_cases:list[dict[str,object]],private_cases:list[dict[str,object]],release:dict[str,object],*,partition:str="regression")->None:
    from app.learn.hybrid import benchmark_v2_predictions as predictions
    accepted=json.loads(path.read_text(encoding="utf-8")); run=json.loads(base64.b64decode(accepted["prediction_run_envelope"]["canonical_bytes_b64"],validate=True))
    children=deepcopy(run["sealed_artifact_envelopes"]); automatic_index=next(index for index,envelope in enumerate(children) if json.loads(base64.b64decode(envelope["canonical_bytes_b64"],validate=True)).get("contract_version")=="automatic_prediction_v3")
    automatic=json.loads(base64.b64decode(children[automatic_index]["canonical_bytes_b64"],validate=True))
    provider=sorted((case for case in provider_cases if case["partition"]==partition),key=lambda case:str(case["case_id"]))[0]
    private=next(case for case in private_cases if case["case_id"]==provider["case_id"])
    dependency=next(item for item in automatic["provider_group_dependencies"] if item["provider_group_ref"]["id"]==provider["screen_group"])
    case_ref={"case_id":provider["case_id"],"case_content_sha256":content_sha256(provider)}; actual_ref=dependency["actual_screen_group_ref"]; capture_ref=dependency["capture_ref"]
    nested=[]
    def nested_ref(kind:str)->dict[str,str]:
        item=predictions._nested_evidence(evidence_kind=kind,canonical_value={"case_id":provider["case_id"],"kind":kind},case_ref=case_ref,actual_screen_group_ref=actual_ref); nested.append(item); return pathless_artifact_ref(item)
    qsource=predictions._source_parent(case_ref=case_ref,arm_scope=["qwen_only"],source_kind="incumbent_qwen_action",evidence_refs={"incumbent_response_ref":nested_ref("incumbent_response"),"available_action_ref":nested_ref("available_action")},actual_screen_group_ref=actual_ref,capture_ref=capture_ref)
    osource=predictions._source_parent(case_ref=case_ref,arm_scope=["omni_only_discovery"],source_kind="omni_inventory_item",evidence_refs={"omni_inventory_ref":dependency["omni_inventory_ref"],"omni_item_ref":nested_ref("omni_item")},actual_screen_group_ref=actual_ref,capture_ref=capture_ref)
    hsource=predictions._source_parent(case_ref=case_ref,arm_scope=["omni_to_qwen","omni_to_qwen_vista"],source_kind="hybrid_bound_fusion_candidate",evidence_refs={"omni_inventory_ref":dependency["omni_inventory_ref"],"qwen_bindings_ref":dependency["qwen_bindings_ref"],"fusion_result_ref":dependency["fusion_result_ref"],"fusion_candidate_ref":nested_ref("fusion_candidate")},actual_screen_group_ref=actual_ref,capture_ref=capture_ref)
    bbox=list(private["acceptable_regions"][0]); qarts=predictions._selection_artifacts(case_id=provider["case_id"],arm_scope=["qwen_only"],candidate_id="candidate/scorer-qwen",bbox=bbox,capture_ref=capture_ref,source_parent=qsource); oarts=predictions._selection_artifacts(case_id=provider["case_id"],arm_scope=["omni_only_discovery"],candidate_id="candidate/scorer-omni",bbox=bbox,capture_ref=capture_ref,source_parent=osource); harts=predictions._selection_artifacts(case_id=provider["case_id"],arm_scope=["omni_to_qwen","omni_to_qwen_vista"],candidate_id="candidate/scorer-hybrid",bbox=bbox,capture_ref=capture_ref,source_parent=hsource,submitted_request_ref=dependency["submitted_vista_request_refs"][0])
    selected={"qwen_only":predictions._selected_row(provider["case_id"],"qwen_only",qarts),"omni_only_discovery":predictions._selected_row(provider["case_id"],"omni_only_discovery",oarts),"omni_to_qwen":predictions._selected_row(provider["case_id"],"omni_to_qwen",harts),"omni_to_qwen_vista":predictions._selected_row(provider["case_id"],"omni_to_qwen_vista",harts)}
    a,b,c,d=bbox; selected["omni_to_qwen_vista"]["vista_result"]={"status":"validated","request_ref":selected["omni_to_qwen_vista"]["vista_request_ref"],"target_binding_ref":selected["omni_to_qwen_vista"]["target_binding_ref"],"canonical_capture_pixel_point":[(a+c)//2,(b+d)//2]}
    rows=[selected.get(row["arm_id"],row) if row["case_id"]==provider["case_id"] else row for row in automatic["rows"]]
    changed=predictions._seal_automatic_prediction_v3(benchmark_release_id=automatic["benchmark_release_id"],partition=automatic["partition"],source_parent_ref=automatic["source_parent_ref"],case_arm_multiset_sha256=automatic["case_arm_multiset_sha256"],provider_group_dependencies=automatic["provider_group_dependencies"],rows=rows)
    children[automatic_index]=seal_pathless_envelope(changed)
    children.extend(seal_pathless_envelope(item) for item in [*nested,*qarts,*oarts,*harts])
    children=order_pathless_envelopes(registry_name="prediction_run_v3",envelopes=children,context={})
    semantic={key:deepcopy(value) for key,value in run.items() if key not in {"contract_version","artifact_id","content_sha256"}}; semantic["corpus_parent_ref"]=deepcopy(release["corpus_parent_ref"]); semantic["provider_manifest_ref"]=deepcopy(release["provider_manifest_ref"]); semantic["provider_corpus_ref"]=deepcopy(release["provider_corpus_ref"]); semantic["automatic_prediction_ref"]=pathless_artifact_ref(changed); semantic["sealed_artifact_envelopes"]=children
    changed_run=seal_pathless_projection(contract_version="benchmark_v2_prediction_run_v3",semantic_payload=semantic)
    accepted["corpus_parent_ref"]=deepcopy(release["corpus_parent_ref"]); accepted["provider_manifest_ref"]=deepcopy(release["provider_manifest_ref"]); accepted["provider_corpus_ref"]=deepcopy(release["provider_corpus_ref"]); accepted["automatic_prediction_ref"]=pathless_artifact_ref(changed); accepted["prediction_run_envelope"]=seal_pathless_envelope(changed_run); accepted["content_sha256"]=hashlib.sha256(canonical_bytes({key:value for key,value in accepted.items() if key!="content_sha256"})).hexdigest(); write(path,accepted)


def _remint_pathless_unchecked(value:dict[str,object])->dict[str,object]:
    changed=deepcopy(value); prefix=str(changed["artifact_id"]).split("/",1)[0]; changed.pop("artifact_id"); changed.pop("content_sha256")
    contract=str(changed["contract_version"]); semantic={key:value for key,value in changed.items() if key!="contract_version"}; identity=semantic if contract=="automatic_prediction_v3" else changed
    semantic_sha=hashlib.sha256(contract.encode("utf-8")+b"\0"+canonical_bytes(identity)).hexdigest(); changed={"contract_version":contract,"artifact_id":f"{prefix}/{semantic_sha}",**semantic}; changed["content_sha256"]=hashlib.sha256(canonical_bytes(changed)).hexdigest(); return changed


def _unchecked_envelope(value:dict[str,object])->dict[str,object]:
    raw=canonical_bytes(value); return {"ref":{"id":value["artifact_id"],"content_sha256":value["content_sha256"]},"canonical_bytes_b64":base64.b64encode(raw).decode("ascii")}


def _rewrite_accepted_outer(accepted:dict[str,object],field:str,outer:dict[str,object])->None:
    reminted=_remint_pathless_unchecked(outer); accepted[field]=_unchecked_envelope(reminted)


def _finish_accepted_mutation(path:Path,accepted:dict[str,object])->None:
    accepted["content_sha256"]=hashlib.sha256(canonical_bytes({key:value for key,value in accepted.items() if key!="content_sha256"})).hexdigest(); write(path,accepted)


@pytest.fixture(scope="module")
def task10_release_inputs(tmp_path_factory:pytest.TempPathFactory)->dict[str,Path]:
    helper_path=ROOT/"tests/test_portfolio_hybrid_v1_1_benchmark_v2_seal.py"
    spec=importlib.util.spec_from_file_location("task10_seal_helpers_for_scoring",helper_path); assert spec is not None and spec.loader is not None
    helpers=importlib.util.module_from_spec(spec); spec.loader.exec_module(helpers)
    base=tmp_path_factory.mktemp("task10-real-child"); sealer=helpers._load_sealer()
    repo,private_path,provider_path,_,_=helpers._task10_bundle(base/"release",sealer)
    runner_path=ROOT/"tests/test_portfolio_hybrid_v1_1_benchmark_v2_runner.py"; runner_spec=importlib.util.spec_from_file_location("s3_runner_helpers_for_scoring",runner_path); assert runner_spec is not None and runner_spec.loader is not None
    runner_helpers=importlib.util.module_from_spec(runner_spec); runner_spec.loader.exec_module(runner_helpers)
    patcher=pytest.MonkeyPatch()
    try: runner_helpers.test_materialize_score_input_true_offline_producer_is_deterministic(patcher,base/"accepted")
    finally: patcher.undo()
    accepted_path=base/"accepted"/"accepted-run-ref.json"; provider_manifest=json.loads(provider_path.read_text(encoding="utf-8")); provider_corpus=json.loads((provider_path.parent/provider_manifest["provider_corpus_ref"]["relative_path"]).read_text(encoding="utf-8"))
    from app.learn.hybrid.benchmark_v2_private_release import derive_private_scoring_cases, validate_task10_private_release_bundle
    release=validate_task10_private_release_bundle(private_manifest_path=private_path); private_cases=derive_private_scoring_cases(validated_release=release,partition="regression")
    _selected_accepted_input(accepted_path,provider_corpus["cases"],private_cases,release)
    return {"private":private_path,"accepted":accepted_path,"provider":provider_path,"corpus":provider_path.parent/provider_manifest["provider_corpus_ref"]["relative_path"]}

def files(tmp:Path,private:dict,run:dict,bundle:dict)->dict[str,Path]:
    paths={k:tmp/f"{k}.json" for k in ("private","run","lifecycle","output","public")}
    for k,v in (("private",private),("run",run),("lifecycle",bundle)): write(paths[k],v)
    return paths


def test_s3_private_scorer_public_signature_is_exactly_four_paths() -> None:
    signature = inspect.signature(run_private_scorer)
    assert list(signature.parameters) == [
        "private_manifest_path",
        "prediction_run_ref_path",
        "private_output_path",
        "public_ref_path",
    ]
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in signature.parameters.values()
    )

def execute(tmp:Path,private:dict,run:dict,bundle:dict)->tuple[dict[str,str],dict[str,object],dict[str,object]]:
    rows,cases,gate=scorer_v2._validate(private,run,bundle); score=scorer_v2._score(rows,cases,gate); raw=canonical_bytes(score); result={"status":score["gate"]["status"],"score_ref":f"direct-fixture/{hashlib.sha256(raw).hexdigest()}","content_sha256":hashlib.sha256(raw).hexdigest()}; return result,score,{}

def decode(env:dict[str,object])->dict[str,object]: return json.loads(base64.b64decode(env["canonical_bytes_b64"]))
def reseal(env:dict[str,object],value:dict[str,object])->None: env.update(sealed_artifact_envelope(value))


def test_public_binding_and_request_contracts_reject_private_target_identity() -> None:
    assert "target_id" not in inspect.signature(seal_target_binding).parameters
    assert "target_id" not in inspect.signature(seal_vista_request).parameters
    parent = ref("parent/public-contract")
    binding = seal_target_binding(
        artifact_id="binding/public",
        case_id="opaque/public",
        candidate_id="candidate/public",
        fusion_ref=ref("fusion/public"),
        capture_ref=ref("capture/public"),
        bbox_ref=ref("bbox/public"),
        bbox=[1, 2, 3, 4],
        source_parent_ref=parent,
    )
    request = seal_vista_request(
        artifact_id="request/public",
        case_id="opaque/public",
        target_binding_ref=artifact_ref(binding),
        candidate_id="candidate/public",
        fusion_ref=binding["fusion_ref"],
        capture_ref=binding["capture_ref"],
        bbox_ref=binding["bbox_ref"],
        source_parent_ref=parent,
    )

    assert binding["contract_version"] == "sealed_target_binding_v3"
    assert request["contract_version"] == "sealed_vista_request_v3"
    assert "target_id" not in binding
    assert "target_id" not in request


def test_automatic_prediction_artifacts_reject_legacy_target_identity() -> None:
    _, run, _ = evidence()
    public_artifacts = [decode(envelope) for envelope in run["sealed_artifacts"]]
    serialized = json.dumps(public_artifacts, sort_keys=True)
    assert "target_id" not in serialized
    assert all(marker not in serialized for marker in PRIVATE_TARGET_MARKERS)
    assert all(marker not in serialized for marker in PRIVATE_LABEL_MARKERS)
    assert PRIVATE_SCREEN_GROUP_MARKER not in serialized
    prediction = next(
        item for item in public_artifacts if item["contract_version"] == "automatic_prediction_v2"
    )
    prediction["rows"][0]["target_id"] = PRIVATE_TARGET_MARKERS[0]

    with pytest.raises(ValueError, match="extra fields"):
        seal_automatic_prediction(
            request_ref=ref("request/legacy-rejection"),
            pre_review=prediction,
            execution_refs=[ref("execution/legacy-rejection")],
            lifecycle_ref=ref("lifecycle/legacy-rejection"),
        )


@pytest.mark.parametrize(
    ("bbox", "expected"),
    [
        ([11, 11, 13, 13], True),
        ([31, 11, 33, 13], False),
        ([11, 11, 33, 13], False),
        ([0, 0, 1, 1], False),
    ],
    ids=("unique-correct", "different-target", "multiple-targets", "zero-targets"),
)
def test_private_semantic_correctness_requires_one_matching_target(
    bbox: list[int], expected: bool
) -> None:
    cases = {
        f"opaque/{index}": {
            "case_id": f"opaque/{index}",
            "screen_group": "screen/opaque",
            "important_target": True,
            "acceptable_regions": [[10 + (index - 1) * 20, 10, 14 + (index - 1) * 20, 14]],
        }
        for index in range(1, 6)
    }

    assert scorer_v2._private_unique_target_center_containment(
        case_id="opaque/1",
        bbox=bbox,
        cases=cases,
    ) is expected


@pytest.mark.parametrize("shape", ["four", "six", "singleton_split"])
def test_private_semantic_correctness_rejects_non_five_target_groups(shape: str) -> None:
    count = 4 if shape == "four" else 6 if shape == "six" else 5
    cases = {
        f"opaque/{index}": {
            "case_id": f"opaque/{index}",
            "screen_group": f"screen/{index}" if shape == "singleton_split" else "screen/opaque",
            "important_target": True,
            "acceptable_regions": [[10 + (index - 1) * 20, 10, 14 + (index - 1) * 20, 14]],
        }
        for index in range(1, count + 1)
    }

    with pytest.raises(ValueError, match="five|cardinality"):
        scorer_v2._private_unique_target_center_containment(
            case_id="opaque/1",
            bbox=[11, 11, 13, 13],
            cases=cases,
        )


def test_private_manifest_accepts_only_post_correction_contract(tmp_path: Path) -> None:
    private, run, bundle = evidence()
    private["contract_version"] = "portfolio_hybrid_v1_1_private_manifest_v2_1_synthetic"
    result, _, _ = execute(tmp_path / "corrected", private, run, bundle)
    assert result["status"] == "PASS"

    private["contract_version"] = "portfolio_hybrid_v1_1_private_manifest_v2_synthetic"
    with pytest.raises(ValueError):
        execute(tmp_path / "legacy", private, run, bundle)


def test_production_launcher_rejects_canonical_synthetic_manifest_without_outputs(tmp_path: Path) -> None:
    private, run, bundle = evidence()
    paths = files(tmp_path, private, run, bundle)
    with pytest.raises(ValueError, match="failed closed"):
        run_private_scorer(
            private_manifest_path=paths["private"],
            prediction_run_ref_path=paths["run"],
            private_output_path=paths["output"],
            public_ref_path=paths["public"],
        )
    assert not paths["output"].exists()
    assert not paths["public"].exists()


def test_real_task10_bundle_traverses_isolated_child_without_private_leakage(
    tmp_path: Path, task10_release_inputs: dict[str, Path]
) -> None:
    private_output=tmp_path/"private-score.json"; public_output=tmp_path/"public-ref.json"
    result=run_private_scorer(
        private_manifest_path=task10_release_inputs["private"],
        prediction_run_ref_path=task10_release_inputs["accepted"],
        private_output_path=private_output,
        public_ref_path=public_output,
    )
    assert set(result)=={"status","score_ref","content_sha256"}
    assert private_output.is_file() and public_output.is_file()
    public_text=public_output.read_text(encoding="utf-8")
    assert "target_id" not in public_text and "acceptable_regions" not in public_text
    assert "gold.v1.json" not in public_text and "artifact_inventory" not in public_text
    assert str(task10_release_inputs["private"]) not in public_text and str(task10_release_inputs["accepted"]) not in public_text
    private_score=json.loads(private_output.read_text(encoding="utf-8")); public=json.loads(public_text); launch=json.loads(base64.b64decode(public["launch_receipt"]["canonical_bytes_b64"],validate=True))
    binding=private_score["score_input_binding"]
    assert set(binding)=={"contract_version","benchmark_release_id","partition","private_manifest_ref","corpus_parent_ref","provider_manifest_ref","provider_corpus_ref","accepted_run_ref","attempt_ref","attempt_ledger_ref","automatic_prediction_ref","selected_lifecycle_ref","estimand_ref","gate_ref","safety"}
    assert binding==launch["score_input_binding"]==public["binding"]["score_input_binding"]==public["score_input_binding"]
    assert private_score["contract_version"]=="portfolio_hybrid_v1_1_private_score_v3" and public["contract_version"]=="private_scorer_public_ref_v3"


def test_s3_public_cli_uses_exact_four_flags_and_one_compact_projection(tmp_path:Path,task10_release_inputs:dict[str,Path])->None:
    output=tmp_path/"cli-private.json"; public=tmp_path/"cli-public.json"
    command=[str(Path(getattr(sys,"_base_executable",sys.executable)).resolve()),str(SCRIPT),"--private-manifest",str(task10_release_inputs["private"]),"--prediction-run-ref",str(task10_release_inputs["accepted"]),"--private-output",str(output),"--public-ref-output",str(public)]
    completed=subprocess.run(command,cwd=tmp_path,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="utf-8",close_fds=True,check=False)
    assert completed.returncode==0 and completed.stderr==""
    projection=json.loads(completed.stdout)
    assert completed.stdout==json.dumps(projection,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n"
    assert list(sorted(projection))==["content_sha256","score_ref","status"] and output.is_file() and public.is_file()


@pytest.mark.parametrize("extra",[["--lifecycle","x"],["--provider-manifest","x"],["--corpus","x"],["--Gold","x"],["--authorization","x"],["--claim","x"]])
def test_s3_cli_rejects_forbidden_path_authorities(extra:list[str],tmp_path:Path)->None:
    command=[str(Path(getattr(sys,"_base_executable",sys.executable)).resolve()),str(SCRIPT),"--private-manifest","p","--prediction-run-ref","r","--private-output","o","--public-ref-output","u",*extra]
    completed=subprocess.run(command,cwd=tmp_path,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="utf-8",close_fds=True,check=False)
    assert completed.returncode==2 and completed.stdout==""


def test_s3_cli_rejects_missing_mixed_and_duplicate_modes(tmp_path:Path)->None:
    python=str(Path(getattr(sys,"_base_executable",sys.executable)).resolve()); base=[python,str(SCRIPT)]
    commands=[base+["--private-manifest","p"],base+["--closed-launch-handle","1","--private-manifest","p","--prediction-run-ref","r","--private-output","o","--public-ref-output","u"],base+["--private-manifest","p","--private-manifest","q","--prediction-run-ref","r","--private-output","o","--public-ref-output","u"]]
    for command in commands:
        completed=subprocess.run(command,cwd=tmp_path,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="utf-8",close_fds=True,check=False)
        assert completed.returncode==2 and completed.stdout==""


def test_s3_cli_rejects_every_flag_prefix_and_abbreviated_duplicate(tmp_path:Path)->None:
    python=str(Path(getattr(sys,"_base_executable",sys.executable)).resolve()); base=[python,str(SCRIPT)]
    flags=("--private-manifest","--prediction-run-ref","--private-output","--public-ref-output","--closed-launch-handle")
    prefixes=[(flag,flag[:length]) for flag in flags for length in range(3,len(flag))]
    failures=[]
    for flag,prefix in prefixes:
        for command in (base+[prefix,"1"],base+[flag,"1",prefix,"2"]):
            completed=subprocess.run(command,cwd=tmp_path,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="utf-8",close_fds=True,check=False)
            if completed.returncode!=2 or completed.stdout!="" or "unrecognized arguments" not in completed.stderr:
                failures.append((flag,prefix,completed.returncode,completed.stdout,completed.stderr))
    assert failures==[]


@pytest.mark.parametrize("mutation",["legacy_contract","selected_lifecycle_substitution"])
def test_s3_production_child_rejects_old_or_substituted_accepted_authority(mutation:str,tmp_path:Path,task10_release_inputs:dict[str,Path])->None:
    accepted=json.loads(task10_release_inputs["accepted"].read_text(encoding="utf-8"))
    if mutation=="legacy_contract": accepted["contract_version"]="benchmark_v2_accepted_regression_score_input_v1"
    else:
        lifecycle=json.loads(base64.b64decode(accepted["lifecycle_bundle_envelope"]["canonical_bytes_b64"],validate=True))
        alternate=next(envelope["ref"] for envelope in lifecycle["sealed_artifact_envelopes"] if envelope["ref"]!=accepted["selected_lifecycle_ref"] and envelope["ref"]["id"].startswith("verified-lifecycle/"))
        accepted["selected_lifecycle_ref"]=alternate
    accepted["content_sha256"]=hashlib.sha256(canonical_bytes({key:value for key,value in accepted.items() if key!="content_sha256"})).hexdigest(); accepted_path=tmp_path/"accepted-mutated.json"; write(accepted_path,accepted)
    private_output=tmp_path/"private.json"; public_output=tmp_path/"public.json"
    with pytest.raises(ValueError,match="failed closed"):
        run_private_scorer(private_manifest_path=task10_release_inputs["private"],prediction_run_ref_path=accepted_path,private_output_path=private_output,public_ref_path=public_output)
    assert not private_output.exists() and not public_output.exists()


@pytest.mark.parametrize("mutation",["missing_referenced_lifecycle_with_orphan","semantic_invalid_lifecycle","closure_order"])
def test_s3_isolated_child_rejects_non_recursive_accepted_closure_mutations(mutation:str,tmp_path:Path,task10_release_inputs:dict[str,Path])->None:
    accepted=json.loads(task10_release_inputs["accepted"].read_text(encoding="utf-8")); lifecycle=json.loads(base64.b64decode(accepted["lifecycle_bundle_envelope"]["canonical_bytes_b64"],validate=True)); children=deepcopy(lifecycle["sealed_artifact_envelopes"])
    if mutation=="closure_order":
        children[0],children[1]=children[1],children[0]
    else:
        target_ref=lifecycle["screen_group_lifecycle_projection_refs"][0]; index=next(i for i,envelope in enumerate(children) if envelope["ref"]==target_ref); target=json.loads(base64.b64decode(children[index]["canonical_bytes_b64"],validate=True))
        target["raw_evidence_sha256"]="f"*64
        if mutation=="semantic_invalid_lifecycle": target["terminal_status"]="FORGED"
        children[index]=_unchecked_envelope(_remint_pathless_unchecked(target))
    lifecycle["sealed_artifact_envelopes"]=children; _rewrite_accepted_outer(accepted,"lifecycle_bundle_envelope",lifecycle); path=tmp_path/f"{mutation}.json"; _finish_accepted_mutation(path,accepted)
    private_output=tmp_path/f"{mutation}-private.json"; public_output=tmp_path/f"{mutation}-public.json"
    with pytest.raises(ValueError,match="failed closed"):
        run_private_scorer(private_manifest_path=task10_release_inputs["private"],prediction_run_ref_path=path,private_output_path=private_output,public_ref_path=public_output)
    assert not private_output.exists() and not public_output.exists()


def test_s3_isolated_child_rejects_later_complete_attempt_substitution(tmp_path:Path,task10_release_inputs:dict[str,Path])->None:
    accepted=json.loads(task10_release_inputs["accepted"].read_text(encoding="utf-8")); replacement_ref=None; replacement_env=None
    outers={}
    for field in ("prediction_run_envelope","lifecycle_bundle_envelope"):
        outer=json.loads(base64.b64decode(accepted[field]["canonical_bytes_b64"],validate=True)); children=deepcopy(outer["sealed_artifact_envelopes"]); index=next(i for i,envelope in enumerate(children) if envelope["ref"]==accepted["attempt_ledger_ref"]); ledger=json.loads(base64.b64decode(children[index]["canonical_bytes_b64"],validate=True)); selected=deepcopy(ledger["entries"][0]); prior=deepcopy(selected); prior.update({"sequence":0,"attempt_ref":{"id":"runner-attempt/prior-complete","content_sha256":"d"*64},"selection_eligible":False,"lifecycle_ref":None,"event_projection_refs":[selected["event_projection_refs"][0]],"observed_state":"result"}); selected["sequence"]=1; ledger["entries"]=[prior,selected]
        reminted=_remint_pathless_unchecked(ledger); envelope=_unchecked_envelope(reminted)
        if replacement_ref is None: replacement_ref=envelope["ref"]; replacement_env=envelope
        else: assert envelope==replacement_env
        children[index]=envelope; outer["projected_attempt_ledger_ref"]=replacement_ref; outer["sealed_artifact_envelopes"]=children; outers[field]=outer
    accepted["attempt_ledger_ref"]=replacement_ref
    for field,outer in outers.items(): _rewrite_accepted_outer(accepted,field,outer)
    path=tmp_path/"later-complete.json"; _finish_accepted_mutation(path,accepted); private_output=tmp_path/"later-private.json"; public_output=tmp_path/"later-public.json"
    with pytest.raises(ValueError,match="failed closed"):
        run_private_scorer(private_manifest_path=task10_release_inputs["private"],prediction_run_ref_path=path,private_output_path=private_output,public_ref_path=public_output)
    assert not private_output.exists() and not public_output.exists()


@pytest.mark.parametrize("mutation", ["four", "six", "singleton_split", "duplicate_case", "invalid_region"])
def test_private_manifest_rejects_invalid_screen_group_cardinality(
    tmp_path: Path, mutation: str
) -> None:
    private, run, bundle = evidence()
    cases = private["cases"]
    if mutation == "four":
        cases.pop()
    elif mutation == "six":
        cases.append(
            {
                "case_id": "opaque/6",
                "screen_group": "screen/opaque",
                "important_target": True,
                "acceptable_regions": [[110, 10, 114, 14]],
            }
        )
    elif mutation == "singleton_split":
        cases[0]["screen_group"] = "screen/singleton"
    elif mutation == "duplicate_case":
        cases.append(deepcopy(cases[0]))
    else:
        cases[-1]["acceptable_regions"] = [[110, 10, 110, 14]]

    with pytest.raises(ValueError):
        execute(tmp_path / mutation, private, run, bundle)

def test_sealed_evidence_scores_exact_pair_and_stdout_ref(tmp_path:Path)->None:
    private,run,bundle=evidence(); result,score,public=execute(tmp_path,private,run,bundle)
    assert set(result)=={"status","score_ref","content_sha256"}; assert result["status"]=="PASS"; assert public=={}
    assert score["automatic"]["arm_metrics"]["omni_to_qwen_vista"]["semantic_precision"]=="1/1"
    assert score["automatic"]["wrong_target_count"]==0
    assert score["point_metric"]=={"gain_numerator":1,"submitted_count":5,"gain":"1/5"}; assert "opaque/" not in json.dumps(public)
    assert all(marker not in json.dumps(public) for marker in PRIVATE_TARGET_MARKERS)
    assert all(marker not in json.dumps(public) for marker in PRIVATE_LABEL_MARKERS)
    assert PRIVATE_SCREEN_GROUP_MARKER not in json.dumps(public)

def test_pre_review_requires_external_anchor_and_noop_is_stable()->None:
    private,run,bundle=evidence(); env=next(x for x in run["sealed_artifacts"] if x["ref"]==run["automatic_prediction_ref"]); raw=base64.b64decode(env["canonical_bytes_b64"])
    sealed=seal_automatic_prediction(request_ref=ref("r"),pre_review=decode(env),execution_refs=[ref("e")],lifecycle_ref=ref("l")); record=sealed["record"]
    decision=seal_review_decision(predecessor_ref=record["revision_ref"],target_binding_ref=next(r["target_binding_ref"] for r in decode(env)["rows"] if r["selection_status"]=="selected"),disposition="corrected",replacement_candidate_id="reviewed")
    revised=append_review_decisions(record,[decision],pre_review_artifact_bytes=raw,expected_pre_review_ref=env["ref"],expected_record_ref=sealed["record_ref"])
    assert canonical_bytes(append_review_decisions(revised,[decision],pre_review_artifact_bytes=raw,expected_pre_review_ref=env["ref"],expected_record_ref=prediction_record_ref(revised)))==canonical_bytes(revised)
    reminted=deepcopy(raw); changed=json.loads(reminted); changed["rows"][0]["failure_reason"]="rewrite" if "failure_reason" in changed["rows"][0] else None
    with pytest.raises(ValueError): append_review_decisions(record,[],pre_review_artifact_bytes=canonical_bytes(changed),expected_pre_review_ref=env["ref"],expected_record_ref=sealed["record_ref"])

def test_existing_review_chain_is_rebuilt_from_external_attempt_anchor()->None:
    _,run,_=evidence(); env=next(x for x in run["sealed_artifacts"] if x["ref"]==run["automatic_prediction_ref"]); raw=base64.b64decode(env["canonical_bytes_b64"])
    sealed=seal_automatic_prediction(request_ref=ref("r"),pre_review=decode(env),execution_refs=[ref("e")],lifecycle_ref=ref("l")); record=sealed["record"]
    decision=seal_review_decision(predecessor_ref=record["revision_ref"],target_binding_ref=next(r["target_binding_ref"] for r in decode(env)["rows"] if r["selection_status"]=="selected"),disposition="corrected",replacement_candidate_id="reviewed")
    revised=append_review_decisions(record,[decision],pre_review_artifact_bytes=raw,expected_pre_review_ref=env["ref"],expected_record_ref=sealed["record_ref"])
    forged_decision=seal_review_decision(predecessor_ref=record["revision_ref"],target_binding_ref=decision["target_binding_ref"],disposition="corrected",replacement_candidate_id="reminted")
    forged=append_review_decisions(record,[forged_decision],pre_review_artifact_bytes=raw,expected_pre_review_ref=env["ref"],expected_record_ref=sealed["record_ref"])
    with pytest.raises(ValueError,match="anchor"):
        append_review_decisions(forged,[],pre_review_artifact_bytes=raw,expected_pre_review_ref=env["ref"],expected_record_ref=prediction_record_ref(revised))

@pytest.mark.parametrize("mutation",["decision_id","decision_type","nonmember","content_sha256","semantics"])
def test_new_review_decision_is_closed_before_append_mutation(mutation:str)->None:
    _,run,_=evidence(); env=next(x for x in run["sealed_artifacts"] if x["ref"]==run["automatic_prediction_ref"]); raw=base64.b64decode(env["canonical_bytes_b64"])
    sealed=seal_automatic_prediction(request_ref=ref("r"),pre_review=decode(env),execution_refs=[ref("e")],lifecycle_ref=ref("l")); record=sealed["record"]
    binding=next(r["target_binding_ref"] for r in decode(env)["rows"] if r["selection_status"]=="selected")
    decision=seal_review_decision(predecessor_ref=record["revision_ref"],target_binding_ref=binding,disposition="corrected",replacement_candidate_id="reviewed")
    if mutation=="decision_id": decision["decision_id"]="not-content-addressed"
    elif mutation=="decision_type": decision["decision_type"]="arbitrary"
    elif mutation=="nonmember": decision=seal_review_decision(predecessor_ref=record["revision_ref"],target_binding_ref=ref("binding/not-selected"),disposition="corrected",replacement_candidate_id="reviewed")
    elif mutation=="content_sha256": decision["content_sha256"]="0"*64
    else: decision["disposition"]="accepted"
    before=canonical_bytes(record)
    with pytest.raises(ValueError,match="decision"):
        append_review_decisions(record,[decision],pre_review_artifact_bytes=raw,expected_pre_review_ref=env["ref"],expected_record_ref=sealed["record_ref"])
    assert canonical_bytes(record)==before

def test_append_postcondition_revalidates_derived_record(monkeypatch:pytest.MonkeyPatch)->None:
    import app.learn.hybrid.benchmark_v2_predictions as predictions
    _,run,_=evidence(); env=next(x for x in run["sealed_artifacts"] if x["ref"]==run["automatic_prediction_ref"]); raw=base64.b64decode(env["canonical_bytes_b64"])
    sealed=seal_automatic_prediction(request_ref=ref("r"),pre_review=decode(env),execution_refs=[ref("e")],lifecycle_ref=ref("l")); record=sealed["record"]
    decision=seal_review_decision(predecessor_ref=record["revision_ref"],target_binding_ref=next(r["target_binding_ref"] for r in decode(env)["rows"] if r["selection_status"]=="selected"),disposition="corrected",replacement_candidate_id="reviewed")
    original=predictions._advance_review_record; calls={"count":0}
    def corrupt(value:dict[str,object],item:dict[str,object],expected:dict[str,str])->None:
        original(value,item,expected); calls["count"]+=1
        if calls["count"]==1: value["revision_ref"]["content_sha256"]="0"*64
    monkeypatch.setattr(predictions,"_advance_review_record",corrupt)
    with pytest.raises(ValueError,match="derived state"):
        append_review_decisions(record,[decision],pre_review_artifact_bytes=raw,expected_pre_review_ref=env["ref"],expected_record_ref=sealed["record_ref"])

@pytest.mark.parametrize("pair_mode",["baseline_missing","vista_missing","binding_mismatch","reason_mismatch"])
def test_independently_anchored_partial_pair_fails_closed(tmp_path:Path,pair_mode:str)->None:
    private,run,bundle=evidence(pair_mode=pair_mode)
    with pytest.raises(ValueError): execute(tmp_path,private,run,bundle)

@pytest.mark.parametrize("mutation",["handcrafted","missing_parent","binding_wrong_id","cross_case_request","legacy_request_target_id","legacy_binding_target_id","later_cherry_pick","lifecycle_hash","regression_self_pass","gate_ref"])
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
        elif mutation in {"cross_case_request","legacy_request_target_id"}:
            req=next(x for x in run["sealed_artifacts"] if x["ref"]==row["vista_request_ref"]); q=decode(req); q["case_id"]="opaque/2" if mutation=="cross_case_request" else q["case_id"]; q.update({"target_id":"target/legacy"} if mutation=="legacy_request_target_id" else {}); reseal(req,q); row["vista_request_ref"]=req["ref"]; row["vista_result"]["request_ref"]=req["ref"]
        else:
            binding=next(x for x in run["sealed_artifacts"] if x["ref"]==row["target_binding_ref"]); b=decode(binding); b["target_id"]="target/legacy"; reseal(binding,b); row["target_binding_ref"]=binding["ref"]; row["vista_result"]["target_binding_ref"]=binding["ref"]
        reseal(auto,value); run["automatic_prediction_ref"]=auto["ref"]
    with pytest.raises(ValueError,match="failed closed|invalid|mismatch|differs|missing|wrong|cherry|lineage|artifact|closed"):
        execute(tmp_path,private,run,bundle)

def test_selection_status_estimands_and_zero_selected_fail(tmp_path:Path)->None:
    private,run,bundle=evidence(missing_qwen=True); _,score,_=execute(tmp_path,private,run,bundle)
    qwen=score["automatic"]["arm_metrics"]["qwen_only"]; assert qwen["coverage"]=="4/5"; assert qwen["semantic_precision"]=="1/1"
    private,run,bundle=evidence(all_missing_qwen=True)
    with pytest.raises(ValueError): execute(tmp_path/"all",private,run,bundle)

def test_first_verified_regression_and_automatic_human_boundary(tmp_path:Path)->None:
    private,run,bundle=evidence(); auto=next(x for x in run["sealed_artifacts"] if x["ref"]==run["automatic_prediction_ref"]); value=decode(auto); row=next(r for r in value["rows"] if r["case_id"]=="opaque/1" and r["arm_id"]=="omni_to_qwen_vista"); wrong=next(x for x in run["sealed_artifacts"] if x["ref"]["id"]=="binding-wrong/opaque/1"); row["target_binding_ref"]=wrong["ref"]; row["vista_result"]["target_binding_ref"]=wrong["ref"]; reseal(auto,value); run["automatic_prediction_ref"]=auto["ref"]
    # private independently pins original automatic ref, so reminting all run-side automatic bytes cannot hide the error
    with pytest.raises(ValueError): execute(tmp_path,private,run,bundle)

def test_direct_cli_cannot_forge_child_authority_and_redacts(tmp_path:Path)->None:
    private,run,bundle=evidence(); p=files(tmp_path,private,run,bundle); envelope={"private_manifest_path":str(p["private"]),"prediction_run_path":str(p["run"]),"lifecycle_path":str(p["lifecycle"]),"private_output_path":str(p["output"]),"public_ref_path":str(p["public"])}
    child_env={"SYSTEMROOT":os.environ["SYSTEMROOT"],"PYTHONIOENCODING":"utf-8","PYTHONUTF8":"1","BENCHMARK_V2_SCORER_CHILD_CAPABILITY":"forged-matching-token"}
    proc=subprocess.run([str(Path(getattr(sys,"_base_executable",sys.executable)).resolve()),str(SCRIPT),"--closed-launch-handle","12345"],cwd=tmp_path,env=child_env,input=json.dumps(envelope,separators=(",",":")),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="utf-8",close_fds=True)
    assert proc.returncode!=0 and str(tmp_path) not in proc.stderr and "opaque" not in proc.stderr

@pytest.mark.parametrize("mutation",["inherited_file","wrong_cwd","wrong_env","no_job"])
def test_real_nonproduction_launcher_without_exact_os_boundary_fails(tmp_path:Path,mutation:str)->None:
    import msvcrt
    from app.learn.hybrid.benchmark_scorer_v2 import _ScorerJob, _process_identity
    python=Path(getattr(sys,"_base_executable",sys.executable)).resolve(); operation=tmp_path/f"operation-{mutation}"; operation.mkdir()
    env={"SYSTEMROOT":os.environ["SYSTEMROOT"],"PYTHONIOENCODING":"utf-8","PYTHONUTF8":"1"}
    if mutation=="wrong_env": env["EXTRA_FORBIDDEN"]="1"
    job=_ScorerJob(); process=None; read_fd=write_fd=-1
    try:
        if mutation=="inherited_file":
            read_fd=os.open(tmp_path/"not-a-pipe.bin",os.O_CREAT|os.O_RDONLY); handle=msvcrt.get_osfhandle(read_fd)
        else:
            read_fd,write_fd=os.pipe(); handle=msvcrt.get_osfhandle(read_fd)
        os.set_handle_inheritable(handle,True); startup=subprocess.STARTUPINFO(); startup.lpAttributeList={"handle_list":[handle]}
        argv=[str(python),str(SCRIPT),"--closed-launch-handle",str(handle)]
        if mutation=="wrong_cwd": (operation/"unexpected.txt").write_text("not empty",encoding="utf-8")
        process=subprocess.Popen(argv,executable=str(python),cwd=operation,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="utf-8",close_fds=True,startupinfo=startup)
        os.close(read_fd); read_fd=-1
        if mutation!="no_job" and mutation!="inherited_file": job.assign(process)
        if mutation!="inherited_file":
            parent=os.getpid(); envelope={"private_manifest_path":str(tmp_path/"private"),"prediction_run_ref_path":str(tmp_path/"run"),"private_output_path":str(tmp_path/"out"),"public_ref_path":str(tmp_path/"public"),"nonce":"a"*64,"pipe_capability":"b"*64,"launcher_process_id":parent,"launcher_process_identity":_process_identity(parent),"expected_process_id":process.pid,"expected_process_identity":_process_identity(process.pid),"job_name":job.name,"job_identity_sha256":job.identity_sha256,"expected_argv_sha256":hashlib.sha256(canonical_bytes([str(SCRIPT),"--closed-launch-handle",str(handle)])).hexdigest(),"expected_env_sha256":hashlib.sha256(canonical_bytes(env)).hexdigest(),"expected_cwd_sha256":hashlib.sha256(canonical_bytes(str(operation.resolve()))).hexdigest(),"expected_executable":str(python)}
            os.write(write_fd,canonical_bytes(envelope)); os.close(write_fd); write_fd=-1
        stdout,stderr=process.communicate(timeout=10)
        assert process.returncode!=0 and "opaque" not in stderr and not (tmp_path/"out").exists()
    finally:
        for fd in (read_fd,write_fd):
            if fd>=0:
                try: os.close(fd)
                except OSError: pass
        if process is not None:
            if process.poll() is None: process.kill()
            process.wait(timeout=10)
            for stream in (process.stdout,process.stderr):
                if stream is not None: stream.close()
        job.close()

def test_gate_release_and_import_graph_are_closed()->None:
    gate=json.loads(GATE.read_text()); assert gate["contract_version"]=="portfolio_hybrid_v1_1_automatic_gate_v2" and gate["benchmark_release_id"]==RELEASE and gate["safety"]==SAFETY
    tree=ast.parse((ROOT/"app/learn/hybrid/benchmark_v2_predictions.py").read_text(encoding="utf-8")); imports={n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)}; assert "app.learn.hybrid.benchmark_scorer_v2" not in imports
    assert "click_point" not in GATE.read_text().casefold()


def test_scorer_consumes_shared_task10_authority_only_inside_private_child() -> None:
    source = (ROOT / "app/learn/hybrid/benchmark_scorer_v2.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert "app.learn.hybrid.benchmark_v2_private_release" in imports
    assert "scripts.seal_portfolio_hybrid_v1_1_benchmark_v2" not in imports

    callers = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        called = {
            child.func.id
            for child in ast.walk(node)
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
        }
        if "derive_private_scoring_cases" in called:
            callers[node.name] = called
    assert set(callers) == {"_run_private_child_once"}

def test_same_threshold_alternate_gate_ref_is_rejected(tmp_path:Path)->None:
    private,run,bundle=evidence(); alternate=json.loads(GATE.read_text()); alternate["benchmark_release_id"]="alternate-release"; alternate_path=tmp_path/"alternate-gate.json"; alternate_path.write_text(json.dumps(alternate),encoding="utf-8")
    raw=alternate_path.read_bytes(); private["gate_ref"]={"relative_path":"alternate-gate.json","file_sha256":hashlib.sha256(raw).hexdigest(),"content_sha256":hashlib.sha256(canonical_bytes(alternate)).hexdigest(),"contract_version":alternate["contract_version"],"release_id":alternate["benchmark_release_id"]}
    with pytest.raises(ValueError): execute(tmp_path/"run",private,run,bundle)

def test_private_loader_direct_call_is_child_only(tmp_path:Path,monkeypatch:pytest.MonkeyPatch)->None:
    monkeypatch.setenv("BENCHMARK_V2_SCORER_CHILD_CAPABILITY","forged-matching-token")
    with pytest.raises(PermissionError,match="child-only"):
        _score_private_child(child_capability="forged-matching-token",private_manifest_path=tmp_path/"private",prediction_run_path=tmp_path/"run",lifecycle_path=tmp_path/"life",private_output_path=tmp_path/"out",public_ref_path=tmp_path/"public")

def test_true_child_entry_rejects_matching_self_identity(tmp_path:Path)->None:
    from app.learn.hybrid.benchmark_scorer_v2 import _process_identity, execute_closed_child_envelope
    import msvcrt
    pid=os.getpid(); identity=_process_identity(pid)
    envelope={"private_manifest_path":str(tmp_path/"private"),"prediction_run_ref_path":str(tmp_path/"run"),"private_output_path":str(tmp_path/"out"),"public_ref_path":str(tmp_path/"public"),"nonce":"a"*64,"pipe_capability":"b"*64,"launcher_process_id":pid,"launcher_process_identity":identity,"expected_process_id":pid,"expected_process_identity":identity,"job_name":"self-job","job_identity_sha256":"0"*64,"expected_argv_sha256":"0"*64,"expected_env_sha256":"0"*64,"expected_cwd_sha256":"0"*64,"expected_executable":str(Path(sys.executable).resolve())}
    read_fd,write_fd=os.pipe(); handle=msvcrt.get_osfhandle(read_fd); os.write(write_fd,canonical_bytes(envelope)); os.close(write_fd)
    with pytest.raises(PermissionError,match="launcher binding"):
        execute_closed_child_envelope(handle)
    try: os.close(read_fd)
    except OSError: pass
    assert not any(path.exists() for path in (tmp_path/"out",tmp_path/"public"))

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

def test_spawner_hides_private_paths_and_uses_fresh_empty_cwd(tmp_path:Path,monkeypatch:pytest.MonkeyPatch,task10_release_inputs:dict[str,Path])->None:
    import app.learn.hybrid.benchmark_scorer_v2 as scorer
    p={**task10_release_inputs,"output":tmp_path/"output.json","public":tmp_path/"public.json"}; observed={}; original=scorer.subprocess.Popen
    def capture(*args:object,**kwargs:object):
        observed.update({"args":deepcopy(args),"env":deepcopy(kwargs["env"]),"cwd":Path(kwargs["cwd"]),"initial":list(Path(kwargs["cwd"]).iterdir()),"stdin":kwargs["stdin"],"handles":list(kwargs["startupinfo"].lpAttributeList["handle_list"])})
        process=original(*args,**kwargs); observed["child_pid"]=process.pid; return process
    monkeypatch.setattr(scorer.subprocess,"Popen",capture)
    result=run_private_scorer(private_manifest_path=p["private"],prediction_run_ref_path=p["accepted"],private_output_path=p["output"],public_ref_path=p["public"])
    projection=json.dumps({"args":observed["args"],"env":observed["env"],"cwd":str(observed["cwd"])},default=str)
    assert set(result)=={"status","score_ref","content_sha256"} and observed["initial"]==[] and observed["stdin"]==subprocess.DEVNULL and len(observed["handles"])==1
    assert str(tmp_path) not in projection and "opaque/" not in projection and "BENCHMARK_V2_SCORER_CHILD_CAPABILITY" not in observed["env"]
    public=json.loads(p["public"].read_text()); launch=json.loads(base64.b64decode(public["launch_receipt"]["canonical_bytes_b64"])); cleanup=json.loads(base64.b64decode(public["cleanup_receipt"]["canonical_bytes_b64"]))
    assert launch["child_process_id"]==observed["child_pid"] and launch["launcher_process_id"]==os.getpid() and launch["child_process_id"]!=launch["launcher_process_id"]
    assert len(launch["pipe_capability_sha256"])==64 and cleanup["job_stable_zero"] is True and public["binding"]["launch_receipt_ref"]==public["launch_receipt"]["ref"]
    expected_python=Path(getattr(sys,"_base_executable",sys.executable)).resolve()
    assert Path(observed["args"][0][0]).resolve()==expected_python

@pytest.mark.parametrize("mutation",["launch_bytes","cleanup_semantics","binding_ref","final_digest"])
def test_downstream_requires_exact_production_launch_cleanup_chain(tmp_path:Path,mutation:str,task10_release_inputs:dict[str,Path])->None:
    from app.learn.hybrid.benchmark_scorer_v2 import _sealed_receipt, validate_private_scorer_public_ref
    output=tmp_path/"score.json"; public_path=tmp_path/"public.json"
    run_private_scorer(private_manifest_path=task10_release_inputs["private"],prediction_run_ref_path=task10_release_inputs["accepted"],private_output_path=output,public_ref_path=public_path)
    public=json.loads(public_path.read_text(encoding="utf-8")); changed=deepcopy(public)
    if mutation=="launch_bytes": changed["launch_receipt"]["canonical_bytes_b64"]="AA=="
    elif mutation=="cleanup_semantics":
        cleanup=json.loads(base64.b64decode(changed["cleanup_receipt"]["canonical_bytes_b64"])); cleanup["job_stable_zero"]=False; changed["cleanup_receipt"]=_sealed_receipt(cleanup,"private-scorer-cleanup"); changed["binding"]["cleanup_receipt_ref"]=changed["cleanup_receipt"]["ref"]
    elif mutation=="binding_ref": changed["binding"]["launch_receipt_ref"]={"id":"wrong","content_sha256":"0"*64}
    else: changed["content_sha256"]="0"*64
    with pytest.raises(ValueError,match="scorer"):
        validate_private_scorer_public_ref(changed)


@pytest.mark.parametrize("mutation",["status","gold_value","private_value","absolute_path","error_value","non_path_field"])
def test_s3_public_v3_rejects_fully_reminted_status_or_recursive_leakage(tmp_path:Path,mutation:str,task10_release_inputs:dict[str,Path])->None:
    from app.learn.hybrid.benchmark_scorer_v2 import _content_bound, _sealed_receipt, validate_private_scorer_public_ref
    output=tmp_path/"score.json"; public_path=tmp_path/"public.json"
    run_private_scorer(private_manifest_path=task10_release_inputs["private"],prediction_run_ref_path=task10_release_inputs["accepted"],private_output_path=output,public_ref_path=public_path)
    public=json.loads(public_path.read_text(encoding="utf-8")); assert validate_private_scorer_public_ref(public)["score_ref"].startswith("private-score-final/")
    launch=json.loads(base64.b64decode(public["launch_receipt"]["canonical_bytes_b64"],validate=True)); cleanup=json.loads(base64.b64decode(public["cleanup_receipt"]["canonical_bytes_b64"],validate=True)); binding=deepcopy(public["score_input_binding"]); child=deepcopy(public["binding"]["child_score_ref"]); assert child["score_ref"].startswith("private-score/")
    if mutation=="status":
        child["status"]="FORGED"; public["status"]="FORGED"
    elif mutation=="non_path_field": launch["launcher_process_identity"]="private/evidence.json"
    else:
        binding["provider_manifest_ref"]["relative_path"]={"gold_value":"gold.v1.json","private_value":"private/evidence.json","absolute_path":r"C:\private\gold.json","error_value":"errors/provider-sensitive.txt"}[mutation]
    launch["child_score_ref"]=deepcopy(child); launch["score_input_binding"]=deepcopy(binding); launch=_content_bound({key:value for key,value in launch.items() if key!="content_sha256"}); launch_env=_sealed_receipt(launch,"private-scorer-launch")
    cleanup["launch_receipt_ref"]=deepcopy(launch_env["ref"]); cleanup_env=_sealed_receipt(cleanup,"private-scorer-cleanup")
    final_binding=_content_bound({"contract_version":"private_scorer_final_binding_v2","child_score_ref":deepcopy(child),"score_input_binding":deepcopy(binding),"launch_receipt_ref":deepcopy(launch_env["ref"]),"cleanup_receipt_ref":deepcopy(cleanup_env["ref"]),"safety":deepcopy(SAFETY)})
    reminted=_content_bound({"contract_version":"private_scorer_public_ref_v3","status":public["status"],"score_ref":f"private-score-final/{final_binding['content_sha256']}","score_input_binding":deepcopy(binding),"binding":final_binding,"launch_receipt":launch_env,"cleanup_receipt":cleanup_env,"safety":deepcopy(SAFETY)})
    with pytest.raises(ValueError,match="scorer"):
        validate_private_scorer_public_ref(reminted)


def test_public_score_boundary_owns_full_v3_validation_and_scorer_alias(tmp_path:Path,task10_release_inputs:dict[str,Path],monkeypatch:pytest.MonkeyPatch)->None:
    from app.learn.hybrid import benchmark_v2_public_score as public_score
    output=tmp_path/"score.json"; public_path=tmp_path/"public.json"
    summary=run_private_scorer(private_manifest_path=task10_release_inputs["private"],prediction_run_ref_path=task10_release_inputs["accepted"],private_output_path=output,public_ref_path=public_path)
    public=json.loads(public_path.read_text(encoding="utf-8")); validated=public_score.validate_private_scorer_public_ref_v3(public)
    assert validated==public and summary=={key:public[key] for key in ("status","score_ref","content_sha256")}
    assert scorer_v2.validate_private_scorer_public_ref is public_score.validate_private_scorer_public_ref_v3
    assert public_score.validate_private_scorer_input_binding_v1(public["score_input_binding"])==public["score_input_binding"]
    noncanonical=deepcopy(public); encoded=noncanonical["launch_receipt"]["canonical_bytes_b64"]; alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"; position=-3 if encoded.endswith("==") else -2
    changed=encoded[:position]+alphabet[alphabet.index(encoded[position])+1]+encoded[position+1:]
    assert base64.b64decode(changed,validate=True)==base64.b64decode(encoded,validate=True) and changed!=encoded
    noncanonical["launch_receipt"]["canonical_bytes_b64"]=changed; noncanonical["content_sha256"]=public_score.content_sha256({key:value for key,value in noncanonical.items() if key!="content_sha256"})
    monkeypatch.setattr(public_score,"scan_benchmark_v2_public_value",lambda value:None)
    with pytest.raises(ValueError,match="receipt encoding"):
        public_score.validate_private_scorer_public_ref_v3(noncanonical)
    tree=ast.parse((ROOT/"app/learn/hybrid/benchmark_v2_public_score.py").read_text(encoding="utf-8"))
    assert {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node,ast.ImportFrom) and node.module} <= {"__future__","collections","typing","urllib"}
    assert {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node,ast.Import) for alias in node.names} <= {"base64","binascii","hashlib","json","re"}


def test_public_score_boundary_exports_task11_task12_authority()->None:
    from app.learn.hybrid import benchmark_v2_public_score as public_score
    assert callable(public_score.validate_private_scorer_input_binding_v1)
    assert callable(public_score.validate_private_scorer_public_ref_v3)
    assert callable(public_score.scan_benchmark_v2_public_value)


def test_h5_holdout_actual_body_projection_uses_holdout_provider_partition(
    tmp_path: Path,
    task10_release_inputs: dict[str, Path],
) -> None:
    from app.learn.hybrid import benchmark_v2_predictions as predictions
    from tests.test_portfolio_hybrid_v1_1_benchmark_v2_lifecycle import (
        _h5_holdout_lifecycle_graph,
    )

    manifest_path = task10_release_inputs["provider"]
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    corpus_path = task10_release_inputs["corpus"]
    corpus_bytes = corpus_path.read_bytes()
    corpus = json.loads(corpus_bytes.decode("utf-8"))
    groups: dict[str, list[dict[str, str]]] = {}
    for case in corpus["cases"]:
        if case["partition"] != "holdout":
            continue
        groups.setdefault(case["screen_group"], []).append(
            {
                "case_id": case["case_id"],
                "case_content_sha256": content_sha256(case),
            }
        )
    graph = _h5_holdout_lifecycle_graph(
        tmp_path, screen_case_groups=sorted(groups.items())
    )

    projection = predictions.project_benchmark_v2_holdout_actual_body(
        actual_body_bytes=graph["body_bytes"],
        provider_manifest_bytes=manifest_bytes,
        provider_corpus_bytes=corpus_bytes,
    )

    assert projection["body_contract_version"] == (
        "benchmark_v2_holdout_runner_actual_body_v1"
    )
    assert projection["screen_group_count"] == 12


def _h5_regression_pass_envelope() -> dict[str, object]:
    from app.learn.hybrid.benchmark_scorer_v2 import _content_bound, _sealed_receipt

    sha = "1" * 64
    ref_value = {"id": "runner-attempt/regression", "content_sha256": sha}
    score_input_binding = {
        "contract_version": "private_scorer_input_binding_v1",
        "benchmark_release_id": RELEASE,
        "partition": "regression",
        "private_manifest_ref": {
            "contract_version": "portfolio_hybrid_v1_1_private_manifest_v2_1",
            "file_sha256": sha,
            "content_sha256": sha,
        },
        "corpus_parent_ref": deepcopy(PARENT_REF),
        "provider_manifest_ref": {
            "contract_version": "portfolio_hybrid_v1_1_provider_manifest_v2_1",
            "relative_path": "benchmark-v2-provider-manifest.json",
            "file_sha256": sha,
        },
        "provider_corpus_ref": {
            "contract_version": "portfolio_hybrid_v1_1_provider_corpus_v2",
            "relative_path": "provider-corpus.v2.json",
            "file_sha256": sha,
            "content_sha256": sha,
            "source_parent_ref": deepcopy(PARENT_REF),
        },
        "accepted_run_ref": {
            "contract_version": "benchmark_v2_accepted_regression_score_input_v2",
            "file_sha256": sha,
            "content_sha256": sha,
        },
        "attempt_ref": deepcopy(ref_value),
        "attempt_ledger_ref": deepcopy(ref_value),
        "automatic_prediction_ref": deepcopy(ref_value),
        "selected_lifecycle_ref": deepcopy(ref_value),
        "estimand_ref": {"contract_version": "estimand_v2", "file_sha256": sha},
        "gate_ref": {"contract_version": "gate_v2", "file_sha256": sha},
        "safety": deepcopy(SAFETY),
    }
    child = {
        "status": "PASS",
        "score_ref": "private-score/" + "2" * 64,
        "content_sha256": "3" * 64,
    }
    launch = _content_bound(
        {
            "contract_version": "private_scorer_launch_receipt_v2",
            "launcher_process_id": 101,
            "launcher_process_identity": "process-101",
            "child_process_id": 102,
            "child_process_identity": "process-102",
            "pipe_capability_sha256": "4" * 64,
            "argv_sha256": "5" * 64,
            "env_sha256": "6" * 64,
            "cwd_sha256": "7" * 64,
            "job_identity_sha256": "8" * 64,
            "child_execution_receipt_sha256": "9" * 64,
            "child_score_ref": deepcopy(child),
            "score_input_binding": deepcopy(score_input_binding),
            "safety": deepcopy(SAFETY),
        }
    )
    launch_envelope = _sealed_receipt(launch, "private-scorer-launch")
    cleanup = {
        "contract_version": "private_scorer_cleanup_receipt_v1",
        "launch_receipt_ref": deepcopy(launch_envelope["ref"]),
        "child_returncode": 0,
        "job_active_processes_after": 0,
        "job_stable_zero": True,
        "pipe_handles_closed": True,
        "process_pipes_closed": True,
        "job_handle_closed": True,
        "safety": deepcopy(SAFETY),
    }
    cleanup_envelope = _sealed_receipt(cleanup, "private-scorer-cleanup")
    binding = _content_bound(
        {
            "contract_version": "private_scorer_final_binding_v2",
            "child_score_ref": deepcopy(child),
            "score_input_binding": deepcopy(score_input_binding),
            "launch_receipt_ref": deepcopy(launch_envelope["ref"]),
            "cleanup_receipt_ref": deepcopy(cleanup_envelope["ref"]),
            "safety": deepcopy(SAFETY),
        }
    )
    public = _content_bound(
        {
            "contract_version": "private_scorer_public_ref_v3",
            "status": "PASS",
            "score_ref": "private-score-final/" + binding["content_sha256"],
            "score_input_binding": score_input_binding,
            "binding": binding,
            "launch_receipt": launch_envelope,
            "cleanup_receipt": cleanup_envelope,
            "safety": deepcopy(SAFETY),
        }
    )
    raw = canonical_bytes(public)
    return {
        "ref": {
            "contract_version": "private_scorer_public_ref_v3",
            "file_sha256": hashlib.sha256(raw + b"\n").hexdigest(),
            "content_sha256": public["content_sha256"],
        },
        "canonical_bytes_b64": base64.b64encode(raw).decode("ascii"),
    }


def test_h5_regression_precondition_ref_hashes_exact_lf_terminated_file_bytes() -> None:
    from app.learn.hybrid import benchmark_v2_predictions as predictions

    envelope = _h5_regression_pass_envelope()
    decoded = base64.b64decode(envelope["canonical_bytes_b64"], validate=True)
    assert envelope["ref"]["file_sha256"] == hashlib.sha256(decoded + b"\n").hexdigest()
    assert predictions._accepted_regression_precondition_envelope(envelope)[1] == envelope["ref"]

    no_newline_hash = deepcopy(envelope)
    no_newline_hash["ref"]["file_sha256"] = hashlib.sha256(decoded).hexdigest()
    with pytest.raises(ValueError, match="precondition ref"):
        predictions._accepted_regression_precondition_envelope(no_newline_hash)


@pytest.fixture(scope="module")
def h5_accepted_holdout(
    tmp_path_factory: pytest.TempPathFactory,
    task10_release_inputs: dict[str, Path],
) -> tuple[dict[str, object], dict[str, object]]:
    from app.learn.hybrid import benchmark_v2_holdout as holdout
    from app.learn.hybrid import benchmark_v2_predictions as predictions
    from tests.test_portfolio_hybrid_v1_1_benchmark_v2_lifecycle import (
        _h5_holdout_lifecycle_graph,
    )

    manifest_bytes = task10_release_inputs["provider"].read_bytes()
    corpus_bytes = task10_release_inputs["corpus"].read_bytes()
    corpus = json.loads(corpus_bytes.decode("utf-8"))
    groups: dict[str, list[dict[str, str]]] = {}
    for case in corpus["cases"]:
        if case["partition"] == "holdout":
            groups.setdefault(case["screen_group"], []).append(
                {
                    "case_id": case["case_id"],
                    "case_content_sha256": content_sha256(case),
                }
            )
    graph = _h5_holdout_lifecycle_graph(
        tmp_path_factory.mktemp("h5-holdout"),
        screen_case_groups=sorted(groups.items()),
    )
    attempt = graph["attempt"]
    native_authorization_ref = deepcopy(attempt["authorization_ref"])
    claim_ref = deepcopy(attempt["claim_ref"])
    claim_id = claim_ref["id"].split("/", 1)[1]
    authorization_projection = holdout._seal_authority_projection(
        contract_version="benchmark_v2_holdout_authorization_public_projection_v1",
        semantic_fields={
            "authorization_id": native_authorization_ref["authorization_id"],
            "envelope_sha256": native_authorization_ref["envelope_sha256"],
            "claim_id": claim_id,
            "safety": deepcopy(holdout.SAFETY),
        },
    )
    authority = {
        "authorization_public_projection_envelope": authorization_projection,
        "claim_public_projection_envelope": holdout._seal_authority_projection(
            contract_version="benchmark_v2_holdout_claim_public_projection_v1",
            semantic_fields={
                "claim_ref": claim_ref,
                "claim_id": claim_id,
                "attempt_id": attempt["attempt_id"],
                "authorization_projection_ref": deepcopy(
                    authorization_projection["ref"]
                ),
                "state": "consumed",
                "safety": deepcopy(holdout.SAFETY),
            },
        ),
        "file_anchor_public_projection_envelope": holdout._seal_authority_projection(
            contract_version="benchmark_v2_holdout_file_anchor_public_projection_v1",
            semantic_fields={
                "anchor_kind": "win32_zero_byte_claim_sentinel",
                "claim_id": claim_id,
                "authorization_envelope_sha256": native_authorization_ref[
                    "envelope_sha256"
                ],
                "size_bytes": 0,
                "verified": True,
                "safety": deepcopy(holdout.SAFETY),
            },
        ),
        "registry_anchor_public_projection_envelope": holdout._seal_authority_projection(
            contract_version="benchmark_v2_holdout_registry_anchor_public_projection_v1",
            semantic_fields={
                "anchor_kind": "hkcu_claim_registry_envelope",
                "claim_id": claim_id,
                "authorization_envelope_sha256": native_authorization_ref[
                    "envelope_sha256"
                ],
                "claim_ref": claim_ref,
                "envelope_verified": True,
                "state": "consumed",
                "safety": deepcopy(holdout.SAFETY),
            },
        ),
    }
    anchor_body = {
        "contract_version": "benchmark_v2_holdout_anchor_verification_result_v1",
        "authorization_ref": {
            "authorization_id": native_authorization_ref["authorization_id"],
            "envelope_sha256": native_authorization_ref["envelope_sha256"],
        },
        "claim_ref": claim_ref,
        "attempt_id": attempt["attempt_id"],
        "authority_projection_envelopes": authority,
        "safety": deepcopy(holdout.SAFETY),
    }
    anchor = {
        **anchor_body,
        "content_sha256": hashlib.sha256(canonical_bytes(anchor_body)).hexdigest(),
    }

    accepted = predictions.materialize_benchmark_v2_accepted_holdout_score_input_v1(
        actual_body_bytes=graph["body_bytes"],
        actual_result_bytes=graph["result_bytes"],
        cleanup_receipt_bytes=graph["cleanup_bytes"],
        expected_attempt_dir=graph["attempt_dir"],
        provider_manifest_bytes=manifest_bytes,
        provider_corpus_bytes=corpus_bytes,
        attempt_events=graph["events"],
        attempt_events_jsonl_bytes=graph["events_bytes"],
        attempt_journal_events=graph["journal"],
        attempt_journal_jsonl_bytes=graph["journal_bytes"],
        native_authorization_ref=native_authorization_ref,
        holdout_anchor_verification_result=anchor,
        regression_score_precondition_envelope=_h5_regression_pass_envelope(),
    )

    graph["h5_materializer_kwargs"] = {
        "actual_body_bytes": graph["body_bytes"],
        "actual_result_bytes": graph["result_bytes"],
        "cleanup_receipt_bytes": graph["cleanup_bytes"],
        "expected_attempt_dir": graph["attempt_dir"],
        "provider_manifest_bytes": manifest_bytes,
        "provider_corpus_bytes": corpus_bytes,
        "attempt_events": graph["events"],
        "attempt_events_jsonl_bytes": graph["events_bytes"],
        "attempt_journal_events": graph["journal"],
        "attempt_journal_jsonl_bytes": graph["journal_bytes"],
        "native_authorization_ref": native_authorization_ref,
        "holdout_anchor_verification_result": anchor,
        "regression_score_precondition_envelope": _h5_regression_pass_envelope(),
    }

    return accepted, graph


def test_h5_authoritative_holdout_materializer_builds_public_closed_graph(
    h5_accepted_holdout: tuple[dict[str, object], dict[str, object]],
) -> None:
    from app.learn.hybrid import benchmark_v2_predictions as predictions

    accepted, graph = h5_accepted_holdout
    assert predictions.validate_benchmark_v2_accepted_holdout_score_input_v1(accepted) == accepted
    serialized = canonical_bytes(accepted)
    assert b"fixed_authorization_path" not in serialized
    assert str(graph["attempt_dir"]).encode("utf-8") not in serialized
    prediction = decode(accepted["prediction_run_envelope"])
    lifecycle_bundle = decode(accepted["lifecycle_bundle_envelope"])
    wanted = {
        "benchmark_v2_holdout_attempt_ledger_pre_result_verified_projection_v1",
        "benchmark_v2_holdout_attempt_ledger_prefix_verified_projection_v1",
        "benchmark_v2_holdout_actual_result_verified_projection_v1",
    }
    for contract in wanted:
        prediction_envelope = next(
            envelope
            for envelope in prediction["sealed_artifact_envelopes"]
            if decode(envelope)["contract_version"] == contract
        )
        lifecycle_envelope = next(
            envelope
            for envelope in lifecycle_bundle["sealed_artifact_envelopes"]
            if decode(envelope)["contract_version"] == contract
        )
        assert prediction_envelope == lifecycle_envelope


def test_h5_public_holdout_validator_rejects_leakage_and_closure_mutations(
    h5_accepted_holdout: tuple[dict[str, object], dict[str, object]],
) -> None:
    from app.learn.hybrid import benchmark_v2_predictions as predictions

    accepted, graph = h5_accepted_holdout
    mutations: list[dict[str, object]] = []

    extra = deepcopy(accepted)
    extra["extra"] = True
    extra["content_sha256"] = hashlib.sha256(
        canonical_bytes({key: value for key, value in extra.items() if key != "content_sha256"})
    ).hexdigest()
    mutations.append(extra)

    native = deepcopy(accepted)
    native["holdout_authorization_ref"] = deepcopy(
        graph["attempt"]["authorization_ref"]
    )
    native["content_sha256"] = hashlib.sha256(
        canonical_bytes({key: value for key, value in native.items() if key != "content_sha256"})
    ).hexdigest()
    mutations.append(native)

    for mode in ("missing", "copied"):
        changed = deepcopy(accepted)
        outer = decode(changed["prediction_run_envelope"])
        children = outer["sealed_artifact_envelopes"]
        if mode == "missing":
            children.pop()
        else:
            children.append(deepcopy(children[-1]))
        changed["prediction_run_envelope"] = _unchecked_envelope(
            _remint_pathless_unchecked(outer)
        )
        changed["content_sha256"] = hashlib.sha256(
            canonical_bytes(
                {key: value for key, value in changed.items() if key != "content_sha256"}
            )
        ).hexdigest()
        mutations.append(changed)

    lifecycle_missing = deepcopy(accepted)
    lifecycle_outer = decode(lifecycle_missing["lifecycle_bundle_envelope"])
    lifecycle_outer["sealed_artifact_envelopes"].pop(0)
    lifecycle_missing["lifecycle_bundle_envelope"] = _unchecked_envelope(
        _remint_pathless_unchecked(lifecycle_outer)
    )
    lifecycle_missing["content_sha256"] = hashlib.sha256(
        canonical_bytes(
            {
                key: value
                for key, value in lifecycle_missing.items()
                if key != "content_sha256"
            }
        )
    ).hexdigest()
    mutations.append(lifecycle_missing)

    regression_substitution = deepcopy(accepted)
    prefix_envelope = regression_substitution["verified_parent_projections"][
        "runner_ledger_prefix_projection_envelope"
    ]
    prefix = decode(prefix_envelope)
    prefix["contract_version"] = (
        "benchmark_v2_runner_ledger_prefix_verified_projection_v1"
    )
    regression_substitution["verified_parent_projections"][
        "runner_ledger_prefix_projection_envelope"
    ] = _unchecked_envelope(_remint_pathless_unchecked(prefix))
    regression_substitution["content_sha256"] = hashlib.sha256(
        canonical_bytes(
            {
                key: value
                for key, value in regression_substitution.items()
                if key != "content_sha256"
            }
        )
    ).hexdigest()
    mutations.append(regression_substitution)

    for changed in mutations:
        with pytest.raises(ValueError):
            predictions.validate_benchmark_v2_accepted_holdout_score_input_v1(changed)


@pytest.mark.parametrize("mutation", ("crlf", "whitespace", "trailing_blank"))
def test_h5_authoritative_materializer_rejects_nonexact_attempt_journal_snapshot(
    h5_accepted_holdout: tuple[dict[str, object], dict[str, object]],
    mutation: str,
) -> None:
    from app.learn.hybrid import benchmark_v2_predictions as predictions

    _, graph = h5_accepted_holdout
    kwargs = deepcopy(graph["h5_materializer_kwargs"])
    raw = kwargs["attempt_journal_jsonl_bytes"]
    assert isinstance(raw, bytes)
    if mutation == "crlf":
        changed = raw.replace(b"\n", b"\r\n", 1)
    elif mutation == "whitespace":
        changed = b" " + raw
    else:
        changed = raw + b"\n"
    kwargs["attempt_journal_jsonl_bytes"] = changed

    with pytest.raises(ValueError, match="attempt journal JSONL"):
        predictions.materialize_benchmark_v2_accepted_holdout_score_input_v1(
            **kwargs
        )


def test_h5_public_authority_rejects_consistently_reminted_attempt_id(
    h5_accepted_holdout: tuple[dict[str, object], dict[str, object]],
) -> None:
    from app.learn.hybrid import benchmark_v2_holdout as holdout
    from app.learn.hybrid import benchmark_v2_predictions as predictions

    accepted, _ = h5_accepted_holdout
    authorization_ref = deepcopy(accepted["holdout_authorization_ref"])
    claim_id = "d" * 64
    claim_ref = {"id": "holdout-claim/" + claim_id, "envelope_sha256": "e" * 64}
    wrong_attempt_id = "f" * 64
    authorization = holdout._seal_authority_projection(
        contract_version="benchmark_v2_holdout_authorization_public_projection_v1",
        semantic_fields={
            "authorization_id": authorization_ref["authorization_id"],
            "envelope_sha256": authorization_ref["envelope_sha256"],
            "claim_id": claim_id,
            "safety": deepcopy(holdout.SAFETY),
        },
    )
    authority = {
        "authorization_public_projection_envelope": authorization,
        "claim_public_projection_envelope": holdout._seal_authority_projection(
            contract_version="benchmark_v2_holdout_claim_public_projection_v1",
            semantic_fields={
                "claim_ref": claim_ref,
                "claim_id": claim_id,
                "attempt_id": wrong_attempt_id,
                "authorization_projection_ref": deepcopy(authorization["ref"]),
                "state": "consumed",
                "safety": deepcopy(holdout.SAFETY),
            },
        ),
        "file_anchor_public_projection_envelope": holdout._seal_authority_projection(
            contract_version="benchmark_v2_holdout_file_anchor_public_projection_v1",
            semantic_fields={
                "anchor_kind": "win32_zero_byte_claim_sentinel",
                "claim_id": claim_id,
                "authorization_envelope_sha256": authorization_ref["envelope_sha256"],
                "size_bytes": 0,
                "verified": True,
                "safety": deepcopy(holdout.SAFETY),
            },
        ),
        "registry_anchor_public_projection_envelope": holdout._seal_authority_projection(
            contract_version="benchmark_v2_holdout_registry_anchor_public_projection_v1",
            semantic_fields={
                "anchor_kind": "hkcu_claim_registry_envelope",
                "claim_id": claim_id,
                "authorization_envelope_sha256": authorization_ref["envelope_sha256"],
                "claim_ref": claim_ref,
                "envelope_verified": True,
                "state": "consumed",
                "safety": deepcopy(holdout.SAFETY),
            },
        ),
    }

    with pytest.raises(ValueError, match="authority lineage"):
        predictions._validate_holdout_public_authority_lineage(
            authorization_ref=authorization_ref,
            claim_ref=claim_ref,
            attempt_ref={
                "id": "holdout-runner-attempt/" + wrong_attempt_id,
                "content_sha256": "1" * 64,
            },
            authority_evidence=authority,
        )


def test_h5_public_authority_rejects_reminted_bool_file_anchor_size(
    h5_accepted_holdout: tuple[dict[str, object], dict[str, object]],
) -> None:
    from app.learn.hybrid import benchmark_v2_holdout as holdout
    from app.learn.hybrid import benchmark_v2_predictions as predictions

    accepted, _ = h5_accepted_holdout
    changed = deepcopy(accepted)
    field = "file_anchor_public_projection_envelope"
    file_anchor = decode(changed["holdout_authority_evidence"][field])
    semantic = {
        key: value
        for key, value in file_anchor.items()
        if key not in {"contract_version", "artifact_id", "content_sha256"}
    }
    semantic["size_bytes"] = False
    changed["holdout_authority_evidence"][field] = holdout._seal_authority_projection(
        contract_version="benchmark_v2_holdout_file_anchor_public_projection_v1",
        semantic_fields=semantic,
    )
    changed["content_sha256"] = hashlib.sha256(
        canonical_bytes(
            {key: value for key, value in changed.items() if key != "content_sha256"}
        )
    ).hexdigest()

    with pytest.raises(ValueError, match="authority lineage"):
        predictions.validate_benchmark_v2_accepted_holdout_score_input_v1(changed)


def _h6_regression_precondition_envelope(
    release: dict[str, object],
    *,
    status: str = "PASS",
    drift: str | None = None,
) -> dict[str, object]:
    from app.learn.hybrid.benchmark_scorer_v2 import _content_bound, _sealed_receipt

    source = _h5_regression_pass_envelope()
    public = decode(source)
    binding = deepcopy(public["score_input_binding"])
    binding.update(
        {
            "benchmark_release_id": RELEASE,
            "private_manifest_ref": deepcopy(release["private_manifest_ref"]),
            "corpus_parent_ref": deepcopy(release["corpus_parent_ref"]),
            "provider_manifest_ref": deepcopy(release["provider_manifest_ref"]),
            "provider_corpus_ref": deepcopy(release["provider_corpus_ref"]),
            "estimand_ref": deepcopy(release["estimand_ref"]),
            "gate_ref": deepcopy(release["gate_ref"]),
        }
    )
    if drift == "release":
        binding["benchmark_release_id"] = "cross-release"
    elif drift in {
        "private_manifest_ref",
        "corpus_parent_ref",
        "provider_manifest_ref",
        "provider_corpus_ref",
        "estimand_ref",
        "gate_ref",
    }:
        binding[drift] = deepcopy(binding[drift])
        sha_field = next(key for key in binding[drift] if key.endswith("sha256"))
        binding[drift][sha_field] = "0" * 64

    launch = decode(public["launch_receipt"])
    child = deepcopy(launch["child_score_ref"])
    child["status"] = status
    launch.update({"child_score_ref": child, "score_input_binding": binding})
    launch.pop("content_sha256")
    launch_envelope = _sealed_receipt(
        _content_bound(launch), "private-scorer-launch"
    )
    cleanup = decode(public["cleanup_receipt"])
    cleanup["launch_receipt_ref"] = deepcopy(launch_envelope["ref"])
    cleanup_envelope = _sealed_receipt(cleanup, "private-scorer-cleanup")
    final_binding = _content_bound(
        {
            "contract_version": "private_scorer_final_binding_v2",
            "child_score_ref": child,
            "score_input_binding": binding,
            "launch_receipt_ref": deepcopy(launch_envelope["ref"]),
            "cleanup_receipt_ref": deepcopy(cleanup_envelope["ref"]),
            "safety": deepcopy(SAFETY),
        }
    )
    reminted = _content_bound(
        {
            "contract_version": "private_scorer_public_ref_v3",
            "status": status,
            "score_ref": "private-score-final/" + final_binding["content_sha256"],
            "score_input_binding": binding,
            "binding": final_binding,
            "launch_receipt": launch_envelope,
            "cleanup_receipt": cleanup_envelope,
            "safety": deepcopy(SAFETY),
        }
    )
    raw = canonical_bytes(reminted)
    return {
        "ref": {
            "contract_version": "private_scorer_public_ref_v3",
            "file_sha256": hashlib.sha256(raw + b"\n").hexdigest(),
            "content_sha256": reminted["content_sha256"],
        },
        "canonical_bytes_b64": base64.b64encode(raw).decode("ascii"),
    }


def _h6_holdout_binding(
    accepted: dict[str, object], release: dict[str, object]
) -> dict[str, object]:
    precondition = accepted["regression_score_precondition_envelope"]
    return {
        "contract_version": "private_scorer_holdout_input_binding_v1",
        "benchmark_release_id": RELEASE,
        "partition": "holdout",
        "private_manifest_ref": deepcopy(release["private_manifest_ref"]),
        "corpus_parent_ref": deepcopy(accepted["corpus_parent_ref"]),
        "provider_manifest_ref": deepcopy(accepted["provider_manifest_ref"]),
        "provider_corpus_ref": deepcopy(accepted["provider_corpus_ref"]),
        "accepted_run_ref": {
            "contract_version": "benchmark_v2_accepted_holdout_score_input_v1",
            "file_sha256": hashlib.sha256(canonical_bytes(accepted) + b"\n").hexdigest(),
            "content_sha256": accepted["content_sha256"],
        },
        "attempt_ref": deepcopy(accepted["attempt_ref"]),
        "attempt_ledger_ref": deepcopy(accepted["attempt_ledger_ref"]),
        "automatic_prediction_ref": deepcopy(accepted["automatic_prediction_ref"]),
        "selected_lifecycle_ref": deepcopy(accepted["selected_lifecycle_ref"]),
        "estimand_ref": deepcopy(release["estimand_ref"]),
        "gate_ref": deepcopy(release["gate_ref"]),
        "regression_score_precondition_ref": deepcopy(precondition["ref"]),
        "holdout_authorization_ref": deepcopy(accepted["holdout_authorization_ref"]),
        "holdout_claim_ref": deepcopy(accepted["holdout_claim_ref"]),
        "safety": deepcopy(SAFETY),
    }


def _h6_public_v3_for_binding(
    binding: dict[str, object],
    *,
    launch_overrides: dict[str, object] | None = None,
    cleanup_overrides: dict[str, object] | None = None,
) -> dict[str, object]:
    from app.learn.hybrid.benchmark_scorer_v2 import _content_bound, _sealed_receipt

    child = {
        "status": "PASS",
        "score_ref": "private-score/" + "2" * 64,
        "content_sha256": "3" * 64,
    }
    launch = {
        "contract_version": "private_scorer_launch_receipt_v2",
        "launcher_process_id": 201,
        "launcher_process_identity": "process-201",
        "child_process_id": 202,
        "child_process_identity": "process-202",
        "pipe_capability_sha256": "4" * 64,
        "argv_sha256": "5" * 64,
        "env_sha256": "6" * 64,
        "cwd_sha256": "7" * 64,
        "job_identity_sha256": "8" * 64,
        "child_execution_receipt_sha256": "9" * 64,
        "child_score_ref": deepcopy(child),
        "score_input_binding": deepcopy(binding),
        "safety": deepcopy(SAFETY),
    }
    launch.update(launch_overrides or {})
    launch_envelope = _sealed_receipt(
        _content_bound(launch), "private-scorer-launch"
    )
    cleanup = {
        "contract_version": "private_scorer_cleanup_receipt_v1",
        "launch_receipt_ref": deepcopy(launch_envelope["ref"]),
        "child_returncode": 0,
        "job_active_processes_after": 0,
        "job_stable_zero": True,
        "pipe_handles_closed": True,
        "process_pipes_closed": True,
        "job_handle_closed": True,
        "safety": deepcopy(SAFETY),
    }
    cleanup.update(cleanup_overrides or {})
    cleanup_envelope = _sealed_receipt(cleanup, "private-scorer-cleanup")
    final_binding = _content_bound(
        {
            "contract_version": "private_scorer_final_binding_v2",
            "child_score_ref": deepcopy(child),
            "score_input_binding": deepcopy(binding),
            "launch_receipt_ref": deepcopy(launch_envelope["ref"]),
            "cleanup_receipt_ref": deepcopy(cleanup_envelope["ref"]),
            "safety": deepcopy(SAFETY),
        }
    )
    return _content_bound(
        {
            "contract_version": "private_scorer_public_ref_v3",
            "status": "PASS",
            "score_ref": "private-score-final/" + final_binding["content_sha256"],
            "score_input_binding": deepcopy(binding),
            "binding": final_binding,
            "launch_receipt": launch_envelope,
            "cleanup_receipt": cleanup_envelope,
            "safety": deepcopy(SAFETY),
        }
    )


@pytest.fixture(scope="module")
def h6_accepted_holdout(
    h5_accepted_holdout: tuple[dict[str, object], dict[str, object]],
    task10_release_inputs: dict[str, Path],
) -> tuple[dict[str, object], dict[str, object]]:
    from app.learn.hybrid.benchmark_v2_private_release import (
        validate_task10_private_release_bundle,
    )

    accepted, _ = h5_accepted_holdout
    release = validate_task10_private_release_bundle(
        private_manifest_path=task10_release_inputs["private"]
    )
    changed = deepcopy(accepted)
    changed["regression_score_precondition_envelope"] = (
        _h6_regression_precondition_envelope(release)
    )
    changed["content_sha256"] = hashlib.sha256(
        canonical_bytes(
            {key: value for key, value in changed.items() if key != "content_sha256"}
        )
    ).hexdigest()
    return changed, release


def test_h6_holdout_binding_and_public_v3_propagate_three_exact_refs(
    h6_accepted_holdout: tuple[dict[str, object], dict[str, object]],
) -> None:
    from app.learn.hybrid import benchmark_v2_public_score as public_score

    accepted, release = h6_accepted_holdout
    binding = _h6_holdout_binding(accepted, release)
    assert public_score.validate_private_scorer_holdout_input_binding_v1(binding) == binding
    public = _h6_public_v3_for_binding(binding)

    assert public_score.validate_private_scorer_public_ref_v3(public) == public
    launch_value = decode(public["launch_receipt"])
    for field in (
        "regression_score_precondition_ref",
        "holdout_authorization_ref",
        "holdout_claim_ref",
    ):
        assert binding[field] == launch_value["score_input_binding"][field]
        assert binding[field] == public["binding"]["score_input_binding"][field]
        assert binding[field] == public["score_input_binding"][field]


@pytest.mark.parametrize(
    ("contract_version", "partition"),
    (
        ("private_scorer_input_binding_v1", "holdout"),
        ("private_scorer_holdout_input_binding_v1", "regression"),
    ),
)
def test_h6_public_binding_rejects_cross_contract_partition(
    h6_accepted_holdout: tuple[dict[str, object], dict[str, object]],
    contract_version: str,
    partition: str,
) -> None:
    from app.learn.hybrid import benchmark_v2_public_score as public_score

    accepted, release = h6_accepted_holdout
    binding = _h6_holdout_binding(accepted, release)
    binding.update({"contract_version": contract_version, "partition": partition})
    with pytest.raises(ValueError):
        public_score._validate_private_scorer_input_binding(binding)


def test_h6_public_binding_rejects_native_authorization_path_leakage(
    h6_accepted_holdout: tuple[dict[str, object], dict[str, object]],
) -> None:
    from app.learn.hybrid import benchmark_v2_public_score as public_score

    accepted, release = h6_accepted_holdout
    binding = _h6_holdout_binding(accepted, release)
    binding["holdout_authorization_ref"] = {
        **binding["holdout_authorization_ref"],
        "fixed_authorization_path": r"C:\private\authorization.json",
    }
    with pytest.raises(ValueError):
        public_score.validate_private_scorer_holdout_input_binding_v1(binding)


@pytest.mark.parametrize(
    "field",
    (
        "attempt_ref",
        "attempt_ledger_ref",
        "automatic_prediction_ref",
        "selected_lifecycle_ref",
    ),
)
def test_h6_holdout_binding_rejects_nonhex_shared_ref_content_sha_after_remint(
    h6_accepted_holdout: tuple[dict[str, object], dict[str, object]],
    field: str,
) -> None:
    from app.learn.hybrid import benchmark_v2_public_score as public_score

    accepted, release = h6_accepted_holdout
    binding = _h6_holdout_binding(accepted, release)
    binding[field]["content_sha256"] = "G" * 64
    public = _h6_public_v3_for_binding(binding)

    with pytest.raises(ValueError):
        public_score.validate_private_scorer_holdout_input_binding_v1(binding)
    with pytest.raises(ValueError):
        public_score.validate_private_scorer_public_ref_v3(public)


@pytest.mark.parametrize(
    ("field", "wrong_prefix"),
    (
        ("attempt_ref", "runner-attempt"),
        ("attempt_ledger_ref", "projected-attempt-ledger"),
        ("automatic_prediction_ref", "prediction-run"),
        ("selected_lifecycle_ref", "lifecycle-bundle"),
    ),
)
def test_h6_holdout_binding_rejects_wrong_h5_shared_ref_prefix_after_remint(
    h6_accepted_holdout: tuple[dict[str, object], dict[str, object]],
    field: str,
    wrong_prefix: str,
) -> None:
    from app.learn.hybrid import benchmark_v2_public_score as public_score

    accepted, release = h6_accepted_holdout
    binding = _h6_holdout_binding(accepted, release)
    binding[field]["id"] = wrong_prefix + "/" + "a" * 64
    public = _h6_public_v3_for_binding(binding)

    with pytest.raises(ValueError):
        public_score.validate_private_scorer_holdout_input_binding_v1(binding)
    with pytest.raises(ValueError):
        public_score.validate_private_scorer_public_ref_v3(public)


@pytest.mark.parametrize("substitution", ("authorization", "claim", "attempt"))
def test_h6_holdout_binding_rejects_authority_attempt_substitution_after_remint(
    h6_accepted_holdout: tuple[dict[str, object], dict[str, object]],
    substitution: str,
) -> None:
    from app.learn.hybrid import benchmark_v2_public_score as public_score

    accepted, release = h6_accepted_holdout
    binding = _h6_holdout_binding(accepted, release)
    if substitution == "authorization":
        original = binding["holdout_authorization_ref"]["authorization_id"].rsplit(
            "/", 1
        )[1]
        binding["holdout_authorization_ref"]["authorization_id"] = (
            "holdout-authorization/"
            + ("0" if original[0] != "0" else "1")
            + original[1:]
        )
    elif substitution == "claim":
        original = binding["holdout_claim_ref"]["id"].rsplit("/", 1)[1]
        binding["holdout_claim_ref"]["id"] = (
            "holdout-claim/"
            + ("0" if original[0] != "0" else "1")
            + original[1:]
        )
    else:
        original = binding["attempt_ref"]["id"].rsplit("/", 1)[1]
        binding["attempt_ref"]["id"] = (
            "holdout-runner-attempt/"
            + ("0" if original[0] != "0" else "1")
            + original[1:]
        )
    public = _h6_public_v3_for_binding(binding)

    with pytest.raises(ValueError):
        public_score.validate_private_scorer_holdout_input_binding_v1(binding)
    with pytest.raises(ValueError):
        public_score.validate_private_scorer_public_ref_v3(public)


@pytest.mark.parametrize(
    ("receipt", "field"),
    (
        ("launch", "launcher_process_id"),
        ("launch", "child_process_id"),
        ("cleanup", "child_returncode"),
        ("cleanup", "job_active_processes_after"),
    ),
)
def test_h6_public_v3_rejects_fully_reminted_bool_numeric_alias(
    receipt: str, field: str
) -> None:
    from app.learn.hybrid import benchmark_v2_public_score as public_score

    regression = decode(_h5_regression_pass_envelope())
    kwargs = {
        "launch_overrides": {field: True},
        "cleanup_overrides": {},
    }
    if receipt == "cleanup":
        kwargs = {
            "launch_overrides": {},
            "cleanup_overrides": {field: False},
        }
    reminted = _h6_public_v3_for_binding(
        regression["score_input_binding"], **kwargs
    )

    with pytest.raises(ValueError, match="launch/cleanup chain"):
        public_score.validate_private_scorer_public_ref_v3(reminted)


@pytest.mark.parametrize(
    ("contract_version", "partition"),
    (
        ("benchmark_v2_accepted_regression_score_input_v2", "holdout"),
        ("benchmark_v2_accepted_holdout_score_input_v1", "regression"),
    ),
)
def test_h6_private_acceptance_rejects_cross_contract_partition(
    h6_accepted_holdout: tuple[dict[str, object], dict[str, object]],
    contract_version: str,
    partition: str,
) -> None:
    accepted, release = h6_accepted_holdout
    changed = deepcopy(accepted)
    changed.update({"contract_version": contract_version, "partition": partition})
    changed["content_sha256"] = hashlib.sha256(
        canonical_bytes(
            {key: value for key, value in changed.items() if key != "content_sha256"}
        )
    ).hexdigest()
    with pytest.raises(ValueError, match="contract/partition mismatch"):
        scorer_v2._validate_accepted_score_input(
            changed,
            raw=canonical_bytes(changed) + b"\n",
            release=release,
        )


def test_h6_private_acceptance_validates_exact_holdout_12x5x4_graph(
    h6_accepted_holdout: tuple[dict[str, object], dict[str, object]],
) -> None:
    accepted, release = h6_accepted_holdout
    validated, automatic, _ = scorer_v2._validate_accepted_score_input(
        accepted,
        raw=canonical_bytes(accepted) + b"\n",
        release=release,
    )
    rows = automatic["rows"]
    assert validated["partition"] == "holdout"
    assert len(rows) == 240
    assert len({row["case_id"] for row in rows}) == 60
    assert len({(row["case_id"], row["arm_id"]) for row in rows}) == 240
    assert len(automatic["provider_group_dependencies"]) == 12


def test_h6_private_child_scores_holdout_and_carries_identical_binding(
    tmp_path: Path,
    h6_accepted_holdout: tuple[dict[str, object], dict[str, object]],
    task10_release_inputs: dict[str, Path],
) -> None:
    from app.learn.hybrid.benchmark_v2_private_release import (
        derive_private_scoring_cases,
    )

    accepted, release = h6_accepted_holdout
    accepted_path = tmp_path / "accepted-holdout.json"
    write(accepted_path, accepted)
    private_cases = derive_private_scoring_cases(
        validated_release=release, partition="holdout"
    )
    _selected_accepted_input(
        accepted_path,
        release["provider_corpus"]["cases"],
        private_cases,
        release,
        partition="holdout",
    )
    private_output = tmp_path / "private-score.json"
    child_public_path = tmp_path / "child-public.json"
    child_public = scorer_v2._run_private_child_once(
        nonce="1" * 64,
        pipe_capability="2" * 64,
        launcher_process_id=101,
        launcher_process_identity="process-101",
        process_identity="process-child",
        job_identity_sha256="3" * 64,
        argv_sha256="4" * 64,
        env_sha256="5" * 64,
        cwd_sha256="6" * 64,
        private_manifest_path=task10_release_inputs["private"],
        prediction_run_ref_path=accepted_path,
        private_output_path=private_output,
        public_ref_path=child_public_path,
    )
    private_score = json.loads(private_output.read_text(encoding="utf-8"))
    binding = private_score["score_input_binding"]
    assert private_score["partition"] == "holdout"
    assert binding == child_public["score_input_binding"]
    for field in (
        "regression_score_precondition_ref",
        "holdout_authorization_ref",
        "holdout_claim_ref",
    ):
        assert binding[field] == _h6_holdout_binding(
            json.loads(accepted_path.read_text(encoding="utf-8")), release
        )[field]


@pytest.mark.parametrize(
    "drift",
    (
        "release",
        "private_manifest_ref",
        "corpus_parent_ref",
        "provider_manifest_ref",
        "provider_corpus_ref",
        "estimand_ref",
        "gate_ref",
    ),
)
def test_h6_private_acceptance_rejects_regression_precondition_drift(
    h6_accepted_holdout: tuple[dict[str, object], dict[str, object]],
    drift: str,
) -> None:
    accepted, release = h6_accepted_holdout
    changed = deepcopy(accepted)
    changed["regression_score_precondition_envelope"] = (
        _h6_regression_precondition_envelope(release, drift=drift)
    )
    changed["content_sha256"] = hashlib.sha256(
        canonical_bytes(
            {key: value for key, value in changed.items() if key != "content_sha256"}
        )
    ).hexdigest()
    with pytest.raises(ValueError):
        scorer_v2._validate_accepted_score_input(
            changed,
            raw=canonical_bytes(changed) + b"\n",
            release=release,
        )


def test_h6_private_acceptance_rejects_regression_fail_and_ref_mismatch(
    h6_accepted_holdout: tuple[dict[str, object], dict[str, object]],
) -> None:
    accepted, release = h6_accepted_holdout
    mutations = []
    failed = deepcopy(accepted)
    failed["regression_score_precondition_envelope"] = (
        _h6_regression_precondition_envelope(release, status="FAIL")
    )
    mutations.append(failed)
    mismatch = deepcopy(accepted)
    mismatch["regression_score_precondition_envelope"]["ref"]["file_sha256"] = "0" * 64
    mutations.append(mismatch)
    for changed in mutations:
        changed["content_sha256"] = hashlib.sha256(
            canonical_bytes(
                {key: value for key, value in changed.items() if key != "content_sha256"}
            )
        ).hexdigest()
        with pytest.raises(ValueError):
            scorer_v2._validate_accepted_score_input(
                changed,
                raw=canonical_bytes(changed) + b"\n",
                release=release,
            )


def test_public_score_scanner_accepts_only_internally_derived_provider_corpus_image_paths(task10_release_inputs:dict[str,Path])->None:
    from app.learn.hybrid.benchmark_v2_public_score import scan_benchmark_v2_public_value
    manifest=json.loads(task10_release_inputs["provider"].read_text(encoding="utf-8")); corpus=json.loads(task10_release_inputs["corpus"].read_text(encoding="utf-8")); exact=corpus["cases"][0]["image"]["path"]
    scan_benchmark_v2_public_value(manifest)
    scan_benchmark_v2_public_value(corpus)
    outside=deepcopy(corpus); outside["copied_image"] = exact
    with pytest.raises(ValueError,match="leakage"):
        scan_benchmark_v2_public_value(outside)
    with pytest.raises(TypeError):
        scan_benchmark_v2_public_value(corpus,allowed_paths={exact})


@pytest.mark.parametrize("mutation",["projection","parent_lineage"])
def test_public_score_scanner_matches_authoritative_provider_snapshot_rejection(task10_release_inputs:dict[str,Path],mutation:str)->None:
    from app.learn.hybrid import benchmark_v2_public_score as public_score
    from app.learn.hybrid.benchmark_v2_contracts import canonical_json_bytes, sha256_bytes
    from app.learn.hybrid.benchmark_v2_provider_corpus import validate_preloaded_provider_corpus, validate_provider_manifest
    manifest=json.loads(task10_release_inputs["provider"].read_text(encoding="utf-8")); corpus=json.loads(task10_release_inputs["corpus"].read_text(encoding="utf-8"))
    if mutation=="projection":
        manifest["evaluation_projection"]={"provider_policy":{},"estimand":{},"gate":{}}
        with pytest.raises(ValueError): validate_provider_manifest(manifest)
        changed=manifest
    else:
        corpus["source_parent_ref"]["artifact_id"]="forged-parent"; corpus["content_sha256"]=public_score.content_sha256({key:value for key,value in corpus.items() if key!="content_sha256"})
        raw=canonical_json_bytes(corpus,pretty=True)
        with pytest.raises(ValueError): validate_preloaded_provider_corpus(raw=raw,expected_sha256=sha256_bytes(raw))
        changed=corpus
    with pytest.raises(ValueError,match="leakage"):
        public_score.scan_benchmark_v2_public_value(changed)


@pytest.mark.parametrize("value",[
    {"contract_version":"portfolio_hybrid_v1_1_provider_corpus_v2","cases":[{"partition":"regression","image":{"path":"tests/fixtures/portfolio_hybrid_v1_1/corpus/regression/case-001.png"}}]},
    {"contract_version":"portfolio_hybrid_v1_1_provider_manifest_v2_1","sealed_runtime":{"code_refs":[{"relative_path":"app/learn/hybrid/benchmark_v2_provider_sandbox.py"}],"release_code_refs":[],"profile_refs":[]}},
    {"junk":{"provider_manifest_ref":{"relative_path":"benchmark-v2-provider-manifest.json"}}},
    {"junk":{"provider_corpus_ref":{"relative_path":"provider-corpus.v2.json"}}},
])
def test_public_score_scanner_rejects_unvalidated_snapshot_or_junk_ref_path_exceptions(value:object)->None:
    from app.learn.hybrid.benchmark_v2_public_score import scan_benchmark_v2_public_value
    with pytest.raises(ValueError,match="leakage"):
        scan_benchmark_v2_public_value(value)


@pytest.mark.parametrize("mutation",["unlisted","case_drift","backslash","dot","parent","partition_mismatch"])
def test_public_score_scanner_rejects_provider_corpus_image_path_aliases(task10_release_inputs:dict[str,Path],mutation:str)->None:
    from app.learn.hybrid.benchmark_v2_public_score import scan_benchmark_v2_public_value
    corpus=json.loads(task10_release_inputs["corpus"].read_text(encoding="utf-8")); case=corpus["cases"][0]; path=case["image"]["path"]
    if mutation=="unlisted": corpus["unlisted_image"]="tests/fixtures/portfolio_hybrid_v1_1/corpus/regression/case-999.png"
    elif mutation=="case_drift": case["image"]["path"]=path.upper()
    elif mutation=="backslash": case["image"]["path"]=path.replace("/","\\")
    elif mutation=="dot": case["image"]["path"]=path.replace("/corpus/","/corpus/./")
    elif mutation=="parent": case["image"]["path"]=path.replace("/corpus/","/corpus/x/../")
    else: case["partition"]="holdout" if case["partition"]=="regression" else "regression"
    with pytest.raises(ValueError,match="leakage"):
        scan_benchmark_v2_public_value(corpus)


@pytest.mark.parametrize("value",[
    {"private_output":"x"},
    {"value":"GOLD.V1.JSON"},
    {"value":r"C:\private\score.json"},
    {"payload_bytes_b64":"%%%"},
    {"canonical_bytes_b64":base64.b64encode(b'{"value":"ok"} trailing').decode("ascii")},
])
def test_public_score_scanner_fails_closed_on_recursive_leakage_and_invalid_envelopes(value:object)->None:
    from app.learn.hybrid.benchmark_v2_public_score import scan_benchmark_v2_public_value
    with pytest.raises(ValueError,match="leakage"):
        scan_benchmark_v2_public_value(value)


@pytest.mark.parametrize("mutation",["percent_once","percent_deep","percent_bound","pad_bits_ze","pad_bits_zb"])
def test_public_score_scanner_rejects_percent_aliases_and_noncanonical_base64(mutation:str)->None:
    from app.learn.hybrid.benchmark_v2_public_score import scan_benchmark_v2_public_value
    if mutation=="percent_once": encoded={"value":"gold%2Ev1%2Ejson"}
    elif mutation in {"percent_deep","percent_bound"}:
        text="gold%2Ev1%2Ejson"
        for _ in range(9 if mutation=="percent_deep" else 33): text=text.replace("%","%25")
        encoded={"value":text}
    else: encoded={"payload_bytes_b64":"ZE==" if mutation=="pad_bits_ze" else "ZB=="}
    with pytest.raises(ValueError,match="leakage"):
        scan_benchmark_v2_public_value(encoded)


def test_public_score_scanner_freezes_bounds_and_nested_decode_depth()->None:
    from app.learn.hybrid import benchmark_v2_public_score as public_score
    assert (public_score.MAX_CONTAINER_DEPTH,public_score.MAX_VISITED_NODES,public_score.MAX_STRING_UTF8_BYTES,public_score.MAX_BASE64_DECODE_DEPTH,public_score.MAX_DECODED_BYTES)==(32,100000,16777216,8,67108864)
    value:object={"value":"ok"}
    for _ in range(8): value={"canonical_bytes_b64":base64.b64encode(public_score.canonical_bytes(value)).decode("ascii")}
    public_score.scan_benchmark_v2_public_value(value)
    value={"canonical_bytes_b64":base64.b64encode(public_score.canonical_bytes(value)).decode("ascii")}
    with pytest.raises(ValueError,match="leakage"):
        public_score.scan_benchmark_v2_public_value(value)


def test_public_score_scanner_container_depth_root_convention_and_practical_bounds(monkeypatch:pytest.MonkeyPatch)->None:
    from app.learn.hybrid import benchmark_v2_public_score as public_score
    def nested(count:int)->object:
        value:object="ok"
        for _ in range(count): value={"value":value}
        return {"root":value}
    public_score.scan_benchmark_v2_public_value(nested(32))
    with pytest.raises(ValueError,match="leakage"):
        public_score.scan_benchmark_v2_public_value(nested(33))
    monkeypatch.setattr(public_score,"MAX_VISITED_NODES",3)
    with pytest.raises(ValueError,match="node"):
        public_score.scan_benchmark_v2_public_value({"a":"a","b":"b"})
    monkeypatch.setattr(public_score,"MAX_VISITED_NODES",100000)
    monkeypatch.setattr(public_score,"MAX_STRING_UTF8_BYTES",3)
    with pytest.raises(ValueError,match="string"):
        public_score.scan_benchmark_v2_public_value({"value":"four"})
    monkeypatch.setattr(public_score,"MAX_STRING_UTF8_BYTES",16777216)
    monkeypatch.setattr(public_score,"MAX_DECODED_BYTES",1)
    with pytest.raises(ValueError,match="decoded byte"):
        public_score.scan_benchmark_v2_public_value({"payload_bytes_b64":base64.b64encode(b"{} ").decode("ascii")})


def test_s3_private_score_v3_rejects_reminted_status_and_recursive_leakage(tmp_path:Path,task10_release_inputs:dict[str,Path])->None:
    import app.learn.hybrid.benchmark_scorer_v2 as scorer
    output=tmp_path/"score.json"; public_path=tmp_path/"public.json"
    run_private_scorer(private_manifest_path=task10_release_inputs["private"],prediction_run_ref_path=task10_release_inputs["accepted"],private_output_path=output,public_ref_path=public_path)
    private_score=json.loads(output.read_text(encoding="utf-8")); assert scorer._validate_private_score_artifact(private_score)["contract_version"]=="portfolio_hybrid_v1_1_private_score_v3"
    for mutation in ("status","gold_value","private_value","absolute_path","error_value","non_path_field"):
        changed=deepcopy(private_score)
        if mutation=="status": changed["gate"]["status"]="FORGED"
        elif mutation=="non_path_field": changed["gate"]["automatic_split"]="private/evidence.json"
        else: changed["score_input_binding"]["provider_manifest_ref"]["relative_path"]={"gold_value":"gold.v1.json","private_value":"private/evidence.json","absolute_path":r"C:\private\gold.json","error_value":"errors/provider-sensitive.txt"}[mutation]
        changed["content_sha256"]=hashlib.sha256(canonical_bytes({key:value for key,value in changed.items() if key!="content_sha256"})).hexdigest()
        with pytest.raises(ValueError,match="scorer"):
            scorer._validate_private_score_artifact(changed)


def _s12_inputs(*, goal: str = "Select the button labeled 'Apply now'") -> dict[str, object]:
    case = {
        "case_id": "a" * 64,
        "partition": "regression",
        "screen_group": "b" * 64,
        "goal": goal,
        "image": {"path": "screenshots/regression/a.png", "sha256": "c" * 64, "width": 1280, "height": 720},
        "layout": {"layout_id": "layout-a", "title": "A", "surface": "web", "density": "normal", "precision_case": False, "source_kind": "synthetic"},
    }
    action = {"contract_version": "available_action_v1", "id": "incumbent-action/apply-now", "label": "Apply now", "role": "button", "bbox": {"x": 10, "y": 20, "w": 40, "h": 20}}
    incumbent = {"screen_reading": {"screen_inventory": {"available_actions": [action]}}}
    item = {"source_item_id": "omni-item/apply-now", "safe_text": "Apply now", "safe_role": "button", "capture_bbox": [12, 22, 52, 42]}
    inventory = {
        "contract_version": "hybrid_omni_inventory_v1",
        "provider_result": {"items": [item]},
        "candidates": [{"candidate_id": "candidate/apply-now", "source_item_id": "omni-item/apply-now", "bbox_original": [12, 22, 52, 42], "coordinate_space": "capture_pixel_xyxy"}],
    }
    bindings = {
        "contract_version": "hybrid_qwen_bindings_v1",
        "bindings": [{"candidate_id": "candidate/apply-now", "role": "button", "label": "Apply now", "ambiguity": None}],
        "ambiguity_sets": [],
    }
    fusion = {
        "contract_version": "hybrid_fusion_result_v1",
        "candidates": [{"candidate_id": "candidate/apply-now", "bbox_original": [12, 22, 52, 42], "coordinate_space": "capture_pixel_xyxy", "state": "BOUND"}],
    }
    request = {"contract_version": "hybrid_vista_refinement_request_v1", "candidate_id": "candidate/apply-now", "submission_status": "SUBMITTED", "candidate_bbox_ref": {"xyxy": [12, 22, 52, 42]}}
    return {
        "provider_case": case,
        "incumbent_response": incumbent,
        "omni_inventory": inventory,
        "qwen_bindings": bindings,
        "fusion_result": fusion,
        "submitted_vista_requests": [request],
        "actual_screen_group_ref": ref("actual-screen-group/one"),
        "capture_ref": ref("capture/one"),
    }


def _s12_select(inputs: dict[str, object]) -> dict[str, object]:
    return select_pre_vista_prediction_rows(**inputs)


@pytest.mark.parametrize(
    ("goal_role", "provider_role"),
    [("button", "button"), ("checkbox", "checkbox"), ("combobox", "select"), ("combobox", "dropdown"), ("link", "hyperlink"), ("menuitem", "menu_item"), ("tab", "tab_item"), ("textbox", "search_input"), ("textbox", "edit")],
)
def test_s12_strict_goal_grammar_and_exact_role_aliases(goal_role: str, provider_role: str) -> None:
    inputs = _s12_inputs(goal=f"Select the {goal_role} labeled 'Apply   now'")
    inputs["incumbent_response"]["screen_reading"]["screen_inventory"]["available_actions"][0]["role"] = provider_role
    inputs["incumbent_response"]["screen_reading"]["screen_inventory"]["available_actions"][0]["label"] = " Apply now "
    inputs["omni_inventory"]["provider_result"]["items"][0]["safe_role"] = provider_role
    inputs["qwen_bindings"]["bindings"][0]["role"] = provider_role
    assert parse_benchmark_v2_goal(inputs["provider_case"]["goal"]) == (goal_role, "Apply now")
    assert all(row["selection_status"] == "selected" for row in _s12_select(inputs)["rows"])


@pytest.mark.parametrize("goal", ["select the button labeled 'Apply now'", " Select the button labeled 'Apply now'", "Select the Button labeled 'Apply now'", "Select the button labelled 'Apply now'", "Select the button labeled \"Apply now\"", "Select the button labeled ''", "Select the unknown labeled 'Apply now'"])
def test_s12_goal_grammar_rejects_non_frozen_forms(goal: str) -> None:
    with pytest.raises(ValueError, match="goal grammar"):
        parse_benchmark_v2_goal(goal)


def test_s12_arm_aware_artifacts_are_closed_and_do_not_fabricate_fusion() -> None:
    selected = _s12_select(_s12_inputs())
    rows = {row["arm_id"]: row for row in selected["rows"]}
    artifacts = {item["artifact_id"]: item for item in selected["sealed_artifacts"]}
    assert list(rows) == ["qwen_only", "omni_only_discovery", "omni_to_qwen", "omni_to_qwen_vista"]
    assert rows["qwen_only"]["candidate_id"] == "incumbent-action/apply-now"
    assert rows["omni_only_discovery"]["candidate_id"] == "candidate/apply-now"
    assert rows["omni_to_qwen"]["target_binding_ref"] == rows["omni_to_qwen_vista"]["target_binding_ref"]
    assert rows["omni_to_qwen"]["vista_request_ref"] == rows["omni_to_qwen_vista"]["vista_request_ref"]
    source_parents = [item for item in artifacts.values() if item["contract_version"] == "sealed_prediction_source_parent_v1"]
    by_kind = {item["source_kind"]: item for item in source_parents}
    assert set(by_kind["incumbent_qwen_action"]["evidence_refs"]) == {"incumbent_response_ref", "available_action_ref"}
    assert set(by_kind["omni_inventory_item"]["evidence_refs"]) == {"omni_inventory_ref", "omni_item_ref"}
    assert set(by_kind["hybrid_bound_fusion_candidate"]["evidence_refs"]) == {"omni_inventory_ref", "qwen_bindings_ref", "fusion_result_ref", "fusion_candidate_ref"}
    assert "fusion_ref" not in by_kind["incumbent_qwen_action"]["evidence_refs"]
    assert "fusion_ref" not in by_kind["omni_inventory_item"]["evidence_refs"]
    inputs = _s12_inputs()
    for raw, key, prefix, domain in (
        (inputs["omni_inventory"], "omni_inventory_ref", "omni-inventory", b"benchmark-v2-omni-inventory\0"),
        (inputs["qwen_bindings"], "qwen_bindings_ref", "qwen-bindings", b"benchmark-v2-qwen-bindings\0"),
        (inputs["fusion_result"], "fusion_result_ref", "fusion-result", b"benchmark-v2-fusion-result\0"),
    ):
        raw_bytes = canonical_bytes(raw)
        assert by_kind["hybrid_bound_fusion_candidate"]["evidence_refs"][key] == {"id": f"{prefix}/{hashlib.sha256(domain + raw_bytes).hexdigest()}", "content_sha256": hashlib.sha256(raw_bytes).hexdigest()}
    request_artifact = next(item for item in artifacts.values() if item["contract_version"] == "sealed_vista_request_v4")
    submitted_bytes = canonical_bytes(inputs["submitted_vista_requests"][0])
    submitted_identity = hashlib.sha256(b"benchmark-v2-submitted-vista-request\0" + submitted_bytes).hexdigest()
    assert request_artifact["submitted_request_ref"] == {"id": f"submitted-vista-request/{submitted_identity}", "content_sha256": hashlib.sha256(submitted_bytes).hexdigest()}
    assert request_artifact["arm_scope"] == ["omni_to_qwen", "omni_to_qwen_vista"]
    expected_fields = {
        "sealed_prediction_source_parent_v1": {"contract_version", "artifact_id", "case_ref", "arm_scope", "source_kind", "evidence_refs", "actual_screen_group_ref", "capture_ref", "safety", "content_sha256"},
        "sealed_prediction_bbox_v1": {"contract_version", "artifact_id", "case_id", "arm_scope", "candidate_id", "coordinate_space", "xyxy", "capture_ref", "source_parent_ref", "safety", "content_sha256"},
        "sealed_target_binding_v4": {"contract_version", "artifact_id", "case_id", "arm_scope", "candidate_id", "source_parent_ref", "capture_ref", "bbox_ref", "safety", "content_sha256"},
        "sealed_vista_request_v4": {"contract_version", "artifact_id", "case_id", "arm_scope", "candidate_id", "target_binding_ref", "source_parent_ref", "capture_ref", "bbox_ref", "submitted_request_ref", "submission_status", "safety", "content_sha256"},
    }
    for item in artifacts.values():
        if item["contract_version"] not in expected_fields:
            continue
        assert set(item) == expected_fields[item["contract_version"]]
        without_content = {key: value for key, value in item.items() if key != "content_sha256"}
        assert item["content_sha256"] == hashlib.sha256(canonical_bytes(without_content)).hexdigest()
        semantic = {key: value for key, value in item.items() if key not in {"artifact_id", "content_sha256"}}
        semantic_sha = hashlib.sha256(item["contract_version"].encode() + b"\0" + canonical_bytes(semantic)).hexdigest()
        assert item["artifact_id"].endswith(semantic_sha)


def test_s12_zero_matches_emit_missing_without_any_binding() -> None:
    inputs = _s12_inputs()
    inputs["provider_case"]["goal"] = "Select the button labeled 'Absent'"
    selected = _s12_select(inputs)
    assert selected["sealed_artifacts"] == []
    assert all(row == {"case_id": "a" * 64, "arm_id": row["arm_id"], "selection_status": "missing", "eligibility": "INELIGIBLE", "failure_reason": "target_not_present_pre_vista"} for row in selected["rows"])


@pytest.mark.parametrize("mutation", ["duplicate_qwen_action", "ambiguous_qwen_binding", "duplicate_request", "conflicting_fusion_bbox"])
def test_s12_ambiguity_duplicate_and_conflicting_lineage_are_fatal(mutation: str) -> None:
    inputs = _s12_inputs()
    if mutation == "duplicate_qwen_action":
        actions = inputs["incumbent_response"]["screen_reading"]["screen_inventory"]["available_actions"]
        actions.append(deepcopy(actions[0])); actions[-1]["id"] = "incumbent-action/duplicate"
    elif mutation == "ambiguous_qwen_binding": inputs["qwen_bindings"]["bindings"][0]["ambiguity"] = "duplicate semantic target"
    elif mutation == "duplicate_request": inputs["submitted_vista_requests"].append(deepcopy(inputs["submitted_vista_requests"][0]))
    else: inputs["fusion_result"]["candidates"][0]["bbox_original"] = [13, 22, 52, 42]
    with pytest.raises(ValueError, match="duplicate|ambiguous|conflicting"):
        _s12_select(inputs)


def test_s12_non_bound_hybrid_is_missing_and_not_repaired_by_vista() -> None:
    inputs = _s12_inputs(); inputs["fusion_result"]["candidates"][0]["state"] = "UNBOUND"; inputs["submitted_vista_requests"] = []
    rows = {row["arm_id"]: row for row in _s12_select(inputs)["rows"]}
    assert rows["qwen_only"]["selection_status"] == "selected" and rows["omni_only_discovery"]["selection_status"] == "selected"
    for arm in ("omni_to_qwen", "omni_to_qwen_vista"):
        assert rows[arm]["selection_status"] == "missing" and rows[arm]["failure_reason"] == "fusion_not_bound"


@pytest.mark.parametrize(("proposal", "expected"), [
    ({"status": "PROPOSED", "candidate_id": "candidate/apply-now", "canonical_point": {"coordinate_space": "capture_pixel_xyxy", "xy": [20, 30]}}, "validated"),
    ({"status": "VISTA_FAILED", "candidate_id": "candidate/apply-now", "failure_category": "request_timeout"}, "timeout"),
    ({"status": "VISTA_FAILED", "candidate_id": "candidate/apply-now", "failure_category": "provider_error"}, "failed"),
    ({"status": "VISTA_OUT_OF_BOUNDS", "candidate_id": "candidate/apply-now"}, "out_of_bounds"),
    ({"status": "TRANSFORM_INVALID", "candidate_id": "candidate/apply-now"}, "failed"),
])
def test_s12_attach_vista_outcome_cannot_change_pre_vista_selection(proposal: dict[str, object], expected: str) -> None:
    selected = _s12_select(_s12_inputs()); before = deepcopy(selected)
    vista_row = next(row for row in selected["rows"] if row["arm_id"] == "omni_to_qwen_vista")
    request_artifact = next(item for item in selected["sealed_artifacts"] if {"id": item["artifact_id"], "content_sha256": item["content_sha256"]} == vista_row["vista_request_ref"])
    proposal["submitted_request_ref"] = deepcopy(request_artifact["submitted_request_ref"])
    attached = attach_vista_outcomes(selected, [proposal])
    assert attached["sealed_artifacts"] == before["sealed_artifacts"]
    for old, new in zip(before["rows"], attached["rows"], strict=True):
        for field in ("candidate_id", "source_parent_ref", "bbox_ref", "target_binding_ref", "vista_request_ref"):
            assert new.get(field) == old.get(field)
    attached_vista = next(row for row in attached["rows"] if row["arm_id"] == "omni_to_qwen_vista")
    assert attached_vista["vista_result"]["status"] == expected
    assert "vista_result" not in next(row for row in attached["rows"] if row["arm_id"] == "omni_to_qwen")


def test_s12_attach_missing_and_mismatched_vista_results_fail_closed() -> None:
    selected = _s12_select(_s12_inputs())
    attached = attach_vista_outcomes(selected, [])
    assert next(row for row in attached["rows"] if row["arm_id"] == "omni_to_qwen_vista")["vista_result"]["status"] == "missing"
    selected_row = next(row for row in selected["rows"] if row["arm_id"] == "omni_to_qwen_vista")
    request_artifact = next(item for item in selected["sealed_artifacts"] if {"id": item["artifact_id"], "content_sha256": item["content_sha256"]} == selected_row["vista_request_ref"])
    wrong = {"status": "PROPOSED", "candidate_id": "candidate/wrong", "submitted_request_ref": request_artifact["submitted_request_ref"], "canonical_point": {"coordinate_space": "capture_pixel_xyxy", "xy": [20, 30]}}
    with pytest.raises(ValueError, match="different candidate"):
        attach_vista_outcomes(selected, [wrong])


def test_s12_attach_rejects_unknown_and_duplicate_selected_results() -> None:
    selected = _s12_select(_s12_inputs())
    row = next(item for item in selected["rows"] if item["arm_id"] == "omni_to_qwen_vista")
    request = next(item for item in selected["sealed_artifacts"] if artifact_ref(item) == row["vista_request_ref"])
    proposal = {"status": "UNKNOWN", "candidate_id": row["candidate_id"], "submitted_request_ref": request["submitted_request_ref"]}
    with pytest.raises(ValueError, match="unknown VISTA"):
        attach_vista_outcomes(selected, [proposal])
    proposal["status"] = "VISTA_FAILED"
    with pytest.raises(ValueError, match="multiple VISTA"):
        attach_vista_outcomes(selected, [proposal, deepcopy(proposal)])


def test_s12_attach_accepts_validated_native_proposal_without_fabricating_request_ref() -> None:
    selected = _s12_select(_s12_inputs())
    native = {
        "contract_version": "hybrid_vista_refinement_proposal_v1",
        "status": "VISTA_FAILED",
        "candidate_id": "candidate/apply-now",
        "candidate_bbox_ref": {"xyxy": [12, 22, 52, 42]},
        "raw_provider_result": {"failure_category": "request_timeout"},
    }
    result = attach_vista_outcomes(selected, [native])
    assert next(row for row in result["rows"] if row["arm_id"] == "omni_to_qwen_vista")["vista_result"]["status"] == "timeout"


def test_s12_attach_rejects_reminted_selection_artifact() -> None:
    selected = _s12_select(_s12_inputs())
    selected["sealed_artifacts"][0]["content_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="content identity"):
        attach_vista_outcomes(selected, [])


def test_s12_selector_requires_incumbent_response_and_cannot_accept_vista_results() -> None:
    signature = inspect.signature(select_pre_vista_prediction_rows)
    assert signature.parameters["incumbent_response"].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.parameters["incumbent_response"].default is inspect.Parameter.empty
    assert not {"vista_proposals", "vista_results", "vista_result"} & set(signature.parameters)


@pytest.mark.parametrize(("safe_role", "safe_text"), [(None, "decorative flourish"), ("text", ""), (None, "")])
def test_s12_non_target_omni_items_without_semantics_do_not_block_selection(safe_role: object, safe_text: object) -> None:
    inputs = _s12_inputs()
    inputs["omni_inventory"]["provider_result"]["items"].append({"source_item_id": "omni-item/decorative", "safe_text": safe_text, "safe_role": safe_role, "capture_bbox": [100, 100, 120, 120]})
    inputs["omni_inventory"]["candidates"].append({"candidate_id": "candidate/decorative", "source_item_id": "omni-item/decorative", "bbox_original": [100, 100, 120, 120], "coordinate_space": "capture_pixel_xyxy"})
    assert all(row["selection_status"] == "selected" for row in _s12_select(inputs)["rows"])


@pytest.mark.parametrize("unsafe_id", [r"C:\Users\tester\capture.json", "/tmp/capture.json", "file:///tmp/capture.json", "capture/../escape", r"capture\..\escape"])
@pytest.mark.parametrize("boundary", ["actual_screen_group_ref", "capture_ref", "action_id", "candidate_id"])
def test_s12_public_identifiers_reject_filesystem_and_alias_escape(unsafe_id: str, boundary: str) -> None:
    inputs = _s12_inputs()
    if boundary in {"actual_screen_group_ref", "capture_ref"}:
        inputs[boundary]["id"] = unsafe_id
    elif boundary == "action_id":
        inputs["incumbent_response"]["screen_reading"]["screen_inventory"]["available_actions"][0]["id"] = unsafe_id
    else:
        inputs["omni_inventory"]["candidates"][0]["candidate_id"] = unsafe_id
        inputs["qwen_bindings"]["bindings"][0]["candidate_id"] = unsafe_id
        inputs["fusion_result"]["candidates"][0]["candidate_id"] = unsafe_id
        inputs["submitted_vista_requests"][0]["candidate_id"] = unsafe_id
    with pytest.raises(ValueError, match="public identifier"):
        _s12_select(inputs)
