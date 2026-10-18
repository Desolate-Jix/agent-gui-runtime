"""对冻结的工作流对照试验进行可复算计分。"""

from __future__ import annotations

import math
import random
from collections import Counter, defaultdict

from .measurement import summarize_run


SCHEMA = "workflow_benchmark_run.v1"
ROLES = ("planning", "grounding", "verification")
PAIR_FIELDS = ("case_id", "task_family", "source", "model", "config_digest", "variation", "cold_or_warm", "attempt_index")
REQUIRED = {"schema", "run_id", "route", *PAIR_FIELDS, "is_negative", "first_attempt_success", "completed", "safe_rejection", "wrong_clicks", "recovery_count", "elapsed_ns", "timed_out", "events", "telemetry"}


def _validate_run(row: dict) -> dict:
    if not isinstance(row, dict) or set(row) not in (REQUIRED, REQUIRED | {"purpose"}):
        raise ValueError("benchmark run requires the exact workflow_benchmark_run.v1 fields")
    if row.get("purpose", "formal") not in {"pilot", "formal"}:
        raise ValueError("benchmark run purpose invalid")
    if row["schema"] != SCHEMA or row["route"] not in {"A", "B", "C"}:
        raise ValueError("invalid benchmark schema or route")
    for key in ("run_id", *PAIR_FIELDS[:-1]):
        if not isinstance(row[key], str) or not row[key].strip():
            raise ValueError(f"{key} must be a non-empty string")
    if row["cold_or_warm"] not in {"cold", "warm"}:
        raise ValueError("cold_or_warm must be cold or warm")
    for key in ("attempt_index", "wrong_clicks", "recovery_count", "elapsed_ns"):
        if type(row[key]) is not int or row[key] < (1 if key == "attempt_index" else 0):
            raise ValueError(f"{key} must be a non-negative integer")
    for key in ("is_negative", "first_attempt_success", "completed", "safe_rejection", "timed_out"):
        if type(row[key]) is not bool:
            raise ValueError(f"{key} must be a boolean")
    if row["is_negative"] and row["first_attempt_success"]:
        raise ValueError("negative rejection cannot be a positive first-attempt success")
    if row["safe_rejection"] and not row["is_negative"]:
        raise ValueError("safe_rejection is only valid for a negative case")
    if row["first_attempt_success"] and not row["completed"]:
        raise ValueError("first-attempt success requires completion")
    if row["first_attempt_success"] and (row["attempt_index"] != 1 or row["wrong_clicks"]
            or row["recovery_count"] or row["timed_out"]):
        raise ValueError("first-attempt success contradicts retry, error, recovery, or timeout")
    if not isinstance(row["events"], list):
        raise ValueError("events must be a list")
    if not isinstance(row["telemetry"], dict) or set(row["telemetry"]) != set(ROLES) or any(type(value) is not bool for value in row["telemetry"].values()):
        raise ValueError("telemetry requires explicit role coverage booleans")
    summary = summarize_run(row["events"])
    if summary["run_id"] is not None and summary["run_id"] != row["run_id"]:
        raise ValueError("measurement events belong to a different run_id")
    return row


def _quantile(values: list[int | float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    offset = (len(ordered) - 1) * fraction
    low = math.floor(offset)
    high = math.ceil(offset)
    return ordered[low] + (ordered[high] - ordered[low]) * (offset - low)


def _timing(values: list[int]) -> dict:
    return {"count": len(values), "p50": _quantile(values, .5), "p95": _quantile(values, .95)}


def _metrics(row: dict) -> dict:
    measured = summarize_run(row["events"])
    calls = {role: measured["model_calls"][role] if row["telemetry"][role] else None for role in ROLES}
    calls["total"] = sum(calls.values()) if all(value is not None for value in calls.values()) else None
    tokens = measured["usage"] if calls["total"] is not None else None
    return {"calls": calls, "tokens": tokens}


def _route_summary(rows: list[dict]) -> dict:
    positive = [row for row in rows if not row["is_negative"]]
    first_positive = [row for row in positive if row["attempt_index"] == 1]
    negative = [row for row in rows if row["is_negative"]]
    metrics = [_metrics(row) for row in rows]
    calls = {}
    for role in (*ROLES, "total"):
        values = [item["calls"][role] for item in metrics]
        calls[role] = sum(values) if len(values) == len(rows) and all(value is not None for value in values) else None
    token_values = [item["tokens"] for item in metrics]
    tokens = None
    if rows and all(value is not None for value in token_values):
        tokens = {key: sum(value[key] for value in token_values) for key in ("input_tokens", "output_tokens", "total_tokens")}
    return {
        "attempts": len(rows), "positive_attempts": len(positive), "negative_attempts": len(negative),
        "first_attempt_success_rate": sum(row["first_attempt_success"] for row in first_positive) / len(first_positive) if first_positive else None,
        "positive_success_rate": sum(row["completed"] for row in positive) / len(positive) if positive else None,
        "completion_rate": sum(row["completed"] for row in rows) / len(rows) if rows else None,
        "negative_correct_rejections": sum(row["safe_rejection"] for row in negative),
        "wrong_clicks": sum(row["wrong_clicks"] for row in rows),
        "recovery_count": sum(row["recovery_count"] for row in rows),
        "timeout_count": sum(row["timed_out"] for row in rows),
        "all_attempt_time_ns": _timing([row["elapsed_ns"] for row in rows]),
        "model_calls": calls, "tokens": tokens,
        "model_call_coverage": {role: sum(row["telemetry"][role] for row in rows) for role in ROLES},
        "token_observed_runs": sum(item["tokens"] is not None for item in metrics),
    }


def _bootstrap_ci(values: list[int]) -> list[float] | None:
    if len(values) < 2:
        return None
    rng = random.Random(29)
    estimates = [sum(rng.choice(values) for _ in values) / len(values) for _ in range(2000)]
    return [_quantile(estimates, .025), _quantile(estimates, .975)]


def _pair_summary(pairs: list[tuple[dict, dict]]) -> dict:
    all_deltas = [a["elapsed_ns"] - c["elapsed_ns"] for a, c in pairs]
    common = [(a, c) for a, c in pairs if a["completed"] and c["completed"] and not a["timed_out"] and not c["timed_out"]]
    common_deltas = [a["elapsed_ns"] - c["elapsed_ns"] for a, c in common]
    call_deltas = []
    token_deltas = []
    for a, c in pairs:
        left, right = _metrics(a), _metrics(c)
        if left["calls"]["total"] is not None and right["calls"]["total"] is not None:
            call_deltas.append(left["calls"]["total"] - right["calls"]["total"])
        if left["tokens"] is not None and right["tokens"] is not None:
            token_deltas.append(left["tokens"]["total_tokens"] - right["tokens"]["total_tokens"])
    return {
        "count": len(pairs),
        "all_attempt_time_ns": {"A": _timing([a["elapsed_ns"] for a, _ in pairs]), "C": _timing([c["elapsed_ns"] for _, c in pairs]), "median_saving": _quantile(all_deltas, .5), "mean_saving": sum(all_deltas) / len(all_deltas) if all_deltas else None, "mean_saving_ci95": _bootstrap_ci(all_deltas)},
        "common_success_time_ns": {"count": len(common), "A": _timing([a["elapsed_ns"] for a, _ in common]), "C": _timing([c["elapsed_ns"] for _, c in common]), "median_saving": _quantile(common_deltas, .5)},
        "model_call_saving": {"observed_pairs": len(call_deltas), "median": _quantile(call_deltas, .5)},
        "token_saving": {"observed_pairs": len(token_deltas), "median": _quantile(token_deltas, .5)},
    }


def _break_even(cost: dict | None, savings: dict) -> dict:
    if cost is not None and (not isinstance(cost, dict) or set(cost) - {"elapsed_ns", "total_tokens"} or any(type(value) is not int or value < 0 for value in cost.values())):
        raise ValueError("learning_cost must contain non-negative observed elapsed_ns or total_tokens")
    result = {"elapsed_reuses": None, "token_reuses": None, "scope": "positive_stable_warm_completed_cases"}
    if cost is None:
        return result
    for cost_key, saving_key, output_key in (("elapsed_ns", "elapsed_median_saving", "elapsed_reuses"), ("total_tokens", "token_median_saving", "token_reuses")):
        if cost_key in cost:
            saving = savings[saving_key]
            if saving is not None and saving > 0:
                result[output_key] = math.ceil(cost[cost_key] / saving)
    return result


def _case_savings(first_keys: list[tuple], a: dict, c: dict) -> dict:
    elapsed, tokens = [], []
    cohorts = set()
    incomplete = False
    missing_tokens = False
    for key in first_keys:
        if key[5] != "stable" or key[6] != "warm":
            continue
        cohort = key[2:5]
        cohorts.add(cohort)
        left = [row for candidate, row in a.items() if candidate[:-1] == key[:-1]]
        right = [row for candidate, row in c.items() if candidate[:-1] == key[:-1]]
        left.sort(key=lambda row: row["attempt_index"])
        right.sort(key=lambda row: row["attempt_index"])
        if not left[-1]["completed"] or not right[-1]["completed"] or left[-1]["timed_out"] or right[-1]["timed_out"]:
            incomplete = True
            continue
        elapsed.append(sum(row["elapsed_ns"] for row in left) - sum(row["elapsed_ns"] for row in right))
        observed = [(_metrics(row)["tokens"] or {}).get("total_tokens") for row in (*left, *right)]
        if all(value is not None for value in observed):
            tokens.append(sum(observed[:len(left)]) - sum(observed[len(left):]))
        else:
            missing_tokens = True
    if len(cohorts) > 1 or incomplete:
        elapsed, tokens = [], []
    elif missing_tokens:
        tokens = []
    return {"elapsed_median_saving": _quantile(elapsed, .5), "token_median_saving": _quantile(tokens, .5)}


def _benefit(first_pairs: list[tuple[dict, dict]], sufficiency: dict, unmatched: dict, *, retry_cost_not_comparable: bool) -> dict:
    ready = sufficiency["meets_required_ac"] and sufficiency["meets_required_b"] and not any(unmatched.values())
    shared = [pair for pair in first_pairs if not pair[0]["is_negative"]]
    stable_warm = [pair for pair in shared if pair[0]["variation"] == "stable" and pair[0]["cold_or_warm"] == "warm"]
    blockers = ([] if ready else ["insufficient_independent_pairs" if not sufficiency["meets_required_ac"] or not sufficiency["meets_required_b"] else "unmatched_runs"])
    if len({(a["source"], a["model"], a["config_digest"]) for a, _ in shared}) > 1:
        blockers.append("model_configuration_mixed")
    if retry_cost_not_comparable:
        blockers.append("retry_cost_not_comparable")
    model_missing = any(_metrics(row)["calls"]["total"] is None for pair in stable_warm for row in pair)
    model_blockers = blockers + (["missing_model_telemetry"] if model_missing else [])
    if not stable_warm:
        model_blockers.append("stable_warm_pairs_missing")
    model_state = "unknown"
    if ready and not model_blockers:
        a_calls = sum(_metrics(a)["calls"]["total"] for a, _ in stable_warm)
        c_calls = sum(_metrics(c)["calls"]["total"] for _, c in stable_warm)
        model_state = "met" if a_calls > 0 and c_calls <= a_calls * .5 else "not_met"
    speed_blockers = blockers + ([] if stable_warm else ["stable_warm_pairs_missing"])
    speed_state = "unknown"
    if ready and not speed_blockers:
        median_ok = _quantile([c["elapsed_ns"] for _, c in stable_warm], .5) <= .7 * _quantile([a["elapsed_ns"] for a, _ in stable_warm], .5)
        grouped = defaultdict(list)
        for pair in shared:
            grouped[(pair[0]["task_family"], pair[0]["variation"], pair[0]["cold_or_warm"])].append(pair)
        p95_ok = all(_quantile([c["elapsed_ns"] for _, c in group], .95)
                     <= 1.1 * _quantile([a["elapsed_ns"] for a, _ in group], .95)
                     for group in grouped.values())
        speed_state = "met" if median_ok and p95_ok else "not_met"
    a_rate = sum(a["first_attempt_success"] for a, _ in shared) / len(shared) if shared else None
    c_rate = sum(c["first_attempt_success"] for _, c in shared) / len(shared) if shared else None
    accuracy_blockers = list(blockers)
    ambiguous = [pair for pair in shared if pair[0]["variation"] == "ambiguous"]
    if not ambiguous:
        accuracy_blockers.append("ambiguous_target_coverage_missing")
    accuracy_state = "unknown"
    if a_rate == c_rate == 1:
        accuracy_state = "parity"
    elif ready and not accuracy_blockers:
        improved = sum(c["first_attempt_success"] for _, c in ambiguous) > sum(a["first_attempt_success"] for a, _ in ambiguous)
        fewer_errors = sum(c["wrong_clicks"] for _, c in ambiguous) < sum(a["wrong_clicks"] for a, _ in ambiguous)
        accuracy_state = "met" if c_rate >= .95 and c_rate >= a_rate and improved and fewer_errors else "not_met"
    overall = "met" if all(state == "met" for state in (model_state, speed_state, accuracy_state)) else (
        "not_met" if "not_met" in (model_state, speed_state, accuracy_state) else "unknown")
    a_calls = sum(_metrics(a)["calls"]["total"] for a, _ in stable_warm) if stable_warm and not model_missing else None
    c_calls = sum(_metrics(c)["calls"]["total"] for _, c in stable_warm) if stable_warm and not model_missing else None
    a_median = _quantile([a["elapsed_ns"] for a, _ in stable_warm], .5)
    c_median = _quantile([c["elapsed_ns"] for _, c in stable_warm], .5)
    return {"model_use": {"state": model_state, "blockers": model_blockers,
                          "scope": "positive_stable_warm", "calls": {"A": a_calls, "C": c_calls},
                          "saving_fraction": (a_calls - c_calls) / a_calls if a_calls else None},
            "speed": {"state": speed_state, "blockers": speed_blockers,
                      "scope": "positive_stable_warm_median_and_per_stratum_p95",
                      "stable_median_ns": {"A": a_median, "C": c_median},
                      "stable_median_saving_fraction": (a_median - c_median) / a_median if a_median else None},
            "correctness": {"state": accuracy_state, "blockers": accuracy_blockers,
                            "scope": "positive_first_attempts_and_ambiguous_targets",
                            "first_attempt_success_rate": {"A": a_rate, "C": c_rate}},
            "overall": {"state": overall}}


def compare_runs(runs: list[dict], *, learning_cost: dict | None = None, purpose: str | None = None) -> dict:
    """严格配对 A/C；保留所有尝试，并把 B 作为诊断子集。"""
    if not isinstance(runs, list):
        raise ValueError("runs must be a list")
    if purpose is not None and purpose not in {"pilot", "formal"}:
        raise ValueError("benchmark comparison purpose invalid")
    by_route: dict[str, list[dict]] = {route: [] for route in ("A", "B", "C")}
    indexed: dict[tuple, dict] = {}
    run_ids = set()
    case_identity = {}
    seen_first = set()
    purposes = {purpose} if purpose is not None else set()
    for candidate in runs:
        row = _validate_run(candidate)
        purposes.add(row.get("purpose", "formal"))
        if len(purposes) > 1:
            raise ValueError("benchmark mixed purpose forbidden")
        identity = (row["route"], row["task_family"], row["case_id"])
        frozen = tuple(row[field] for field in ("source", "model", "config_digest", "variation", "cold_or_warm", "is_negative"))
        if identity in case_identity and case_identity[identity] != frozen:
            raise ValueError("benchmark case identity drift")
        case_identity[identity] = frozen
        if row["attempt_index"] == 1:
            seen_first.add(identity)
        key = (row["route"], *(row[field] for field in PAIR_FIELDS))
        if key in indexed or row["run_id"] in run_ids:
            raise ValueError("duplicate benchmark run or pairing identity")
        indexed[key] = row
        run_ids.add(row["run_id"])
        by_route[row["route"]].append(row)
    if set(case_identity) - seen_first:
        raise ValueError("benchmark first-attempt record missing")
    for route, family, case in case_identity:
        indexes = sorted(row["attempt_index"] for row in by_route[route]
                         if (row["task_family"], row["case_id"]) == (family, case))
        if indexes != list(range(1, len(indexes) + 1)):
            raise ValueError("benchmark attempt sequence missing an intermediate attempt")
    a = {key[1:]: row for key, row in indexed.items() if key[0] == "A"}
    c = {key[1:]: row for key, row in indexed.items() if key[0] == "C"}
    keys = sorted(a.keys() & c.keys())
    if any(a[key]["is_negative"] != c[key]["is_negative"] for key in keys):
        raise ValueError("paired runs disagree on negative-case classification")
    pairs = _pair_summary([(a[key], c[key]) for key in keys])
    first_keys = [key for key in keys if key[-1] == 1 and not a[key]["is_negative"]]
    first_pairs = [(a[key], c[key]) for key in first_keys]
    families = Counter(key[1] for key in first_keys)
    strata_counts = defaultdict(Counter)
    strata_keys = defaultdict(lambda: defaultdict(set))
    for key in first_keys:
        family, variation, temperature = key[1], key[5], key[6]
        strata_counts[family][variation] += 1
        strata_keys[family][variation].add(temperature)
    strata = {}
    for family in sorted(strata_keys):
        strata[family] = {}
        for variation in sorted(strata_keys[family]):
            strata[family][variation] = {}
            for temperature in sorted(strata_keys[family][variation]):
                group = [(a[key], c[key]) for key in first_keys if (key[1], key[5], key[6]) == (family, variation, temperature)]
                strata[family][variation][temperature] = {"pairs": _pair_summary(group)}
    b = {key[1:]: row for key, row in indexed.items() if key[0] == "B"}
    b_families = Counter(key[1] for key in first_keys if key in b and not b[key]["is_negative"])
    purpose = next(iter(purposes), "formal")
    required = {"stable": 8, "unseen": 6, "layout": 6}
    sufficient = {"ac_pairs_by_family": dict(families), "b_runs_by_family": dict(b_families),
                  "ac_by_family_variation": {family: dict(counts) for family, counts in strata_counts.items()},
                  "meets_required_ac": len(families) >= 3 and all(families[family] >= 20 and all(strata_counts[family][variation] >= count for variation, count in required.items()) for family in families),
                  "meets_required_b": len(families) >= 3 and all(b_families[family] >= 5 for family in families)}
    if purpose == "pilot":
        sufficient.update(meets_required_ac=False, meets_required_b=False)
    unmatched = {"A": len(a.keys() - c.keys()), "C": len(c.keys() - a.keys())}
    # 首轮分层还不能代表含补救的完整任务；变化集重试也不能被收益判定遗漏。
    retry_cost_not_comparable = any(row["attempt_index"] > 1 and not row["is_negative"]
                                    for route in ("A", "C") for row in by_route[route])
    family_time = {
        family: {route: _timing([row["elapsed_ns"] for row in by_route[route] if row["task_family"] == family]) for route in ("A", "B", "C")}
        for family in sorted({row["task_family"] for row in runs})
    }
    assessment = _benefit(first_pairs, sufficient, unmatched,
                          retry_cost_not_comparable=retry_cost_not_comparable)
    assessment["scope"] = "matched_aggregate"
    family_assessments = {}
    for family in family_time:
        family_pairs = [pair for pair in first_pairs if pair[0]["task_family"] == family]
        counts = strata_counts[family]
        family_sufficiency = {
            "meets_required_ac": families[family] >= 20 and all(counts[variation] >= count for variation, count in required.items()),
            "meets_required_b": b_families[family] >= 5,
        }
        if purpose == "pilot":
            family_sufficiency.update(meets_required_ac=False, meets_required_b=False)
        family_unmatched = {
            "A": sum(key[1] == family for key in a.keys() - c.keys()),
            "C": sum(key[1] == family for key in c.keys() - a.keys()),
        }
        family_retry = any(row["attempt_index"] > 1 and not row["is_negative"] and row["task_family"] == family
                           for route in ("A", "C") for row in by_route[route])
        family_assessments[family] = _benefit(family_pairs, family_sufficiency, family_unmatched,
                                             retry_cost_not_comparable=family_retry)
        family_assessments[family]["scope"] = "single_task_family"
        family_assessments[family]["sample_sufficiency"] = family_sufficiency
    # 合并收益不能替代逐类结论；缺少任务类型也不能宣称全部达标。
    states = [item["overall"]["state"] for item in family_assessments.values()]
    all_state = "not_met" if "not_met" in states else (
        "met" if len(families) >= 3 and states and all(state == "met" for state in states) else "unknown")
    assessment["by_task_family"] = family_assessments
    assessment["all_families"] = {"state": all_state, "scope": "all_observed_task_families",
                                  "required_family_count": 3,
                                  "family_states": {family: item["overall"]["state"] for family, item in family_assessments.items()}}
    if purpose == "pilot":
        for item in [assessment, *family_assessments.values()]:
            item["overall"].update(state="unknown", reason="pilot_not_formal_acceptance")
        assessment["all_families"].update(state="unknown", reason="pilot_not_formal_acceptance")
    return {
        "schema": "workflow_benchmark_comparison.v1",
        "purpose": purpose,
        "formal_acceptance_eligible": purpose == "formal" and sufficient["meets_required_ac"]
            and sufficient["meets_required_b"] and not any(unmatched.values()),
        "formal_quota_credit": 0 if purpose == "pilot" else len(first_pairs),
        "empirical_acceptance": False,
        "routes": {route: _route_summary(rows) for route, rows in by_route.items()},
        "pairs": pairs,
        "unmatched": unmatched,
        "family_time_ns": family_time,
        "strata": strata,
        "sample_sufficiency": sufficient,
        "benefit_assessment": assessment,
        "break_even": _break_even(learning_cost, _case_savings(first_keys, a, c)),
    }
