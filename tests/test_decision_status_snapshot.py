"""预算状态读原账本，不把宿主启动时的快照当作当前用量。"""
from copy import deepcopy
from hashlib import sha256
import json
from types import SimpleNamespace

import pytest

from app.core.decision_configuration import freeze_decision_profile
from app.core.instant_attachment_transport import InstantAttachmentTransport
from app.judgment import DecisionService
from test_adaptive_decision_policy import context, service
from test_decision_service import arguments, setup_service


def _files(root):
    return {path.relative_to(root).as_posix(): sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}


def _attachment(root, runtime):
    freeze_decision_profile(runtime)
    for directory in ("commands", "responses"):
        (root / directory).mkdir(exist_ok=True)
    (root / "report.json").write_text(json.dumps({"phase": "ready",
        "decision_service": runtime.status()}, ensure_ascii=False), encoding="utf-8")
    attachment = InstantAttachmentTransport(root, root)
    attachment.session = root
    attachment.process = SimpleNamespace(poll=lambda: None)
    return attachment


@pytest.fixture
def current(tmp_path, monkeypatch):
    runtime, requests, client = service(tmp_path, monkeypatch, profile={"request_cap": 11})
    attachment = _attachment(tmp_path, runtime)
    try:
        yield runtime, requests, attachment
    finally:
        runtime.close()
        client.close()


def test_status_reports_completed_dispatch_without_mutating_authenticated_budget(current, tmp_path):
    runtime, requests, attachment = current
    args = arguments(tmp_path, review_context=context())
    result = runtime.evaluate(**args)
    frozen = deepcopy(result)
    before = _files(tmp_path)
    for _ in range(2):
        status = attachment.status()["decision_service"]
        assert (status["used"], status["remaining"], status["unknown_dispatches"]) == (1, 10, 0)
        assert status["profile_sha256"] == result["profile_sha256"]
    assert _files(tmp_path) == before and result == frozen
    assert runtime.validate_result(result, **args) and len(requests) == 1


def test_status_counts_unknown_dispatch_without_provider_replay(current, tmp_path, monkeypatch):
    runtime, requests, attachment = current
    def crash(_):
        raise KeyboardInterrupt()
    monkeypatch.setattr(runtime._provider, "judge", crash)
    with pytest.raises(KeyboardInterrupt):
        runtime.evaluate(**arguments(tmp_path, review_context=context()))
    before = _files(tmp_path)
    status = attachment.status()["decision_service"]
    assert (status["used"], status["remaining"], status["unknown_dispatches"]) == (1, 10, 1)
    assert _files(tmp_path) == before and requests == []


def test_status_does_not_charge_policy_skip_or_same_request_read(current, tmp_path):
    runtime, requests, attachment = current
    args = arguments(tmp_path, review_context=context())
    result = runtime.evaluate(**args)
    assert runtime.evaluate(**args) == result
    skip_args = {**args, "request_id": "skip-not-allowlisted", "condition": "Unlisted condition"}
    skipped = runtime.evaluate(**skip_args)
    assert skipped["status"] == "skipped" and runtime.validate_result(skipped, **skip_args)
    status = attachment.status()["decision_service"]
    assert (status["used"], status["remaining"], status["unknown_dispatches"]) == (1, 10, 0)
    assert len(requests) == 1


def test_status_keeps_host_budget_across_new_runs_and_new_attachment(current, tmp_path):
    runtime, requests, attachment = current
    args = arguments(tmp_path, mode="learning", run_id="run-one", step_id="step-one",
                     review_context=context())
    assert runtime.evaluate(**args)["adopted"]
    assert runtime.evaluate(**{**args, "request_id": "run-two-request", "run_id": "run-two"})["adopted"]
    reattached = InstantAttachmentTransport(tmp_path, tmp_path)
    reattached.session, reattached.process = tmp_path, attachment.process
    for reader in (attachment, reattached):
        status = reader.status()["decision_service"]
        assert (status["used"], status["remaining"]) == (2, 9)
    assert len(requests) == 2


def test_status_after_service_reopen_keeps_existing_ledger(current, tmp_path):
    runtime, _, attachment = current
    args = arguments(tmp_path, review_context=context())
    result = runtime.evaluate(**args)
    runtime.close()
    reopened = DecisionService(tmp_path, profile=runtime.profile)
    try:
        assert reopened.evaluate(**args) == result
        assert reopened.validate_result(result, **args)
        status = attachment.status()["decision_service"]
        assert (status["used"], status["remaining"]) == (1, 10)
    finally:
        reopened.close()


def test_status_poll_without_ledger_never_constructs_service_or_creates_files(current, tmp_path, monkeypatch):
    _, _, attachment = current
    before = _files(tmp_path)
    def reject_constructor(*args, **kwargs):
        raise AssertionError("Status poll must not construct a DecisionService")
    monkeypatch.setattr(DecisionService, "__init__", reject_constructor)
    status = attachment.status()["decision_service"]
    assert (status["used"], status["remaining"], status["unknown_dispatches"]) == (0, 11, 0)
    assert _files(tmp_path) == before and not (tmp_path / "judgments").exists()


def test_status_ledger_failure_is_unavailable_not_zero(current, tmp_path):
    _, _, attachment = current
    (tmp_path / "judgments").mkdir()
    (tmp_path / "judgments" / "decisions.sqlite3").write_bytes(b"not a sqlite ledger")
    before = _files(tmp_path)
    status = attachment.status()["decision_service"]
    assert status["budget_status"] == "unavailable"
    assert (status["used"], status["remaining"], status["unknown_dispatches"]) == (None, None, None)
    assert status["request_cap"] == 11 and _files(tmp_path) == before


@pytest.mark.parametrize("fault", ["empty_directory", "missing_after_dispatch", "storage_is_file", "ledger_is_directory"])
def test_existing_persistence_without_readable_ledger_is_unavailable(current, tmp_path, fault):
    runtime, _, attachment = current
    storage = tmp_path / "judgments"
    ledger = storage / "decisions.sqlite3"
    if fault == "missing_after_dispatch":
        args = arguments(tmp_path, review_context=context())
        result = runtime.evaluate(**args)
        assert runtime.validate_result(result, **args)
        ledger.rename(tmp_path / "retained-original-ledger.sqlite3")
    elif fault == "storage_is_file":
        storage.write_bytes(b"not a persistence directory")
    else:
        storage.mkdir()
        if fault == "ledger_is_directory":
            ledger.mkdir()
    before = _files(tmp_path)
    for status in (runtime.status(), attachment.status()["decision_service"]):
        assert status["budget_status"] == "unavailable"
        assert (status["used"], status["remaining"], status["unknown_dispatches"]) == (None, None, None)
        assert status["request_cap"] == 11
    assert _files(tmp_path) == before and not ledger.is_file()


@pytest.mark.parametrize("fault", ["missing", "invalid", "different_cap"])
def test_status_refuses_missing_invalid_or_changed_frozen_profile(current, tmp_path, fault):
    runtime, _, attachment = current
    snapshot = tmp_path / "decision-profile.snapshot.json"
    if fault == "missing":
        snapshot.rename(tmp_path / "retained-original-profile.json")
    elif fault == "invalid":
        snapshot.write_text("{", encoding="utf-8")
    else:
        altered = runtime.profile.model_dump(mode="json")
        altered["request_cap"] = 2
        snapshot.write_text(json.dumps(altered, ensure_ascii=False), encoding="utf-8")
    before = _files(tmp_path)
    status = attachment.status()["decision_service"]
    assert status["budget_status"] == "unavailable"
    assert (status["used"], status["remaining"], status["unknown_dispatches"]) == (None, None, None)
    assert status["request_cap"] == 11 and _files(tmp_path) == before


def test_v1_status_keeps_execution_scope_instead_of_counting_learning(tmp_path, monkeypatch):
    runtime, calls, client = setup_service(tmp_path, monkeypatch, mode="auto",
        conditions=["\u8be6\u60c5\u5df2\u6253\u5f00"], request_cap=3)
    attachment = _attachment(tmp_path, runtime)
    try:
        args = arguments(tmp_path, mode="learning", run_id="learning-one", step_id="step-one")
        assert runtime.evaluate(**args)["adopted"]
        learning_status = attachment.status()["decision_service"]
        assert (learning_status["used"], learning_status["remaining"]) == (0, 3)
        assert runtime.evaluate(**{**args, "request_id": "execution-one", "mode": "execution"})["adopted"]
        status = attachment.status()["decision_service"]
        assert (status["used"], status["remaining"], status["unknown_dispatches"]) == (1, 2, 0)
        assert status["budget_scope"] == "execution" and len(calls) == 2
    finally:
        runtime.close()
        client.close()


def test_off_status_needs_no_profile_or_ledger(tmp_path):
    (tmp_path / "commands").mkdir()
    (tmp_path / "responses").mkdir()
    (tmp_path / "report.json").write_text(json.dumps({"phase": "ready"}), encoding="utf-8")
    attachment = InstantAttachmentTransport(tmp_path, tmp_path)
    attachment.session, attachment.process = tmp_path, SimpleNamespace(poll=lambda: None)
    before = _files(tmp_path)
    assert attachment.status()["decision_service"] == {"mode": "off"}
    assert _files(tmp_path) == before
