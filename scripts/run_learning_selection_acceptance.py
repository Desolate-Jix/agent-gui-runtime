"""固定 35 个目标的三策略接入验收，不调用任何 GUI 动作。"""
from __future__ import annotations
import argparse
from copy import deepcopy
from hashlib import sha256
import json
import math
from pathlib import Path
import subprocess
import sys
import threading
import time
import traceback
from typing import Any, Mapping
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.learn.hybrid.static_capture import seal_static_capture_bundle
from app.learn.draft_review import load_learning_draft_review
from app.learn.recognition.uei.omniparser_shadow_adapter import TrustedOmniParserConfiguration
from app.learn.workflow_service import run_learning_selection_actual_no_action

POLICIES = ("never", "conditional", "always")
NVIDIA_SAMPLE_SECONDS = 1.0
E_MODEL_STORAGE_CAP_BYTES = 32_212_254_720
FROZEN_CATALOG_SHA256 = "bb09975c8042f72a59e41fa9f22969cf5104c8419deb5e9d62804ee855a35d92"

class _NvidiaSampler:
    """只采样整卡显存，不操作模型进程，也不声称是模型独占峰值。"""
    def __init__(self) -> None:
        self.samples: list[dict[str, Any]] = []
        self.error: str | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        self._thread.join(timeout=6.5)
        if self._thread.is_alive():
            self.error = "sampler_thread_did_not_exit"
        peak = max((sample["used_mib"] for sample in self.samples), default=None)
        return {"contract_version": "learning_selection_device_memory_observation_v1",
                "scope": "device_wide_inclusive_other_processes", "measurement": "unmeasured" if self.error else "observed",
                "peak_device_used_mib": peak, "samples": deepcopy(self.samples), "error": self.error}

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                output = subprocess.check_output(
                    ["nvidia-smi", "--query-gpu=uuid,memory.total,memory.used,memory.free", "--format=csv,noheader,nounits"],
                    text=True, stderr=subprocess.STDOUT, timeout=5.0,
                )
                for line in output.splitlines():
                    fields = [item.strip() for item in line.split(",")]
                    if len(fields) != 4 or not all(fields):
                        raise ValueError("invalid nvidia-smi row")
                    self.samples.append({"timestamp_unix_ms": round(time.time() * 1000), "uuid": fields[0],
                                         "total_mib": int(fields[1]), "used_mib": int(fields[2]), "free_mib": int(fields[3])})
            except (OSError, subprocess.SubprocessError, ValueError) as error:
                self.error = f"{type(error).__name__}:{error}"
                return
            self._stop.wait(NVIDIA_SAMPLE_SECONDS)

def _write_new(path: Path, value: object) -> None:
    if path.exists(): raise ValueError(f"refusing to overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))

def _key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    out = tuple(row.get(x) for x in ("suite", "case_id", "target_id"))
    if not all(isinstance(x, str) and x for x in out): raise ValueError("invalid catalog key")
    return out # type: ignore[return-value]

def _catalog(path: Path) -> dict[str, Any]:
    if sha256(path.read_bytes()).hexdigest() != FROZEN_CATALOG_SHA256: raise ValueError("catalog is not the approved pinned 35-case catalog")
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("contract_version") != "learning_selection_acceptance_catalog_v1": raise ValueError("invalid catalog")
    if not isinstance(value.get("inference_rows"), list) or not isinstance(value.get("scoring_rows"), list): raise ValueError("invalid catalog rows")
    if len(value["inference_rows"]) != 35 or len(value["scoring_rows"]) != 35: raise ValueError("catalog is not exact35")
    inference={_key(row) for row in value["inference_rows"]}; scoring={_key(row) for row in value["scoring_rows"]}
    if len(inference) != 35 or inference != scoring: raise ValueError("catalog keys are not exact joined35")
    if any(row.get("human_correction_applied") is not False for row in value["scoring_rows"]): raise ValueError("human corrected rows are excluded")
    return value

def _copy_exact(source: Path, destination: Path, expected: str) -> None:
    raw = source.read_bytes()
    if sha256(raw).hexdigest() != expected: raise ValueError(f"pinned SHA differs: {source}")
    if destination.exists():
        if destination.read_bytes() != raw: raise ValueError(f"existing static artifact differs: {destination}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True); destination.write_bytes(raw)

def _static(row: Mapping[str, Any], run_id: str) -> tuple[Path, dict[str, Any]]:
    source = Path(str(row["image_path"])); digest = str(row["image_sha256"])
    image = ROOT / "artifacts/screenshots/learning-selection-acceptance" / (digest + (source.suffix.lower() or ".png"))
    _copy_exact(source, image, digest)
    if row["suite"] == "fixed25":
        # 固定集只投影已批准清单中的图像身份，绝不复制历史预测或评分答案。
        value = {"schema": "learning_selection_fixed_capture_manifest_v1", "dataset": "portfolio_hybrid_v1_1",
            "revision": FROZEN_CATALOG_SHA256, "source_catalog_sha256": FROZEN_CATALOG_SHA256,
            "records": [{"case_id": row["case_id"], "image_sha256": digest, "image_bytes": image.stat().st_size,
                         "width": row["image_size"][0], "height": row["image_size"][1]}]}
        raw = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        manifest_sha = sha256(raw).hexdigest()
        manifest = ROOT / "artifacts/static-manifests/learning-selection-fixed" / (manifest_sha + ".json")
        if manifest.exists() and manifest.read_bytes() != raw:
            raise ValueError("fixed static manifest identity changed")
        if not manifest.exists():
            _write_new(manifest, value)
    elif row["suite"] == "public10":
        refs = row.get("source_manifest_refs")
        if not isinstance(refs, list) or not refs or not isinstance(refs[0], Mapping): raise ValueError("missing source manifest")
        ref = refs[0]; manifest_sha = str(ref["sha256"])
        manifest = ROOT / "artifacts/static-manifests" / (manifest_sha + ".json")
        _copy_exact(Path(str(ref["path"])), manifest, manifest_sha)
        value = json.loads(manifest.read_text(encoding="utf-8"))
    else:
        raise ValueError("unknown acceptance suite")
    bundle = seal_static_capture_bundle(project_root=ROOT, image_path=image, run_id=run_id, workflow_revision=0,
        static_asset={"case_id": row["case_id"], "dataset": value["dataset"], "revision": value["revision"],
        "source_manifest_ref": {"relative_path": manifest.relative_to(ROOT).as_posix(), "sha256": manifest_sha}})
    return image, bundle

def _configuration(assets: Path) -> TrustedOmniParserConfiguration:
    base = assets.resolve()
    return TrustedOmniParserConfiguration(interpreter=base / "tools/omniparser-v2.0.1/.venv/Scripts/python.exe",
        worker_script=ROOT / "scripts/run_uei_omniparser_shadow_worker.py", code_path=base / "tools/omniparser-v2.0.1",
        weights_path=base / "models/omniparser/v2.0.1/weights", cache_path=Path("~/.cache/huggingface/hub").expanduser())

def _point(value: object) -> list[int | float] | None:
    if not isinstance(value, list) or len(value) != 2 or any(isinstance(x, bool) or not isinstance(x, (int,float)) or not math.isfinite(x) for x in value): return None
    return list(value)

def _score(point: list[int | float] | None, gold: Mapping[str, Any]) -> str:
    if point is None: return "abstained"
    geometry = gold.get("ground_truth")
    if not isinstance(geometry, Mapping): raise ValueError("missing scoring geometry")
    if isinstance(geometry.get("acceptable_regions"), list):
        return "correct" if any(isinstance(r,list) and len(r)==4 and r[0] < point[0] < r[2] and r[1] < point[1] < r[3] for r in geometry["acceptable_regions"]) else "wrong"
    bbox = geometry.get("bbox_xyxy")
    if not isinstance(bbox,list) or len(bbox)!=4: raise ValueError("invalid scoring geometry")
    return "correct" if bbox[0] <= point[0] <= bbox[2] and bbox[1] <= point[1] <= bbox[3] else "wrong"

def _read_response(case_dir: Path) -> dict[str, Any] | None:
    path=case_dir / "selection-result.json"
    if not path.is_file(): return None
    value=json.loads(path.read_text(encoding="utf-8")); return value if isinstance(value,dict) else None

def _identities(response: Mapping[str, Any] | None) -> dict[str, Any]:
    selection=response.get("selection") if isinstance(response,Mapping) else None; refinement=response.get("refinement") if isinstance(response,Mapping) else None
    proposal=selection.get("model_proposal") if isinstance(selection,Mapping) else None; refined=refinement.get("provider_result") if isinstance(refinement,Mapping) else None
    return {"selection": proposal.get("provider_id") if isinstance(proposal,Mapping) else None, "refinement": refined.get("provider_id") if isinstance(refined,Mapping) else None}

def _actual_score(result: Mapping[str,Any], response: Mapping[str,Any] | None, gold: Mapping[str,Any]) -> dict[str,Any]:
    if result.get("outcome") != "completed" or not isinstance(response,Mapping): return {"outcome":"abstained","point":None,"reason":"actual_run_not_completed"}
    selection=response.get("selection"); refinement=response.get("refinement"); review=response.get("review_projection")
    if not isinstance(selection,Mapping) or not isinstance(review,Mapping) or review.get("execution_origin") != "actual_model" or review.get("artifact_is_authorization") is not False or review.get("execute_binding_enabled") is not False:
        return {"outcome":"abstained","point":None,"reason":"selection_protocol_validation_failed"}
    if selection.get("selection_status") in {"ambiguous", "unbound", "provider_failure"}:
        return {"outcome": "abstained", "point": None, "reason": "selection_" + selection["selection_status"]}
    if selection.get("selection_status") != "selected":
        return {"outcome": "abstained", "point": None, "reason": "selection_protocol_validation_failed"}
    proposal=selection.get("model_proposal") if isinstance(selection,Mapping) else None; provider=refinement.get("provider_result") if isinstance(refinement,Mapping) else None
    original=_point(proposal.get("canonical_capture_pixel_point") if isinstance(proposal,Mapping) else None)
    status=refinement.get("status") if isinstance(refinement,Mapping) else None; refined=_point(provider.get("canonical_capture_pixel_point") if isinstance(provider,Mapping) else None)
    chosen=original if status == "skipped" else refined if status == "validated" else None
    if _point(result.get("original_capture_pixel_point")) != original or _point(result.get("canonical_capture_pixel_point")) != chosen:
        return {"outcome":"abstained","point":None,"reason":"result_point_evidence_mismatch"}
    if chosen is None: return {"outcome":"abstained","point":None,"reason":"refinement_not_validated_or_selection_not_selected"}
    return {"outcome":_score(chosen,gold),"point":chosen,"reason":"scored_model_evidence"}

def _file_ref(path: Path) -> dict[str,str] | None:
    return {"path":path.name,"sha256":sha256(path.read_bytes()).hexdigest()} if path.is_file() else None


def _source_identity() -> dict[str, str]:
    names = ["scripts/run_learning_selection_acceptance.py", "scripts/run_uei_omniparser_shadow_worker.py",
        "configs/learn_hybrid_v1_2.json", "configs/model_profiles/vista_4b_transformers.json",
        "app/learn/recognition/uei/omniparser_shadow_adapter.py",
        "app/learn/recognition/uei/schemas/hybrid_static_capture_context_v1.schema.json",
        "app/learn/workflow_tasks/hybrid_selection.py"]
    names += ["app/learn/hybrid/" + name + ".py" for name in (
        "selection_actual", "selection_refinement", "refinement_policy", "target_selection",
        "selection_review", "selection_persistence", "gui_actor_current_source", "vista_current_source", "omni_discovery", "omni_candidates", "static_capture")]
    return {name: sha256((ROOT / name).read_bytes()).hexdigest() for name in names}


def _verified_response(actual: Mapping, response: Mapping | None, row: Mapping, mode: str) -> None:
    """评分只读取经过既有存储重建的原模型父证据，不读取人工框或人工点。"""
    if actual.get("outcome") != "completed":
        return
    if not isinstance(response, Mapping) or actual.get("execution_origin") != "actual_model" or actual.get("refinement_mode") != mode:
        raise ValueError("actual selection response identity is invalid")
    if actual.get("artifact_is_authorization") is not False or actual.get("execute_binding_enabled") is not False:
        raise ValueError("actual result is authorizing")
    trial = actual.get("trial_path")
    if not isinstance(trial, str):
        raise ValueError("completed model result has no sealed trial")
    loaded = load_learning_draft_review(trial, project_root=ROOT)
    projection = loaded.get("hybrid_review_projection", {})
    selection, refinement = projection.get("selection"), projection.get("refinement")
    if not isinstance(selection, Mapping) or not isinstance(refinement, Mapping) or projection.get("execution_origin") != "actual_model":
        raise ValueError("sealed actual selection projection missing")
    if response.get("selection") != selection or response.get("refinement") != refinement:
        raise ValueError("scoring response differs from sealed model parents")
    if selection.get("target_text") != row["target_text"] or selection.get("capture", {}).get("image_sha256") != row["image_sha256"]:
        raise ValueError("sealed model input identity differs from pinned case")
    if refinement.get("policy", {}).get("mode") != mode:
        raise ValueError("sealed refinement policy differs from acceptance arm")


def _cleanup_verified(case_dir: Path, model_call_started: bool) -> bool:
    """有不确定的模型清理证据时停止下一模型，不以 GPU 空闲代替所有权证明。"""
    if not model_call_started:
        return True
    omni_path = case_dir / "omni-result.json"
    if not omni_path.is_file() or json.loads(omni_path.read_text(encoding="utf-8")).get("cleanup_status") != "clean":
        return False
    for provider in ("gui-actor", "vista"):
        directory = case_dir / provider
        if not directory.exists():
            continue
        path = directory / "result.json"
        if not path.is_file():
            path = directory / "failure-result.json"
        if not path.is_file():
            return False
        value = json.loads(path.read_text(encoding="utf-8"))
        child = value.get("child", {})
        cleanup = value.get("cleanup", child.get("cleanup", {}))
        if child.get("status") == "not_started" and child.get("pid") is None and cleanup.get("status") == "not_started":
            continue
        if provider == "vista":
            if cleanup.get("status") != "verified_exact_child_killed" or cleanup.get("owned_tree_exited") is not True or cleanup.get("listener_absent") is not True:
                return False
        elif cleanup.get("status") not in {"verified_exact_child_exited", "verified_exact_child_killed"}:
            return False
    return True

def _reuse(path: Path,row: Mapping[str,Any],mode:str,gold: Mapping[str,Any], identity_sha: str) -> dict[str,Any]|None:
    if not path.is_file(): return None
    value=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value,dict) or value.get("contract_version")!="learning_selection_acceptance_case_receipt_v1": return None
    if value.get("key") != list(_key(row)) or value.get("refinement_mode") != mode or value.get("image_sha256") != row.get("image_sha256") or value.get("target_sha256") != sha256(str(row["target_text"]).encode()).hexdigest(): return None
    if value.get("run_identity_sha256") != identity_sha or value.get("human_correction_applied") is not False:
        return None
    try:
        for key, name in (("actual_result_file_ref", "runner-result.json"), ("coordinator_result_file_ref", "result.json"), ("selection_result_file_ref", "selection-result.json"), ("memory_file_ref", "device-memory.json")):
            if value.get(key) != _file_ref(path.parent / name):
                return None
        actual = json.loads((path.parent / "runner-result.json").read_text(encoding="utf-8"))
        if value.get("actual_result") != actual:
            return None
        response=_read_response(path.parent)
        _verified_response(actual, response, row, mode)
        verified=_actual_score(actual,response,gold)
        if value.get("resource_cleanup_verified") is not _cleanup_verified(path.parent, bool(value.get("model_call_started"))):
            return None
    except (OSError, ValueError, KeyError, TypeError):
        return None
    value["score"]=verified
    value["baseline_outcome"] = gold["baseline_outcome"]
    return value

def _runtime_metrics(receipts: list[Mapping[str,Any]]) -> dict[str,Any]:
    output={}
    for mode in POLICIES:
        values=sorted(float(r["runtime_ms"]) for r in receipts if r["refinement_mode"]==mode and isinstance(r.get("runtime_ms"),(int,float)))
        output[mode]={"call_count":len(values),"startup_mode":"cold_per_case","warm_stats":"not_measured","peak_model_vram_bytes":"unmeasured",
            "p50_ms": values[(len(values)-1)//2] if values else None,
            "p95_ms": values[min(len(values)-1, max(0, int((len(values)*.95 + .999999))-1))] if values else None}
    return output

def _tree_bytes(root: Path) -> int:
    if not root.is_dir(): raise ValueError(f"artifact root is unavailable: {root}")
    total = 0
    for path in root.rglob("*"):
        if path.is_file(): total += path.stat().st_size
    return total

def run_acceptance(*,catalog_path:Path,out_dir:Path,limit:int|None,assets_root:Path,artifact_root:Path) -> dict[str,Any]:
    if not out_dir.resolve().is_relative_to(ROOT): raise ValueError("acceptance outputs must remain under project root")
    catalog=_catalog(catalog_path); all_rows=catalog["inference_rows"]; rows=all_rows if limit is None else all_rows[:limit]
    if limit is not None and limit<=0: raise ValueError("limit must be positive")
    scores={_key(r):r for r in catalog["scoring_rows"]}
    if len(scores)!=len(catalog["scoring_rows"]): raise ValueError("duplicate scoring keys")
    before_bytes = _tree_bytes(artifact_root)
    if before_bytes > E_MODEL_STORAGE_CAP_BYTES:
        raise RuntimeError("existing E artifact root exceeds 30GiB preflight cap")
    out_dir.mkdir(parents=True,exist_ok=True); configuration=_configuration(assets_root); receipts=[]
    identity = {"catalog_sha256": sha256(catalog_path.read_bytes()).hexdigest(), "code_identity": _source_identity(),
        "assets_root": str(assets_root.resolve()), "artifact_root": str(artifact_root.resolve()), "policies": list(POLICIES)}
    identity_path = out_dir / "run-identity.json"
    if identity_path.exists():
        if json.loads(identity_path.read_text(encoding="utf-8")) != identity:
            raise ValueError("resume inputs or implementation changed; use a new acceptance directory")
    else:
        _write_new(identity_path, identity)
    identity_sha = sha256(identity_path.read_bytes()).hexdigest()
    stopped_for_cleanup = False
    for row in rows:
        gold=scores[_key(row)]
        for mode in POLICIES:
            token=sha256(("|".join(_key(row))+"|"+mode).encode()).hexdigest(); case_dir=out_dir/"cases"/token; receipt_path=case_dir/"acceptance-receipt.json"; cached=_reuse(receipt_path,row,mode,gold,identity_sha)
            if cached is not None:
                receipts.append(cached)
                if cached["resource_cleanup_verified"] is not True:
                    stopped_for_cleanup = True
                    break
                continue
            if case_dir.exists(): raise ValueError(f"unverifiable incomplete case: {case_dir}")
            run_id="learning-selection-acceptance-"+uuid4().hex; started=time.perf_counter(); sampler=None
            model_call_started = False
            validation_error = None
            try:
                image,bundle=_static(row,run_id); sampler=_NvidiaSampler(); sampler.start()
                model_call_started = True
                actual=run_learning_selection_actual_no_action(project_root=ROOT,run_id=run_id,workflow_revision=0,capture_bundle_ref=bundle["bundle_ref"],image_path=image,target_text=row["target_text"],omni_configuration=configuration,artifact_root=artifact_root,out_dir=case_dir,refinement_mode=mode)
            except Exception as error:
                # 单项失败明确进入分母，仍需检查清理后才能继续下一个模型。
                _write_new(case_dir / "runner-exception.json", {"exception_type": type(error).__name__, "message": str(error), "traceback_utf8": traceback.format_exc()})
                actual={"outcome":"safe_stopped","reason":f"input_or_runner_failure:{type(error).__name__}:{error}"}
            finally:
                memory=sampler.stop() if sampler is not None else {"contract_version":"learning_selection_device_memory_observation_v1","scope":"device_wide_inclusive_other_processes","measurement":"unmeasured","peak_device_used_mib":None,"samples":[],"error":"sampler_not_started"}
            runtime_ms=round((time.perf_counter()-started)*1000,3)
            _write_new(case_dir / "device-memory.json", memory)
            _write_new(case_dir / "runner-result.json", actual)
            response = None
            try:
                response = _read_response(case_dir)
                _verified_response(actual, response, row, mode)
                score = _actual_score(actual, response, gold)
            except (OSError, ValueError, KeyError, TypeError) as error:
                validation_error = f"{type(error).__name__}: {error}"
                score = {"outcome": "abstained", "point": None, "reason": "sealed_model_evidence_validation_failed"}
            try:
                cleanup_verified = _cleanup_verified(case_dir, model_call_started)
            except (OSError, ValueError, KeyError, TypeError):
                cleanup_verified = False
            model_identities = _identities(response)
            for provider in ("gui-actor", "vista"):
                native_path = case_dir / provider / "result.json"
                if native_path.is_file():
                    model_identities[provider + "_current_source"] = json.loads(native_path.read_text(encoding="utf-8")).get("current_source_receipt")
            receipt={"contract_version":"learning_selection_acceptance_case_receipt_v1","key":list(_key(row)),"refinement_mode":mode,"image_sha256":row["image_sha256"],"target_sha256":sha256(str(row["target_text"]).encode()).hexdigest(),
                "actual_result":deepcopy(actual), "actual_result_file_ref":_file_ref(case_dir/"runner-result.json"), "coordinator_result_file_ref":_file_ref(case_dir/"result.json"),
                "selection_result_file_ref":_file_ref(case_dir/"selection-result.json"), "memory_file_ref": _file_ref(case_dir / "device-memory.json"),
                "model_identities":model_identities,"score":score,"baseline_outcome":gold["baseline_outcome"],"human_correction_applied":False,"runtime_ms":runtime_ms,"runtime_kind":"cold_only","device_memory_ref":"device-memory.json","peak_device_used_mib":memory["peak_device_used_mib"],
                "run_identity_sha256": identity_sha, "model_call_started": model_call_started, "resource_cleanup_verified": cleanup_verified,
                "validation_error": validation_error, "refinement_requested": (case_dir / "vista-roi.png").exists()}
            _write_new(receipt_path,receipt); receipts.append(receipt); print(json.dumps({"case":receipt["key"],"mode":mode,"outcome":score["outcome"],"runtime_ms":runtime_ms},ensure_ascii=False),flush=True)
            if not cleanup_verified:
                stopped_for_cleanup = True
                break
        if stopped_for_cleanup:
            break
    counts={}; regressions=[]; transitions={}
    for receipt in receipts:
        mode=receipt["refinement_mode"]; outcome=receipt["score"]["outcome"]; stat=counts.setdefault(mode,{"targets":0,"correct":0,"wrong":0,"abstained":0});stat["targets"]+=1;stat[outcome]+=1
        key=tuple(receipt["key"]);transitions.setdefault(key,{})[mode]=outcome
        if receipt["baseline_outcome"]=="correct" and outcome!="correct": regressions.append({"key":receipt["key"],"refinement_mode":mode,"actual_outcome":outcome,"reason":receipt["score"]["reason"]})
    full=len(rows)==len(all_rows) and len(receipts)==len(all_rows)*len(POLICIES)
    conditional=counts.get("conditional",{})
    conditional_regressions=[row for row in regressions if row["refinement_mode"] == "conditional"]
    after_bytes = _tree_bytes(artifact_root)
    within_cap = after_bytes <= E_MODEL_STORAGE_CAP_BYTES
    source_unchanged = identity["code_identity"] == _source_identity()
    evidence_errors = [r["key"] + [r["refinement_mode"]] for r in receipts if r.get("validation_error") or r["score"]["reason"] in {"selection_protocol_validation_failed", "result_point_evidence_mismatch"}]
    report={"contract_version":"learning_selection_acceptance_report_v1","catalog_ref":{"path":str(catalog_path),"sha256":sha256(catalog_path.read_bytes()).hexdigest()},"policies":list(POLICIES),"partial":not full,"full_denominator":len(all_rows)*len(POLICIES),"completed_denominator":len(receipts),"per_policy":counts,"runtime":_runtime_metrics(receipts),
        "denominator_per_policy": {mode: len(all_rows) for mode in POLICIES}, "not_run_per_policy": {mode: len(all_rows) - counts.get(mode, {}).get("targets", 0) for mode in POLICIES},
        "refinement_call_counts": {mode: sum(r["refinement_requested"] for r in receipts if r["refinement_mode"] == mode) for mode in POLICIES},
        "storage_preflight":{"before_bytes": before_bytes, "after_bytes": after_bytes,"cap_bytes":E_MODEL_STORAGE_CAP_BYTES,"within_cap":within_cap},
        "source_unchanged": source_unchanged, "evidence_errors": evidence_errors, "stopped_for_unverified_cleanup": stopped_for_cleanup,
        "generalization_validation": "not_run", "original_correct_regressions":regressions,"cross_policy_transitions":[{"key":list(key),"outcomes":value} for key,value in sorted(transitions.items())],
        "full_acceptance_pass":bool(full and source_unchanged and within_cap and not evidence_errors and not stopped_for_cleanup and conditional.get("correct",0) >= 26 and conditional.get("wrong") == 0 and not conditional_regressions),"human_corrected_results_excluded":True,"artifact_is_authorization":False,"execute_binding_enabled":False}
    _write_new(out_dir/("acceptance-report-"+uuid4().hex+".json"),report);return report

def main()->int:
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--out",required=True,type=Path);parser.add_argument("--catalog",type=Path,default=ROOT/"configs/benchmarks/learning_selection_acceptance_v1.json");parser.add_argument("--config",dest="catalog",type=Path);parser.add_argument("--limit",type=int);parser.add_argument("--no-action",action="store_true");parser.add_argument("--omni-assets-root",type=Path,default=Path("D:/agent-gui-runtime"));parser.add_argument("--artifact-root",type=Path,default=Path("E:/")/"\u6a21\u578b\u6d4b\u8bd5");args=parser.parse_args()
    report=run_acceptance(catalog_path=args.catalog,out_dir=args.out,limit=args.limit,assets_root=args.omni_assets_root,artifact_root=args.artifact_root);print(json.dumps(report,ensure_ascii=False,indent=2));return 0 if report["full_acceptance_pass"] else 1
if __name__=="__main__": raise SystemExit(main())
