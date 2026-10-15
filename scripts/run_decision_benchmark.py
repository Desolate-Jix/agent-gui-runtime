"""冻结真实截图评测；默认只预检，显式执行时严格单次发送。"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import sys
from time import monotonic, perf_counter_ns
from uuid import uuid4

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from app.judgment.http_deadline import DeadlineHTTPTransport
from app.judgment.openai_decisions import ENDPOINT, _parse_choice_reply, _usage_counts
from app.vision.recognition_source import _invalid_constant, _unique_object
from scripts.decision_benchmark import load_suite, read_json, request_body, summarize, task_order
from scripts.decision_benchmark_budget import BudgetExceeded, BudgetOverrun, TokenBudget


MAX_TOKENS = 5_000_000
RESERVE_TOKENS = 1_000_000
TIMEOUT_SECONDS = 8


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
        separators=(",", ":")) + "\n").encode("utf-8")


def _digest(value):
    return sha256(_json_bytes(value)).hexdigest()


def _write(path, data, *, exclusive=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    target = path if exclusive else path.with_name(path.name + "." + uuid4().hex + ".tmp")
    with target.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    if not exclusive:
        os.replace(target, path)


def _save(path, value, *, exclusive=False):
    _write(path, _json_bytes(value), exclusive=exclusive)


@contextmanager
def _run_lock(output):
    output.mkdir(parents=True, exist_ok=True)
    fd = os.open(output / ".runner.lock", os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0), 0o600)
    acquired = False
    try:
        if os.fstat(fd).st_size == 0:
            os.write(fd, b"\0")
            os.fsync(fd)
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ValueError("benchmark_run_busy") from None
        acquired = True
        yield
    finally:
        if acquired:
            os.lseek(fd, 0, os.SEEK_SET)
            if os.name == "nt":
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _variants(path, categories):
    variants = read_json(path)
    if (type(variants) is not dict or not 1 <= len(variants) <= 20 or variants.get("baseline") != {}
            or any(type(name) is not str or re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", name) is None
                for name in variants)):
        raise ValueError("benchmark_variants_invalid")
    for name, mapping in variants.items():
        if (type(mapping) is not dict or set(mapping) - categories
                or any(type(text) is not str or not text.strip() or len(text) > 8000 for text in mapping.values())):
            raise ValueError("benchmark_variants_invalid")
        if name != "baseline" and not mapping:
            raise ValueError("benchmark_variants_invalid")
    return {name: variants[name] for name in ["baseline", *sorted(set(variants) - {"baseline"})]}


def _request_record(body, request_hash):
    record = deepcopy(body)
    for part in record["input"][0]["content"]:
        if part["type"] == "input_image":
            image_url = part["image_url"]
            part["image_url"] = {"omitted": "base64_image", "sha256": sha256(image_url.encode("ascii")).hexdigest()}
    if len(_json_bytes(record)) > 65_536:
        raise ValueError("benchmark_request_too_large")
    return {"request_sha256": request_hash, "body": record}


def _prepare(suite_path, variants_path, output, budget_path, *, split, repeats, seed, budget_limit, resume):
    suite = load_suite(suite_path)
    variants = _variants(variants_path, {case["category"] for case in suite["cases"]})
    order = task_order(suite, list(variants), split, repeats, seed)
    if not order:
        raise ValueError("benchmark_split_empty")
    config = {"suite_path": str(suite_path), "manifest_sha256": suite["manifest_sha256"],
        "variants_path": str(variants_path), "variants_sha256": sha256(variants_path.read_bytes()).hexdigest(),
        "split": split, "repeats": repeats, "seed": seed, "budget_path": str(budget_path),
        "budget_limit": budget_limit, "reserve_tokens": RESERVE_TOKENS,
        "endpoint": ENDPOINT, "timeout_seconds": TIMEOUT_SECONDS}
    existing = (output / "run.json").exists()
    if existing:
        if not resume:
            raise ValueError("benchmark_resume_required")
        run = read_json(output / "run.json")
        if (type(run) is not dict or set(run) != {"schema", "run_id", "config", "tasks"}
                or run["schema"] != "decision_benchmark_run.v1" or run["config"] != config
                or type(run["run_id"]) is not str or re.fullmatch(r"[0-9a-f]{32}", run["run_id"]) is None):
            raise ValueError("benchmark_run_conflict")
    else:
        if resume or any(path.name != ".runner.lock" for path in output.iterdir()):
            raise ValueError("benchmark_run_conflict")
        run = {"schema": "decision_benchmark_run.v1", "run_id": uuid4().hex, "config": config, "tasks": []}
    cases = {case["id"]: case for case in suite["cases"]}
    tasks = []
    for index, (case_id, variant, repeat) in enumerate(order):
        body = request_body(cases[case_id], variants[variant])
        request_hash = _digest(body)
        request_id = "benchmark-" + sha256(f"{run['run_id']}:{index}".encode("ascii")).hexdigest()
        task = {"case": case_id, "variant": variant, "repeat": repeat,
            "request_id": request_id, "request_sha256": request_hash}
        tasks.append(task)
        record = _request_record(body, request_hash)
        record_path = output / "requests" / (request_id + ".json")
        if existing:
            if not record_path.exists() or read_json(record_path) != record:
                raise ValueError("benchmark_request_conflict")
        else:
            _save(record_path, record, exclusive=True)
    if existing:
        if run["tasks"] != tasks:
            raise ValueError("benchmark_run_conflict")
    else:
        run["tasks"] = tasks
        _save(output / "run.json", run, exclusive=True)
    return run, cases, variants


def _base_row(task, case):
    return {**task, "group_id": case["group_id"], "category": case["category"], "expected": case["expected"],
        "choice": None, "usage": None, "http_elapsed_ms": None, "provider_request_id": None}


def _received_row(base, receipt, output):
    if (type(receipt) is not dict or set(receipt) != {"request_id", "request_sha256", "http_status",
            "http_elapsed_ms", "provider_request_id", "response_sha256", "error"}
            or any(receipt[key] != base[key] for key in ("request_id", "request_sha256"))
            or type(receipt["http_elapsed_ms"]) not in (int, float)
            or not math.isfinite(receipt["http_elapsed_ms"]) or receipt["http_elapsed_ms"] < 0):
        raise ValueError("benchmark_response_conflict")
    row = {**base, **{key: receipt[key] for key in ("http_elapsed_ms", "provider_request_id", "response_sha256")}}
    if receipt["response_sha256"] is None:
        if receipt["http_status"] is not None or receipt["error"] not in {"timeout", "transport_error"}:
            raise ValueError("benchmark_response_conflict")
        return {**row, "status": "unknown", "error": receipt["error"]}
    raw = (output / "responses" / (base["request_id"] + ".raw")).read_bytes()
    if (len(raw) > 65_536 or sha256(raw).hexdigest() != receipt["response_sha256"]
            or type(receipt["http_status"]) is not int or not 100 <= receipt["http_status"] <= 599
            or receipt["error"] is not None):
        raise ValueError("benchmark_response_conflict")
    row["http_status"] = receipt["http_status"]
    try:
        body = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    except (ValueError, UnicodeError):
        return {**row, "status": "error", "error": "invalid_json" if receipt["http_status"] == 200
            else "http_status_" + str(receipt["http_status"])}
    try:
        row["usage"] = _usage_counts(body.get("usage") if type(body) is dict else None)
    except (TypeError, ValueError):
        pass
    if receipt["http_status"] != 200:
        return {**row, "status": "error", "error": "http_status_" + str(receipt["http_status"])}
    try:
        answer, usage = _parse_choice_reply(body)
    except (ValueError, TypeError, KeyError):
        return {**row, "status": "error", "error": "invalid_reply"}
    return {**row, "choice": answer["choice"], "usage": usage, "choice_result": answer,
        "status": "completed" if answer["type"] == "choice" else "refusal", "error": None}


def _send(client, key, base, output):
    started = perf_counter_ns()
    receipt = {key: base[key] for key in ("request_id", "request_sha256")}
    receipt.update(http_status=None, http_elapsed_ms=0, provider_request_id=None, response_sha256=None, error=None)
    try:
        response = client.post(ENDPOINT, content=_json_bytes(base["_body"]), headers={"Authorization": "Bearer " + key,
            "Content-Type": "application/json",
            "Accept-Encoding": "identity", "X-Client-Request-Id": base["request_id"]},
            timeout=TIMEOUT_SECONDS, follow_redirects=False,
            extensions={"total_deadline": monotonic() + TIMEOUT_SECONDS})
    except (httpx.TimeoutException, TimeoutError):
        receipt["error"] = "timeout"
    except (httpx.HTTPError, OSError, ValueError):
        receipt["error"] = "transport_error"
    else:
        receipt["http_elapsed_ms"] = (perf_counter_ns() - started) / 1_000_000
        raw = response.content
        if len(raw) > 65_536:
            receipt["error"] = "transport_error"
        else:
            _write(output / "responses" / (base["request_id"] + ".raw"), raw, exclusive=True)
            receipt.update(http_status=response.status_code, response_sha256=sha256(raw).hexdigest())
            provider_id = response.headers.get("x-request-id")
            if (type(provider_id) is str and key not in provider_id
                    and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", provider_id)):
                receipt["provider_request_id"] = provider_id
    if receipt["error"] is not None:
        receipt["http_elapsed_ms"] = (perf_counter_ns() - started) / 1_000_000
    _save(output / "responses" / (base["request_id"] + ".json"), receipt, exclusive=True)
    return receipt


def _summary(rows):
    return {**summarize(rows), "by_variant": {variant: summarize([row for row in rows if row["variant"] == variant])
        for variant in sorted({row["variant"] for row in rows})}}


def run_benchmark(suite_path, variants_path, output_dir, budget_path, *, split="train", repeats=1, seed=0,
        execute=False, resume=False, api_key_env="OPENAI_API_KEY", budget_limit=MAX_TOKENS, client=None):
    if type(execute) is not bool or type(resume) is not bool:
        raise ValueError("benchmark_mode_invalid")
    if type(budget_limit) is not int or not 0 <= budget_limit <= MAX_TOKENS:
        raise ValueError("benchmark_budget_limit_invalid")
    if type(api_key_env) is not str or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", api_key_env) is None:
        raise ValueError("benchmark_key_environment_invalid")
    suite_path, variants_path, output, budget_path = map(lambda p: Path(p).resolve(),
        (suite_path, variants_path, output_dir, budget_path))
    with _run_lock(output):
        run, cases, variants = _prepare(suite_path, variants_path, output, budget_path,
            split=split, repeats=repeats, seed=seed, budget_limit=budget_limit, resume=resume)
        rows, budget, owned_client = [], None, False
        key = None
        try:
            if execute:
                key = os.environ.get(api_key_env)
                if not key or not key.strip():
                    raise ValueError("benchmark_key_missing")
                budget = TokenBudget(budget_path, limit=budget_limit)
            for task in run["tasks"]:
                case = cases[task["case"]]
                base = _base_row(task, case)
                receipt_path = output / "responses" / (task["request_id"] + ".json")
                if not execute:
                    row = _received_row(base, read_json(receipt_path), output) if receipt_path.exists() else {
                        **base, "status": "prepared"}
                elif receipt_path.exists():
                    entry = budget.snapshot()["requests"].get(task["request_id"])
                    if (entry is None or entry["amount"] != RESERVE_TOKENS
                            or entry["request_sha256"] != task["request_sha256"]):
                        raise ValueError("benchmark_budget_response_conflict")
                    row = _received_row(base, read_json(receipt_path), output)
                else:
                    dispatch_path = output / "dispatches" / (task["request_id"] + ".json")
                    raw_path = output / "responses" / (task["request_id"] + ".raw")
                    if dispatch_path.exists() or raw_path.exists():
                        entry = budget.snapshot()["requests"].get(task["request_id"])
                        if (entry is None or entry["amount"] != RESERVE_TOKENS
                                or entry["request_sha256"] != task["request_sha256"]
                                or dispatch_path.exists() and read_json(dispatch_path) != {
                                    **task, "reserved_tokens": RESERVE_TOKENS}):
                            raise ValueError("benchmark_dispatch_conflict")
                    try:
                        fresh = budget.reserve(task["request_id"], RESERVE_TOKENS, task["request_sha256"])
                    except BudgetExceeded:
                        rows.append({**base, "status": "budget_exceeded", "error": "budget_exceeded"})
                        continue
                    if not fresh:
                        row = {**base, "status": "unknown", "error": "reserved_without_response"}
                    else:
                        body = request_body(case, variants[task["variant"]])
                        if _digest(body) != task["request_sha256"]:
                            raise ValueError("benchmark_request_conflict")
                        _save(output / "dispatches" / (task["request_id"] + ".json"),
                            {**task, "reserved_tokens": RESERVE_TOKENS}, exclusive=True)
                        if client is None:
                            client = httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False, trust_env=False,
                                transport=DeadlineHTTPTransport())
                            owned_client = True
                        receipt = _send(client, key, {**base, "_body": body}, output)
                        row = _received_row(base, receipt, output)
                if execute and row["usage"] is not None:
                    try:
                        budget.settle(task["request_id"], row["usage"]["input_tokens"],
                            row["usage"]["output_tokens"], row["response_sha256"])
                    except BudgetOverrun:
                        row = {**row, "status": "error", "choice": None, "error": "budget_overrun"}
                rows.append(row)
                _save(output / "results.json", rows)
                _save(output / "summary.json", _summary(rows))
            result = {"mode": "executed" if execute else "prepared", "rows": rows, "summary": _summary(rows),
                "budget": budget.snapshot() if budget else None}
            _save(output / "results.json", rows)
            _save(output / "summary.json", result["summary"])
            if budget:
                _save(output / "budget-snapshot.json", result["budget"])
            return result
        finally:
            key = None
            if owned_client:
                client.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", required=True)
    parser.add_argument("--variants", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--budget-journal", required=True)
    parser.add_argument("--split", choices=("train", "validation", "test"), default="train")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    parser.add_argument("--budget-limit", type=int, default=MAX_TOKENS)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_benchmark(args.suite, args.variants, args.output_dir, args.budget_journal,
            split=args.split, repeats=args.repeats, seed=args.seed, api_key_env=args.api_key_env,
            budget_limit=args.budget_limit, execute=args.execute, resume=args.resume)
    except (ValueError, OSError, KeyError, TypeError) as error:
        code = str(error)
        if re.fullmatch(r"benchmark_[a-z0-9_]+", code) is None:
            code = "benchmark_execution_failed"
        print(code + ": inspect frozen artifacts and budget journal; no automatic retry", file=sys.stderr)
        return 2
    print(json.dumps({"mode": result["mode"], "cases": len(result["rows"]),
        "completed": result["summary"]["returned"], "errors": result["summary"]["errors"]}, ensure_ascii=False))
    return 1 if result["mode"] == "executed" and result["summary"]["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
