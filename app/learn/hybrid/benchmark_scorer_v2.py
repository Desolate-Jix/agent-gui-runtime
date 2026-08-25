"""Child-only private scorer plus production-owned isolated scorer spawner."""
from __future__ import annotations
import base64, hashlib, json, os, secrets, subprocess, sys, tempfile
from fractions import Fraction
from pathlib import Path
from typing import Any, Mapping
from app.learn.hybrid.benchmark_v2_predictions import SAFETY, ARMS, artifact_ref, canonical_bytes, exact_ref, _validate_pre

ROOT=Path(__file__).resolve().parents[3]
GATE_PATH=ROOT/"configs/benchmarks/portfolio_hybrid_v1_1_gate.v2.json"
ESTIMAND_PATH=ROOT/"configs/benchmarks/portfolio_hybrid_v1_1_estimand.v2.json"
SCRIPT=ROOT/"scripts/score_portfolio_hybrid_v1_1_benchmark_v2_private.py"
FAILURES={"failed","timeout","out_of_bounds","missing"}
RELEASE="portfolio_hybrid_v1_1_benchmark_v2_release_1"

def _scorer_python_executable()->Path:
    path=Path(getattr(sys,"_base_executable",sys.executable)).resolve(strict=True)
    if not path.is_file(): raise ValueError("private scorer base interpreter invalid")
    return path

def _load(path:Path)->Any:
    raw=Path(path).read_bytes(); value=json.loads(raw.decode("utf-8"))
    if raw!=canonical_bytes(value)+b"\n": raise ValueError("input is not canonical")
    return value

def config_ref(path:Path)->dict[str,str]:
    raw=path.read_bytes(); return _config_ref_from_bytes(path,raw)

def _config_ref_from_bytes(path:Path,raw:bytes)->dict[str,str]:
    value=json.loads(raw.decode("utf-8"))
    return {"relative_path":path.relative_to(ROOT).as_posix(),"file_sha256":hashlib.sha256(raw).hexdigest(),"content_sha256":hashlib.sha256(canonical_bytes(value)).hexdigest(),"contract_version":value["contract_version"],"release_id":value["benchmark_release_id"]}

def _verified_config_snapshot(path:Path,expected:object)->dict[str,Any]:
    raw=Path(path).read_bytes()
    if not isinstance(expected,Mapping) or set(expected)!={"relative_path","file_sha256","content_sha256","contract_version","release_id"}: raise ValueError("configuration ref invalid")
    value=json.loads(raw.decode("utf-8"))
    observed={"relative_path":expected["relative_path"],"file_sha256":hashlib.sha256(raw).hexdigest(),"content_sha256":hashlib.sha256(canonical_bytes(value)).hexdigest(),"contract_version":value["contract_version"],"release_id":value["benchmark_release_id"]}
    if observed!=expected: raise ValueError("configuration byte lineage mismatch")
    return json.loads(canonical_bytes(value).decode("utf-8"))

def _envelopes(items:object)->dict[str,dict[str,Any]]:
    if not isinstance(items,list): raise ValueError("sealed artifacts must be list")
    found={}
    for env in items:
        if not isinstance(env,Mapping) or set(env)!={"ref","canonical_bytes_b64"}: raise ValueError("artifact envelope not closed")
        ref=exact_ref(env["ref"],"artifact")
        raw=base64.b64decode(env["canonical_bytes_b64"],validate=True); value=json.loads(raw.decode("utf-8"))
        if raw!=canonical_bytes(value) or artifact_ref(value)!=ref or ref["id"] in found: raise ValueError("artifact SHA/ref invalid")
        found[ref["id"]]={"ref":ref,"value":value}
    return found

def _get(found:Mapping[str,dict[str,Any]],ref:object,name:str)->dict[str,Any]:
    exact=exact_ref(ref,name); item=found.get(exact["id"])
    if item is None or item["ref"]!=exact: raise ValueError(f"{name} missing or wrong ID/SHA")
    return item["value"]
def _closed(value:object,fields:set[str],name:str)->dict[str,Any]:
    if not isinstance(value,Mapping) or set(value)!=fields: raise ValueError(f"{name} not closed")
    return dict(value)
def _hit(point:tuple[Fraction,Fraction],regions:list[list[int]])->int:
    return int(any(Fraction(a)<=point[0]<Fraction(c) and Fraction(b)<=point[1]<Fraction(d) for a,b,c,d in regions))

def _validate_lifecycle(bundle:object,run:Mapping[str,object],private:Mapping[str,object])->dict[str,Any]:
    bundle=_closed(bundle,{"contract_version","sealed_artifacts","safety"},"lifecycle bundle")
    if bundle["contract_version"]!="benchmark_v2_lifecycle_bundle_v2" or bundle["safety"]!=SAFETY: raise ValueError("lifecycle bundle invalid")
    arts=_envelopes(bundle["sealed_artifacts"])
    ledger=_get(arts,run["attempt_ledger_ref"],"attempt ledger")
    ledger=_closed(ledger,{"contract_version","artifact_id","release_id","partition","source_parent_ref","automatic_prediction_ref","entries","safety"},"attempt ledger")
    if ledger["contract_version"]!="regression_attempt_ledger_v2" or ledger["release_id"]!=RELEASE or ledger["partition"]!=run["partition"] or ledger["source_parent_ref"]!=private["source_parent_ref"] or ledger["automatic_prediction_ref"]!=run["automatic_prediction_ref"] or ledger["safety"]!=SAFETY: raise ValueError("attempt ledger lineage invalid")
    first=None
    if not isinstance(ledger["entries"],list): raise ValueError("attempt ledger entries invalid")
    for index,entry in enumerate(ledger["entries"]):
        entry=_closed(entry,{"sequence","attempt_id","lifecycle_ref","disposition"},"attempt entry")
        if entry["sequence"]!=index: raise ValueError("attempt ledger is not append-only ordered")
        life=_get(arts,entry["lifecycle_ref"],"lifecycle receipt")
        life=_closed(life,{"contract_version","artifact_id","attempt_id","release_id","partition","source_parent_ref","automatic_prediction_ref","complete","lifecycle_verified","cleanup_stable_zero","safety"},"lifecycle receipt")
        if life["contract_version"]!="lifecycle_receipt_v2" or life["attempt_id"]!=entry["attempt_id"] or life["release_id"]!=RELEASE or life["partition"]!=run["partition"] or life["source_parent_ref"]!=private["source_parent_ref"] or life["automatic_prediction_ref"]!=run["automatic_prediction_ref"] or life["safety"]!=SAFETY: raise ValueError("lifecycle lineage invalid")
        if first is None and life["complete"] is True and life["lifecycle_verified"] is True and life["cleanup_stable_zero"] is True: first=(entry,life)
    if first is None: raise ValueError("no complete lifecycle-verified attempt")
    regression=_get(arts,run["regression_precondition_ref"],"regression precondition")
    regression=_closed(regression,{"contract_version","artifact_id","release_id","partition","source_parent_ref","regression_attempt_ledger_ref","selected_attempt_id","selected_lifecycle_ref","status","safety"},"regression receipt")
    entry,life=first
    reg_ledger=_get(arts,regression["regression_attempt_ledger_ref"],"regression attempt ledger")
    reg_ledger=_closed(reg_ledger,{"contract_version","artifact_id","release_id","partition","source_parent_ref","automatic_prediction_ref","entries","safety"},"regression ledger")
    if reg_ledger["partition"]!="regression" or reg_ledger["source_parent_ref"]!=private["source_parent_ref"] or reg_ledger["release_id"]!=RELEASE: raise ValueError("regression ledger lineage invalid")
    reg_first=None
    for index,reg_entry in enumerate(reg_ledger["entries"]):
        if reg_entry.get("sequence")!=index: raise ValueError("regression ledger order invalid")
        reg_life=_get(arts,reg_entry["lifecycle_ref"],"regression lifecycle")
        if reg_life.get("attempt_id")!=reg_entry.get("attempt_id") or reg_life.get("partition")!="regression" or reg_life.get("source_parent_ref")!=private["source_parent_ref"]: raise ValueError("regression lifecycle lineage invalid")
        if reg_first is None and reg_life.get("complete") is True and reg_life.get("lifecycle_verified") is True and reg_life.get("cleanup_stable_zero") is True: reg_first=(reg_entry,reg_life)
    if reg_first is None: raise ValueError("regression has no verified attempt")
    reg_entry,reg_life=reg_first
    if regression["contract_version"]!="regression_precondition_receipt_v2" or regression["release_id"]!=RELEASE or regression["partition"]!="regression" or regression["source_parent_ref"]!=private["source_parent_ref"] or regression["selected_attempt_id"]!=reg_entry["attempt_id"] or regression["selected_lifecycle_ref"]!=reg_entry["lifecycle_ref"] or regression["status"]!="PASS" or regression["safety"]!=SAFETY: raise ValueError("regression precondition is not first verified attempt")
    if run["lifecycle_ref"]!=entry["lifecycle_ref"]: raise ValueError("run cherry-picked a later lifecycle")
    return life

def _validate(private:object,run:object,lifecycle_bundle:object)->tuple[list[dict[str,Any]],dict[str,dict[str,Any]],dict[str,Any]]:
    private=_closed(private,{"contract_version","source_parent_ref","partition","release_id","cases","expected_automatic_prediction_ref","expected_attempt_ledger_ref","expected_regression_precondition_ref","estimand_ref","gate_ref"},"private manifest")
    if private["contract_version"]!="portfolio_hybrid_v1_1_private_manifest_v2_synthetic" or private["release_id"]!=RELEASE or private["partition"]!="holdout": raise ValueError("private manifest invalid")
    exact_ref(private["source_parent_ref"],"parent")
    estimand=_verified_config_snapshot(ESTIMAND_PATH,private["estimand_ref"]); gate=_verified_config_snapshot(GATE_PATH,private["gate_ref"])
    if estimand["contract_version"]!="portfolio_hybrid_v1_1_estimand_v2" or estimand["benchmark_release_id"]!=RELEASE or gate["contract_version"]!="portfolio_hybrid_v1_1_automatic_gate_v2" or gate["benchmark_release_id"]!=RELEASE: raise ValueError("estimand/gate release lineage mismatch")
    run=_closed(run,{"contract_version","release_id","partition","source_parent_ref","automatic_prediction_ref","attempt_ledger_ref","regression_precondition_ref","lifecycle_ref","sealed_artifacts","safety"},"prediction run")
    if run["contract_version"]!="benchmark_v2_prediction_run_v2" or run["release_id"]!=RELEASE or run["partition"]!=private["partition"] or run["source_parent_ref"]!=private["source_parent_ref"] or run["safety"]!=SAFETY: raise ValueError("prediction run lineage invalid")
    for field,expected in (("automatic_prediction_ref",private["expected_automatic_prediction_ref"]),("attempt_ledger_ref",private["expected_attempt_ledger_ref"]),("regression_precondition_ref",private["expected_regression_precondition_ref"])):
        if run[field]!=expected: raise ValueError(f"{field} differs from private anchor")
    arts=_envelopes(run["sealed_artifacts"]); prediction=_validate_pre(_get(arts,run["automatic_prediction_ref"],"automatic prediction"))
    if prediction["source_parent_ref"]!=private["source_parent_ref"] or prediction["partition"]!=run["partition"] or prediction["release_id"]!=RELEASE: raise ValueError("automatic prediction lineage invalid")
    _validate_lifecycle(lifecycle_bundle,run,private)
    cases={c["case_id"]:dict(c) for c in private["cases"]}
    if not cases or len(cases)!=len(private["cases"]): raise ValueError("private cases empty/duplicate")
    rows=prediction["rows"]; by={(r["case_id"],r["arm_id"]):r for r in rows}
    if len(by)!=len(rows) or set(by)!={(c,a) for c in cases for a in ARMS}: raise ValueError("automatic arm/case rows incomplete")
    binding_by_row={}; request_by_row={}; global_owners={field:{} for field in ("binding_ref","candidate_id","bbox_ref","request_ref")}
    for case_id in cases:
        selected=[]
        for arm in ARMS:
            row=by[(case_id,arm)]
            if row["selection_status"]!="selected": continue
            binding=_get(arts,row["target_binding_ref"],"target binding")
            binding=_closed(binding,{"contract_version","artifact_id","case_id","target_id","candidate_id","fusion_ref","capture_ref","bbox_ref","bbox","source_parent_ref","safety"},"binding")
            if binding["contract_version"]!="sealed_target_binding_v2" or binding["case_id"]!=case_id or binding["source_parent_ref"]!=private["source_parent_ref"] or binding["safety"]!=SAFETY: raise ValueError("cross-target binding")
            bref=artifact_ref(binding); binding_by_row[(case_id,arm)]=bref
            row["_target_id"]=binding["target_id"]; row["_bbox"]=list(binding["bbox"])
            for field,value in (("binding_ref",bref["id"]),("candidate_id",binding["candidate_id"]),("bbox_ref",binding["bbox_ref"]["id"])):
                owner=global_owners[field].setdefault(value,case_id)
                if owner!=case_id: raise ValueError(f"{field} reused across targets")
            selected.append((row,binding))
            if arm in {"omni_to_qwen","omni_to_qwen_vista"}:
                request=_get(arts,row["vista_request_ref"],"VISTA request")
                request=_closed(request,{"contract_version","artifact_id","case_id","target_id","target_binding_ref","candidate_id","fusion_ref","capture_ref","bbox_ref","submission_status","source_parent_ref","safety"},"request")
                expected={"case_id":binding["case_id"],"target_id":binding["target_id"],"target_binding_ref":bref,"candidate_id":binding["candidate_id"],"fusion_ref":binding["fusion_ref"],"capture_ref":binding["capture_ref"],"bbox_ref":binding["bbox_ref"]}
                if request["contract_version"]!="sealed_vista_request_v2" or any(request[k]!=v for k,v in expected.items()) or request["submission_status"]!="SUBMITTED" or request["source_parent_ref"]!=private["source_parent_ref"] or request["safety"]!=SAFETY: raise ValueError("VISTA request parent mapping invalid")
                qref=artifact_ref(request); request_by_row[(case_id,arm)]=qref
                owner=global_owners["request_ref"].setdefault(qref["id"],case_id)
                if owner!=case_id: raise ValueError("request ref reused across targets")
                if arm=="omni_to_qwen_vista":
                    result=row["vista_result"]
                    if result["request_ref"]!=qref or result["target_binding_ref"]!=bref: raise ValueError("VISTA proposal parent mismatch")
        pair_keys=[(case_id,a) for a in ("omni_to_qwen","omni_to_qwen_vista")]
        pair=[by[key] for key in pair_keys]
        if pair[0]["selection_status"]!=pair[1]["selection_status"] or pair[0]["eligibility"]!=pair[1]["eligibility"]: raise ValueError("paired arm eligibility mismatch")
        if pair[0]["selection_status"]=="selected":
            if any(key not in binding_by_row or key not in request_by_row for key in pair_keys): raise ValueError("selected pair evidence missing")
            if binding_by_row[pair_keys[0]]!=binding_by_row[pair_keys[1]] or request_by_row[pair_keys[0]]!=request_by_row[pair_keys[1]]: raise ValueError("selected pair evidence mismatch")
        elif pair[0]["failure_reason"]!=pair[1]["failure_reason"]:
            raise ValueError("ineligible pair reason mismatch")
    return list(by.values()),cases,gate

def _score(rows:list[dict[str,Any]],cases:dict[str,dict[str,Any]],gate:Mapping[str,Any])->dict[str,object]:
    metrics={}
    selected_bindings={}
    # binding target and bbox are joined earlier; reload from attached cached metadata is forbidden, so caller annotates below
    for arm in ARMS:
        armrows=[r for r in rows if r["arm_id"]==arm]; selected=[r for r in armrows if r["selection_status"]=="selected"]
        if not selected: raise ValueError("semantic precision selected denominator is zero")
        correct=sum(r["_target_id"]==cases[r["case_id"]]["target_id"] for r in selected)
        important_total=sum(bool(c["important"]) for c in cases.values()); important_correct=sum(r["_target_id"]==cases[r["case_id"]]["target_id"] and cases[r["case_id"]]["important"] for r in selected)
        metrics[arm]={"coverage":Fraction(len(selected),len(cases)),"important_correct_coverage":Fraction(important_correct,important_total),"semantic_precision":Fraction(correct,len(selected)),"wrong":len(selected)-correct}
    numerator=submitted=0
    baselines={r["case_id"]:r for r in rows if r["arm_id"]=="omni_to_qwen"}
    for r in rows:
        if r["arm_id"]!="omni_to_qwen_vista" or r["selection_status"]!="selected": continue
        baseline_row=baselines[r["case_id"]]
        if baseline_row["selection_status"]!="selected": raise ValueError("VISTA selection has no exact baseline")
        submitted+=1; a,b,c,d=baseline_row["_bbox"]; baseline=_hit((Fraction(a+c,2),Fraction(b+d,2)),cases[r["case_id"]]["acceptable_regions"]); result=r["vista_result"]
        refined=0 if result["status"] in FAILURES else _hit(tuple(Fraction(v) for v in result["canonical_capture_pixel_point"]),cases[r["case_id"]]["acceptable_regions"]); numerator+=refined-baseline
    if not submitted: raise ValueError("zero submitted denominator")
    t=gate["thresholds"]; release,base=metrics["omni_to_qwen_vista"],metrics["qwen_only"]
    passed=release["wrong"]==t["wrong_target_count"] and release["coverage"]>=Fraction(t["min_coverage"]) and release["important_correct_coverage"]-base["important_correct_coverage"]>=Fraction(t["min_important_target_correct_coverage_delta"]) and release["semantic_precision"]-base["semantic_precision"]>=Fraction(t["min_semantic_precision_delta"]) and submitted>=t["min_vista_submitted_count"] and numerator>0
    serial={a:{k:(f"{v.numerator}/{v.denominator}" if isinstance(v,Fraction) else v) for k,v in m.items()} for a,m in metrics.items()}
    return {"automatic":{"wrong_target_count":release["wrong"],"arm_metrics":serial},"point_metric":{"gain_numerator":numerator,"submitted_count":submitted,"gain":f"{Fraction(numerator,submitted).numerator}/{Fraction(numerator,submitted).denominator}"},"gate":{"status":"PASS" if passed else "FAIL","automatic_split":"pre_review","regression_role":"precondition_only"}}

def _score_private_child(**_:object)->dict[str,object]:
    raise PermissionError("private scorer direct path is child-only")

_CHILD_ENTRY_USED=False

def _process_identity(pid:int)->str:
    if os.name=="nt":
        import ctypes
        kernel=ctypes.WinDLL("kernel32",use_last_error=True)
        kernel.OpenProcess.argtypes=(ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong); kernel.OpenProcess.restype=ctypes.c_void_p
        kernel.CloseHandle.argtypes=(ctypes.c_void_p,); kernel.CloseHandle.restype=ctypes.c_int
        kernel.GetProcessTimes.argtypes=(ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p); kernel.GetProcessTimes.restype=ctypes.c_int
        handle=kernel.OpenProcess(0x1000,False,pid)
        if not handle: raise OSError("process identity unavailable")
        try:
            creation=ctypes.c_ulonglong(); exit_time=ctypes.c_ulonglong(); kernel_time=ctypes.c_ulonglong(); user_time=ctypes.c_ulonglong()
            if not kernel.GetProcessTimes(handle,ctypes.byref(creation),ctypes.byref(exit_time),ctypes.byref(kernel_time),ctypes.byref(user_time)): raise OSError("process identity unavailable")
            return f"win-filetime/{creation.value}"
        finally: kernel.CloseHandle(handle)
    stat=Path(f"/proc/{pid}/stat").read_text(encoding="ascii").split()
    return f"proc-start/{stat[21]}"

def execute_closed_child_envelope(envelope:Mapping[str,object])->dict[str,object]:
    global _CHILD_ENTRY_USED
    fields={"private_manifest_path","prediction_run_path","lifecycle_path","private_output_path","public_ref_path","nonce","expected_process_id","expected_process_identity"}
    if _CHILD_ENTRY_USED or not isinstance(envelope,Mapping) or set(envelope)!=fields: raise PermissionError("private scorer entrypoint state invalid")
    pid=os.getpid(); nonce=envelope["nonce"]
    if not isinstance(nonce,str) or len(nonce)!=64 or envelope["expected_process_id"]!=pid or envelope["expected_process_identity"]!=_process_identity(pid): raise PermissionError("private scorer launcher binding invalid")
    _CHILD_ENTRY_USED=True
    paths={key:Path(str(envelope[key])) for key in fields if key.endswith("_path")}
    return _run_private_child_once(nonce=nonce,process_identity=str(envelope["expected_process_identity"]),**paths)

def _run_private_child_once(*,nonce:str,process_identity:str,private_manifest_path:Path,prediction_run_path:Path,lifecycle_path:Path,private_output_path:Path,public_ref_path:Path)->dict[str,object]:
    private,run,bundle=_load(private_manifest_path),_load(prediction_run_path),_load(lifecycle_path)
    rows,cases,gate=_validate(private,run,bundle)
    result=_score(rows,cases,gate); private_result={"contract_version":"portfolio_hybrid_v1_1_private_score_v2",**result,"source_parent_ref":private["source_parent_ref"],"automatic_prediction_ref":run["automatic_prediction_ref"],"estimand_ref":private["estimand_ref"],"gate_ref":private["gate_ref"],"safety":dict(SAFETY)}
    raw=canonical_bytes(private_result)+b"\n"; digest=hashlib.sha256(raw).hexdigest(); receipt={"contract_version":"private_scorer_child_receipt_v2","nonce":nonce,"process_id":os.getpid(),"process_identity":process_identity,"safety":dict(SAFETY)}; public={"status":private_result["gate"]["status"],"score_ref":f"private-score/{digest}","content_sha256":digest,"execution_receipt":receipt,"safety":dict(SAFETY)}
    for path,payload in ((Path(private_output_path),raw),(Path(public_ref_path),canonical_bytes(public)+b"\n")):
        path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_name("."+path.name+".tmp")
        try: tmp.write_bytes(payload); tmp.replace(path)
        finally:
            if tmp.exists(): tmp.unlink()
    return public

def run_private_scorer(*,private_manifest_path:Path,prediction_run_path:Path,lifecycle_path:Path,private_output_path:Path,public_ref_path:Path)->dict[str,str]:
    system_root=os.environ.get("SYSTEMROOT") or os.environ.get("SystemRoot")
    nonce=secrets.token_hex(32)
    env={"SYSTEMROOT":system_root,"PYTHONIOENCODING":"utf-8","PYTHONUTF8":"1"}
    envelope={k:str(Path(v).resolve()) for k,v in {"private_manifest_path":private_manifest_path,"prediction_run_path":prediction_run_path,"lifecycle_path":lifecycle_path,"private_output_path":private_output_path,"public_ref_path":public_ref_path}.items()}
    with tempfile.TemporaryDirectory(prefix="benchmark-v2-score-") as operation_root:
        root=Path(operation_root).resolve()
        if root==Path(private_output_path).resolve().parent or root==Path(private_manifest_path).resolve().parent or any(root.iterdir()): raise ValueError("private scorer operation root invalid")
        python_executable=_scorer_python_executable()
        process=subprocess.Popen([str(python_executable),str(SCRIPT),"--closed-stdin"],executable=str(python_executable),cwd=root,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="utf-8",close_fds=True)
        try:
            identity=_process_identity(process.pid); envelope.update({"nonce":nonce,"expected_process_id":process.pid,"expected_process_identity":identity})
            stdout,stderr=process.communicate(json.dumps(envelope,sort_keys=True,separators=(",",":")),timeout=30)
        finally:
            try:
                if process.poll() is None: process.kill()
            finally:
                try:
                    process.wait(timeout=10)
                finally:
                    for pipe in (process.stdin,process.stdout,process.stderr):
                        if pipe is not None:
                            try: pipe.close()
                            except OSError: pass
    if process.returncode!=0: raise ValueError("private scorer failed closed; sensitive details redacted")
    lines=stdout.splitlines()
    if len(lines)!=1: raise ValueError("private scorer stdout contract invalid")
    ref=json.loads(lines[0])
    if not isinstance(ref,dict) or set(ref)!={"status","score_ref","content_sha256"}: raise ValueError("private scorer public stdout ref invalid")
    public=json.loads(Path(public_ref_path).read_text(encoding="utf-8"))
    receipt=public.get("execution_receipt")
    if {k:public[k] for k in ref}!=ref or public.get("safety")!=SAFETY or not isinstance(receipt,Mapping) or receipt!={"contract_version":"private_scorer_child_receipt_v2","nonce":nonce,"process_id":process.pid,"process_identity":identity,"safety":SAFETY}: raise ValueError("private scorer public artifact mismatch")
    return ref
