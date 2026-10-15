"""对冻结真实截图请求作受控提示词比较；不采图、不派发输入。"""
from __future__ import annotations

import base64
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
import math
from pathlib import Path
import random
import statistics

from PIL import Image


CHOICES = ("condition_met", "condition_not_met", "evidence_insufficient")
SPLITS = {"train", "validation", "test"}


def read_json(path):
    from app.vision.recognition_source import _invalid_constant, _unique_object
    return json.loads(Path(path).read_text(encoding="utf-8-sig"),
        object_pairs_hook=_unique_object, parse_constant=_invalid_constant)


def _asset(root, spec, *, image=False):
    if type(spec) is not dict or set(spec) != {"path", "sha256"}:
        raise ValueError("benchmark_asset_invalid")
    path = (root / spec["path"]).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError("benchmark_asset_outside_suite")
    data = path.read_bytes()
    if len(data) > 16 * 1024 * 1024 or sha256(data).hexdigest() != spec["sha256"]:
        raise ValueError("benchmark_asset_hash_mismatch")
    if image:
        with Image.open(BytesIO(data)) as original:
            if original.format != "PNG" or max(original.size) > 4096 or original.width * original.height > 16_777_216:
                raise ValueError("benchmark_image_invalid")
            original.verify()
    return path, data


def load_suite(path):
    path = Path(path).resolve()
    suite = read_json(path)
    if (type(suite) is not dict or set(suite) != {"schema", "suite_id", "cases"}
            or suite["schema"] != "decision_benchmark.v1" or type(suite["suite_id"]) is not str
            or not suite["suite_id"] or type(suite["cases"]) is not list or not 1 <= len(suite["cases"]) <= 1000):
        raise ValueError("benchmark_suite_invalid")
    seen, families = set(), {}
    for case in suite["cases"]:
        if (type(case) is not dict or set(case) != {"id", "group_id", "split", "category", "expected", "truth",
                "provenance", "source", "image", "request", "question_data"}
                or any(type(case[k]) is not str or not case[k].strip() for k in ("id", "group_id", "category"))
                or case["id"] in seen or case["split"] not in SPLITS or case["expected"] not in CHOICES):
            raise ValueError("benchmark_case_invalid")
        seen.add(case["id"])
        truth, provenance = case["truth"], case["provenance"]
        if (type(truth) is not dict or set(truth) != {"annotator", "reason"}
                or any(type(truth[k]) is not str or not truth[k].strip() for k in truth)):
            raise ValueError("benchmark_reviewed_truth_required")
        if (type(provenance) is not dict or set(provenance) != {"capture_id", "session_id", "kind"}
                or provenance["kind"] != "real_capture"
                or any(type(provenance[k]) is not str or not provenance[k] for k in provenance)):
            raise ValueError("benchmark_real_capture_required")
        for family in (("scene", case["group_id"]), ("capture", provenance["capture_id"]),
                ("source", case["source"]["sha256"]), ("image", case["image"]["sha256"])):
            if family in families and families[family] != case["split"]:
                raise ValueError("benchmark_split_leakage")
            families[family] = case["split"]
        _asset(path.parent, case["source"], image=True)
        image_path, _ = _asset(path.parent, case["image"], image=True)
        request_path, raw = _asset(path.parent, case["request"])
        if len(raw) > 65_536:
            raise ValueError("benchmark_request_too_large")
        body = read_json(request_path)
        if (type(body) is not dict or body.get("model") != "gpt-6-luna"
                or type(body.get("questions")) is not list or len(body["questions"]) != 1
                or type(body.get("input")) is not list or len(body["input"]) != 1):
            raise ValueError("benchmark_frozen_request_invalid")
        question = body["questions"][0]
        if (question.get("type") != "choice" or question.get("name") != "current_step"
                or [item.get("value") for item in question.get("choices", [])] != list(CHOICES)
                or type(question.get("instructions")) is not str):
            raise ValueError("benchmark_question_invalid")
        content = body["input"][0].get("content")
        if type(content) is not list or any(part.get("type") not in {"input_text", "input_image"} for part in content):
            raise ValueError("benchmark_content_invalid")
        images = [part for part in content if part["type"] == "input_image"]
        if len(images) != 1 or images[0].get("image_url") != case["image"]["path"]:
            raise ValueError("benchmark_image_binding_invalid")
        if (type(case["question_data"]) is not dict
                or set(case["question_data"]) - {"target", "expected_text", "condition"}
                or any(type(v) is not str or len(v) > 8000 for v in case["question_data"].values())):
            raise ValueError("benchmark_question_data_invalid")
        case["_body"], case["_image_path"] = body, image_path
    suite["manifest_sha256"] = sha256(path.read_bytes()).hexdigest()
    return suite


def request_body(case, instructions_by_category=None):
    body = deepcopy(case["_body"])
    data = Path(case["_image_path"]).read_bytes()
    if sha256(data).hexdigest() != case["image"]["sha256"]:
        raise ValueError("benchmark_asset_hash_mismatch")
    for part in body["input"][0]["content"]:
        if part["type"] == "input_image":
            part["image_url"] = "data:image/png;base64," + base64.b64encode(data).decode("ascii")
    variants = instructions_by_category or {}
    if case["category"] in variants:
        template = variants[case["category"]]
        if type(template) is not str or len(template) > 8000:
            raise ValueError("benchmark_prompt_invalid")
        values = {key: json.dumps(value, ensure_ascii=False) for key, value in case["question_data"].items()}
        body["questions"][0]["instructions"] = template.format_map(values)
    return body


def task_order(suite, variants, split, repeats, seed):
    if (split not in SPLITS or type(repeats) is not int or not 1 <= repeats <= 20
            or len(set(variants)) != len(variants) or not variants or type(seed) is not int):
        raise ValueError("benchmark_trials_invalid")
    tasks = [(case["id"], variant, repeat) for case in suite["cases"] if case["split"] == split
        for variant in variants for repeat in range(repeats)]
    random.Random(seed).shuffle(tasks)
    return tasks


def _latency(values):
    values = sorted(x for x in values if type(x) in (int, float) and math.isfinite(x) and x >= 0)
    return {"n": len(values), "p50_ms": statistics.median(values) if values else None,
        "p95_ms": values[math.ceil(.95 * len(values)) - 1] if values else None}


def summarize(rows, *, _categories=True):
    returned = [r for r in rows if r.get("status") == "completed" and r.get("choice") in CHOICES]
    positive = [r for r in returned if r["expected"] == "condition_met"]
    false_rejects = sum(r["choice"] != "condition_met" for r in positive)
    correct = sum(r["choice"] == r["expected"] for r in returned)
    result = {"cases": len(rows), "returned": len(returned), "exact_correct": correct,
        "accuracy": correct / len(rows) if rows else None,
        "false_accepts": sum(r["choice"] == "condition_met" and r["expected"] != "condition_met" for r in returned),
        "false_rejects": false_rejects, "returned_nonpass_on_positive": false_rejects,
        "errors": len(rows) - len(returned),
        "input_tokens": sum((r.get("usage") or {}).get("input_tokens", 0) for r in rows),
        "output_tokens": sum((r.get("usage") or {}).get("output_tokens", 0) for r in rows),
        "unknown_usage_requests": sum(r.get("usage") is None for r in rows),
        "http_latency": _latency([r.get("http_elapsed_ms") for r in rows]),
        "returned_http_latency": _latency([r.get("http_elapsed_ms") for r in returned]),
        "unique_cases": len({r["case"] for r in rows if "case" in r}),
        "scene_groups": len({r["group_id"] for r in rows if "group_id" in r})}
    if _categories:
        result["by_category"] = {category: summarize([r for r in rows if r["category"] == category], _categories=False)
            for category in sorted({r["category"] for r in rows})}
    return result
