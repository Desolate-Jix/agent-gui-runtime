"""Create and verify a sealed, regression-only Omni candidate snapshot."""
from __future__ import annotations
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
import json, os, re, stat
from pathlib import Path
from typing import Mapping, Sequence
from PIL import Image
from app.learn.hybrid.simple_native_contracts import parse_omni_native_output
from app.learn.hybrid.contracts import stable_candidate_id
from app.learn.hybrid.simple_native_smoke import OmniNativeCaller, ProviderCase, _hash as _native_hash, _parse_provider_goals, _prepare_capture, _verify_capture_freshness, build_omni_evidence_from_native
from app.learn.recognition.uei.canonical import content_sha256
_CASE_IDS=tuple(f"case-{i:03d}" for i in range(1,6))
_IDENTITY_KEYS=frozenset({"provider_id","profile_id","model_revision","preprocessing_revision"})
_DATA_PATH=re.compile(r"(?<![a-z0-9])(gold|holdout)(?![a-z0-9])",re.I)
_SHA=re.compile(r"\A[0-9a-f]{64}\Z"); _CID=re.compile(r"\Acandidate/[0-9a-f]{64}\Z")
def _canonical_bytes(value: object)->bytes: return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode("utf-8")
def _sha(value: bytes)->str: return sha256(value).hexdigest()
def _hash(value: object)->str: return _sha(_canonical_bytes(value))
def _no_constant(value: str)->None: raise ValueError(f"non-finite JSON constant {value!r}")
def _read(path: Path,*,label:str)->dict[str,object]:
 try: raw=path.read_bytes(); value=json.loads(raw.decode("utf-8"),parse_constant=_no_constant)
 except (OSError,UnicodeDecodeError,ValueError,json.JSONDecodeError) as exc: raise ValueError(f"{label} is not valid finite UTF-8 JSON") from exc
 if not isinstance(value,dict) or raw!=_canonical_bytes(value): raise ValueError(f"{label} is not canonical JSON")
 return value
def _closed(value:Mapping[str,object],keys:set[str],*,label:str)->None:
 if set(value)!=keys: raise ValueError(f"{label} has closed-contract key mismatch")
def _forbidden(value:object,*,label:str,key:str|None=None)->None:
 safe_false={"contains_holdout","artifact_is_authorization","regression_only"}
 safe_true={"final_submit_forbidden"}
 control={"action_authorized","approved_to_click","approved_to_execute","click_authorized","execute","final_submit","submit_authorized","action_authority","click_authority","review_authority"}
 if key is not None:
  folded=key.casefold()
  if key in safe_false:
   if value is not (key=="regression_only"): raise ValueError(f"{label} violates safe declaration")
   return
  if key in safe_true:
   if value is not True: raise ValueError(f"{label} violates safe declaration")
   return
  if "gold" in folded or "holdout" in folded or key in control: raise ValueError(f"{label} includes forbidden semantic")
  if folded.endswith("path") and isinstance(value,str) and _DATA_PATH.search(value) is not None: raise ValueError(f"{label} includes forbidden semantic")
 if isinstance(value,Mapping):
  for k,v in value.items():
   if not isinstance(k,str): raise ValueError(f"{label} has non-string key")
   _forbidden(v,label=label,key=k)
 elif isinstance(value,list):
  for v in value: _forbidden(v,label=label)

def _cases(cases:Sequence[ProviderCase])->tuple[ProviderCase,...]:
 result=tuple(cases)
 if len(result)!=5 or tuple(c.case_id for c in result)!=_CASE_IDS: raise ValueError("Omni snapshot requires exactly case-001 through case-005")
 if any(len(c.goals)!=5 for c in result) or sum(len(c.goals) for c in result)!=25: raise ValueError("Omni snapshot requires exactly five goals per case and 25 goals")
 for c in result: _parse_provider_goals(c); _forbidden(list(c.goals),label="provider goals")
 return result
def _identity(value:Mapping[str,object])->dict[str,object]:
 result=deepcopy(dict(value))
 if set(result)!=_IDENTITY_KEYS or not all(isinstance(result[k],str) and result[k] for k in _IDENTITY_KEYS): raise ValueError("Omni snapshot provider identity is incomplete")
 _forbidden(result,label="provider identity"); return result
def _reparse(path:Path)->bool:
 try: return path.is_symlink() or bool(path.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
 except (AttributeError,OSError): return path.is_symlink()
def _safe(path:Path,*,label:str)->None:
 if _reparse(path): raise ValueError(f"{label} must not be a symlink or reparse point")
def _safe_ancestors(path:Path,*,label:str)->None:
 for part in (path.absolute(),*path.absolute().parents):
  if os.path.lexists(part): _safe(part,label=label)
def _new_dir(path:Path)->Path:
 result=path.absolute(); _safe_ancestors(result.parent,label="Omni snapshot output parent")
 if os.path.lexists(result): raise ValueError("Omni snapshot output directory already exists")
 result.mkdir(); _safe(result,label="Omni snapshot output directory"); return result
def _file(root:Path,name:str,*,label:str)->Path:
 if Path(name).name!=name or Path(name).is_absolute(): raise ValueError(f"{label} filename mismatch")
 result=root/name
 if not os.path.lexists(result) or not result.is_file(): raise ValueError(f"{label} is unavailable")
 _safe(result,label=label)
 if result.lstat().st_nlink != 1: raise ValueError(f"{label} must not have hardlink aliases")
 try: common=os.path.commonpath([str(root.resolve(strict=True)),str(result.resolve(strict=True))])
 except OSError as exc: raise ValueError(f"{label} cannot resolve") from exc
 if common!=str(root.resolve(strict=True)): raise ValueError(f"{label} escapes snapshot directory")
 return result
def _write(path:Path,value:object)->None:
 _safe(path.parent,label="Omni snapshot parent")
 with path.open("xb") as f: f.write(_canonical_bytes(value)); f.flush(); os.fsync(f.fileno())
def _replace(path:Path,value:object)->None:
 temp=path.with_name(path.name+".tmp"); _write(temp,value); os.replace(temp,path)
def _journal(*,state:str,completed:list[str],next_case:str|None,error:str|None,manifest_sha:str|None)->dict[str,object]: return {"contract_version":"omni_snapshot_creation_journal_v1","state":state,"completed_case_ids":completed,"next_case_id":next_case,"error":error,"manifest_content_sha256":manifest_sha}
def _ref(value:object,*,label:str)->dict[str,str]:
 if not isinstance(value,Mapping): raise ValueError(f"{label} is invalid")
 result=dict(value); _closed(result,{"id","content_sha256"},label=label)
 if not isinstance(result["id"],str) or not isinstance(result["content_sha256"],str) or not _SHA.fullmatch(result["content_sha256"]): raise ValueError(f"{label} is invalid")
 return {"id":result["id"],"content_sha256":result["content_sha256"]}
def _capture(value:object,*,label:str)->dict[str,object]:
 if not isinstance(value,Mapping): raise ValueError(f"{label} is invalid")
 result=deepcopy(dict(value)); _closed(result,{"capture_id","screenshot_sha256","image_size","capture_lineage_ref"},label=label); size=result["image_size"]
 if not isinstance(result["capture_id"],str) or not isinstance(result["screenshot_sha256"],str) or not _SHA.fullmatch(result["screenshot_sha256"]) or not isinstance(size,Mapping) or set(size)!={"width","height"} or any(isinstance(size[k],bool) or not isinstance(size[k],int) or size[k]<=0 for k in ("width","height")): raise ValueError(f"{label} is invalid")
 result["capture_lineage_ref"]=_ref(result["capture_lineage_ref"],label=f"{label} lineage"); return result
def _candidates(value:object,*,size:Mapping[str,object])->tuple[list[dict[str,object]],list[dict[str,object]]]:
 if not isinstance(value,list): raise ValueError("Omni snapshot candidates are invalid")
 w,h=size["width"],size["height"]; assert isinstance(w,int) and isinstance(h,int)
 items=[]; geometry=[]; ids=set(); keys={"active","bbox_original","candidate_id","confidence","coordinate_space","inactive_reason","provenance","provider_result_ref","source_item_id"}
 for raw in value:
  if not isinstance(raw,Mapping): raise ValueError("Omni snapshot candidate is invalid")
  item=deepcopy(dict(raw)); _closed(item,keys,label="Omni snapshot candidate"); box=item["bbox_original"]; cid=item["candidate_id"]
  if not isinstance(cid,str) or not _CID.fullmatch(cid) or cid in ids or not isinstance(box,list) or len(box)!=4 or any(isinstance(v,bool) or not isinstance(v,int) for v in box) or not(0<=box[0]<box[2]<=w and 0<=box[1]<box[3]<=h) or item["coordinate_space"]!="capture_pixel_xyxy" or not isinstance(item["active"],bool) or item["confidence"] is not None or not isinstance(item["source_item_id"],str) or (item["active"] is True and item["inactive_reason"] is not None) or (item["active"] is False and item["inactive_reason"] != "provider_reported_inactive"): raise ValueError("Omni snapshot candidate geometry is invalid")
  item["provider_result_ref"]=_ref(item["provider_result_ref"],label="Omni snapshot provider result ref")
  if not isinstance(item["provenance"],Mapping): raise ValueError("Omni snapshot candidate provenance is invalid")
  p=deepcopy(dict(item["provenance"])); _closed(p,{"contract_version","content_sha256","provider_result_ref","source_item_id"},label="Omni snapshot candidate provenance")
  p["provider_result_ref"]=_ref(p["provider_result_ref"],label="Omni snapshot candidate provenance ref")
  if p["contract_version"]!="hybrid_candidate_provenance_v1" or p["source_item_id"]!=item["source_item_id"] or p["provider_result_ref"]!=item["provider_result_ref"] or not isinstance(p["content_sha256"],str) or p["content_sha256"] != content_sha256(p) or item["candidate_id"] != stable_candidate_id(provider_result_ref=item["provider_result_ref"], source_item_id=item["source_item_id"]): raise ValueError("Omni snapshot candidate provenance is invalid")
  item["provenance"]=p; ids.add(cid); items.append(item); geometry.append({"candidate_id":cid,"bbox_original":list(box),"active":item["active"]})
 return items,geometry
def _inventory(case_id:str,capture:Mapping[str,object],candidates:list[dict[str,object]])->str: return _hash({"contract_version":"omni_snapshot_canonical_inventory_v1","case_id":case_id,"capture":capture,"candidates":candidates})
def _payload(*,case:ProviderCase,capture:Mapping[str,object],inventory:Mapping[str,object],native_name:str,native_sha:str,raw_sha:str)->dict[str,object]:
 raw=inventory.get("candidates")
 if not isinstance(raw,list): raise ValueError("Omni canonical inventory is invalid")
 cap=_capture({"capture_id":capture["capture_id"],"screenshot_sha256":capture["screenshot_sha256"],"image_size":deepcopy(capture["image_size"]),"capture_lineage_ref":deepcopy(capture["bundle"]["capture_lineage_ref"])},label="Omni snapshot capture")
 candidates,_=_candidates(raw,size=cap["image_size"])
 return {"contract_version":"omni_snapshot_candidates_v1","case_id":case.case_id,"capture":cap,"native_output_file":native_name,"native_output_file_sha256":native_sha,"native_output_sha256":raw_sha,"canonical_inventory_sha256":_inventory(case.case_id,cap,candidates),"candidates":candidates,"artifact_is_authorization":False}
def _content(manifest:Mapping[str,object])->str: result=deepcopy(dict(manifest)); result.pop("content_sha256",None); return _hash(result)
def _aggregate(identity:Mapping[str,object],records:list[dict[str,object]])->str: return _hash({"provider_identity":identity,"cases":records})
def create_omni_snapshot(*,cases:Sequence[ProviderCase],omni:OmniNativeCaller,output_dir:Path,provider_identity:Mapping[str,object])->Path:
 expected=_cases(cases); identity=_identity(provider_identity); root=_new_dir(output_dir); journal=root/"creation.journal.json"; _write(journal,_journal(state="started",completed=[],next_case=expected[0].case_id,error=None,manifest_sha=None)); stage=root/"staging"; stage.mkdir(); _safe(stage,label="Omni snapshot staging"); records=[]; completed=[]
 try:
  for case in expected:
   _replace(journal,_journal(state="running",completed=completed,next_case=case.case_id,error=None,manifest_sha=None)); capture=_prepare_capture(case,stage); image=_verify_capture_freshness(capture,"Omni snapshot"); raw=omni(image); _verify_capture_freshness(capture,"Omni snapshot"); raw_text=raw if isinstance(raw,str) else _canonical_bytes(raw).decode("utf-8")
   native={"contract_version":"omni_snapshot_native_output_v1","case_id":case.case_id,"raw_utf8":raw_text,"raw_output_sha256":_sha(raw_text.encode("utf-8")),"artifact_is_authorization":False}; _forbidden(native,label="Omni native output"); native_name=f"{case.case_id}.native.json"; native_path=stage/native_name; _write(native_path,native); native_sha=_sha(native_path.read_bytes())
   evidence=build_omni_evidence_from_native(case=case,capture=capture,parsed=parse_omni_native_output(raw),artifact_dir=stage); inventory=evidence.get("inventory")
   if not isinstance(inventory,Mapping): raise ValueError("Omni canonical inventory is unavailable")
   candidate_name=f"{case.case_id}.candidates.json"; payload=_payload(case=case,capture=capture,inventory=inventory,native_name=native_name,native_sha=native_sha,raw_sha=native["raw_output_sha256"]); _forbidden(payload,label="Omni candidate output"); candidate_path=stage/candidate_name; _write(candidate_path,payload); candidates=payload["candidates"]; assert isinstance(candidates,list); _,geometry=_candidates(candidates,size=payload["capture"]["image_size"]); ids=[x["candidate_id"] for x in candidates]
   records.append({"case_id":case.case_id,"screenshot_path":str(case.image_path.absolute()),"image_size":{"width":case.image_size[0],"height":case.image_size[1]},"capture_sha256":case.image_sha256,"capture_id":capture["capture_id"],"capture_lineage_sha256":_hash(capture["bundle"]["capture_lineage_ref"]),"goals":list(case.goals),"goals_sha256":_hash(list(case.goals)),"native_output_file":native_name,"native_output_file_sha256":native_sha,"native_output_sha256":native["raw_output_sha256"],"candidate_file":candidate_name,"candidate_file_sha256":_sha(candidate_path.read_bytes()),"canonical_inventory_sha256":payload["canonical_inventory_sha256"],"candidate_ids":ids,"candidate_order_sha256":_hash(ids),"candidate_geometry_sha256":_hash(geometry)}); completed.append(case.case_id)
  manifest={"contract_version":"omni_snapshot_v1","provider_identity":identity,"provider_identity_sha256":_hash(identity),"regression_only":True,"contains_holdout":False,"artifact_is_authorization":False,"screen_count":5,"target_count":25,"cases":records,"aggregate_snapshot_sha256":_aggregate(identity,records)}; _forbidden(manifest,label="Omni snapshot manifest"); manifest["content_sha256"]=_content(manifest); _write(stage/"manifest.json",manifest)
  for cid in _CASE_IDS:
   for suffix in ("native.json","candidates.json"): os.replace(stage/f"{cid}.{suffix}",root/f"{cid}.{suffix}")
  os.replace(stage/"manifest.json",root/"manifest.json")
  if (stage/"artifacts").exists(): os.replace(stage/"artifacts",root/"artifacts")
  stage.rmdir(); _replace(journal,_journal(state="finalized",completed=list(_CASE_IDS),next_case=None,error=None,manifest_sha=manifest["content_sha256"])); return root/"manifest.json"
 except BaseException as exc:
  _replace(journal,_journal(state="blocked",completed=completed,next_case=None,error=type(exc).__name__,manifest_sha=None)); raise
def _expected(record:Mapping[str,object],case:ProviderCase)->None:
 keys={"case_id","screenshot_path","image_size","capture_sha256","capture_id","capture_lineage_sha256","goals","goals_sha256","native_output_file","native_output_file_sha256","native_output_sha256","candidate_file","candidate_file_sha256","canonical_inventory_sha256","candidate_ids","candidate_order_sha256","candidate_geometry_sha256"}; _closed(dict(record),keys,label="Omni snapshot case record")
 if record["case_id"]!=case.case_id or record["screenshot_path"]!=str(case.image_path.absolute()): raise ValueError("Omni snapshot case order mismatch")
 if record["capture_sha256"]!=case.image_sha256 or record["image_size"]!={"width":case.image_size[0],"height":case.image_size[1]}: raise ValueError("Omni snapshot capture mismatch")
 if record["goals"]!=list(case.goals) or record["goals_sha256"]!=_hash(list(case.goals)): raise ValueError("Omni snapshot goal order mismatch")
 _safe_ancestors(case.image_path,label="Omni snapshot expected capture")
 if not case.image_path.is_file() or _sha(case.image_path.read_bytes())!=case.image_sha256: raise ValueError("Omni snapshot expected capture sha256 mismatch")
 with Image.open(case.image_path) as image:
  if image.size!=case.image_size: raise ValueError("Omni snapshot expected capture geometry mismatch")
def _verify_case(root:Path,record:Mapping[str,object])->dict[str,object]:
 cid=record["case_id"]; assert isinstance(cid,str); native_name=f"{cid}.native.json"; candidate_name=f"{cid}.candidates.json"
 if record["native_output_file"]!=native_name: raise ValueError("Omni snapshot native filename mismatch")
 if record["candidate_file"]!=candidate_name: raise ValueError("Omni snapshot candidate filename mismatch")
 native_path=_file(root,native_name,label="Omni snapshot native sidecar"); candidate_path=_file(root,candidate_name,label="Omni snapshot candidate sidecar")
 if _sha(native_path.read_bytes())!=record["native_output_file_sha256"]: raise ValueError("Omni snapshot native file sha256 mismatch")
 if _sha(candidate_path.read_bytes())!=record["candidate_file_sha256"]: raise ValueError("Omni snapshot candidate file sha256 mismatch")
 native=_read(native_path,label="Omni snapshot native file"); payload=_read(candidate_path,label="Omni snapshot candidate file"); _forbidden(native,label="Omni snapshot native file"); _forbidden(payload,label="Omni snapshot candidate file")
 _closed(native,{"contract_version","case_id","raw_utf8","raw_output_sha256","artifact_is_authorization"},label="Omni snapshot native file")
 if native["contract_version"]!="omni_snapshot_native_output_v1" or native["case_id"]!=cid or native["artifact_is_authorization"] is not False or not isinstance(native["raw_utf8"],str) or _sha(native["raw_utf8"].encode("utf-8"))!=native["raw_output_sha256"] or native["raw_output_sha256"]!=record["native_output_sha256"]: raise ValueError("Omni snapshot native output mismatch")
 try: parsed_native=parse_omni_native_output(json.loads(native["raw_utf8"],parse_constant=_no_constant))
 except (ValueError,json.JSONDecodeError,TypeError) as exc: raise ValueError("Omni snapshot native output parse mismatch") from exc
 source_ids={f"omni-native/{index:04d}/{_native_hash(asdict(item))[:16]}" for index,item in enumerate(parsed_native)}
 _closed(payload,{"contract_version","case_id","capture","native_output_file","native_output_file_sha256","native_output_sha256","canonical_inventory_sha256","candidates","artifact_is_authorization"},label="Omni snapshot candidate file")
 if payload["contract_version"]!="omni_snapshot_candidates_v1" or payload["case_id"]!=cid or payload["artifact_is_authorization"] is not False or payload["native_output_file"]!=native_name or payload["native_output_file_sha256"]!=record["native_output_file_sha256"] or payload["native_output_sha256"]!=record["native_output_sha256"]: raise ValueError("Omni snapshot candidate native reference mismatch")
 cap=_capture(payload["capture"],label="Omni snapshot candidate capture")
 if cap["capture_id"]!=record["capture_id"] or cap["screenshot_sha256"]!=record["capture_sha256"] or cap["image_size"]!=record["image_size"] or _hash(cap["capture_lineage_ref"])!=record["capture_lineage_sha256"]: raise ValueError("Omni snapshot candidate capture mismatch")
 candidates,geometry=_candidates(payload["candidates"],size=cap["image_size"]); ids=[x["candidate_id"] for x in candidates]
 if any(candidate["source_item_id"] not in source_ids for candidate in candidates): raise ValueError("Omni snapshot source item lineage mismatch")
 if ids!=record["candidate_ids"] or _hash(ids)!=record["candidate_order_sha256"] or _hash(geometry)!=record["candidate_geometry_sha256"]: raise ValueError("Omni snapshot candidate order or geometry mismatch")
 if _inventory(cid,cap,candidates)!=payload["canonical_inventory_sha256"] or payload["canonical_inventory_sha256"]!=record["canonical_inventory_sha256"]: raise ValueError("Omni snapshot canonical inventory mismatch")
 return {"case_id":cid,"capture":cap,"candidates":deepcopy(candidates),"candidate_file":str(candidate_path)}
def load_verified_omni_snapshot(path:Path,*,expected_cases:Sequence[ProviderCase],expected_provider_identity:Mapping[str,object])->dict[str,object]:
 expected=_cases(expected_cases); trusted=_identity(expected_provider_identity); manifest_path=path.absolute()
 if manifest_path.name!="manifest.json": raise ValueError("Omni snapshot manifest filename mismatch")
 _safe_ancestors(manifest_path,label="Omni snapshot manifest"); root=manifest_path.parent; manifest=_read(_file(root,"manifest.json",label="Omni snapshot manifest"),label="Omni snapshot manifest"); _forbidden(manifest,label="Omni snapshot manifest")
 _closed(manifest,{"contract_version","provider_identity","provider_identity_sha256","regression_only","contains_holdout","artifact_is_authorization","screen_count","target_count","cases","aggregate_snapshot_sha256","content_sha256"},label="Omni snapshot manifest"); identity_value=manifest["provider_identity"]
 if not isinstance(identity_value,Mapping) or _hash(identity_value)!=manifest["provider_identity_sha256"]: raise ValueError("Omni snapshot provider identity mismatch")
 identity=_identity(identity_value)
 if identity!=trusted: raise ValueError("Omni snapshot trusted provider identity mismatch")
 if manifest["contract_version"]!="omni_snapshot_v1" or manifest["regression_only"] is not True or manifest["contains_holdout"] is not False or manifest["artifact_is_authorization"] is not False or manifest["screen_count"]!=5 or manifest["target_count"]!=25: raise ValueError("Omni snapshot manifest boundary is invalid")
 if _content(manifest)!=manifest["content_sha256"]: raise ValueError("Omni snapshot manifest sha256 mismatch")
 records=manifest["cases"]
 if not isinstance(records,list) or len(records)!=5 or _aggregate(identity,records)!=manifest["aggregate_snapshot_sha256"]: raise ValueError("Omni snapshot aggregate sha256 mismatch")
 journal=_read(_file(root,"creation.journal.json",label="Omni snapshot journal"),label="Omni snapshot journal"); _forbidden(journal,label="Omni snapshot journal"); _closed(journal,{"contract_version","state","completed_case_ids","next_case_id","error","manifest_content_sha256"},label="Omni snapshot journal")
 if journal!=_journal(state="finalized",completed=list(_CASE_IDS),next_case=None,error=None,manifest_sha=manifest["content_sha256"]): raise ValueError("Omni snapshot journal is not finalized")
 allowed={"manifest.json","creation.journal.json","artifacts",*{f"{cid}.{suffix}" for cid in _CASE_IDS for suffix in ("native.json","candidates.json")}}
 if {x.name for x in root.iterdir()}!=allowed: raise ValueError("Omni snapshot contains unexpected sidecar")
 if not (root/"artifacts").is_dir(): raise ValueError("Omni snapshot artifacts are unavailable")
 _safe(root/"artifacts",label="Omni snapshot artifacts")
 verified=[]
 for record,case in zip(records,expected,strict=True):
  if not isinstance(record,Mapping): raise ValueError("Omni snapshot case record is invalid")
  _expected(record,case); verified.append(_verify_case(root,record))
 return {"contract_version":"omni_snapshot_v1","provider_identity":deepcopy(identity),"snapshot_sha256":manifest["aggregate_snapshot_sha256"],"screen_count":5,"target_count":25,"cases":verified,"regression_only":True,"contains_holdout":False,"artifact_is_authorization":False}
