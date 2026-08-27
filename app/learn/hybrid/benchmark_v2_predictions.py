"""Sealed public evidence contracts for Benchmark-v2 automatic predictions."""
from __future__ import annotations
import base64
from copy import deepcopy
import hashlib
import json
from typing import Any, Mapping

SAFETY={"artifact_is_authorization":False,"execute_binding_enabled":False,"display_only":True}
ARMS=("qwen_only","omni_only_discovery","omni_to_qwen","omni_to_qwen_vista")
STATUSES={"selected","missing","failed"}
ELIGIBILITY={"selected":"ELIGIBLE","missing":"INELIGIBLE","failed":"INELIGIBLE"}


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")

def artifact_ref(artifact: Mapping[str,object]) -> dict[str,str]:
    raw=canonical_bytes(artifact)
    return {"id":str(artifact["artifact_id"]),"content_sha256":hashlib.sha256(raw).hexdigest()}

def sealed_artifact_envelope(artifact: Mapping[str,object]) -> dict[str,object]:
    raw=canonical_bytes(artifact)
    return {"ref":artifact_ref(artifact),"canonical_bytes_b64":base64.b64encode(raw).decode("ascii")}

def exact_ref(value: object,name: str) -> dict[str,str]:
    if not isinstance(value,Mapping) or set(value)!={"id","content_sha256"}: raise ValueError(f"{name} must be exact ref")
    result=dict(value)
    if not isinstance(result["id"],str) or not result["id"] or not isinstance(result["content_sha256"],str) or len(result["content_sha256"])!=64: raise ValueError(f"{name} invalid")
    return result

def seal_target_binding(*,artifact_id:str,case_id:str,candidate_id:str,fusion_ref:Mapping[str,str],capture_ref:Mapping[str,str],bbox_ref:Mapping[str,str],bbox:list[int],source_parent_ref:Mapping[str,str])->dict[str,object]:
    if len(bbox)!=4 or not all(isinstance(v,int) for v in bbox): raise ValueError("bbox invalid")
    value={"contract_version":"sealed_target_binding_v3","artifact_id":artifact_id,"case_id":case_id,"candidate_id":candidate_id,"fusion_ref":exact_ref(fusion_ref,"fusion"),"capture_ref":exact_ref(capture_ref,"capture"),"bbox_ref":exact_ref(bbox_ref,"bbox"),"bbox":list(bbox),"source_parent_ref":exact_ref(source_parent_ref,"parent"),"safety":deepcopy(SAFETY)}
    if not all(isinstance(value[k],str) and value[k] for k in ("artifact_id","case_id","candidate_id")): raise ValueError("binding identity invalid")
    return value

def seal_vista_request(*,artifact_id:str,case_id:str,target_binding_ref:Mapping[str,str],candidate_id:str,fusion_ref:Mapping[str,str],capture_ref:Mapping[str,str],bbox_ref:Mapping[str,str],source_parent_ref:Mapping[str,str])->dict[str,object]:
    if not all(isinstance(value,str) and value for value in (artifact_id,case_id,candidate_id)): raise ValueError("request identity invalid")
    return {"contract_version":"sealed_vista_request_v3","artifact_id":artifact_id,"case_id":case_id,"target_binding_ref":exact_ref(target_binding_ref,"binding"),"candidate_id":candidate_id,"fusion_ref":exact_ref(fusion_ref,"fusion"),"capture_ref":exact_ref(capture_ref,"capture"),"bbox_ref":exact_ref(bbox_ref,"bbox"),"submission_status":"SUBMITTED","source_parent_ref":exact_ref(source_parent_ref,"parent"),"safety":deepcopy(SAFETY)}

def _validate_pre(pre: Mapping[str,object])->dict[str,object]:
    if set(pre)!={"contract_version","artifact_id","prediction_id","source_parent_ref","partition","release_id","rows","safety"} or pre["contract_version"]!="automatic_prediction_v2" or pre["safety"]!=SAFETY: raise ValueError("automatic prediction artifact not closed")
    exact_ref(pre["source_parent_ref"],"prediction parent")
    if pre["partition"] not in {"regression","holdout"}: raise ValueError("partition invalid")
    rows=pre["rows"]
    if not isinstance(rows,list) or not rows: raise ValueError("automatic rows empty")
    keys=set(); checked=[]
    for raw in rows:
        if not isinstance(raw,Mapping): raise ValueError("automatic row invalid")
        row=deepcopy(dict(raw)); base={"case_id","arm_id","selection_status","eligibility"}
        if not base.issubset(row) or row["arm_id"] not in ARMS or row["selection_status"] not in STATUSES: raise ValueError("automatic row identity invalid")
        if row["eligibility"]!=ELIGIBILITY[row["selection_status"]]: raise ValueError("automatic row eligibility invalid")
        key=(row["case_id"],row["arm_id"])
        if key in keys: raise ValueError("duplicate automatic arm/case")
        keys.add(key)
        if row["selection_status"]=="selected":
            allowed=base|{"target_binding_ref","vista_request_ref","vista_result"}
            exact_ref(row.get("target_binding_ref"),"row binding")
            if row["arm_id"] in {"omni_to_qwen","omni_to_qwen_vista"}: exact_ref(row.get("vista_request_ref"),"row request")
            elif "vista_request_ref" in row: raise ValueError("non-pair arm cannot carry VISTA request")
            if row["arm_id"]=="omni_to_qwen_vista":
                result=row.get("vista_result")
                if not isinstance(result,Mapping) or set(result)-{"status","request_ref","target_binding_ref","canonical_capture_pixel_point"} or result.get("status") not in {"validated","failed","timeout","out_of_bounds","missing"}: raise ValueError("VISTA result invalid")
                exact_ref(result.get("request_ref"),"result request"); exact_ref(result.get("target_binding_ref"),"result binding")
            elif "vista_result" in row: raise ValueError("only VISTA arm may carry result")
        else:
            allowed=base|{"failure_reason"}
            if not isinstance(row.get("failure_reason"),str) or not row["failure_reason"]: raise ValueError("missing/failed selection requires reason")
        if set(row)-allowed: raise ValueError("automatic row has extra fields")
        checked.append(row)
    by={(row["case_id"],row["arm_id"]):row for row in checked}
    for case_id in {row["case_id"] for row in checked}:
        baseline=by.get((case_id,"omni_to_qwen")); vista=by.get((case_id,"omni_to_qwen_vista"))
        if baseline is None or vista is None: continue
        if baseline["selection_status"]!=vista["selection_status"] or baseline["eligibility"]!=vista["eligibility"]: raise ValueError("paired arm eligibility mismatch")
        if baseline["selection_status"]=="selected":
            if baseline["target_binding_ref"]!=vista["target_binding_ref"] or baseline["vista_request_ref"]!=vista["vista_request_ref"]: raise ValueError("selected pair evidence mismatch")
        elif baseline["failure_reason"]!=vista["failure_reason"]:
            raise ValueError("ineligible pair reason mismatch")
    value=deepcopy(dict(pre)); value["rows"]=checked
    return value

def seal_automatic_prediction(*,request_ref:Mapping[str,str],pre_review:Mapping[str,object],execution_refs:list[Mapping[str,str]],lifecycle_ref:Mapping[str,str])->dict[str,object]:
    artifact=_validate_pre(pre_review); pre_ref=artifact_ref(artifact)
    record={"contract_version":"automatic_prediction_record_v2","prediction_id":artifact["prediction_id"],"request_ref":exact_ref(request_ref,"request"),"pre_review_ref":pre_ref,"execution_refs":[exact_ref(x,"execution") for x in execution_refs],"lifecycle_ref":exact_ref(lifecycle_ref,"lifecycle"),"decisions":[],"post_review_ref":pre_ref,"safety":deepcopy(SAFETY)}
    record["revision_ref"]={"id":"prediction-revision/0","content_sha256":hashlib.sha256(canonical_bytes(record)).hexdigest()}
    return {"record":record,"record_ref":prediction_record_ref(record),"pre_review_artifact":sealed_artifact_envelope(artifact)}

def prediction_record_ref(record:Mapping[str,object])->dict[str,str]:
    prediction_id=record.get("prediction_id")
    if not isinstance(prediction_id,str) or not prediction_id: raise ValueError("prediction record identity invalid")
    return {"id":f"prediction-record/{prediction_id}","content_sha256":hashlib.sha256(canonical_bytes(record)).hexdigest()}

def seal_review_decision(*,predecessor_ref:Mapping[str,str],target_binding_ref:Mapping[str,str],disposition:str,replacement_candidate_id:str|None)->dict[str,object]:
    if disposition not in {"accepted","corrected","rejected"}: raise ValueError("review disposition invalid")
    if (disposition=="corrected") != (isinstance(replacement_candidate_id,str) and bool(replacement_candidate_id)): raise ValueError("review replacement semantics invalid")
    payload={"contract_version":"automatic_review_decision_v2","decision_type":"candidate_review","predecessor_ref":exact_ref(predecessor_ref,"decision predecessor"),"target_binding_ref":exact_ref(target_binding_ref,"decision binding"),"disposition":disposition,"replacement_candidate_id":replacement_candidate_id}
    digest=hashlib.sha256(canonical_bytes(payload)).hexdigest()
    return {**payload,"decision_id":f"review-decision/{digest}","content_sha256":digest}

def _validate_decision(raw:object,predecessor_ref:Mapping[str,str],allowed_bindings:set[bytes])->dict[str,object]:
    if not isinstance(raw,Mapping): raise ValueError("decision invalid")
    fields={"contract_version","decision_id","decision_type","predecessor_ref","target_binding_ref","disposition","replacement_candidate_id","content_sha256"}
    item=deepcopy(dict(raw))
    if set(item)!=fields or item["contract_version"]!="automatic_review_decision_v2" or item["decision_type"]!="candidate_review" or item["predecessor_ref"]!=predecessor_ref: raise ValueError("decision schema/type/predecessor invalid")
    if canonical_bytes(exact_ref(item["target_binding_ref"],"decision binding")) not in allowed_bindings: raise ValueError("decision binding is not in pre-review")
    if item["disposition"] not in {"accepted","corrected","rejected"} or (item["disposition"]=="corrected") != (isinstance(item["replacement_candidate_id"],str) and bool(item["replacement_candidate_id"])): raise ValueError("decision semantics invalid")
    payload={k:item[k] for k in ("contract_version","decision_type","predecessor_ref","target_binding_ref","disposition","replacement_candidate_id")}
    digest=hashlib.sha256(canonical_bytes(payload)).hexdigest()
    if item["content_sha256"]!=digest or item["decision_id"]!=f"review-decision/{digest}": raise ValueError("decision content identity invalid")
    return item

def _advance_review_record(value:dict[str,object],item:dict[str,object],expected_pre:Mapping[str,str])->None:
    value["decisions"].append(item)
    index=len(value["decisions"])
    value["post_review_ref"]={"id":f"post-review/{index}","content_sha256":hashlib.sha256(canonical_bytes({"pre_review_ref":expected_pre,"decisions":value["decisions"]})).hexdigest()}
    value["revision_ref"]={"id":f"prediction-revision/{index}","content_sha256":hashlib.sha256(canonical_bytes({k:v for k,v in value.items() if k!="revision_ref"})).hexdigest()}

def _validate_existing_record(record:Mapping[str,object],artifact:Mapping[str,object],expected_pre:Mapping[str,str])->dict[str,object]:
    fields={"contract_version","prediction_id","request_ref","pre_review_ref","execution_refs","lifecycle_ref","decisions","post_review_ref","safety","revision_ref"}
    if set(record)!=fields or record["contract_version"]!="automatic_prediction_record_v2" or record["prediction_id"]!=artifact["prediction_id"] or record["pre_review_ref"]!=expected_pre or record["safety"]!=SAFETY: raise ValueError("prediction record not closed")
    exact_ref(record["request_ref"],"request"); exact_ref(record["lifecycle_ref"],"lifecycle")
    if not isinstance(record["execution_refs"],list): raise ValueError("execution refs invalid")
    for item in record["execution_refs"]: exact_ref(item,"execution")
    allowed_bindings={canonical_bytes(row["target_binding_ref"]) for row in artifact["rows"] if row["selection_status"]=="selected"}
    current={k:deepcopy(v) for k,v in record.items() if k not in {"decisions","post_review_ref","revision_ref"}}
    current["decisions"]=[]; current["post_review_ref"]=deepcopy(expected_pre)
    current["revision_ref"]={"id":"prediction-revision/0","content_sha256":hashlib.sha256(canonical_bytes({k:v for k,v in current.items() if k!="revision_ref"})).hexdigest()}
    seen=set()
    raw_decisions=record["decisions"]
    if not isinstance(raw_decisions,list): raise ValueError("decision chain invalid")
    for index,raw in enumerate(raw_decisions,1):
        item=_validate_decision(raw,current["revision_ref"],allowed_bindings)
        if item["decision_id"] in seen: raise ValueError("duplicate decision identity")
        seen.add(item["decision_id"]); _advance_review_record(current,item,expected_pre)
    if current!=record: raise ValueError("existing prediction record derived state invalid")
    return current

def append_review_decisions(record:Mapping[str,object],decisions:list[Mapping[str,object]],*,pre_review_artifact_bytes:bytes,expected_pre_review_ref:Mapping[str,str],expected_record_ref:Mapping[str,str])->dict[str,object]:
    value=deepcopy(dict(record)); expected=exact_ref(expected_pre_review_ref,"expected pre-review")
    if prediction_record_ref(value)!=exact_ref(expected_record_ref,"expected record"): raise ValueError("external attempt record anchor mismatch")
    if value.get("pre_review_ref")!=expected or hashlib.sha256(pre_review_artifact_bytes).hexdigest()!=expected["content_sha256"]: raise ValueError("external pre-review anchor mismatch")
    artifact=json.loads(pre_review_artifact_bytes.decode("utf-8"))
    if canonical_bytes(artifact)!=pre_review_artifact_bytes or artifact_ref(artifact)!=expected: raise ValueError("pre-review CAS bytes invalid")
    artifact=_validate_pre(artifact)
    value=_validate_existing_record(value,artifact,expected)
    existing={d["decision_id"]:d for d in value["decisions"]}
    allowed_bindings={canonical_bytes(row["target_binding_ref"]) for row in artifact["rows"] if row["selection_status"]=="selected"}
    for raw in decisions:
        prior=existing.get(raw.get("decision_id")) if isinstance(raw,Mapping) else None
        item=_validate_decision(raw,prior["predecessor_ref"] if prior is not None else value["revision_ref"],allowed_bindings)
        if prior is not None:
            if prior!=item: raise ValueError("decision rewrite")
            continue
        _advance_review_record(value,item,expected); existing[item["decision_id"]]=item
    return _validate_existing_record(value,artifact,expected)
