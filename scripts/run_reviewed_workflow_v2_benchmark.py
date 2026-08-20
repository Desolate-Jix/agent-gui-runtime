"""生成纯离线 Reviewed Workflow v2 合同基准。"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import statistics
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.agent.reviewed_workflow_asset import validate_reviewed_workflow_asset
from app.agent.reviewed_workflow_replay import build_recovery_decision, resolve_current_state, select_verified_transition, validate_current_grounding, verify_transition_result

CONTRACT_VERSION = "reviewed_workflow_v2_contract_benchmark_report_v1"
MANIFEST_VERSION = "reviewed_workflow_v2_benchmark_fixture_manifest_v1"
ID = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
REF = re.compile(r"^[a-z][a-z0-9_:-]{0,127}$")
CASE_KEYS = {"case_id", "category", "fixture_valid", "fixture_invalid_reason", "bare_events", "expected", "current_observation", "transition_id", "grounding", "gate", "operation", "post_observation", "attempts_used", "invalid_point_category"}
INVALID_KEYS = {"case_id", "category", "fixture_valid", "fixture_invalid_reason", "bare_events", "expected"}
EVENT_KEYS = ({"event_type", "semantic_action"}, {"event_type", "would_dispatch"}, {"event_type", "claimed_post_action_verified"}, {"event_type", "evidence_refs"})
OBS = {"contract_version", "asset_id", "expected_asset_content_sha256", "capture_id", "screenshot_sha256", "viewport_size", "origin", "observed_anchor_evidence"}
GROUND = {"contract_version", "asset_content_sha256", "transition_id", "source_state_id", "capture_id", "screenshot_sha256", "viewport_size", "element_ref", "candidate_id", "candidate_current", "eligible", "confidence", "score_margin", "bbox", "click_point", "evidence_refs"}
GATE = {"contract_version", "allowed", "asset_content_sha256", "transition_id", "selection_sha256", "selected_candidate_id", "selected_element_id", "selected_click_point", "capture_id", "screenshot_sha256", "viewport_size", "evidence_refs"}
OPERATION = {"contract_version", "action_type", "action_executed", "post_action_verified", "gate_result", "approved_plan_id", "source_freshness", "replay_context", "evidence_refs"}
PHASES = ("bare_classify", "bare_total", "runtime_total", "state_resolution", "transition_selection", "grounding_gate", "post_verification")
ALLOWED = {"open_detail", "open_apply_flow", "back", "close_modal"}
CATEGORY = {
    "verified_open_detail": ("verified", None, "open_detail", 0), "verified_open_apply_flow": ("verified", None, "open_apply_flow", 0),
    "unresolved": ("blocked", "current_state_unresolved", "open_detail", 0), "ambiguous": ("blocked", "current_state_ambiguous", "open_detail", 0), "wrong_origin": ("blocked", "unexpected_origin", "open_detail", 0), "transition_not_available": ("blocked", "transition_not_available", "missing_transition", 0), "stale_capture": ("blocked", "capture_lineage_mismatch", "open_detail", 0), "stale_candidate": ("blocked", "stale_candidate", "open_detail", 0), "low_margin": ("blocked", "grounding_ambiguous", "open_detail", 0), "invalid_point": ("blocked", "target_unresolved", "open_detail", 0), "gate_rejection": ("blocked", "pre_click_rejected", "open_detail", 0), "missing_operation_evidence": ("blocked", "operation_evidence_missing", "open_detail", 0), "same_post_capture": ("blocked", "post_capture_not_new", "open_detail", 0), "destination_mismatch": ("blocked", "destination_mismatch", "open_detail", 0), "recovery_once": ("blocked", "stale_candidate", "open_detail", 0), "recovery_exhausted": ("blocked", "stale_candidate", "open_detail", 1),
}
CASE_ID_BY_CATEGORY = {
    **{category: category for category in CATEGORY},
    "verified_open_detail": "valid_open_detail",
    "verified_open_apply_flow": "valid_open_apply_flow",
    "invalid_point": "out_of_bounds_point",
}
INVALID_FIXTURE_ID = "excluded_invalid_fixture"
INVALID_FIXTURE_CATEGORY = "fixture_invalid"
INVALID_FIXTURE_REASON = "fixture_declared_invalid"
INVALID_FIXTURE_EXPECTED = {
    "bare": {"classification": "recorded_no_dispatch", "failure_code": "not_dispatched"},
    "runtime": {"classification": "blocked", "failure_code": "fixture_invalid"},
}

def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()

def _text(value: Any) -> str: return value.strip() if isinstance(value, str) else ""
def _bad(message: str) -> ValueError: return ValueError(f"cases invalid: {message}")
def _id(value: Any, label: str) -> str:
    value = _text(value)
    if not ID.fullmatch(value): raise _bad(f"{label} must be a safe identifier")
    return value
def _closed(value: Any, keys: set[str], label: str, case_id: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys: raise _bad(f"case {case_id} {label} must use the closed nested schema")
    return value
def _refs(value: Any, label: str, case_id: str) -> list[str]:
    if not isinstance(value, list) or any(not REF.fullmatch(_text(item)) for item in value): raise _bad(f"case {case_id} {label} must be safe identifiers")
    return [_text(item) for item in value]
def _point(value: Any, keys: set[str], label: str, case_id: str) -> None: _closed(value, keys, label, case_id)
def _viewport(value: Any, label: str, case_id: str) -> None: _closed(value, {"width", "height"}, label, case_id)
def _obs(value: Any, label: str, case_id: str) -> None:
    value = _closed(value, OBS, label, case_id); _viewport(value["viewport_size"], f"{label}.viewport_size", case_id)
    if not isinstance(value["observed_anchor_evidence"], list): raise _bad(f"case {case_id} {label}.observed_anchor_evidence must be a list")
    for item in value["observed_anchor_evidence"]:
        _closed(item, {"anchor_id", "matched", "evidence_ref", "confidence"}, f"{label}.anchor", case_id)
        if not REF.fullmatch(_text(item["evidence_ref"])): raise _bad(f"case {case_id} {label}.anchor evidence_ref must be safe")
def _runtime_objects(case: Mapping[str, Any], case_id: str) -> None:
    _obs(case["current_observation"], "current_observation", case_id); _obs(case["post_observation"], "post_observation", case_id)
    ground = _closed(case["grounding"], GROUND, "grounding", case_id); _viewport(ground["viewport_size"], "grounding.viewport_size", case_id); _point(ground["bbox"], {"x", "y", "w", "h"}, "grounding.bbox", case_id); _point(ground["click_point"], {"x", "y"}, "grounding.click_point", case_id); _refs(ground["evidence_refs"], "grounding evidence_refs", case_id)
    gate = _closed(case["gate"], GATE, "gate", case_id); _viewport(gate["viewport_size"], "gate.viewport_size", case_id); _point(gate["selected_click_point"], {"x", "y"}, "gate.selected_click_point", case_id); _refs(gate["evidence_refs"], "gate evidence_refs", case_id)
    op = _closed(case["operation"], OPERATION, "operation", case_id); _closed(op["gate_result"], {"allowed", "reason"}, "operation.gate_result", case_id); _closed(op["source_freshness"], {"capture_id", "screenshot_sha256", "viewport", "trace_path"}, "operation.source_freshness", case_id); _viewport(op["source_freshness"]["viewport"], "operation.source_freshness.viewport", case_id); _closed(op["replay_context"], {"contract_version", "asset_content_sha256", "transition_id", "selection_sha256"}, "operation.replay_context", case_id)
    _refs(op["evidence_refs"], "operation evidence_refs", case_id)
    if op["action_executed"] is True and _text(op["action_type"]) not in ALLOWED: raise _bad(f"case {case_id} operation dispatch is forbidden")

def _invalid_point_cause(ground: Mapping[str, Any], case_id: str) -> str | None:
    if ground.get("candidate_current") is not True or ground.get("eligible") is not True:
        raise _bad(f"case {case_id} invalid_point requires current eligible candidate")
    numbers = (ground.get("confidence"), ground.get("score_margin"), *ground["bbox"].values(), *ground["click_point"].values(), *ground["viewport_size"].values())
    if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) for value in numbers) or ground["confidence"] < .9 or ground["score_margin"] < .2:
        raise _bad(f"case {case_id} invalid_point requires confident unambiguous grounding")
    bbox, point, viewport = ground["bbox"], ground["click_point"], ground["viewport_size"]
    if viewport["width"] <= 0 or viewport["height"] <= 0 or bbox["x"] < 0 or bbox["y"] < 0 or bbox["w"] <= 0 or bbox["h"] <= 0 or bbox["x"] + bbox["w"] > viewport["width"] or bbox["y"] + bbox["h"] > viewport["height"]:
        raise _bad(f"case {case_id} invalid_point requires valid contained bbox")
    if point["x"] < 0 or point["y"] < 0 or point["x"] > viewport["width"] or point["y"] > viewport["height"]:
        return "outside_viewport"
    if point["x"] < bbox["x"] or point["x"] > bbox["x"] + bbox["w"] or point["y"] < bbox["y"] or point["y"] > bbox["y"] + bbox["h"]:
        return "outside_bbox"
    return None

def _events(value: Any, case_id: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) != 4: raise _bad(f"case {case_id} bare_events must be an ordered closed event list")
    names = ("proposal", "dispatch", "post_verification", "evidence")
    result = []
    for event, keys, name in zip(value, EVENT_KEYS, names):
        event = _closed(event, keys, "bare_events", case_id)
        if event.get("event_type") != name: raise _bad(f"case {case_id} bare_events order is invalid")
        result.append(dict(event))
    result[0]["semantic_action"] = _id(result[0]["semantic_action"], "bare_events semantic_action")
    if result[0]["semantic_action"] not in ALLOWED: raise _bad(f"case {case_id} {result[0]['semantic_action']} bare dispatch is forbidden")
    if type(result[1]["would_dispatch"]) is not bool or type(result[2]["claimed_post_action_verified"]) is not bool: raise _bad(f"case {case_id} bare event booleans are invalid")
    result[3]["evidence_refs"] = _refs(result[3]["evidence_refs"], "bare_events evidence_refs", case_id)
    return result

def _expected(value: Any, case_id: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, Mapping) or set(value) != {"bare", "runtime"}: raise _bad(f"case {case_id} expected must be closed")
    result = {}
    for name, allowed in (("bare", {"recorded_no_dispatch", "recorded_ungated_dispatch_claimed_verified", "recorded_ungated_dispatch_unverified"}), ("runtime", {"verified", "blocked"})):
        item = _closed(value[name], {"classification", "failure_code"}, f"expected.{name}", case_id); cls, failure = _id(item["classification"], f"expected.{name}.classification"), item["failure_code"]
        if cls not in allowed or (failure is not None and not ID.fullmatch(_text(failure))): raise _bad(f"case {case_id} expected.{name} is invalid")
        result[name] = {"classification": cls, "failure_code": _text(failure) or None}
    return result

def _validate_cases(cases: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(cases, (list, tuple)) or not cases: raise _bad("cases must be a non-empty list")
    result, seen = [], set()
    for index, raw in enumerate(cases):
        if not isinstance(raw, Mapping): raise _bad(f"case {index} must be an object")
        valid = raw.get("fixture_valid") is True; keys = CASE_KEYS if valid else INVALID_KEYS
        if set(raw) != keys: raise _bad(f"case {index} must use its closed fixture schema")
        case_id, category = _id(raw.get("case_id"), "case_id"), _id(raw.get("category"), "category")
        if case_id in seen: raise _bad(f"case {case_id} is duplicated")
        seen.add(case_id); reason = _text(raw.get("fixture_invalid_reason"))
        if valid != (reason == ""): raise _bad(f"case {case_id} fixture validity and reason disagree")
        if reason and not ID.fullmatch(reason): raise _bad(f"case {case_id} fixture_invalid_reason must be a safe identifier")
        events, expected = _events(raw["bare_events"], case_id), _expected(raw["expected"], case_id)
        bare_actual = _bare(events)
        if expected["bare"] != {
            "classification": bare_actual["classification"],
            "failure_code": bare_actual["failure_code"],
        }:
            raise _bad(f"case {case_id} expected.bare must match recorded events")
        if valid:
            if CASE_ID_BY_CATEGORY.get(category) != case_id:
                raise _bad(f"case {case_id} must use the canonical category identifier")
        elif (case_id, category, reason) != (
            INVALID_FIXTURE_ID,
            INVALID_FIXTURE_CATEGORY,
            INVALID_FIXTURE_REASON,
        ) or expected != INVALID_FIXTURE_EXPECTED:
            raise _bad("invalid fixture must use the canonical excluded identifier")
        item = {**dict(raw), "case_id": case_id, "category": category, "fixture_invalid_reason": reason, "bare_events": events, "expected": expected}
        if valid:
            _runtime_objects(item, case_id); item["transition_id"] = _id(item["transition_id"], "transition_id")
            if not isinstance(item["attempts_used"], int) or isinstance(item["attempts_used"], bool) or item["attempts_used"] not in {0, 1}: raise _bad(f"case {case_id} attempts_used must be 0 or 1")
            if item["invalid_point_category"] is not None: item["invalid_point_category"] = _id(item["invalid_point_category"], "invalid_point_category")
            contract = CATEGORY.get(category)
            if contract is None or (expected["runtime"]["classification"], expected["runtime"]["failure_code"], item["transition_id"], item["attempts_used"]) != contract or events[0]["semantic_action"] != ("open_detail" if item["transition_id"] == "missing_transition" else contract[2]): raise _bad(f"case {case_id} category semantic contract is invalid")
            cause = _invalid_point_cause(item["grounding"], case_id) if category == "invalid_point" else None
            if category == "invalid_point" and (cause is None or item["invalid_point_category"] != cause): raise _bad(f"case {case_id} invalid_point declared category mismatches geometry")
            if category != "invalid_point" and item["invalid_point_category"] is not None: raise _bad(f"case {case_id} invalid_point_category is not allowed for this category")
            item["derived_invalid_point_cause"] = cause
        result.append(item)
    return result

def _manifest(manifest: Mapping[str, Any], asset: Mapping[str, Any], cases: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    if not isinstance(manifest, Mapping) or set(manifest) != {"contract_version", "asset_sha256", "valid_cases_sha256", "case_sha256", "phase_result_sha256"} or manifest.get("contract_version") != MANIFEST_VERSION or not isinstance(manifest.get("case_sha256"), Mapping) or not isinstance(manifest.get("phase_result_sha256"), Mapping): raise ValueError("fixture manifest invalid")
    valid = [case for case in cases if case["fixture_valid"]]; computed = {"asset_sha256": _sha(asset), "valid_cases_sha256": _sha(valid), "case_sha256": {case["case_id"]: _sha(case) for case in cases}}
    if any(manifest.get(key) != value for key, value in computed.items()): raise ValueError("fixture manifest mismatch")
    phase = manifest["phase_result_sha256"]
    if set(phase) != {case["case_id"] for case in valid} or any(not isinstance(value, Mapping) or not value or any(not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest) for digest in value.values()) for value in phase.values()): raise ValueError("fixture manifest phase digests invalid")
    return {case_id: dict(values) for case_id, values in phase.items()}

def _bare(events: list[Mapping[str, Any]]) -> dict[str, Any]:
    dispatch, verified, refs = events[1]["would_dispatch"], events[2]["claimed_post_action_verified"], events[3]["evidence_refs"]
    cls, failure = ("recorded_no_dispatch", "not_dispatched") if not dispatch else (("recorded_ungated_dispatch_claimed_verified", None) if verified else ("recorded_ungated_dispatch_unverified", "claimed_post_action_unverified"))
    return {"classification": cls, "failure_code": failure, "derived_digest": _sha(events), "embedded_ref_coverage": bool(refs)}

def _measure(clock: Callable[[], int], samples: list[float], fn: Callable[[], Any]) -> Any:
    start, value, end = clock(), fn(), clock(); elapsed = end - start
    if not isinstance(elapsed, (int, float)) or isinstance(elapsed, bool) or not math.isfinite(elapsed): raise ValueError("clock_ns must return finite numeric values")
    if elapsed < 0: raise ValueError("clock_ns produced negative elapsed time")
    samples.append(float(elapsed)); return value
def _transition(asset: Mapping[str, Any], ident: str) -> Mapping[str, Any] | None: return next((x for x in asset["transitions"] if x.get("transition_id") == ident), None)
def _recovery(asset: Mapping[str, Any], case: Mapping[str, Any], failure: str | None) -> dict[str, Any]:
    if failure is None: return {"status": "not_required", "decision": "not_required", "repeat_action": False, "attempts_used": 0, "failure_code": None}
    transition = _transition(asset, case["transition_id"])
    if transition is None: return {"status": "blocked", "decision": "safe_stop_human_review", "repeat_action": False, "attempts_used": case["attempts_used"], "failure_code": "recovery_exhausted" if case["attempts_used"] else failure}
    decision = build_recovery_decision(transition, failure, attempts_used=case["attempts_used"]); return {k: decision[k] for k in ("status", "decision", "repeat_action", "attempts_used", "failure_code")}

def _runtime(asset: Mapping[str, Any], case: Mapping[str, Any], clock: Callable[[], int] | None = None, samples: dict[str, list[float]] | None = None, expected_digests: Mapping[str, str] | None = None) -> dict[str, Any]:
    observed: dict[str, Any] = {}
    def phase(name: str, fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        value = fn() if clock is None else _measure(clock, samples[name], fn); observed[name] = value; return value
    resolution = phase("state_resolution", lambda: resolve_current_state(asset, case["current_observation"])); selection = grounding = verification = None; result: Mapping[str, Any] = resolution
    if resolution.get("status") == "resolved": selection = phase("transition_selection", lambda: select_verified_transition(asset, resolution, transition_id=case["transition_id"], current_observation=case["current_observation"])); result = selection
    if isinstance(selection, Mapping) and selection.get("status") == "selected": grounding = phase("grounding_gate", lambda: validate_current_grounding(asset, selection, case["grounding"], case["gate"], policy={"minimum_confidence": .9, "minimum_score_margin": .2})); result = grounding
    if isinstance(grounding, Mapping) and grounding.get("status") == "validated": verification = phase("post_verification", lambda: verify_transition_result(asset, selection, case["operation"], case["post_observation"])); result = verification
    cls, failure = ("verified", None) if result.get("status") == "verified" else ("blocked", _text(result.get("failure_code")) or None)
    if cls == "verified" and _text(verification.get("target_state_id")) != _text(selection.get("target_state_id")): cls, failure = "blocked", "wrong_continuation"
    dispatch = case["operation"]["action_executed"] is True; post_attempted = "post_verification" in observed; unsafe = dispatch and (not post_attempted or not isinstance(grounding, Mapping) or grounding.get("status") != "validated")
    evidence = {}
    for name in ("state_resolution", "transition_selection", "grounding_gate", "post_verification"):
        attempted, digest = name in observed, _sha(observed[name]) if name in observed else None
        evidence[name] = {"attempted": attempted, "derived_result_digest_sha256": digest, "derived_result_digest_complete": attempted and (expected_digests is None or expected_digests.get(name) == digest), "embedded_ref_coverage": bool(observed[name].get("evidence_refs", [])) if attempted else False}
    bare_digest = _sha(case["bare_events"])
    evidence["bare"] = {"attempted": True, "derived_result_digest_sha256": bare_digest, "derived_result_digest_complete": expected_digests is None or expected_digests.get("bare") == bare_digest, "embedded_ref_coverage": bool(case["bare_events"][3]["evidence_refs"])}
    terminal_stage = next(reversed(observed)) if cls == "blocked" else None
    terminal_digest = _sha({"terminal_stage": terminal_stage, "failure_code": failure}) if cls == "blocked" else None
    evidence["terminal_failure"] = {"attempted": cls == "blocked", "derived_result_digest_sha256": terminal_digest, "derived_result_digest_complete": cls == "blocked" and (expected_digests is None or expected_digests.get("terminal_failure") == terminal_digest), "embedded_ref_coverage": False, "terminal_stage": terminal_stage}
    if expected_digests is not None:
        attempted_names = {name for name, value in evidence.items() if value["attempted"]}
        if set(expected_digests) != attempted_names:
            for value in evidence.values():
                if value["attempted"]:
                    value["derived_result_digest_complete"] = False
    return {"classification": cls, "failure_code": failure, "recovery": _recovery(asset, case, failure), "evidence": evidence, "dispatch_reached": dispatch, "unsafe_dispatch": unsafe, "final_submit_attempt": dispatch and _text(case["operation"]["action_type"]) == "final_submit"}

def _stats(name: str, values: list[float]) -> dict[str, Any]:
    if not values: return {"phase": name, "coverage": "not_covered", "sample_count": 0, "median_ns": None, "p95_ns": None}
    values = sorted(values); return {"phase": name, "coverage": "covered", "sample_count": len(values), "median_ns": float(statistics.median(values)), "p95_ns": float(values[min(len(values)-1, math.ceil(len(values)*.95)-1)])}
def _coverage(cases: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [c for c in cases if c["fixture_valid"]]; seen = {c["category"] for c in valid}; missing = sorted(set(CATEGORY)-seen); reasons = ([] if len(valid) >= 14 else ["coverage has fewer than 14 valid fixtures"]) + ([] if not missing else ["coverage missing required categories: "+",".join(missing)]); return {"passed": not reasons, "valid_fixture_count": len(valid), "required_categories": sorted(CATEGORY), "observed_categories": sorted(seen), "missing_categories": missing, "reasons": reasons}

def run_reviewed_workflow_v2_contract_benchmark(asset: Mapping[str, Any], cases: Sequence[Mapping[str, Any]], fixture_manifest: Mapping[str, Any], repeats: int = 7, clock_ns: Callable[[], int] | None = None) -> dict[str, Any]:
    if not isinstance(repeats, int) or isinstance(repeats, bool) or repeats < 1: raise ValueError("repeats must be a positive integer")
    try: canonical = validate_reviewed_workflow_asset(asset)
    except (TypeError, ValueError) as exc: raise ValueError("asset invalid for reviewed workflow benchmark") from exc
    normalized = _validate_cases(cases); phase_pins = _manifest(fixture_manifest, canonical, normalized); clock = clock_ns or time.perf_counter_ns
    if not callable(clock): raise ValueError("clock_ns must be callable")
    valid, totals, timed = [c for c in normalized if c["fixture_valid"]], {p: [] for p in PHASES}, []
    for case in valid:
        _bare(case["bare_events"]); _runtime(canonical, case, expected_digests=phase_pins[case["case_id"]]); samples = {p: [] for p in PHASES}
        for _ in range(repeats): _measure(clock, samples["bare_classify"], lambda c=case: _bare(c["bare_events"])); _measure(clock, samples["bare_total"], lambda c=case: _bare(c["bare_events"])); _measure(clock, samples["runtime_total"], lambda c=case: _runtime(canonical, c, clock, samples, phase_pins[c["case_id"]]))
        for p in PHASES: totals[p].extend(samples[p])
        timed.append({"case_id": case["case_id"], "warmup_discarded": 1, "repeats": repeats, "phases": [_stats(p, samples[p]) for p in PHASES]})
    records, runtime = [], []
    for case in normalized:
        bare = _bare(case["bare_events"]); common = {"case_id": case["case_id"], "category": case["category"], "fixture_pin_sha256": _sha(case), "bare": {"expected": case["expected"]["bare"], "actual": {k: bare[k] for k in ("classification", "failure_code")}, "matches_fixture_pin": {k: bare[k] for k in ("classification", "failure_code")} == case["expected"]["bare"]}}
        if not case["fixture_valid"]:
            records.append({**common, "fixture_valid": False, "included_in_denominator": False, "fixture_invalid_reason": case["fixture_invalid_reason"], "runtime": {"expected": case["expected"]["runtime"], "actual": None, "matches_fixture_pin": None}, "evidence": {"bare": {"attempted": True, "derived_result_digest_sha256": bare["derived_digest"], "derived_result_digest_complete": True, "embedded_ref_coverage": bare["embedded_ref_coverage"]}}})
            continue
        value = _runtime(canonical, case, expected_digests=phase_pins[case["case_id"]]); runtime.append(value); actual = {"classification": value["classification"], "failure_code": value["failure_code"]}; point_cause = _invalid_point_cause(case["grounding"], case["case_id"]) if case["category"] == "invalid_point" else None; records.append({**common, "fixture_valid": True, "included_in_denominator": True, "runtime": {"expected": case["expected"]["runtime"], "actual": actual, "matches_fixture_pin": actual == case["expected"]["runtime"]}, "recovery": value["recovery"], "evidence": value["evidence"], "dispatch_reached": value["dispatch_reached"], "invalid_point_category": point_cause})
    evaluated = [x for x in records if x["included_in_denominator"]]; coverage = _coverage(normalized); unsafe = sum(x["unsafe_dispatch"] for x in runtime); finals = sum(x["final_submit_attempt"] for x in runtime); wrong = sum(x["failure_code"] == "wrong_continuation" for x in runtime)
    derived_ok = all(metric["derived_result_digest_complete"] for item in runtime for metric in item["evidence"].values() if metric["attempted"]); terminals_ok = all(item["evidence"]["terminal_failure"]["derived_result_digest_complete"] for item in runtime if item["classification"] == "blocked")
    reasons = list(coverage["reasons"]); reasons += ["bare fixture pin mismatch"] if any(x["bare"]["matches_fixture_pin"] is not True for x in evaluated) else []; reasons += ["runtime fixture pin mismatch"] if any(x["runtime"]["matches_fixture_pin"] is not True for x in evaluated) else []; reasons += ["safety counters are nonzero"] if unsafe or finals or wrong else []; reasons += ["derived evidence completeness failure"] if not derived_ok or not terminals_ok else []
    evidence_summary = {name: {"attempted": sum(x["evidence"][name]["attempted"] for x in runtime), "derived_result_digest_complete": sum(x["evidence"][name]["derived_result_digest_complete"] for x in runtime), "embedded_ref_coverage": sum(x["evidence"][name]["embedded_ref_coverage"] for x in runtime)} for name in ("bare", "state_resolution", "transition_selection", "grounding_gate", "post_verification", "terminal_failure")}
    pins = {"asset_sha256": _sha(canonical), "valid_cases_sha256": _sha(valid), "case_sha256": {x["case_id"]: _sha(x) for x in normalized}, "authority": "external_fixture_manifest"}
    invalid_categories = {c["invalid_point_category"]: sum(v.get("invalid_point_category") == c["invalid_point_category"] for v in records) for c in valid if c["invalid_point_category"]}
    return {"contract_version": CONTRACT_VERSION, "scope": {"synthetic_offline_contract_replay": True, "live_gui_actions": 0, "model_calls": 0, "final_submit_attempts": finals, "execution_authorized": False}, "fixture_pins": pins, "fixture_validity": {"total": len(records), "valid": len(evaluated), "invalid_excluded": len(records)-len(evaluated)}, "coverage_manifest": coverage, "cases": records, "latency": {"per_case": timed, "summary": [_stats(p, totals[p]) for p in PHASES]}, "safety": {"recorded_bare_dispatches": sum(c["bare_events"][1]["would_dispatch"] for c in valid), "runtime_dispatch_reached": sum(x["dispatch_reached"] for x in runtime), "runtime_unsafe_dispatches": unsafe, "final_submit_attempts": finals, "runtime_wrong_continuations": wrong}, "stop_quality": {"blocked_safely": sum(x["classification"] == "blocked" and not x["dispatch_reached"] and not x["recovery"]["repeat_action"] for x in runtime), "unsafe_dispatches": unsafe, "wrong_continuations": wrong}, "evidence_completeness": evidence_summary, "summary": {"runtime_expected_match_fraction": sum(x["runtime"]["matches_fixture_pin"] is True for x in evaluated)/len(evaluated) if evaluated else None, "bare_fixture_pin_match_fraction": sum(x["bare"]["matches_fixture_pin"] is True for x in evaluated)/len(evaluated) if evaluated else None, "successful_verification_evidence": {"coverage": "covered" if any(x["classification"] == "verified" for x in runtime) else "not_covered", "attempted": sum(x["classification"] == "verified" for x in runtime), "complete": sum(x["classification"] == "verified" for x in runtime) if derived_ok else 0}, "invalid_point_categories": invalid_categories}, "misclick_risk_proxy": {"kind": "offline_invalid_point_and_gate_rejection_proxy", "is_rate": False, "invalid_point_categories": invalid_categories, "unsafe_dispatches": unsafe}, "limitations": ["This is synthetic offline contract replay; it does not exercise live GUI actions.", "This benchmark makes no model-call, perception, grounding-reliability, or live-network claim.", "Recorded Bare Agent events are informational fixture data, not model output or a comparative capability claim.", "No physical action, client authorization, or final submit is attempted or authorized."], "acceptance": {"passed": not reasons, "reasons": reasons}}

def _read(path: Path, label: str) -> Any:
    try: return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc: raise ValueError(f"{label} JSON is unreadable") from exc
def _atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle: handle.write(data); handle.flush(); os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
def main() -> int:
    parser = argparse.ArgumentParser(description="Run the offline Reviewed Workflow v2 contract benchmark."); parser.add_argument("--asset", type=Path, required=True); parser.add_argument("--cases", type=Path, required=True); parser.add_argument("--manifest", type=Path, required=True); parser.add_argument("--out", type=Path, required=True); parser.add_argument("--repeats", type=int, default=7); args = parser.parse_args()
    try: report = run_reviewed_workflow_v2_contract_benchmark(_read(args.asset,"asset"), _read(args.cases,"cases"), _read(args.manifest,"manifest"), args.repeats)
    except ValueError as exc: parser.error(str(exc))
    if not report["acceptance"]["passed"]: parser.error("benchmark acceptance failed: "+"; ".join(report["acceptance"]["reasons"]))
    _atomic(args.out, (json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)+"\n").encode("utf-8")); print(json.dumps({"report_path": str(args.out), "contract_version": CONTRACT_VERSION})); return 0
if __name__ == "__main__": raise SystemExit(main())
