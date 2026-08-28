"""Child-only private scorer plus production-owned isolated scorer spawner."""
from __future__ import annotations
import base64, hashlib, json, os, secrets, stat, subprocess, sys, tempfile
from fractions import Fraction
from pathlib import Path
from typing import Any, Mapping
from app.learn.hybrid.benchmark_v2_predictions import SAFETY, ARMS, artifact_ref, canonical_bytes, exact_ref, _validate_pre
from app.learn.hybrid.benchmark_v2_private_release import (
    derive_private_scoring_cases,
    validate_task10_private_release_bundle,
)

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

def _validate_private_regions(value:object)->list[list[int]]:
    if not isinstance(value,list) or not value: raise ValueError("private acceptable regions invalid")
    regions=[]
    for raw in value:
        if not isinstance(raw,list) or len(raw)!=4 or not all(isinstance(item,int) for item in raw): raise ValueError("private acceptable region invalid")
        x1,y1,x2,y2=raw
        if x2<=x1 or y2<=y1: raise ValueError("private acceptable region invalid")
        regions.append(list(raw))
    return regions

def _require_five_target_groups(cases:Mapping[str,Mapping[str,Any]])->None:
    groups:dict[str,set[str]]={}
    for case_id,case in cases.items():
        group=case.get("screen_group")
        if not isinstance(case_id,str) or not case_id or not isinstance(group,str) or not group: raise ValueError("private case identity invalid")
        groups.setdefault(group,set()).add(case_id)
    if not groups or any(len(case_ids)!=5 for case_ids in groups.values()): raise ValueError("private screen_group must contain exactly five unique cases")

def _validated_private_cases(value:object)->dict[str,dict[str,Any]]:
    if not isinstance(value,list) or not value: raise ValueError("private cases empty/invalid")
    cases:dict[str,dict[str,Any]]={}
    for raw in value:
        case=_closed(raw,{"case_id","screen_group","important_target","acceptable_regions"},"private case")
        case_id=case["case_id"]
        if not isinstance(case_id,str) or not case_id or case_id in cases or not isinstance(case["screen_group"],str) or not case["screen_group"] or not isinstance(case["important_target"],bool): raise ValueError("private case empty/duplicate/invalid")
        case["acceptable_regions"]=_validate_private_regions(case["acceptable_regions"])
        cases[case_id]=case
    _require_five_target_groups(cases)
    return cases

def _private_unique_target_center_containment(*,case_id:str,bbox:list[int],cases:Mapping[str,Mapping[str,Any]])->bool:
    if case_id not in cases or len(bbox)!=4 or not all(isinstance(value,int) for value in bbox): raise ValueError("private target geometry invalid")
    _require_five_target_groups(cases)
    x1,y1,x2,y2=bbox
    if x2<=x1 or y2<=y1: raise ValueError("private target bbox invalid")
    group=cases[case_id].get("screen_group")
    matches=[]
    for candidate_id,candidate in cases.items():
        if candidate.get("screen_group")!=group: continue
        regions=_validate_private_regions(candidate.get("acceptable_regions"))
        centers=[]
        for region in regions:
            a,b,c,d=region
            centers.append((Fraction(a+c,2),Fraction(b+d,2)))
        if any(Fraction(x1)<=x<Fraction(x2) and Fraction(y1)<=y<Fraction(y2) for x,y in centers): matches.append(candidate_id)
    return len(matches)==1 and matches[0]==case_id

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

def _validate(private:object,run:object,lifecycle_bundle:object,*,_task10_release:bool=False)->tuple[list[dict[str,Any]],dict[str,dict[str,Any]],dict[str,Any]]:
    private=_closed(private,{"contract_version","source_parent_ref","partition","release_id","cases","expected_automatic_prediction_ref","expected_attempt_ledger_ref","expected_regression_precondition_ref","estimand_ref","gate_ref"},"private manifest")
    expected_private_contract=("task10_private_release_scoring_projection_v1" if _task10_release else "portfolio_hybrid_v1_1_private_manifest_v2_1_synthetic")
    allowed_partitions=({"regression","holdout"} if _task10_release else {"holdout"})
    if private["contract_version"]!=expected_private_contract or private["release_id"]!=RELEASE or private["partition"] not in allowed_partitions: raise ValueError("private manifest invalid")
    exact_ref(private["source_parent_ref"],"parent")
    estimand=_verified_config_snapshot(ESTIMAND_PATH,private["estimand_ref"]); gate=_verified_config_snapshot(GATE_PATH,private["gate_ref"])
    if estimand["contract_version"]!="portfolio_hybrid_v1_1_estimand_v2_1" or estimand["benchmark_release_id"]!=RELEASE or gate["contract_version"]!="portfolio_hybrid_v1_1_automatic_gate_v2" or gate["benchmark_release_id"]!=RELEASE: raise ValueError("estimand/gate release lineage mismatch")
    run=_closed(run,{"contract_version","release_id","partition","source_parent_ref","automatic_prediction_ref","attempt_ledger_ref","regression_precondition_ref","lifecycle_ref","sealed_artifacts","safety"},"prediction run")
    if run["contract_version"]!="benchmark_v2_prediction_run_v2" or run["release_id"]!=RELEASE or run["partition"]!=private["partition"] or run["source_parent_ref"]!=private["source_parent_ref"] or run["safety"]!=SAFETY: raise ValueError("prediction run lineage invalid")
    for field,expected in (("automatic_prediction_ref",private["expected_automatic_prediction_ref"]),("attempt_ledger_ref",private["expected_attempt_ledger_ref"]),("regression_precondition_ref",private["expected_regression_precondition_ref"])):
        if run[field]!=expected: raise ValueError(f"{field} differs from private anchor")
    arts=_envelopes(run["sealed_artifacts"]); prediction=_validate_pre(_get(arts,run["automatic_prediction_ref"],"automatic prediction"))
    if prediction["source_parent_ref"]!=private["source_parent_ref"] or prediction["partition"]!=run["partition"] or prediction["release_id"]!=RELEASE: raise ValueError("automatic prediction lineage invalid")
    _validate_lifecycle(lifecycle_bundle,run,private)
    cases=_validated_private_cases(private["cases"])
    rows=prediction["rows"]; by={(r["case_id"],r["arm_id"]):r for r in rows}
    if len(by)!=len(rows) or set(by)!={(c,a) for c in cases for a in ARMS}: raise ValueError("automatic arm/case rows incomplete")
    binding_by_row={}; request_by_row={}; global_owners={field:{} for field in ("binding_ref","candidate_id","bbox_ref","request_ref")}
    for case_id in cases:
        selected=[]
        for arm in ARMS:
            row=by[(case_id,arm)]
            if row["selection_status"]!="selected": continue
            binding=_get(arts,row["target_binding_ref"],"target binding")
            binding=_closed(binding,{"contract_version","artifact_id","case_id","candidate_id","fusion_ref","capture_ref","bbox_ref","bbox","source_parent_ref","safety"},"binding")
            if binding["contract_version"]!="sealed_target_binding_v3" or binding["case_id"]!=case_id or binding["source_parent_ref"]!=private["source_parent_ref"] or binding["safety"]!=SAFETY: raise ValueError("cross-case binding")
            bref=artifact_ref(binding); binding_by_row[(case_id,arm)]=bref
            row["_bbox"]=list(binding["bbox"])
            for field,value in (("binding_ref",bref["id"]),("candidate_id",binding["candidate_id"]),("bbox_ref",binding["bbox_ref"]["id"])):
                owner=global_owners[field].setdefault(value,case_id)
                if owner!=case_id: raise ValueError(f"{field} reused across targets")
            selected.append((row,binding))
            if arm in {"omni_to_qwen","omni_to_qwen_vista"}:
                request=_get(arts,row["vista_request_ref"],"VISTA request")
                request=_closed(request,{"contract_version","artifact_id","case_id","target_binding_ref","candidate_id","fusion_ref","capture_ref","bbox_ref","submission_status","source_parent_ref","safety"},"request")
                expected={"case_id":binding["case_id"],"target_binding_ref":bref,"candidate_id":binding["candidate_id"],"fusion_ref":binding["fusion_ref"],"capture_ref":binding["capture_ref"],"bbox_ref":binding["bbox_ref"]}
                if request["contract_version"]!="sealed_vista_request_v3" or any(request[k]!=v for k,v in expected.items()) or request["submission_status"]!="SUBMITTED" or request["source_parent_ref"]!=private["source_parent_ref"] or request["safety"]!=SAFETY: raise ValueError("VISTA request parent mapping invalid")
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
    # 公开 binding 只携带不透明 case 身份；正确性由私有几何判定。
    for arm in ARMS:
        armrows=[r for r in rows if r["arm_id"]==arm]; selected=[r for r in armrows if r["selection_status"]=="selected"]
        if not selected: raise ValueError("semantic precision selected denominator is zero")
        correct=sum(_private_unique_target_center_containment(case_id=r["case_id"],bbox=r["_bbox"],cases=cases) for r in selected)
        important_total=sum(bool(c["important_target"]) for c in cases.values()); important_correct=sum(_private_unique_target_center_containment(case_id=r["case_id"],bbox=r["_bbox"],cases=cases) and cases[r["case_id"]]["important_target"] for r in selected)
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

def _sealed_receipt(value:Mapping[str,object],kind:str)->dict[str,object]:
    raw=canonical_bytes(value); digest=hashlib.sha256(raw).hexdigest()
    return {"ref":{"id":f"{kind}/{digest}","content_sha256":digest},"canonical_bytes_b64":base64.b64encode(raw).decode("ascii")}

class _ScorerJob:
    def __init__(self)->None:
        if os.name!="nt": self.name=""; self.identity_sha256="non-windows"; self._handle=None; return
        import ctypes
        from ctypes import wintypes
        class IO(ctypes.Structure): _fields_=[(name,ctypes.c_ulonglong) for name in ("ReadOperationCount","WriteOperationCount","OtherOperationCount","ReadTransferCount","WriteTransferCount","OtherTransferCount")]
        class BASIC(ctypes.Structure): _fields_=[("PerProcessUserTimeLimit",ctypes.c_longlong),("PerJobUserTimeLimit",ctypes.c_longlong),("LimitFlags",wintypes.DWORD),("MinimumWorkingSetSize",ctypes.c_size_t),("MaximumWorkingSetSize",ctypes.c_size_t),("ActiveProcessLimit",wintypes.DWORD),("Affinity",ctypes.c_size_t),("PriorityClass",wintypes.DWORD),("SchedulingClass",wintypes.DWORD)]
        class EXTENDED(ctypes.Structure): _fields_=[("BasicLimitInformation",BASIC),("IoInfo",IO),("ProcessMemoryLimit",ctypes.c_size_t),("JobMemoryLimit",ctypes.c_size_t),("PeakProcessMemoryUsed",ctypes.c_size_t),("PeakJobMemoryUsed",ctypes.c_size_t)]
        class ACCOUNTING(ctypes.Structure): _fields_=[("TotalUserTime",ctypes.c_longlong),("TotalKernelTime",ctypes.c_longlong),("ThisPeriodTotalUserTime",ctypes.c_longlong),("ThisPeriodTotalKernelTime",ctypes.c_longlong),("TotalPageFaultCount",wintypes.DWORD),("TotalProcesses",wintypes.DWORD),("ActiveProcesses",wintypes.DWORD),("TotalTerminatedProcesses",wintypes.DWORD)]
        kernel=ctypes.WinDLL("kernel32",use_last_error=True); name=f"Local\\portfolio-hybrid-v2-scorer-{os.getpid()}-{secrets.token_hex(16)}"
        kernel.CreateJobObjectW.argtypes=(ctypes.c_void_p,wintypes.LPCWSTR); kernel.CreateJobObjectW.restype=wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes=(wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD); kernel.SetInformationJobObject.restype=wintypes.BOOL
        kernel.AssignProcessToJobObject.argtypes=(wintypes.HANDLE,wintypes.HANDLE); kernel.AssignProcessToJobObject.restype=wintypes.BOOL
        kernel.QueryInformationJobObject.argtypes=(wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD)); kernel.QueryInformationJobObject.restype=wintypes.BOOL
        kernel.CloseHandle.argtypes=(wintypes.HANDLE,); kernel.CloseHandle.restype=wintypes.BOOL
        handle=kernel.CreateJobObjectW(None,name)
        if not handle: raise OSError(ctypes.get_last_error(),"CreateJobObjectW failed")
        limits=EXTENDED(); limits.BasicLimitInformation.LimitFlags=0x2000
        if not kernel.SetInformationJobObject(handle,9,ctypes.byref(limits),ctypes.sizeof(limits)): kernel.CloseHandle(handle); raise OSError(ctypes.get_last_error(),"SetInformationJobObject failed")
        self._ctypes=ctypes; self._kernel=kernel; self._accounting=ACCOUNTING; self._handle=handle; self.name=name; self.identity_sha256=hashlib.sha256(name.encode("utf-8")).hexdigest()
    def assign(self,process:subprocess.Popen[str])->None:
        if os.name=="nt" and not self._kernel.AssignProcessToJobObject(self._handle,int(process._handle)): raise OSError(self._ctypes.get_last_error(),"AssignProcessToJobObject failed")
    def active_processes(self)->int:
        if os.name!="nt": return 0
        value=self._accounting()
        if not self._kernel.QueryInformationJobObject(self._handle,1,self._ctypes.byref(value),self._ctypes.sizeof(value),None): raise OSError(self._ctypes.get_last_error(),"QueryInformationJobObject failed")
        return int(value.ActiveProcesses)
    def close(self)->None:
        if os.name=="nt" and self._handle:
            if not self._kernel.CloseHandle(self._handle): raise OSError(self._ctypes.get_last_error(),"CloseHandle(job) failed")
            self._handle=None

def _verify_job_membership(name:str,expected_sha256:str)->None:
    if os.name!="nt":
        if name or expected_sha256!="non-windows": raise PermissionError("private scorer Job identity invalid")
        return
    import ctypes
    from ctypes import wintypes
    if hashlib.sha256(name.encode("utf-8")).hexdigest()!=expected_sha256: raise PermissionError("private scorer Job identity invalid")
    kernel=ctypes.WinDLL("kernel32",use_last_error=True); kernel.OpenJobObjectW.argtypes=(wintypes.DWORD,wintypes.BOOL,wintypes.LPCWSTR); kernel.OpenJobObjectW.restype=wintypes.HANDLE; kernel.IsProcessInJob.argtypes=(wintypes.HANDLE,wintypes.HANDLE,ctypes.POINTER(wintypes.BOOL)); kernel.IsProcessInJob.restype=wintypes.BOOL; kernel.GetCurrentProcess.restype=wintypes.HANDLE; kernel.CloseHandle.argtypes=(wintypes.HANDLE,)
    handle=kernel.OpenJobObjectW(0x0004,False,name)
    if not handle: raise PermissionError("private scorer Job missing")
    try:
        member=wintypes.BOOL()
        if not kernel.IsProcessInJob(kernel.GetCurrentProcess(),handle,ctypes.byref(member)) or not member.value: raise PermissionError("private scorer Job membership invalid")
    finally: kernel.CloseHandle(handle)

def _read_launch_capability(handle_value:int)->dict[str,object]:
    if not isinstance(handle_value,int) or handle_value<=0: raise PermissionError("private scorer launch handle invalid")
    if os.name=="nt":
        import ctypes, msvcrt
        kernel=ctypes.WinDLL("kernel32",use_last_error=True); kernel.GetFileType.argtypes=(ctypes.c_void_p,); kernel.GetFileType.restype=ctypes.c_ulong
        if kernel.GetFileType(handle_value)!=3: raise PermissionError("private scorer launch handle is not a pipe")
        fd=msvcrt.open_osfhandle(handle_value,os.O_RDONLY|os.O_BINARY)
    else:
        fd=handle_value
        if not stat.S_ISFIFO(os.fstat(fd).st_mode): raise PermissionError("private scorer launch handle is not a pipe")
    with os.fdopen(fd,"rb",closefd=True) as stream: raw=stream.read(131073)
    if not raw or len(raw)>131072: raise PermissionError("private scorer launch pipe payload invalid")
    value=json.loads(raw.decode("utf-8"))
    if canonical_bytes(value)!=raw or not isinstance(value,dict): raise PermissionError("private scorer launch pipe payload invalid")
    return value

def execute_closed_child_envelope(handle_value:int)->dict[str,object]:
    global _CHILD_ENTRY_USED
    envelope=_read_launch_capability(handle_value)
    fields={"private_manifest_path","prediction_run_path","lifecycle_path","private_output_path","public_ref_path","nonce","pipe_capability","launcher_process_id","launcher_process_identity","expected_process_id","expected_process_identity","job_name","job_identity_sha256","expected_argv_sha256","expected_env_sha256","expected_cwd_sha256","expected_executable"}
    if _CHILD_ENTRY_USED or not isinstance(envelope,Mapping) or set(envelope)!=fields: raise PermissionError("private scorer entrypoint state invalid")
    pid=os.getpid(); nonce=envelope["nonce"]; capability=envelope["pipe_capability"]; launcher_pid=envelope["launcher_process_id"]
    actual_env=dict(os.environ); actual_cwd=Path.cwd().resolve(); actual_argv=list(sys.argv); actual_executable=Path(sys.executable).resolve()
    projection=canonical_bytes({"argv":actual_argv,"env":actual_env,"cwd":str(actual_cwd),"executable":str(actual_executable)}).decode("utf-8").casefold()
    private_values=[str(envelope[key]).casefold() for key in fields if key.endswith("_path")]
    if not isinstance(nonce,str) or len(nonce)!=64 or not isinstance(capability,str) or len(capability)!=64 or not isinstance(launcher_pid,int) or pid==launcher_pid or os.getppid()!=launcher_pid or envelope["launcher_process_identity"]!=_process_identity(launcher_pid) or envelope["expected_process_id"]!=pid or envelope["expected_process_identity"]!=_process_identity(pid): raise PermissionError("private scorer launcher binding invalid")
    if len(actual_argv)!=3 or Path(actual_argv[0]).resolve()!=SCRIPT.resolve() or actual_argv[1]!="--closed-launch-handle" or actual_argv[2]!=str(handle_value) or set(actual_env)!={"SYSTEMROOT","PYTHONIOENCODING","PYTHONUTF8"} or actual_env["PYTHONIOENCODING"]!="utf-8" or actual_env["PYTHONUTF8"]!="1": raise PermissionError("private scorer argv/environment invalid")
    if hashlib.sha256(canonical_bytes(actual_argv)).hexdigest()!=envelope["expected_argv_sha256"] or hashlib.sha256(canonical_bytes(actual_env)).hexdigest()!=envelope["expected_env_sha256"] or hashlib.sha256(canonical_bytes(str(actual_cwd))).hexdigest()!=envelope["expected_cwd_sha256"] or str(actual_executable)!=envelope["expected_executable"] or any(value in projection for value in private_values): raise PermissionError("private scorer process projection invalid")
    if any(actual_cwd.iterdir()) or sys.stdin.read()!="": raise PermissionError("private scorer neutral cwd/stdin invalid")
    _verify_job_membership(str(envelope["job_name"]),str(envelope["job_identity_sha256"]))
    _CHILD_ENTRY_USED=True
    paths={key:Path(str(envelope[key])) for key in fields if key.endswith("_path")}
    return _run_private_child_once(nonce=nonce,pipe_capability=capability,launcher_process_id=launcher_pid,launcher_process_identity=str(envelope["launcher_process_identity"]),process_identity=str(envelope["expected_process_identity"]),job_identity_sha256=str(envelope["job_identity_sha256"]),argv_sha256=str(envelope["expected_argv_sha256"]),env_sha256=str(envelope["expected_env_sha256"]),cwd_sha256=str(envelope["expected_cwd_sha256"]),**paths)

def _run_private_child_once(*,nonce:str,pipe_capability:str,launcher_process_id:int,launcher_process_identity:str,process_identity:str,job_identity_sha256:str,argv_sha256:str,env_sha256:str,cwd_sha256:str,private_manifest_path:Path,prediction_run_path:Path,lifecycle_path:Path,private_output_path:Path,public_ref_path:Path)->dict[str,object]:
    run,bundle=_load(prediction_run_path),_load(lifecycle_path)
    release=validate_task10_private_release_bundle(private_manifest_path=Path(private_manifest_path))
    partition=run.get("partition") if isinstance(run,Mapping) else None
    derived=derive_private_scoring_cases(validated_release=release,partition=partition)
    score_parent_ref={"id":release["corpus_parent_ref"]["artifact_id"],"content_sha256":release["corpus_parent_ref"]["content_sha256"]}
    private={
        "contract_version":"task10_private_release_scoring_projection_v1",
        "source_parent_ref":score_parent_ref,
        "partition":partition,
        "release_id":release["private_manifest"]["benchmark_release_id"],
        "cases":[{key:value for key,value in case.items() if key!="partition"} for case in derived],
        "expected_automatic_prediction_ref":run.get("automatic_prediction_ref"),
        "expected_attempt_ledger_ref":run.get("attempt_ledger_ref"),
        "expected_regression_precondition_ref":run.get("regression_precondition_ref"),
        "estimand_ref":config_ref(ESTIMAND_PATH),
        "gate_ref":config_ref(GATE_PATH),
    }
    rows,cases,gate=_validate(private,run,bundle,_task10_release=True)
    result=_score(rows,cases,gate); private_result={"contract_version":"portfolio_hybrid_v1_1_private_score_v2",**result,"source_parent_ref":private["source_parent_ref"],"automatic_prediction_ref":run["automatic_prediction_ref"],"estimand_ref":private["estimand_ref"],"gate_ref":private["gate_ref"],"safety":dict(SAFETY)}
    raw=canonical_bytes(private_result)+b"\n"; digest=hashlib.sha256(raw).hexdigest(); receipt={"contract_version":"private_scorer_child_receipt_v2","nonce":nonce,"pipe_capability_sha256":hashlib.sha256(pipe_capability.encode("ascii")).hexdigest(),"launcher_process_id":launcher_process_id,"launcher_process_identity":launcher_process_identity,"process_id":os.getpid(),"process_identity":process_identity,"job_identity_sha256":job_identity_sha256,"argv_sha256":argv_sha256,"env_sha256":env_sha256,"cwd_sha256":cwd_sha256,"safety":dict(SAFETY)}; public={"status":private_result["gate"]["status"],"score_ref":f"private-score/{digest}","content_sha256":digest,"execution_receipt":receipt,"safety":dict(SAFETY)}
    for path,payload in ((Path(private_output_path),raw),(Path(public_ref_path),canonical_bytes(public)+b"\n")):
        path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_name("."+path.name+".tmp")
        try: tmp.write_bytes(payload); tmp.replace(path)
        finally:
            if tmp.exists(): tmp.unlink()
    return public

def run_private_scorer(*,private_manifest_path:Path,prediction_run_path:Path,lifecycle_path:Path,private_output_path:Path,public_ref_path:Path)->dict[str,str]:
    system_root=os.environ.get("SYSTEMROOT") or os.environ.get("SystemRoot")
    nonce=secrets.token_hex(32); pipe_capability=secrets.token_hex(32); launcher_pid=os.getpid(); launcher_identity=_process_identity(launcher_pid)
    env={"SYSTEMROOT":system_root,"PYTHONIOENCODING":"utf-8","PYTHONUTF8":"1"}
    envelope={k:str(Path(v).resolve()) for k,v in {"private_manifest_path":private_manifest_path,"prediction_run_path":prediction_run_path,"lifecycle_path":lifecycle_path,"private_output_path":private_output_path,"public_ref_path":public_ref_path}.items()}
    process=None; job=None; stdout=stderr=""; identity=""; active_after=-1; read_fd=write_fd=-1
    with tempfile.TemporaryDirectory(prefix="benchmark-v2-score-") as operation_root:
        root=Path(operation_root).resolve()
        if root==Path(private_output_path).resolve().parent or root==Path(private_manifest_path).resolve().parent or any(root.iterdir()): raise ValueError("private scorer operation root invalid")
        python_executable=_scorer_python_executable()
        job=_ScorerJob()
        try:
            read_fd,write_fd=os.pipe(); startupinfo=None; popen_extra={}
            if os.name=="nt":
                import msvcrt
                inherited_handle=msvcrt.get_osfhandle(read_fd); write_handle=msvcrt.get_osfhandle(write_fd)
                os.set_handle_inheritable(inherited_handle,True); os.set_handle_inheritable(write_handle,False)
                startupinfo=subprocess.STARTUPINFO(); startupinfo.lpAttributeList={"handle_list":[inherited_handle]}
            else:
                inherited_handle=read_fd; os.set_inheritable(read_fd,True); os.set_inheritable(write_fd,False); popen_extra={"pass_fds":(read_fd,)}
            argv=[str(python_executable),str(SCRIPT),"--closed-launch-handle",str(inherited_handle)]
            process=subprocess.Popen(argv,executable=str(python_executable),cwd=root,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="utf-8",close_fds=True,startupinfo=startupinfo,**popen_extra)
            os.close(read_fd); read_fd=-1; job.assign(process); identity=_process_identity(process.pid)
            child_argv=[str(SCRIPT),"--closed-launch-handle",str(inherited_handle)]
            envelope.update({"nonce":nonce,"pipe_capability":pipe_capability,"launcher_process_id":launcher_pid,"launcher_process_identity":launcher_identity,"expected_process_id":process.pid,"expected_process_identity":identity,"job_name":job.name,"job_identity_sha256":job.identity_sha256,"expected_argv_sha256":hashlib.sha256(canonical_bytes(child_argv)).hexdigest(),"expected_env_sha256":hashlib.sha256(canonical_bytes(env)).hexdigest(),"expected_cwd_sha256":hashlib.sha256(canonical_bytes(str(root))).hexdigest(),"expected_executable":str(python_executable)})
            os.write(write_fd,canonical_bytes(envelope)); os.close(write_fd); write_fd=-1
            stdout,stderr=process.communicate(timeout=30)
        finally:
            try:
                if read_fd>=0: os.close(read_fd); read_fd=-1
            finally:
                try:
                    if write_fd>=0: os.close(write_fd); write_fd=-1
                finally:
                    try:
                        if process is not None:
                            if process.poll() is None: process.kill()
                            process.wait(timeout=10)
                            for pipe in (process.stdout,process.stderr):
                                if pipe is not None: pipe.close()
                        active_after=job.active_processes()
                    finally: job.close()
    if process is None or process.returncode!=0: raise ValueError("private scorer failed closed; sensitive details redacted")
    lines=stdout.splitlines()
    if len(lines)!=1: raise ValueError("private scorer stdout contract invalid")
    child_ref=json.loads(lines[0]); child_public=json.loads(Path(public_ref_path).read_text(encoding="utf-8")); receipt=child_public.get("execution_receipt")
    expected_receipt={"contract_version":"private_scorer_child_receipt_v2","nonce":nonce,"pipe_capability_sha256":hashlib.sha256(pipe_capability.encode("ascii")).hexdigest(),"launcher_process_id":launcher_pid,"launcher_process_identity":launcher_identity,"process_id":process.pid,"process_identity":identity,"job_identity_sha256":job.identity_sha256,"argv_sha256":envelope["expected_argv_sha256"],"env_sha256":envelope["expected_env_sha256"],"cwd_sha256":envelope["expected_cwd_sha256"],"safety":SAFETY}
    if not isinstance(child_ref,dict) or set(child_ref)!={"status","score_ref","content_sha256"} or {k:child_public[k] for k in child_ref}!=child_ref or receipt!=expected_receipt or os.getpid()!=launcher_pid or _process_identity(launcher_pid)!=launcher_identity: raise ValueError("private scorer child artifact mismatch")
    launch={"contract_version":"private_scorer_launch_receipt_v1","launcher_process_id":launcher_pid,"launcher_process_identity":launcher_identity,"child_process_id":process.pid,"child_process_identity":identity,"pipe_capability_sha256":expected_receipt["pipe_capability_sha256"],"argv_sha256":envelope["expected_argv_sha256"],"env_sha256":envelope["expected_env_sha256"],"cwd_sha256":envelope["expected_cwd_sha256"],"job_identity_sha256":job.identity_sha256,"child_execution_receipt_sha256":hashlib.sha256(canonical_bytes(receipt)).hexdigest(),"child_score_ref":child_ref,"safety":dict(SAFETY)}; launch_env=_sealed_receipt(launch,"private-scorer-launch")
    cleanup={"contract_version":"private_scorer_cleanup_receipt_v1","launch_receipt_ref":launch_env["ref"],"child_returncode":process.returncode,"job_active_processes_after":active_after,"job_stable_zero":active_after==0,"pipe_handles_closed":read_fd<0 and write_fd<0,"process_pipes_closed":all(pipe is None or pipe.closed for pipe in (process.stdout,process.stderr)),"job_handle_closed":getattr(job,"_handle",None) is None,"safety":dict(SAFETY)}
    if not all(cleanup[key] is True for key in ("job_stable_zero","pipe_handles_closed","process_pipes_closed","job_handle_closed")): raise ValueError("private scorer cleanup did not reach stable zero")
    cleanup_env=_sealed_receipt(cleanup,"private-scorer-cleanup"); binding={"contract_version":"private_scorer_final_binding_v1","child_score_ref":child_ref,"launch_receipt_ref":launch_env["ref"],"cleanup_receipt_ref":cleanup_env["ref"],"safety":dict(SAFETY)}; digest=hashlib.sha256(canonical_bytes(binding)).hexdigest(); final_ref={"status":child_ref["status"],"score_ref":f"private-score-final/{digest}","content_sha256":digest}
    final_public={**final_ref,"contract_version":"private_scorer_public_ref_v2","binding":binding,"launch_receipt":launch_env,"cleanup_receipt":cleanup_env,"safety":dict(SAFETY)}
    final_path=Path(public_ref_path); temporary=final_path.with_name("."+final_path.name+".final.tmp")
    try: temporary.write_bytes(canonical_bytes(final_public)+b"\n"); temporary.replace(final_path)
    finally:
        if temporary.exists(): temporary.unlink()
    return validate_private_scorer_public_ref(final_public)

def validate_private_scorer_public_ref(public:object)->dict[str,str]:
    fields={"status","score_ref","content_sha256","contract_version","binding","launch_receipt","cleanup_receipt","safety"}
    if not isinstance(public,Mapping) or set(public)!=fields or public["contract_version"]!="private_scorer_public_ref_v2" or public["safety"]!=SAFETY: raise ValueError("private scorer public chain invalid")
    decoded=[]
    for name,contract,kind in (("launch_receipt","private_scorer_launch_receipt_v1","private-scorer-launch"),("cleanup_receipt","private_scorer_cleanup_receipt_v1","private-scorer-cleanup")):
        env=public[name]
        if not isinstance(env,Mapping) or set(env)!={"ref","canonical_bytes_b64"}: raise ValueError("private scorer receipt envelope invalid")
        try: raw=base64.b64decode(env["canonical_bytes_b64"],validate=True); value=json.loads(raw.decode("utf-8"))
        except (ValueError,UnicodeDecodeError,base64.binascii.Error) as error: raise ValueError("private scorer receipt encoding invalid") from error
        digest=hashlib.sha256(raw).hexdigest()
        if canonical_bytes(value)!=raw or env["ref"]!={"id":f"{kind}/{digest}","content_sha256":digest} or value.get("contract_version")!=contract or value.get("safety")!=SAFETY: raise ValueError("private scorer receipt invalid")
        decoded.append(value)
    launch,cleanup=decoded; binding=public["binding"]
    child_score=binding.get("child_score_ref") if isinstance(binding,Mapping) else None
    launch_fields={"contract_version","launcher_process_id","launcher_process_identity","child_process_id","child_process_identity","pipe_capability_sha256","argv_sha256","env_sha256","cwd_sha256","job_identity_sha256","child_execution_receipt_sha256","child_score_ref","safety"}; cleanup_fields={"contract_version","launch_receipt_ref","child_returncode","job_active_processes_after","job_stable_zero","pipe_handles_closed","process_pipes_closed","job_handle_closed","safety"}
    sha_fields=("pipe_capability_sha256","argv_sha256","env_sha256","cwd_sha256","job_identity_sha256","child_execution_receipt_sha256")
    if set(launch)!=launch_fields or set(cleanup)!=cleanup_fields or not isinstance(launch.get("launcher_process_id"),int) or not isinstance(launch.get("child_process_id"),int) or launch["launcher_process_id"]<=0 or launch["child_process_id"]<=0 or launch["launcher_process_id"]==launch["child_process_id"] or any(not isinstance(launch.get(key),str) or len(launch[key])!=64 for key in sha_fields) or not isinstance(child_score,Mapping) or set(child_score)!={"status","score_ref","content_sha256"} or launch["child_score_ref"]!=child_score or binding!={"contract_version":"private_scorer_final_binding_v1","child_score_ref":child_score,"launch_receipt_ref":public["launch_receipt"]["ref"],"cleanup_receipt_ref":public["cleanup_receipt"]["ref"],"safety":SAFETY} or cleanup.get("launch_receipt_ref")!=public["launch_receipt"]["ref"] or cleanup.get("child_returncode")!=0 or cleanup.get("job_active_processes_after")!=0 or any(cleanup.get(key) is not True for key in ("job_stable_zero","pipe_handles_closed","process_pipes_closed","job_handle_closed")): raise ValueError("private scorer launch/cleanup chain invalid")
    digest=hashlib.sha256(canonical_bytes(binding)).hexdigest(); result={"status":binding["child_score_ref"]["status"],"score_ref":f"private-score-final/{digest}","content_sha256":digest}
    if any(public[key]!=value for key,value in result.items()): raise ValueError("private scorer final ref invalid")
    return result
