"""评测执行器只在新预留后发送，并保留未知费用。"""
from copy import deepcopy
from hashlib import sha256
import json

import httpx
from PIL import Image
import pytest

from scripts.decision_benchmark_budget import TokenBudget
import scripts.run_decision_benchmark as runner
from scripts.run_decision_benchmark import run_benchmark


def _save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def setup_run(tmp_path, monkeypatch):
    Image.new("RGB", (24, 20), "white").save(tmp_path / "source.png")
    Image.new("RGB", (24, 20), "cyan").save(tmp_path / "marked.png")
    choices = ("condition_met", "condition_not_met", "evidence_insufficient")
    body = {"model": "gpt-6-luna", "input": [{"role": "user", "content": [
        {"type": "input_text", "text": "Marker is an annotation."},
        {"type": "input_image", "image_url": "marked.png", "detail": "high"}]}],
        "questions": [{"type": "choice", "name": "current_step", "instructions": "Is the point in the input?",
            "choices": [{"value": value, "description": value} for value in choices]}]}
    _save(tmp_path / "request.json", body)
    asset = lambda name: {"path": name, "sha256": sha256((tmp_path / name).read_bytes()).hexdigest()}
    case = {"id": "field", "group_id": "scene-a", "split": "train", "category": "input_field",
        "expected": "condition_not_met", "truth": {"annotator": "human-only", "reason": "label-secret"},
        "provenance": {"capture_id": "capture-a", "session_id": "session-a", "kind": "real_capture"},
        "source": asset("source.png"), "image": asset("marked.png"), "request": asset("request.json"),
        "question_data": {"target": "the address input"}}
    _save(tmp_path / "suite.json", {"schema": "decision_benchmark.v1", "suite_id": "offline-fixture", "cases": [case]})
    _save(tmp_path / "variants.json", {"baseline": {}})
    monkeypatch.setenv("BENCHMARK_TEST_KEY", "private-test-key")
    return {"suite_path": tmp_path / "suite.json", "variants_path": tmp_path / "variants.json",
        "output_dir": tmp_path / "out", "budget_path": tmp_path / "budget.jsonl",
        "api_key_env": "BENCHMARK_TEST_KEY", "split": "train", "repeats": 1, "seed": 17}


def _reply(choice="condition_not_met", usage=True):
    return {"model": "gpt-6-luna", "answers": [{"type": "choice", "name": "current_step", "choice": choice,
        "confidence": .9, "probabilities": [{"value": value, "probability": .9 if value == choice else .05}
            for value in ("condition_met", "condition_not_met", "evidence_insufficient")]}],
        "usage": {"input_tokens": 31, "output_tokens": 1, "total_tokens": 32} if usage else None}


class Client:
    def __init__(self, outcomes, before_send=None):
        self.outcomes, self.calls, self.before_send = list(outcomes), [], before_send

    def post(self, url, **kwargs):
        if self.before_send:
            self.before_send(url, kwargs)
        self.calls.append((url, deepcopy(kwargs)))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _response(body=None, status=200):
    return httpx.Response(status, json=_reply() if body is None else body,
        headers={"x-request-id": "provider-test-id"})


def test_prepare_is_offline_and_execution_requires_explicit_resume(setup_run, monkeypatch):
    monkeypatch.delenv("BENCHMARK_TEST_KEY")
    client = Client([])
    result = run_benchmark(**setup_run, client=client)
    assert result["mode"] == "prepared" and result["rows"][0]["status"] == "prepared"
    assert not client.calls and not setup_run["budget_path"].exists()
    run = json.loads((setup_run["output_dir"] / "run.json").read_text(encoding="utf-8"))
    assert len(run["tasks"]) == 1 and len(run["tasks"][0]["request_sha256"]) == 64
    with pytest.raises(ValueError, match="resume_required"):
        run_benchmark(**setup_run, execute=True, client=client)


def test_success_persists_dispatch_before_http_and_never_wires_labels(setup_run):
    def before_send(url, kwargs):
        dispatches = list((setup_run["output_dir"] / "dispatches").glob("*.json"))
        assert len(dispatches) == 1
        dispatch = json.loads(dispatches[0].read_text(encoding="utf-8"))
        budget = TokenBudget(setup_run["budget_path"]).snapshot()
        assert budget["requests"][dispatch["request_id"]]["settlement"] is None
        assert url == "https://api.openai.com/v1/decisions"
        assert kwargs["timeout"] <= 8 and kwargs["follow_redirects"] is False
        assert kwargs["extensions"]["total_deadline"] > 0
        wire = kwargs["content"].decode("utf-8")
        assert all(secret not in wire for secret in ("human-only", "label-secret", '"expected"', '"truth"'))
    client = Client([_response()], before_send)
    result = run_benchmark(**setup_run, execute=True, client=client)
    row = result["rows"][0]
    assert row["status"] == "completed" and row["choice"] == "condition_not_met"
    assert row["provider_request_id"] == "provider-test-id" and result["summary"]["exact_correct"] == 1
    assert result["budget"]["spent"] == 32 and result["budget"]["reserved"] == 0
    assert len(list((setup_run["output_dir"] / "responses").glob("*.raw"))) == 1
    request_record = next((setup_run["output_dir"] / "requests").glob("*.json")).read_text(encoding="utf-8")
    assert "base64," not in request_record
    rerun = run_benchmark(**setup_run, execute=True, resume=True, client=Client([]))
    assert rerun["rows"] == result["rows"] and rerun["budget"]["spent"] == 32


def test_timeout_keeps_reservation_and_resume_never_resends(setup_run):
    client = Client([httpx.ReadTimeout("private-test-key must not escape")])
    result = run_benchmark(**setup_run, execute=True, client=client)
    assert result["rows"][0]["status"] == "unknown"
    assert result["budget"]["reserved"] == 1_000_000
    assert "private-test-key" not in json.dumps(result)
    resumed_client = Client([])
    resumed = run_benchmark(**setup_run, execute=True, resume=True, client=resumed_client)
    assert not resumed_client.calls and resumed["budget"]["reserved"] == 1_000_000
    assert resumed["summary"]["exact_correct"] == 0 and resumed["summary"]["errors"] == 1


@pytest.mark.parametrize("kind", ["invalid_answer", "http_error"])
def test_readable_usage_settles_even_when_reply_is_invalid(setup_run, kind):
    body = _reply()
    if kind == "invalid_answer":
        body["answers"] = []
    result = run_benchmark(**setup_run, execute=True, client=Client([_response(body, 503 if kind == "http_error" else 200)]))
    assert result["rows"][0]["status"] == "error" and result["rows"][0]["choice"] is None
    assert result["budget"]["spent"] == 32 and result["budget"]["reserved"] == 0
    assert result["summary"]["exact_correct"] == 0


@pytest.mark.parametrize("body", [{"invalid": True}, _reply(usage=False)])
def test_unknown_usage_keeps_full_reservation(setup_run, body):
    result = run_benchmark(**setup_run, execute=True, client=Client([_response(body)]))
    assert result["budget"]["reserved"] == 1_000_000 and result["budget"]["spent"] == 0
    assert result["rows"][0]["usage"] is None and result["rows"][0]["status"] == "error"


def test_reserve_without_dispatch_or_result_is_unknown_and_cannot_resend(setup_run):
    run_benchmark(**setup_run)
    run = json.loads((setup_run["output_dir"] / "run.json").read_text(encoding="utf-8"))
    task = run["tasks"][0]
    TokenBudget(setup_run["budget_path"]).reserve(task["request_id"], 1_000_000, task["request_sha256"])
    client = Client([])
    result = run_benchmark(**setup_run, execute=True, resume=True, client=client)
    assert not client.calls and result["rows"][0]["status"] == "unknown"
    assert result["budget"]["reserved"] == 1_000_000


def test_budget_cap_stops_sixth_unknown_request(setup_run):
    setup_run["repeats"] = 6
    client = Client([httpx.ReadTimeout("timeout") for _ in range(6)])
    result = run_benchmark(**setup_run, execute=True, client=client)
    assert len(client.calls) == 5 and result["budget"]["reserved"] == 5_000_000
    assert sum(row["status"] == "budget_exceeded" for row in result["rows"]) == 1
    assert result["summary"]["exact_correct"] == 0


@pytest.mark.parametrize("change", ["seed", "variant", "manifest", "request"])
def test_resume_rejects_changed_frozen_run(setup_run, change):
    run_benchmark(**setup_run)
    if change == "seed":
        setup_run["seed"] += 1
    elif change == "variant":
        _save(setup_run["variants_path"], {"baseline": {}, "short": {"input_field": "Check {target}."}})
    elif change == "manifest":
        value = json.loads(setup_run["suite_path"].read_text(encoding="utf-8"))
        value["cases"][0]["truth"]["reason"] = "different human reason"
        _save(setup_run["suite_path"], value)
    else:
        record = next((setup_run["output_dir"] / "requests").glob("*.json"))
        value = json.loads(record.read_text(encoding="utf-8"))
        value["request_sha256"] = "0" * 64
        _save(record, value)
    with pytest.raises(ValueError, match="conflict"):
        run_benchmark(**setup_run, execute=True, resume=True, client=Client([]))


def test_variant_only_changes_instructions_and_order_is_frozen(setup_run):
    _save(setup_run["variants_path"], {"baseline": {}, "short": {"input_field": "Inspect {target}."}})
    setup_run["repeats"] = 2
    result = run_benchmark(**setup_run, execute=True, client=Client([_response() for _ in range(4)]))
    assert {(r["variant"], r["repeat"]) for r in result["rows"]} == {
        (variant, repeat) for variant in ("baseline", "short") for repeat in range(2)}
    saved = json.loads((setup_run["output_dir"] / "run.json").read_text(encoding="utf-8"))
    assert [(r["case"], r["variant"], r["repeat"]) for r in result["rows"]] == [
        (r["case"], r["variant"], r["repeat"]) for r in saved["tasks"]]


def test_response_corruption_rejects_resume_without_resending(setup_run):
    run_benchmark(**setup_run, execute=True, client=Client([_response()]))
    next((setup_run["output_dir"] / "responses").glob("*.raw")).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="response.*conflict"):
        run_benchmark(**setup_run, execute=True, resume=True, client=Client([]))


def test_api_key_is_required_only_at_execution_and_budget_limit_cannot_expand(setup_run, monkeypatch):
    run_benchmark(**setup_run)
    monkeypatch.delenv("BENCHMARK_TEST_KEY")
    with pytest.raises(ValueError, match="key_missing"):
        run_benchmark(**setup_run, execute=True, resume=True, client=Client([]))
    with pytest.raises(ValueError, match="limit_invalid"):
        run_benchmark(**setup_run, budget_limit=5_000_001, resume=True)


@pytest.mark.parametrize("artifact", ["dispatches", "responses"])
def test_dispatch_or_raw_without_budget_is_conflict_never_resend(setup_run, artifact):
    run_benchmark(**setup_run)
    run = json.loads((setup_run["output_dir"] / "run.json").read_text(encoding="utf-8"))
    task = run["tasks"][0]
    directory = setup_run["output_dir"] / artifact
    directory.mkdir()
    if artifact == "dispatches":
        _save(directory / (task["request_id"] + ".json"), {**task, "reserved_tokens": 1_000_000})
    else:
        (directory / (task["request_id"] + ".raw")).write_bytes(b"orphan response")
    client = Client([_response()])
    with pytest.raises(ValueError, match="conflict"):
        run_benchmark(**setup_run, execute=True, resume=True, client=client)
    assert not client.calls


def test_existing_receipt_settles_after_crash_without_sending_again(setup_run, monkeypatch):
    original = TokenBudget.settle
    def crash(*args, **kwargs):
        raise OSError("simulated crash between receipt fsync and settle")
    monkeypatch.setattr(TokenBudget, "settle", crash)
    with pytest.raises(OSError, match="simulated crash"):
        run_benchmark(**setup_run, execute=True, client=Client([_response()]))
    assert TokenBudget(setup_run["budget_path"]).snapshot()["reserved"] == 1_000_000
    monkeypatch.setattr(TokenBudget, "settle", original)
    client = Client([])
    result = run_benchmark(**setup_run, execute=True, resume=True, client=client)
    assert not client.calls and result["budget"]["spent"] == 32 and result["budget"]["reserved"] == 0


def test_production_client_factory_is_reused_closed_and_constrained(setup_run, monkeypatch):
    setup_run["repeats"] = 2
    created = []
    class ProductionFake(Client):
        def __init__(self, **kwargs):
            created.append(kwargs)
            super().__init__([_response(), _response()])
            self.closed = False
        def close(self):
            self.closed = True
    transport = object()
    monkeypatch.setattr(runner, "DeadlineHTTPTransport", lambda: transport)
    instance = ProductionFake()
    created.clear()
    def factory(**kwargs):
        created.append(kwargs)
        return instance
    monkeypatch.setattr(runner.httpx, "Client", factory)
    run_benchmark(**setup_run, execute=True)
    assert len(created) == 1 and created[0] == {"timeout": 8, "follow_redirects": False,
        "trust_env": False, "transport": transport}
    assert len(instance.calls) == 2 and instance.closed


def test_run_output_lock_refuses_second_runner(setup_run):
    with runner._run_lock(setup_run["output_dir"]):
        with pytest.raises(ValueError, match="run_busy"):
            run_benchmark(**setup_run)


def test_cli_returns_incomplete_without_printing_secrets(setup_run, monkeypatch, capsys):
    monkeypatch.setattr(runner, "run_benchmark", lambda *args, **kwargs: {
        "mode": "executed", "rows": [{"status": "unknown"}], "summary": {"returned": 0, "errors": 1}})
    args = ["--suite", str(setup_run["suite_path"]), "--variants", str(setup_run["variants_path"]),
        "--output-dir", str(setup_run["output_dir"]), "--budget-journal", str(setup_run["budget_path"]), "--execute"]
    assert runner.main(args) == 1
    captured = capsys.readouterr()
    assert "private-test-key" not in captured.out + captured.err
    def failure(*args, **kwargs):
        raise ValueError("benchmark_run_conflict")
    monkeypatch.setattr(runner, "run_benchmark", failure)
    assert runner.main(args) == 2
    assert "benchmark_run_conflict" in capsys.readouterr().err


def test_non200_empty_transport_body_keeps_usage_unknown_and_http_diagnostic(setup_run):
    result = run_benchmark(**setup_run, execute=True, client=Client([httpx.Response(503, content=b"")]))
    assert result["rows"][0]["error"] == "http_status_503"
    assert result["rows"][0]["usage"] is None and result["budget"]["reserved"] == 1_000_000


def test_prepare_can_resume_under_another_key_environment(setup_run, monkeypatch):
    run_benchmark(**setup_run)
    monkeypatch.setenv("ANOTHER_BENCHMARK_KEY", "other-private-key")
    setup_run["api_key_env"] = "ANOTHER_BENCHMARK_KEY"
    client = Client([_response()])
    run_benchmark(**setup_run, execute=True, resume=True, client=client)
    assert client.calls[0][1]["headers"]["Authorization"] == "Bearer other-private-key"


def test_execute_must_be_explicit_boolean_not_truthy_text(setup_run):
    client = Client([_response()])
    with pytest.raises(ValueError, match="mode_invalid"):
        run_benchmark(**setup_run, execute="false", client=client)
    assert not client.calls


def test_real_httpx_wire_bytes_match_frozen_request_dispatch_and_budget_hashes(setup_run):
    _save(setup_run["variants_path"], {"baseline": {}, "utf8": {"input_field": "核验 {target}。"}})
    captured = []
    def receive(request):
        request_id = request.headers["X-Client-Request-Id"]
        dispatch = json.loads((setup_run["output_dir"] / "dispatches" / (request_id + ".json")).read_text(encoding="utf-8"))
        record = json.loads((setup_run["output_dir"] / "requests" / (request_id + ".json")).read_text(encoding="utf-8"))
        entry = TokenBudget(setup_run["budget_path"]).snapshot()["requests"][request_id]
        wire_hash = sha256(request.content).hexdigest()
        assert wire_hash == dispatch["request_sha256"] == record["request_sha256"] == entry["request_sha256"]
        assert request.headers["Content-Type"] == "application/json"
        assert request.content.endswith(b"\n")
        assert "truth" not in json.loads(request.content) and "expected" not in json.loads(request.content)
        captured.append((request_id, request.content))
        return _response()
    with httpx.Client(transport=httpx.MockTransport(receive)) as client:
        result = run_benchmark(**setup_run, execute=True, client=client)
    run = json.loads((setup_run["output_dir"] / "run.json").read_text(encoding="utf-8"))
    assert [request_id for request_id, _ in captured] == [task["request_id"] for task in run["tasks"]]
    assert all(row["status"] == "completed" for row in result["rows"])
    assert any("核验".encode("utf-8") in content for _, content in captured)
