"""只生成可复现的学习工作流基准案例与场景真值。"""

from __future__ import annotations

from hashlib import sha256
import math
import re

from app.learning_memory.benchmark_manifest import FAMILIES
from app.learning_memory.benchmark_provenance import validate_binding


_COUNTS = (("stable", 8), ("unseen", 6), ("layout", 6))
_VARIANT_INDEX = {"stable": 0, "unseen": 1, "layout": 2}
_CASE_ID = re.compile(r"([a-z_]+)-(stable|unseen|layout)-([0-9]{2})-s([0-9]+)\Z")


def _base(total_seed: int, family_index: int) -> int:
    return total_seed * 10000 + family_index * 1000


def _target_id(total_seed: int, family_index: int, variation: str, index: int) -> str:
    base = _base(total_seed, family_index)
    return f"R{base + (200 + index if variation == 'unseen' else 100)}"


def _detail(total_seed: int, family: str, variation: str, index: int, position: int) -> str:
    content_variation = "unseen" if variation == "unseen" and position == 0 else "stable"
    content_index = index if content_variation == "unseen" else 0
    material = f"{total_seed}|{family}|{content_variation}|{content_index}|{position}".encode("ascii")
    return "state-" + sha256(material).hexdigest()[:12]


def build_cases(seed: int) -> list[dict]:
    if type(seed) is not int or seed < 0:
        raise ValueError("benchmark seed must be a nonnegative integer")
    cases = []
    for family_index, family in enumerate(FAMILIES):
        global_index = 0
        for variation, count in _COUNTS:
            for index in range(count):
                target = _target_id(seed, family_index, variation, index)
                routes = ["A", "C"] if global_index % 2 == 0 else ["C", "A"]
                if global_index < 5:
                    routes.append("B")
                cases.append({
                    "case_id": f"{family}-{variation}-{index:02d}-s{seed}",
                    "task_family": family,
                    "variation": variation,
                    "cohort": "scored",
                    "seed": seed * 1000 + family_index * 100 + _VARIANT_INDEX[variation] * 20 + index,
                    "inputs": {"record_id": target, "query": target},
                    "success_rule": {"all": [{"path": ["result", "case_verdict", "completed"], "equals": True}]},
                    "timeout_seconds": 90,
                    "cold_or_warm": "warm",
                    "is_negative": False,
                    "routes": routes,
                })
                global_index += 1
    return cases


def scenario_for(case: dict) -> dict:
    if not isinstance(case, dict) or not isinstance(case.get("case_id"), str):
        raise ValueError("benchmark case identity invalid")
    match = _CASE_ID.fullmatch(case["case_id"])
    if match is None:
        raise ValueError("benchmark case identity invalid")
    family, variation, index_text, total_seed_text = match.groups()
    total_seed, index = int(total_seed_text), int(index_text)
    if family not in FAMILIES or index >= dict(_COUNTS)[variation]:
        raise ValueError("benchmark case identity invalid")
    canonical = next((item for item in build_cases(total_seed) if item["case_id"] == case["case_id"]), None)
    timeout = case.get("timeout_seconds")
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("benchmark case timeout_seconds must be finite and positive")
    if canonical is None:
        raise ValueError("benchmark case fields do not match the generated scenario")
    expected = {**canonical, "timeout_seconds": timeout}
    if "c_workflow" in case:
        expected["c_workflow"] = validate_binding(case["c_workflow"])
    if expected != case:
        raise ValueError("benchmark case fields do not match the generated scenario")
    family_index = FAMILIES.index(family)
    base = _base(total_seed, family_index)
    target = _target_id(total_seed, family_index, variation, index)
    distractors = (f"R{base + 101}", f"R{base + 102}")
    ids = (target, *distractors)
    records = [{"id": record_id, "name": f"Record {record_id}",
                "detail": _detail(total_seed, family, variation, index, position)}
               for position, record_id in enumerate(ids)]
    if variation == "layout":
        orders = ((1, 0, 2), (2, 0, 1), (1, 2, 0), (2, 1, 0))
        ordered_ids = [ids[position] for position in orders[index % len(orders)]]
        variant = {"query_verify": "search_below_rows", "unique_row_detail": "detail_above_rows",
                  "current_detail_downstream": "detail_above_rows"}[family]
    else:
        ordered_ids = list(ids)
        variant = "default"
    return {"case_id": case["case_id"], "records": records,
            "ordered_ids": ordered_ids, "layout_variant": variant}


__all__ = ["build_cases", "scenario_for"]
