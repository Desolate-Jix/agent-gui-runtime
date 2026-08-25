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

def seal_target_binding(*,artifact_id:str,case_id:str,target_id:str,candidate_id:str,fusion_ref:Mapping[str,str],capture_ref:Mapping[str,str],bbox_ref:Mapping[str,str],bbox:list[int],source_parent_ref:Mapping[str,str])->dict[str,object]:
    if len(bbox)!=4 or not all(isinstance(v,int) for v in bbox): raise ValueError("bbox invalid")
    value={"contract_version":"sealed_target_binding_v2","artifact_id":artifact_id,"case_id":case_id,"target_id":target_id,"candidate_id":candidate_id,"fusion_ref":exact_ref(fusion_ref,"fusion"),"capture_ref":exact_ref(capture_ref,"capture"),"bbox_ref":exact_ref(bbox_ref,"bbox"),"bbox":list(bbox),"source_parent_ref":exact_ref(source_parent_ref,"parent"),"safety":deepcopy(SAFETY)}
    if not all(isinstance(value[k],str) and value[k] for k in ("artifact_id","case_id","target_id","candidate_id")): raise ValueError("binding identity invalid")
    return value

def seal_vista_request(*,artifact_id:str,case_id:str,target_id:str,target_binding_ref:Mapping[str,str],candidate_id:str,fusion_ref:Mapping[str,str],capture_ref:Mapping[str,str],bbox_ref:Mapping[str,str],source_parent_ref:Mapping[str,str])->dict[str,object]:
    return {"contract_version":"sealed_vista_request_v2","artifact_id":artifact_id,"case_id":case_id,"target_id":target_id,"target_binding_ref":exact_ref(target_binding_ref,"binding"),"candidate_id":candidate_id,"fusion_ref":exact_ref(fusion_ref,"fusion"),"capture_ref":exact_ref(capture_ref,"capture"),"bbox_ref":exact_ref(bbox_ref,"bbox"),"submission_status":"SUBMITTED","source_parent_ref":exact_ref(source_parent_ref,"parent"),"safety":deepcopy(SAFETY)}

def _validate_pre(pre: Mapping[str,object])->dict[str,object]:
    if set(pre)!={"contract_version","artifact_id","prediction_id","source_parent_ref","partition","release_id","rows","safety"} or pre["contract_version"]!="automatic_prediction_v2" or pre["safety"]!=SAFETY: raise ValueError("automatic prediction artifact not closed")
    exact_ref(pre["source_parent_ref"],"prediction parent")
    if pre["partition"] not in {"regression","holdout"}: raise ValueError("partition invalid")
    rows=pre["rows"]
    if not isinstance(rows,list) or not rows: raise ValueError("automatic rows empty")
    keys=set(); checked=[]
    for raw in rows:
        if not isinstance(raw,Mapping): raise ValueError("automatic row invalid")
        row=deepcopy(dict(raw)); base={"case_id","arm_id","selection_status"}
        if not base.issubset(row) or row["arm_id"] not in ARMS or row["selection_status"] not in STATUSES: raise ValueError("automatic row identity invalid")
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
    value=deepcopy(dict(pre)); value["rows"]=checked
    return value

def seal_automatic_prediction(*,request_ref:Mapping[str,str],pre_review:Mapping[str,object],execution_refs:list[Mapping[str,str]],lifecycle_ref:Mapping[str,str])->dict[str,object]:
    artifact=_validate_pre(pre_review); pre_ref=artifact_ref(artifact)
    record={"contract_version":"automatic_prediction_record_v2","prediction_id":artifact["prediction_id"],"request_ref":exact_ref(request_ref,"request"),"pre_review_ref":pre_ref,"execution_refs":[exact_ref(x,"execution") for x in execution_refs],"lifecycle_ref":exact_ref(lifecycle_ref,"lifecycle"),"decisions":[],"post_review_ref":pre_ref,"safety":deepcopy(SAFETY)}
    record["revision_ref"]={"id":"prediction-revision/0","content_sha256":hashlib.sha256(canonical_bytes(record)).hexdigest()}
    return {"record":record,"pre_review_artifact":sealed_artifact_envelope(artifact)}

def append_review_decisions(record:Mapping[str,object],decisions:list[Mapping[str,object]],*,pre_review_artifact_bytes:bytes,expected_pre_review_ref:Mapping[str,str])->dict[str,object]:
    value=deepcopy(dict(record)); expected=exact_ref(expected_pre_review_ref,"expected pre-review")
    if value.get("pre_review_ref")!=expected or hashlib.sha256(pre_review_artifact_bytes).hexdigest()!=expected["content_sha256"]: raise ValueError("external pre-review anchor mismatch")
    artifact=json.loads(pre_review_artifact_bytes.decode("utf-8"))
    if canonical_bytes(artifact)!=pre_review_artifact_bytes or artifact_ref(artifact)!=expected: raise ValueError("pre-review CAS bytes invalid")
    _validate_pre(artifact)
    existing={d["decision_id"]:d for d in value["decisions"]}
    for raw in decisions:
        item=deepcopy(dict(raw)); prior=existing.get(item.get("decision_id"))
        if prior is not None:
            if prior!=item: raise ValueError("decision rewrite")
            continue
        if set(item)!={"decision_id","predecessor_ref","target_binding_ref","disposition","replacement_candidate_id"} or item["predecessor_ref"]!=value["revision_ref"]: raise ValueError("decision predecessor invalid")
        value["decisions"].append(item); existing[item["decision_id"]]=item
        value["post_review_ref"]={"id":f"post-review/{len(value['decisions'])}","content_sha256":hashlib.sha256(canonical_bytes({"pre_review_ref":expected,"decisions":value["decisions"]})).hexdigest()}
        draft={k:v for k,v in value.items() if k!="revision_ref"}
        value["revision_ref"]={"id":f"prediction-revision/{len(value['decisions'])}","content_sha256":hashlib.sha256(canonical_bytes(draft)).hexdigest()}
    return value
