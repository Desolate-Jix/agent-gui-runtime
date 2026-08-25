"""Private Benchmark-v2 scorer; only this module consumes the private manifest."""
from __future__ import annotations

from fractions import Fraction
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

SAFETY = {"artifact_is_authorization": False, "execute_binding_enabled": False, "display_only": True}
ARMS = ("qwen_only", "omni_only_discovery", "omni_to_qwen", "omni_to_qwen_vista")
PAIR_ARMS = ("omni_to_qwen", "omni_to_qwen_vista")
FAILURES = {"failed", "timeout", "out_of_bounds", "missing"}
GATE_PATH = Path(__file__).resolve().parents[3] / "configs" / "benchmarks" / "portfolio_hybrid_v1_1_gate.v2.json"


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _load(path: Path) -> Any:
    raw = Path(path).read_bytes()
    try: value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc: raise ValueError("private scorer input is invalid UTF-8 JSON") from exc
    if raw != _canonical(value) + b"\n": raise ValueError("private scorer input bytes are not canonical")
    return value


def _ref(value: object, name: str, *, extra: set[str] = set()) -> dict[str, Any]:
    fields = {"id", "content_sha256"} | extra
    if not isinstance(value, Mapping) or set(value) != fields: raise ValueError(f"{name} is not an exact ref")
    result = dict(value)
    if not isinstance(result["id"], str) or len(str(result["content_sha256"])) != 64: raise ValueError(f"{name} is invalid")
    return result


def _hit(point: tuple[Fraction, Fraction], regions: list[list[int]]) -> int:
    return int(any(Fraction(x1) <= point[0] < Fraction(x2) and Fraction(y1) <= point[1] < Fraction(y2) for x1,y1,x2,y2 in regions))


def _gate() -> dict[str, Any]:
    try:
        value = json.loads(GATE_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("automatic gate config is unavailable") from exc
    if not isinstance(value, dict) or set(value) != {"automatic_split", "benchmark_release_id", "contract_version", "holdout_role", "regression_role", "thresholds", "safety"}:
        raise ValueError("automatic gate config is not closed")
    if value["automatic_split"] != "pre_review" or value["holdout_role"] != "automatic_gate" or value["regression_role"] != "precondition_only" or value["safety"] != SAFETY:
        raise ValueError("automatic gate boundary is invalid")
    expected = {"min_coverage":"1/5", "min_important_target_correct_coverage_delta":"1/20", "min_semantic_precision_delta":"0/1", "min_vista_submitted_count":1, "required_vista_gain_numerator":">0", "wrong_target_count":0}
    if value["thresholds"] != expected:
        raise ValueError("automatic gate thresholds differ from the preregistered estimand")
    return value


def _validate(private: object, run: object, lifecycle: object) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    if not isinstance(private, Mapping) or set(private) != {"contract_version", "source_parent_ref", "partition", "cases"}: raise ValueError("private manifest is not closed")
    if private["contract_version"] != "portfolio_hybrid_v1_1_private_manifest_v2_synthetic" or private["partition"] not in {"regression", "holdout"}: raise ValueError("private manifest contract is invalid")
    parent = _ref(private["source_parent_ref"], "private parent")
    if not isinstance(run, Mapping) or set(run) - {"contract_version", "source_parent_ref", "partition", "attempt_ref", "lifecycle_ref", "regression_precondition_ref", "pre_review_rows", "post_review_rows", "vista_proposals", "safety"}: raise ValueError("prediction run is not closed")
    required = {"contract_version", "source_parent_ref", "partition", "attempt_ref", "lifecycle_ref", "regression_precondition_ref", "pre_review_rows", "vista_proposals", "safety"}
    if not required.issubset(run) or run["contract_version"] != "benchmark_v2_prediction_run_v1" or run["safety"] != SAFETY: raise ValueError("prediction run contract is invalid")
    if _ref(run["source_parent_ref"], "run parent") != parent: raise ValueError("same-SHA parent lineage mismatch")
    if run["partition"] != private["partition"]: raise ValueError("partition mismatch")
    if run["regression_precondition_ref"].get("status") != "PASS": raise ValueError("regression precondition did not pass")
    life_ref = _ref(run["lifecycle_ref"], "lifecycle ref")
    if not isinstance(lifecycle, Mapping) or lifecycle.get("complete") is not True or lifecycle.get("lifecycle_verified") is not True or lifecycle.get("artifact_is_authorization") is not False or lifecycle.get("execute_binding_enabled") is not False: raise ValueError("lifecycle is incomplete")
    if {"id": lifecycle.get("id"), "content_sha256": lifecycle.get("content_sha256")} != life_ref: raise ValueError("lifecycle ref mismatch")
    cases = private["cases"]
    if not isinstance(cases, list) or not cases: raise ValueError("zero submitted cases are forbidden")
    case_map: dict[str, dict[str, Any]] = {}
    for case in cases:
        if not isinstance(case, Mapping) or set(case) != {"case_id", "target_id", "important", "acceptable_regions"}: raise ValueError("private case is not closed")
        if case["case_id"] in case_map: raise ValueError("duplicate private case")
        case_map[case["case_id"]] = dict(case)
    rows = run["pre_review_rows"]
    if not isinstance(rows, list): raise ValueError("pre_review rows are invalid")
    by_key: dict[tuple[str,str], dict[str,Any]] = {}
    for raw in rows:
        if not isinstance(raw, Mapping): raise ValueError("prediction row is invalid")
        row = dict(raw); key = (row.get("case_id"), row.get("arm_id"))
        if key in by_key: raise ValueError("duplicate arm/case row")
        if key[0] not in case_map or key[1] not in ARMS: raise ValueError("unknown arm/case row")
        by_key[key] = row
    expected = {(case, arm) for case in case_map for arm in ARMS}
    if set(by_key) != expected: raise ValueError("missing or extra arm/case row")
    vista_results = []
    global_refs: dict[str, set[object]] = {
        field: set() for field in ("target_binding_ref", "candidate_id", "bbox_ref", "vista_request_ref")
    }
    for case_id in case_map:
        pair = [by_key[(case_id, arm)] for arm in PAIR_ARMS]
        five = {(r.get("case_id"), case_map[case_id]["target_id"], r.get("arm_id"), r.get("candidate_id"), r.get("vista_request_ref")) for r in pair}
        if len(five) != 2 or {r.get("arm_id") for r in pair} != set(PAIR_ARMS): raise ValueError("five-key pair is duplicate or ambiguous")
        for field in ("candidate_id", "fusion_ref", "capture_ref", "target_binding_ref", "bbox_ref", "vista_request_ref"):
            if pair[0].get(field) != pair[1].get(field): raise ValueError("five-key pair parent mismatch")
        for field, observed in global_refs.items():
            value = pair[0].get(field)
            if value is None and field == "vista_request_ref":
                continue
            if value in observed:
                raise ValueError(f"{field} must be globally unique")
            observed.add(value)
        for row in pair:
            if row.get("target_binding_ref") != f"binding/{case_id}" or row.get("candidate_id") != f"candidate/{case_id}": raise ValueError("cross-target selected mapping")
            if row.get("eligibility") == "ELIGIBLE":
                if row.get("submission_status") != "SUBMITTED" or not row.get("vista_request_ref"): raise ValueError("eligible request is unsent")
            elif row.get("eligibility") == "INELIGIBLE":
                if row.get("vista_request_ref") is not None or not row.get("ineligible_reason"): raise ValueError("ineligible request is invalid")
            else: raise ValueError("eligibility is invalid")
        vista = pair[1]
        if vista.get("eligibility") == "ELIGIBLE":
            result = vista.get("vista_result")
            if not isinstance(result, Mapping) or result.get("status") not in ({"validated"} | FAILURES): raise ValueError("VISTA terminal status is invalid")
            lineage = result.get("proposal_lineage")
            expected_lineage = {key: vista.get(key) for key in ("case_id", "selected_target_id", "vista_request_ref", "candidate_id", "fusion_ref", "capture_ref", "target_binding_ref", "bbox_ref")}
            if lineage != expected_lineage: raise ValueError("VISTA proposal lineage mismatch")
            vista_results.append(result)
    if run["vista_proposals"] != vista_results: raise ValueError("VISTA proposals must be exact request results; no best-proposal search")
    if not vista_results: raise ValueError("zero submitted VISTA requests are forbidden")
    return list(by_key.values()), case_map


def _score(rows: list[dict[str,Any]], cases: dict[str,dict[str,Any]], gate: Mapping[str, object]) -> dict[str,object]:
    metrics: dict[str,dict[str,Fraction|int]] = {}
    for arm in ARMS:
        arm_rows=[r for r in rows if r["arm_id"]==arm]
        correct=sum(r["selected_target_id"]==cases[r["case_id"]]["target_id"] for r in arm_rows)
        important=[r for r in arm_rows if cases[r["case_id"]]["important"]]
        important_correct=sum(r["selected_target_id"]==cases[r["case_id"]]["target_id"] for r in important)
        metrics[arm]={"coverage":Fraction(len(arm_rows),len(cases)),"important_correct_coverage":Fraction(important_correct,len(important) or 1),"semantic_precision":Fraction(correct,len(arm_rows) or 1),"wrong":len(arm_rows)-correct}
    numerator=0; submitted=0
    for row in rows:
        if row["arm_id"]!="omni_to_qwen_vista" or row.get("eligibility")!="ELIGIBLE": continue
        submitted+=1; x1,y1,x2,y2=row["bbox"]; baseline=_hit((Fraction(x1+x2,2),Fraction(y1+y2,2)),cases[row["case_id"]]["acceptable_regions"])
        result=row["vista_result"]
        refined=0 if result["status"] in FAILURES else _hit(tuple(Fraction(v) for v in result["canonical_capture_pixel_point"]),cases[row["case_id"]]["acceptable_regions"])
        numerator += refined-baseline
    if submitted == 0: raise ValueError("zero submitted denominator")
    release=metrics["omni_to_qwen_vista"]; base=metrics["qwen_only"]
    thresholds = gate["thresholds"]
    passed = release["wrong"]==thresholds["wrong_target_count"] and release["coverage"]>=Fraction(thresholds["min_coverage"]) and release["important_correct_coverage"]-base["important_correct_coverage"]>=Fraction(thresholds["min_important_target_correct_coverage_delta"]) and release["semantic_precision"]-base["semantic_precision"]>=Fraction(thresholds["min_semantic_precision_delta"]) and submitted>=thresholds["min_vista_submitted_count"] and numerator>0
    serial={arm:{k:(f"{v.numerator}/{v.denominator}" if isinstance(v,Fraction) else v) for k,v in data.items()} for arm,data in metrics.items()}
    return {"automatic": {"wrong_target_count": release["wrong"], "arm_metrics":serial}, "point_metric":{"gain_numerator":numerator,"submitted_count":submitted,"gain":f"{Fraction(numerator,submitted).numerator}/{Fraction(numerator,submitted).denominator}"}, "gate":{"status":"PASS" if passed else "FAIL","automatic_split":"pre_review","regression_role":"precondition_only"}}


def score_private(*, private_manifest_path: Path, prediction_run_path: Path, lifecycle_path: Path, private_output_path: Path, public_ref_path: Path) -> dict[str,str]:
    private, run, lifecycle = _load(private_manifest_path), _load(prediction_run_path), _load(lifecycle_path)
    rows,cases=_validate(private,run,lifecycle); result=_score(rows,cases,_gate())
    private_result={"contract_version":"portfolio_hybrid_v1_1_private_score_v2",**result,"source_parent_ref":private["source_parent_ref"],"attempt_ref":run["attempt_ref"],"safety":dict(SAFETY)}
    raw=_canonical(private_result)+b"\n"; digest=hashlib.sha256(raw).hexdigest()
    public={"status":private_result["gate"]["status"],"score_ref":f"private-score/{digest}","content_sha256":digest,"artifact_is_authorization":False,"execute_binding_enabled":False}
    def atomic_write(path: Path, payload: bytes) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.tmp")
        try:
            temporary.write_bytes(payload)
            temporary.replace(target)
        finally:
            if temporary.exists():
                temporary.unlink()
    atomic_write(Path(private_output_path), raw)
    atomic_write(Path(public_ref_path), _canonical(public)+b"\n")
    return public
