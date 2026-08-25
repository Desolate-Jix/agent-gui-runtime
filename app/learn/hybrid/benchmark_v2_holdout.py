"""Partitioned Benchmark-v2 ledgers and production holdout claim facade."""
from __future__ import annotations
import hashlib, json, os
from pathlib import Path
from typing import Mapping
from app.learn.hybrid.benchmark_v2_durable_claim import IDENTITY, SAFETY, _claim_with_backend, _production_backend, _recover_with_backend, authorization_envelope, canonical_bytes, claim_id

_ZERO="0"*64

def _chain(path:Path)->list[dict[str,object]]:
    if not path.exists(): return []
    result=[]; previous=_ZERO
    for sequence,line in enumerate(path.read_bytes().splitlines()):
        value=json.loads(line.decode("utf-8"))
        if canonical_bytes(value)!=line or set(value)!={"contract_version","event","event_sha256"} or value["contract_version"]!="portfolio_hybrid_benchmark_v2_ledger_event_envelope_v1": raise ValueError("ledger envelope invalid")
        event=value["event"]
        if not isinstance(event,Mapping) or set(event)!={"partition","sequence","event_type","previous_envelope_sha256","event_payload"} or event["sequence"]!=sequence or event["previous_envelope_sha256"]!=previous or value["event_sha256"]!=hashlib.sha256(canonical_bytes(event)).hexdigest(): raise ValueError("ledger hash chain invalid")
        previous=hashlib.sha256(canonical_bytes(value)).hexdigest(); result.append(value)
    return result

def _append(path:Path,event:Mapping[str,object])->dict[str,object]:
    path.parent.mkdir(parents=True,exist_ok=True); chain=_chain(path); previous=_ZERO if not chain else hashlib.sha256(canonical_bytes(chain[-1])).hexdigest(); body=dict(event)
    if body.get("sequence")!=len(chain) or body.get("previous_envelope_sha256")!=previous: raise ValueError("ledger append predecessor invalid")
    wrapped={"contract_version":"portfolio_hybrid_benchmark_v2_ledger_event_envelope_v1","event":body,"event_sha256":hashlib.sha256(canonical_bytes(body)).hexdigest()}; raw=canonical_bytes(wrapped)
    with path.open("ab") as stream: stream.write(raw+b"\n"); stream.flush(); os.fsync(stream.fileno())
    if _chain(path)[-1]!=wrapped: raise ValueError("ledger reload mismatch")
    return wrapped

def append_regression_event(*,ledger_root:Path,event:Mapping[str,object])->dict[str,object]:
    if event.get("partition")!="regression" or event.get("event_type") not in {"authorized_genesis","regression_attempt","cleanup"}: raise ValueError("regression ledger event invalid")
    return _append(Path(ledger_root)/"regression/events.jsonl",event)

def authorize_holdout_genesis(*,ledger_root:Path,claim_identity:Mapping[str,str],authorization_ref:Mapping[str,str])->dict[str,object]:
    if dict(claim_identity)!=IDENTITY or authorization_ref.get("authorization_id")!=f"holdout-authorization/{claim_id(IDENTITY)}": raise ValueError("holdout genesis authority invalid")
    path=Path(ledger_root)/"holdout/events.jsonl"; chain=_chain(path)
    if chain:
        if len(chain)!=1 or chain[0]["event"]["event_type"]!="authorized_genesis" or chain[0]["event"]["event_payload"]!={"claim_id":claim_id(IDENTITY),"authorization_ref":dict(authorization_ref),"safety":SAFETY}: raise ValueError("holdout genesis immutable mismatch")
        return chain[0]
    event={"partition":"holdout","sequence":0,"event_type":"authorized_genesis","previous_envelope_sha256":_ZERO,"event_payload":{"claim_id":claim_id(IDENTITY),"authorization_ref":dict(authorization_ref),"safety":dict(SAFETY)}}
    return _append(path,event)

def claim_holdout_once(*,ledger_root:Path,claim_identity:Mapping[str,str],authorization_ref:Mapping[str,str])->dict[str,object]:
    backend=_production_backend()
    if Path(ledger_root).resolve()!=backend.ledger_root or dict(claim_identity)!=IDENTITY: raise ValueError("production holdout roots/identity are fixed")
    path=Path(str(authorization_ref.get("fixed_authorization_path",""))).resolve()
    if path!=backend.file_root/f"{claim_id(IDENTITY)}.authorization.json" or not path.exists(): raise ValueError("production authorization path invalid")
    wrapped=json.loads(path.read_text(encoding="utf-8")); candidate,digest=authorization_envelope(wrapped["payload"])
    expected={"authorization_id":f"holdout-authorization/{claim_id(IDENTITY)}","envelope_sha256":digest,"fixed_authorization_path":str(path)}
    if wrapped!=candidate or dict(authorization_ref)!=expected: raise ValueError("production authorization ref invalid")
    return _claim_with_backend(backend=backend,authorization=wrapped["payload"])

def recover_claim(*,claim_identity:Mapping[str,str])->dict[str,object]:
    if dict(claim_identity)!=IDENTITY: raise ValueError("production holdout identity is fixed")
    backend=_production_backend(); path=backend.file_root/f"{claim_id(IDENTITY)}.authorization.json"
    if not path.exists(): return {"state":"permanent_refusal","claim_id":claim_id(IDENTITY),"safety":dict(SAFETY)}
    wrapped=json.loads(path.read_text(encoding="utf-8")); return _recover_with_backend(backend=backend,authorization=wrapped["payload"])

__all__=["append_regression_event","authorize_holdout_genesis","claim_holdout_once","recover_claim"]
