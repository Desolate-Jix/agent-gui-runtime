"""Crash-safe local dual-anchor claim for the Benchmark-v2 holdout."""
from __future__ import annotations
import base64, ctypes, hashlib, json, os, re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from ctypes import wintypes

RELEASE="portfolio_hybrid_v1_1_benchmark_v2_release_1"
CORPUS="8503010496a426893456e903b9d768f2a281ef0509f11230d312b073c0760757"
IDENTITY={"benchmark_release_id":RELEASE,"corpus_parent_seal_sha256":CORPUS,"partition":"holdout"}
SAFETY={"artifact_is_authorization":False,"execute_binding_enabled":False,"display_only":True}
PRODUCTION_FILE_ROOT=Path(os.environ["LOCALAPPDATA"])/"AgentGuiRuntime/PortfolioHybridBenchmarkV2/Claims"
PRODUCTION_REGISTRY_ROOT=r"Software\AgentGuiRuntime\PortfolioHybridBenchmarkV2\Claims"
_SHA=re.compile(r"[0-9a-f]{64}")

def canonical_bytes(value:object)->bytes:
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode("utf-8")

def claim_id(identity:Mapping[str,str])->str:
    if dict(identity)!=IDENTITY: raise ValueError("holdout claim identity is not frozen")
    return hashlib.sha256(canonical_bytes(dict(identity))).hexdigest()

def envelope(contract:str,payload:Mapping[str,object])->tuple[dict[str,object],str]:
    body=dict(payload); wrapped={"contract_version":contract,"payload":body,"payload_sha256":hashlib.sha256(canonical_bytes(body)).hexdigest()}
    return wrapped,hashlib.sha256(canonical_bytes(wrapped)).hexdigest()

def authorization_envelope(payload:Mapping[str,object])->tuple[dict[str,object],str]:
    required={"contract_version","claim_identity","claim_id","ledger_identity","fixed_authorization_path","provider_manifest_sha256","provider_manifest_contract_version","code_sha256_by_path","config_sha256_by_path","profile_sha256_by_id","arm_order","exact_holdout_command","exact_run_order","absolute_owner_journal_root"}
    if set(payload)!=required or payload["contract_version"]!="portfolio_hybrid_benchmark_v2_holdout_authorization_payload_v1" or payload["claim_identity"]!=IDENTITY or payload["claim_id"]!=claim_id(IDENTITY) or payload["arm_order"]!=["qwen_only","omni_only_discovery","omni_to_qwen","omni_to_qwen_vista"]: raise ValueError("holdout authorization payload invalid")
    for key in ("provider_manifest_sha256",):
        if not isinstance(payload[key],str) or _SHA.fullmatch(payload[key]) is None: raise ValueError("holdout authorization SHA invalid")
    wrapped,digest=envelope("portfolio_hybrid_benchmark_v2_holdout_authorization_envelope_v1",payload)
    return wrapped,digest

@dataclass(frozen=True)
class _Backend:
    file_root:Path
    registry_root:str
    ledger_root:Path
    test_capability:str|None=None

def _test_backend(*,file_root:Path,registry_root:str,ledger_root:Path,capability:str)->_Backend:
    if not capability or "\\Tests\\" not in registry_root or "PortfolioHybridBenchmarkV2Tests" not in str(file_root): raise ValueError("test backend capability/root invalid")
    if file_root.resolve()==PRODUCTION_FILE_ROOT.resolve() or registry_root==PRODUCTION_REGISTRY_ROOT: raise ValueError("test backend overlaps production")
    return _Backend(file_root.resolve(),registry_root,ledger_root.resolve(),capability)

def _production_backend()->_Backend:
    return _Backend(PRODUCTION_FILE_ROOT.resolve(),PRODUCTION_REGISTRY_ROOT,(PRODUCTION_FILE_ROOT/"ledger").resolve())

def _authorization_ref(backend:_Backend,wrapped:Mapping[str,object],digest:str)->dict[str,str]:
    cid=claim_id(IDENTITY); return {"authorization_id":f"holdout-authorization/{cid}","envelope_sha256":digest,"fixed_authorization_path":str((backend.file_root/f"{cid}.authorization.json").resolve())}

def _create_authorization(backend:_Backend,wrapped:Mapping[str,object],digest:str)->dict[str,str]:
    path=(backend.file_root/f"{claim_id(IDENTITY)}.authorization.json").resolve(); backend.file_root.mkdir(parents=True,exist_ok=True); raw=canonical_bytes(wrapped)
    try:
        with path.open("xb") as stream: stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    except FileExistsError:
        if path.read_bytes()!=raw: raise ValueError("permanent_refusal: authorization byte drift")
    ref=_authorization_ref(backend,wrapped,digest)
    if str(path)!=ref["fixed_authorization_path"]: raise ValueError("authorization path mismatch")
    return ref

def _sentinel_create(path:Path)->bool:
    path.parent.mkdir(parents=True,exist_ok=True)
    kernel=ctypes.WinDLL("kernel32",use_last_error=True); kernel.CreateFileW.argtypes=(wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE); kernel.CreateFileW.restype=wintypes.HANDLE; kernel.FlushFileBuffers.argtypes=(wintypes.HANDLE,); kernel.CloseHandle.argtypes=(wintypes.HANDLE,)
    invalid=ctypes.c_void_p(-1).value; handle=kernel.CreateFileW(str(path),0x40000000|0x80|0x100000,1,None,1,0x1|0x80000000,None)
    if handle==invalid:
        if ctypes.get_last_error() in (80,183): return False
        raise OSError(ctypes.get_last_error(),"CreateFileW sentinel failed")
    try:
        if not kernel.FlushFileBuffers(handle): raise OSError(ctypes.get_last_error(),"FlushFileBuffers sentinel failed")
    finally: kernel.CloseHandle(handle)
    if path.stat().st_size!=0: raise ValueError("sentinel is not zero bytes")
    return True

_REG_VALUES={"ContractVersion":1,"ClaimId":1,"AuthorizationEnvelopeSha256":1,"ClaimEnvelope":3,"ClaimEnvelopeSha256":1}

def _registry_read(backend:_Backend,cid:str)->dict[str,object]|None:
    import winreg
    try: key=winreg.OpenKey(winreg.HKEY_CURRENT_USER,backend.registry_root+"\\"+cid,0,winreg.KEY_READ|winreg.KEY_WOW64_64KEY)
    except FileNotFoundError: return None
    try:
        found={}; index=0
        while True:
            try: name,value,kind=winreg.EnumValue(key,index); found[name]=(value,kind); index+=1
            except OSError: break
        if set(found)!=set(_REG_VALUES) or any(found[k][1]!=v for k,v in _REG_VALUES.items()): raise ValueError("permanent_refusal: registry schema mismatch")
        return {k:found[k][0] for k in found}
    finally: winreg.CloseKey(key)

def _registry_create(backend:_Backend,cid:str,values:Mapping[str,object],failpoint:str|None)->bool:
    adv=ctypes.WinDLL("advapi32",use_last_error=True); handle=wintypes.HKEY(); disposition=wintypes.DWORD(); subkey=backend.registry_root+"\\"+cid
    adv.RegCreateKeyExW.argtypes=(wintypes.HKEY,wintypes.LPCWSTR,wintypes.DWORD,wintypes.LPWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,ctypes.POINTER(wintypes.HKEY),ctypes.POINTER(wintypes.DWORD)); adv.RegSetValueExW.argtypes=(wintypes.HKEY,wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD); adv.RegFlushKey.argtypes=(wintypes.HKEY,); adv.RegCloseKey.argtypes=(wintypes.HKEY,)
    rc=adv.RegCreateKeyExW(0x80000001,subkey,0,None,0,0x1|0x2|0x4|0x100,None,ctypes.byref(handle),ctypes.byref(disposition))
    if rc: raise OSError(rc,"RegCreateKeyExW failed")
    try:
        if disposition.value!=1: return False
        if failpoint=="registry_create": os._exit(91)
        for name in ("ContractVersion","ClaimId","AuthorizationEnvelopeSha256","ClaimEnvelope","ClaimEnvelopeSha256"):
            value=values[name]
            if isinstance(value,bytes): buffer=ctypes.create_string_buffer(value); kind=3; size=len(value)
            else: buffer=ctypes.create_unicode_buffer(str(value)); kind=1; size=ctypes.sizeof(buffer)
            rc=adv.RegSetValueExW(handle,name,0,kind,ctypes.cast(buffer,ctypes.c_void_p),size)
            if rc: raise OSError(rc,"RegSetValueExW failed")
            if failpoint=="registry_record" and name=="ClaimEnvelope": os._exit(92)
        if failpoint=="registry_flush": os._exit(93)
        rc=adv.RegFlushKey(handle)
        if rc: raise OSError(rc,"RegFlushKey failed")
    finally: adv.RegCloseKey(handle)
    return True

def _claim_payload(auth_ref:Mapping[str,str],authorization_payload:Mapping[str,object])->tuple[dict[str,object],dict[str,object],str]:
    cid=claim_id(IDENTITY); attempt=hashlib.sha256(("benchmark-v2-holdout-attempt\0"+cid+"\0"+auth_ref["envelope_sha256"]).encode()).hexdigest(); payload={"claim_id":cid,"authorization_ref":dict(auth_ref),"attempt_id":attempt,"provider_manifest_sha256":authorization_payload["provider_manifest_sha256"],"absolute_owner_journal_root":authorization_payload["absolute_owner_journal_root"],"state":"consumed"}; wrapped,digest=envelope("portfolio_hybrid_benchmark_v2_holdout_claim_envelope_v1",payload); return payload,wrapped,digest

def _mirror_claim(backend:_Backend,auth_ref:Mapping[str,str],claim_ref:Mapping[str,str],*,require_existing_genesis:bool)->None:
    from app.learn.hybrid.benchmark_v2_holdout import _append,_chain,authorize_holdout_genesis
    path=backend.ledger_root/"holdout/events.jsonl"; chain=_chain(path)
    if not chain:
        if require_existing_genesis: raise ValueError("holdout exact genesis is required before first claim")
        authorize_holdout_genesis(ledger_root=backend.ledger_root,claim_identity=IDENTITY,authorization_ref=auth_ref); chain=_chain(path)
    expected={"claim_id":claim_id(IDENTITY),"authorization_ref":dict(auth_ref),"safety":SAFETY}
    if chain[0]["event"]["event_type"]!="authorized_genesis" or chain[0]["event"]["event_payload"]!=expected: raise ValueError("holdout genesis mismatch")
    claims=[item for item in chain[1:] if item["event"]["event_type"]=="claim_consumed"]
    if claims:
        if len(claims)!=1 or claims[0]["event"]["event_payload"]!={"claim_ref":dict(claim_ref),"safety":SAFETY}: raise ValueError("holdout claim mirror mismatch")
        return
    previous=hashlib.sha256(canonical_bytes(chain[-1])).hexdigest(); _append(path,{"partition":"holdout","sequence":len(chain),"event_type":"claim_consumed","previous_envelope_sha256":previous,"event_payload":{"claim_ref":dict(claim_ref),"safety":dict(SAFETY)}})

def _require_fresh_genesis(backend:_Backend,auth_ref:Mapping[str,str])->None:
    from app.learn.hybrid.benchmark_v2_holdout import _chain
    chain=_chain(backend.ledger_root/"holdout/events.jsonl"); expected={"claim_id":claim_id(IDENTITY),"authorization_ref":dict(auth_ref),"safety":SAFETY}
    if len(chain)!=1 or chain[0]["event"]["event_type"]!="authorized_genesis" or chain[0]["event"]["event_payload"]!=expected: raise ValueError("holdout exact zero-claim genesis required")

def _inspect(backend:_Backend,auth_ref:Mapping[str,str],expected_values:Mapping[str,object])->str:
    cid=claim_id(IDENTITY); sentinels=list(backend.file_root.glob(f"{cid}--*.claim")); exact=backend.file_root/f"{cid}--{auth_ref['envelope_sha256']}.claim"
    try: registry=_registry_read(backend,cid)
    except ValueError: return "permanent_refusal"
    if len(sentinels)>1 or any(path!=exact or path.stat().st_size!=0 for path in sentinels): return "permanent_refusal"
    sentinel=bool(sentinels)
    if registry is not None and registry!=expected_values: return "permanent_refusal"
    if sentinel and registry is not None: return "consumed"
    if sentinel or registry is not None: return "consumed_incomplete"
    return "fresh"

def _claim_with_backend(*,backend:_Backend,authorization:Mapping[str,object],failpoint:str|None=None)->dict[str,object]:
    wrapped,digest=authorization_envelope(authorization); auth_ref=_create_authorization(backend,wrapped,digest); payload,claim_wrapped,claim_digest=_claim_payload(auth_ref,authorization); expected={"ContractVersion":"portfolio_hybrid_benchmark_v2_holdout_claim_envelope_v1","ClaimId":payload["claim_id"],"AuthorizationEnvelopeSha256":auth_ref["envelope_sha256"],"ClaimEnvelope":canonical_bytes(claim_wrapped),"ClaimEnvelopeSha256":claim_digest}; state=_inspect(backend,auth_ref,expected)
    if state!="fresh": return {"state":state,"claim_id":payload["claim_id"],"attempt_id":payload["attempt_id"],"newly_created":False,"safety":dict(SAFETY)}
    claim_ref={"id":f"holdout-claim/{payload['claim_id']}","envelope_sha256":claim_digest}; _require_fresh_genesis(backend,auth_ref)
    sentinel=backend.file_root/f"{payload['claim_id']}--{auth_ref['envelope_sha256']}.claim"
    if not _sentinel_create(sentinel): return {"state":"consumed_incomplete","claim_id":payload["claim_id"],"attempt_id":payload["attempt_id"],"newly_created":False,"safety":dict(SAFETY)}
    if failpoint=="sentinel_create": os._exit(90)
    created=_registry_create(backend,payload["claim_id"],expected,failpoint)
    state=_inspect(backend,auth_ref,expected)
    if state=="consumed": _mirror_claim(backend,auth_ref,claim_ref,require_existing_genesis=False)
    return {"state":state,"claim_id":payload["claim_id"],"attempt_id":payload["attempt_id"],"claim_ref":claim_ref,"newly_created":created and state=="consumed","safety":dict(SAFETY)}

def _claim_with_backend_for_test(*,backend:_Backend,authorization:Mapping[str,object],failpoint:str|None=None)->dict[str,object]:
    if backend.test_capability is None: raise ValueError("explicit test backend capability required")
    return _claim_with_backend(backend=backend,authorization=authorization,failpoint=failpoint)

def _recover_with_backend(*,backend:_Backend,authorization:Mapping[str,object])->dict[str,object]:
    wrapped,digest=authorization_envelope(authorization); auth_ref=_authorization_ref(backend,wrapped,digest); payload,claim_wrapped,claim_digest=_claim_payload(auth_ref,authorization); expected={"ContractVersion":"portfolio_hybrid_benchmark_v2_holdout_claim_envelope_v1","ClaimId":payload["claim_id"],"AuthorizationEnvelopeSha256":digest,"ClaimEnvelope":canonical_bytes(claim_wrapped),"ClaimEnvelopeSha256":claim_digest}; path=Path(auth_ref["fixed_authorization_path"])
    state="permanent_refusal" if not path.exists() or path.read_bytes()!=canonical_bytes(wrapped) else _inspect(backend,auth_ref,expected)
    if state=="consumed": _mirror_claim(backend,auth_ref,{"id":f"holdout-claim/{payload['claim_id']}","envelope_sha256":claim_digest},require_existing_genesis=False)
    return {"state":state,"claim_id":payload["claim_id"],"attempt_id":payload["attempt_id"],"safety":dict(SAFETY)}

def recover_with_backend_for_test(*,backend:_Backend,authorization:Mapping[str,object])->dict[str,object]:
    if backend.test_capability is None: raise ValueError("explicit test backend capability required")
    return _recover_with_backend(backend=backend,authorization=authorization)

__all__=["claim_id","authorization_envelope","SAFETY"]
