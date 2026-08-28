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


def _selected_accepted_input(path:Path,provider_cases:list[dict[str,object]],private_cases:list[dict[str,object]],release:dict[str,object])->None:
    from app.learn.hybrid import benchmark_v2_predictions as predictions
    accepted=json.loads(path.read_text(encoding="utf-8")); run=json.loads(base64.b64decode(accepted["prediction_run_envelope"]["canonical_bytes_b64"],validate=True))
    children=deepcopy(run["sealed_artifact_envelopes"]); automatic_index=next(index for index,envelope in enumerate(children) if json.loads(base64.b64decode(envelope["canonical_bytes_b64"],validate=True)).get("contract_version")=="automatic_prediction_v3")
    automatic=json.loads(base64.b64decode(children[automatic_index]["canonical_bytes_b64"],validate=True))
    provider=sorted((case for case in provider_cases if case["partition"]=="regression"),key=lambda case:str(case["case_id"]))[0]
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
    return {"private":private_path,"accepted":accepted_path}

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
