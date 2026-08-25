from __future__ import annotations
import hashlib,json,multiprocessing as mp,os,shutil,stat,sys,uuid,winreg
from copy import deepcopy
from pathlib import Path
import pytest
from app.learn.hybrid.benchmark_v2_durable_claim import CORPUS,IDENTITY,PRODUCTION_FILE_ROOT,PRODUCTION_REGISTRY_ROOT,RELEASE,SAFETY,_claim_with_backend_for_test,_test_backend,authorization_envelope,canonical_bytes,claim_id,recover_with_backend_for_test
from app.learn.hybrid.benchmark_v2_holdout import append_regression_event,authorize_holdout_genesis

def authorization(backend,provider:str="1"*64)->dict[str,object]:
    cid=claim_id(IDENTITY); auth_path=(backend.file_root/f"{cid}.authorization.json").resolve()
    return {"contract_version":"portfolio_hybrid_benchmark_v2_holdout_authorization_payload_v1","claim_identity":dict(IDENTITY),"claim_id":cid,"ledger_identity":{"absolute_ledger_root":str(backend.ledger_root),"holdout_events_path":str(backend.ledger_root/"holdout/events.jsonl"),"genesis_envelope_sha256":"2"*64},"fixed_authorization_path":str(auth_path),"provider_manifest_sha256":provider,"provider_manifest_contract_version":"provider_manifest_v2","code_sha256_by_path":{"code.py":"3"*64},"config_sha256_by_path":{"estimand.json":"4"*64},"profile_sha256_by_id":{"profile":"5"*64},"arm_order":["qwen_only","omni_only_discovery","omni_to_qwen","omni_to_qwen_vista"],"exact_holdout_command":["python","runner.py"],"exact_run_order":["sealed-regression","sealed-holdout"],"absolute_owner_journal_root":str(backend.file_root/"owner")}

def prepared(backend,provider:str="1"*64)->dict[str,object]:
    payload=authorization(backend,provider); _,digest=authorization_envelope(payload); ref={"authorization_id":f"holdout-authorization/{claim_id(IDENTITY)}","envelope_sha256":digest,"fixed_authorization_path":payload["fixed_authorization_path"]}; authorize_holdout_genesis(ledger_root=backend.ledger_root,claim_identity=IDENTITY,authorization_ref=ref); return payload

def backend(tmp:Path):
    token=uuid.uuid4().hex; root=tmp/"AgentGuiRuntime/PortfolioHybridBenchmarkV2Tests"/token/"Claims"; registry=rf"Software\AgentGuiRuntime\Tests\PortfolioHybridBenchmarkV2\{token}\Claims"; return _test_backend(file_root=root,registry_root=registry,ledger_root=tmp/"ledger"/token,capability=token)

def cleanup(value)->None:
    cid=claim_id(IDENTITY)
    try: winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER,value.registry_root+"\\"+cid,winreg.KEY_WOW64_64KEY,0)
    except FileNotFoundError: pass
    parts=value.registry_root.split("\\")
    for length in range(len(parts),4,-1):
        try: winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER,"\\".join(parts[:length]),winreg.KEY_WOW64_64KEY,0)
        except OSError: pass
    if value.file_root.exists():
        for path in value.file_root.glob("*.claim"): path.chmod(stat.S_IWRITE)
        shutil.rmtree(value.file_root.parent.parent.parent,ignore_errors=True)
    shutil.rmtree(value.ledger_root.parent,ignore_errors=True)

def child_claim(value,payload,start,queue,failpoint=None)->None:
    start.wait(); result=_claim_with_backend_for_test(backend=value,authorization=payload,failpoint=failpoint); queue.put(result)

@pytest.fixture
def test_backend(tmp_path:Path):
    value=backend(tmp_path)
    assert value.file_root!=PRODUCTION_FILE_ROOT and value.registry_root!=PRODUCTION_REGISTRY_ROOT
    try: yield value
    finally: cleanup(value)

def test_two_layer_hashes_have_no_self_reference_and_stable_identity(test_backend)->None:
    payload=authorization(test_backend); wrapped,digest=authorization_envelope(payload)
    assert "envelope_sha256" not in wrapped and wrapped["payload_sha256"]==hashlib.sha256(canonical_bytes(payload)).hexdigest() and digest==hashlib.sha256(canonical_bytes(wrapped)).hexdigest()
    changed=deepcopy(payload); changed["provider_manifest_sha256"]="9"*64
    assert claim_id(changed["claim_identity"])==claim_id(payload["claim_identity"]) and authorization_envelope(changed)[1]!=digest

def test_partition_ledgers_are_independent_and_holdout_genesis_is_immutable(tmp_path:Path)->None:
    root=tmp_path/"ledgers"; regression={"partition":"regression","sequence":0,"event_type":"authorized_genesis","previous_envelope_sha256":"0"*64,"event_payload":{"release":RELEASE}}
    append_regression_event(ledger_root=root,event=regression)
    ref={"authorization_id":f"holdout-authorization/{claim_id(IDENTITY)}","envelope_sha256":"1"*64,"fixed_authorization_path":str(tmp_path/"auth")}; genesis=authorize_holdout_genesis(ledger_root=root,claim_identity=IDENTITY,authorization_ref=ref)
    assert (root/"regression/events.jsonl").read_bytes()!=(root/"holdout/events.jsonl").read_bytes() and authorize_holdout_genesis(ledger_root=root,claim_identity=IDENTITY,authorization_ref=ref)==genesis
    with pytest.raises(ValueError): authorize_holdout_genesis(ledger_root=root,claim_identity=IDENTITY,authorization_ref={**ref,"envelope_sha256":"2"*64})

def test_two_real_processes_have_one_winner_and_same_attempt(test_backend)->None:
    payload=prepared(test_backend); context=mp.get_context("spawn"); start=context.Event(); queue=context.Queue(); children=[context.Process(target=child_claim,args=(test_backend,payload,start,queue)) for _ in range(2)]
    try:
        for child in children: child.start()
        start.set(); results=[queue.get(timeout=20) for _ in children]
        for child in children: child.join(20)
        assert all(child.exitcode==0 for child in children) and sum(item["newly_created"] for item in results)==1 and len({item["attempt_id"] for item in results})==1
        assert recover_with_backend_for_test(backend=test_backend,authorization=payload)["state"]=="consumed"
    finally:
        for child in children:
            if child.is_alive(): child.kill()
            child.join(); child.close()
        queue.close(); queue.join_thread()

@pytest.mark.parametrize("failpoint",["sentinel_create","registry_create","registry_record","registry_flush"])
def test_crash_windows_never_recover_fresh(tmp_path:Path,failpoint:str)->None:
    value=backend(tmp_path); payload=prepared(value); context=mp.get_context("spawn"); start=context.Event(); queue=context.Queue(); child=context.Process(target=child_claim,args=(value,payload,start,queue,failpoint))
    try:
        child.start(); start.set(); child.join(20); assert child.exitcode in (90,91,92,93)
        recovered=recover_with_backend_for_test(backend=value,authorization=payload); assert recovered["state"] in {"consumed_incomplete","permanent_refusal","consumed"}
        assert recovered["attempt_id"]==hashlib.sha256(("benchmark-v2-holdout-attempt\0"+claim_id(IDENTITY)+"\0"+authorization_envelope(payload)[1]).encode()).hexdigest()
    finally:
        if child.is_alive(): child.kill()
        child.join(); child.close(); queue.close(); queue.join_thread(); cleanup(value)

@pytest.mark.parametrize("lost",["sentinel","registry","ledger_output"])
def test_anchor_or_audit_deletion_never_restores_fresh(test_backend,lost:str)->None:
    payload=prepared(test_backend); result=_claim_with_backend_for_test(backend=test_backend,authorization=payload); assert result["state"]=="consumed"
    sentinel=next(test_backend.file_root.glob("*.claim")); assert sentinel.name==f"{claim_id(IDENTITY)}--{authorization_envelope(payload)[1]}.claim" and sentinel.stat().st_size==0
    if lost=="sentinel":
        sentinel.chmod(stat.S_IWRITE); sentinel.unlink()
    elif lost=="registry": winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER,test_backend.registry_root+"\\"+claim_id(IDENTITY),winreg.KEY_WOW64_64KEY,0)
    else: shutil.rmtree(test_backend.ledger_root,ignore_errors=True)
    assert recover_with_backend_for_test(backend=test_backend,authorization=payload)["state"] in ({"consumed_incomplete"} if lost!="ledger_output" else {"consumed"})

def test_dual_anchor_mismatch_is_permanent_refusal(test_backend)->None:
    payload=prepared(test_backend); _claim_with_backend_for_test(backend=test_backend,authorization=payload); subkey=test_backend.registry_root+"\\"+claim_id(IDENTITY)
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,subkey,0,winreg.KEY_SET_VALUE|winreg.KEY_WOW64_64KEY) as key: winreg.SetValueEx(key,"ClaimEnvelopeSha256",0,winreg.REG_SZ,"0"*64); winreg.FlushKey(key)
    assert recover_with_backend_for_test(backend=test_backend,authorization=payload)["state"]=="permanent_refusal"

def test_provider_change_and_authorization_byte_drift_are_permanent(test_backend)->None:
    payload=prepared(test_backend); first=_claim_with_backend_for_test(backend=test_backend,authorization=payload); assert first["newly_created"] is True
    with pytest.raises(ValueError,match="permanent_refusal"): _claim_with_backend_for_test(backend=test_backend,authorization=authorization(test_backend,"9"*64))
    auth=Path(payload["fixed_authorization_path"]); auth.chmod(stat.S_IWRITE); auth.write_bytes(auth.read_bytes()+b" ")
    assert recover_with_backend_for_test(backend=test_backend,authorization=payload)["state"]=="permanent_refusal"

def test_public_surface_has_no_reset_delete_override()->None:
    import app.learn.hybrid.benchmark_v2_holdout as holdout
    assert set(holdout.__all__)=={"append_regression_event","authorize_holdout_genesis","claim_holdout_once","recover_claim"}
    assert not any(token in name.casefold() for name in holdout.__all__ for token in ("reset","delete","clear","override"))
