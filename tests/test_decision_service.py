"""共享判断服务：证据门禁、自动采用边界和重开后的零重派。"""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
import sqlite3
from threading import Event

import httpx
from PIL import Image
import pytest

from test_openai_decisions import reply


def frame(root, role="after", name="current"):
    path = root / "captures" / f"{name}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (12, 8), "white").save(path)
    return {"capture_id": name, "sha256": sha256(path.read_bytes()).hexdigest(), "image_path": str(path),
            "window_identity": {"handle": 123, "process_id": 456, "process_create_time": 1000.25}, "role": role}


def arguments(root, **patch):
    return {"request_id": "judge-1", "execution_request_id": "execute-1", "condition": "详情已打开",
            "frames": [frame(root)], **patch}


def setup_service(root, monkeypatch, *, response=None, mode="shadow", conditions=(), request_cap=20, handler=None):
    from app.judgment import DecisionProfile, DecisionService, OpenAIDecisionsProvider
    monkeypatch.setenv("DECISION_TEST_KEY", "synthetic-secret")
    calls = []
    def handle(request):
        calls.append(request)
        return handler(request) if handler else httpx.Response(200, json=response or reply())
    client = httpx.Client(transport=httpx.MockTransport(handle))
    profile = DecisionProfile(mode=mode, api_key_env="DECISION_TEST_KEY", auto_conditions=list(conditions), request_cap=request_cap)
    provider = OpenAIDecisionsProvider(api_key_env="DECISION_TEST_KEY", client=client)
    return DecisionService(root, profile=profile, provider=provider), calls, client


def test_absent_or_off_profile_has_zero_credential_evidence_client_or_disk_work(tmp_path, monkeypatch):
    from app.judgment import DecisionService
    monkeypatch.delenv("AGENT_GUI_DECISION_PROFILE", raising=False)
    service = DecisionService.from_environment(tmp_path / "absent")
    assert not service.enabled and service.adoption_mode == "off"
    assert service.evaluate(request_id="bad", execution_request_id="bad", condition="", frames=[]) ["status"] == "disabled"
    assert not (tmp_path / "absent").exists()
    profile_path = tmp_path / "off.json"
    profile_path.write_text(json.dumps({"contract_version": "decision_profile.v1", "mode": "off", "api_key_env": "DONT_READ"}), encoding="utf-8")
    service = DecisionService.from_environment(tmp_path / "off", profile_path=profile_path)
    assert service.status()["enabled"] is False
    assert service.evaluate(request_id="x", execution_request_id="x", condition="x", frames=[]) ["status"] == "disabled"
    assert not (tmp_path / "off").exists()


@pytest.mark.parametrize("patch", [{"mode": "yes"}, {"contract_version": "v2"}, {"timeout_seconds": 0},
    {"timeout_seconds": 61}, {"pass_threshold": True}, {"pass_threshold": 0.2, "fail_threshold": 0.3},
    {"request_cap": 0}, {"auto_conditions": [""]}, {"url": "https://evil.invalid"}])
def test_profile_validation_rejects_unsafe_configuration(patch):
    from app.judgment import DecisionProfile
    with pytest.raises(ValueError):
        DecisionProfile.model_validate({"contract_version": "decision_profile.v1", **patch})


@pytest.mark.parametrize("kind", ["hash", "window", "escape", "invalid_image", "missing", "roles", "capture"])
def test_invalid_evidence_is_rejected_before_http(tmp_path, monkeypatch, kind):
    service, calls, client = setup_service(tmp_path / "session", monkeypatch)
    args = arguments(tmp_path / "session")
    if kind == "hash":
        args["frames"][0]["sha256"] = "a" * 64
    elif kind == "window":
        before = frame(tmp_path / "session", "before", "before")
        before["window_identity"]["process_create_time"] += 1
        args["frames"].insert(0, before)
    elif kind == "escape":
        args["frames"] = [frame(tmp_path / "outside")]
    elif kind == "invalid_image":
        path = tmp_path / "session" / "captures" / "current.png"
        path.write_bytes(b"not an image")
        args["frames"][0]["sha256"] = sha256(path.read_bytes()).hexdigest()
    elif kind == "missing":
        args["frames"][0]["image_path"] += ".missing"
    elif kind == "roles":
        args["frames"][0]["role"] = "before"
    else:
        args["frames"].insert(0, {**args["frames"][0], "role": "before"})
    result = service.evaluate(**args)
    assert result["status"] == "rejected" and result["verdict"] == "uncertain"
    assert not result["adopted"] and calls == []
    client.close()


@pytest.mark.parametrize("p,error,verdict", [(0.9, 0.1, "success"), (0.1, 0.01, "failure"),
    (0.6, 0.01, "uncertain"), (0.6, 0.9, "failure"), (0.99, 0.9, "uncertain"), (0.99, 0.4, "uncertain")])
def test_thresholds_preserve_uncertainty_and_visible_error_veto(tmp_path, monkeypatch, p, error, verdict):
    service, calls, client = setup_service(tmp_path, monkeypatch, response=reply(p, error), mode="auto", conditions=["详情已打开"])
    args = arguments(tmp_path)
    result = service.evaluate(**args)
    assert result["status"] == "completed" and result["verdict"] == verdict
    assert result["adopted"] is (verdict != "uncertain")
    assert result["authorizes_action"] is False and result["automatic_retry_allowed"] is False
    assert service.validate_result(result, **args)
    assert result["evidence_hashes"] == [args["frames"][0]["sha256"]]
    assert result["usage"]["input_tokens"] == 12 and result["elapsed_ms"] >= 0
    assert len(calls) == 1
    client.close()


@pytest.mark.parametrize("mode,conditions", [("shadow", ["详情已打开"]), ("auto", []), ("auto", ["详情已打开 "])])
def test_adoption_requires_explicit_auto_and_exact_condition(tmp_path, monkeypatch, mode, conditions):
    service, _, client = setup_service(tmp_path, monkeypatch, mode=mode, conditions=conditions)
    assert service.evaluate(**arguments(tmp_path))["adopted"] is False
    client.close()


def test_before_phase_uses_one_frame_and_unsafe_effect_predicate_without_authorizing_action(tmp_path, monkeypatch):
    body = reply()
    body["answers"][1]["name"] = "unsafe_effect"
    service, calls, client = setup_service(tmp_path, monkeypatch, response=body, mode="auto", conditions=["详情已打开"])
    args = arguments(tmp_path, phase="before_action", frames=[frame(tmp_path, "before")], action={"goal": "打开详情", "click_point": [4, 5]})
    result = service.evaluate(**args)
    assert result["adopted"] and result["authorizes_action"] is False
    assert [q["name"] for q in json.loads(calls[0].content)["questions"]] == ["condition_met", "unsafe_effect"]
    assert service.validate_result(result, **args)
    client.close()


def test_durable_duplicate_conflict_and_tampered_result_never_dispatch_again(tmp_path, monkeypatch):
    service, calls, client = setup_service(tmp_path, monkeypatch, mode="auto", conditions=["详情已打开"])
    args = arguments(tmp_path)
    original = service.evaluate(**args)
    service.close()
    reopened, next_calls, next_client = setup_service(tmp_path, monkeypatch, mode="auto", conditions=["详情已打开"])
    assert reopened.evaluate(**args) == original and not next_calls
    assert reopened.evaluate(**{**args, "condition": "另一个条件"})["status"] == "conflict"
    forged = {**original, "verdict": "failure"}
    assert not reopened.validate_result(forged, **args)
    assert not reopened.validate_result(original, **{**args, "execution_request_id": "wrong"})
    db = sqlite3.connect(tmp_path / "judgments" / "decisions.sqlite3")
    db.execute("UPDATE dispatches SET result_blob = ?", (json.dumps(original).encode(),))
    db.commit()
    db.close()
    result = reopened.evaluate(**args)
    assert result["status"] == "error" and not result["adopted"] and not next_calls
    assert not reopened.validate_result(original, **args)
    assert len(calls) == 1
    client.close()
    next_client.close()


def test_timeout_is_durable_and_sanitized_without_retry(tmp_path, monkeypatch):
    def fail(request):
        raise httpx.ReadTimeout("synthetic-secret", request=request)
    service, calls, client = setup_service(tmp_path, monkeypatch, handler=fail)
    args = arguments(tmp_path)
    result = service.evaluate(**args)
    assert result["status"] == "timeout" and result["verdict"] == "uncertain"
    assert "synthetic-secret" not in json.dumps(result)
    assert service.evaluate(**args) == result and len(calls) == 1
    client.close()


def test_crash_marker_blocks_reopen_and_counts_toward_scope_cap(tmp_path, monkeypatch):
    def crash(_):
        raise KeyboardInterrupt()
    service, calls, client = setup_service(tmp_path, monkeypatch, handler=crash, request_cap=1)
    args = arguments(tmp_path)
    with pytest.raises(KeyboardInterrupt):
        service.evaluate(**args)
    reopened, next_calls, next_client = setup_service(tmp_path, monkeypatch, request_cap=1)
    unknown = reopened.evaluate(**args)
    assert unknown["status"] == "unknown" and reopened.validate_result(unknown, **args)
    limited_args = {**args, "request_id": "new"}
    limited = reopened.evaluate(**limited_args)
    assert limited["status"] == "limited" and reopened.validate_result(limited, **limited_args)
    assert len(calls) == 1 and not next_calls
    client.close()
    next_client.close()


def test_concurrent_same_request_has_one_dispatch_and_validated_saved_result(tmp_path, monkeypatch):
    entered, release = Event(), Event()
    def handle(_):
        entered.set()
        assert release.wait(5)
        return httpx.Response(200, json=reply())
    service, calls, client = setup_service(tmp_path, monkeypatch, handler=handle)
    other, other_calls, other_client = setup_service(tmp_path, monkeypatch)
    args = arguments(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(service.evaluate, **args)
        assert entered.wait(5)
        concurrent = other.evaluate(**args)
        assert concurrent["status"] == "unknown" and not concurrent["adopted"]
        release.set()
        saved = pending.result(timeout=5)
    assert other.evaluate(**args) == saved and len(calls) == 1 and not other_calls
    client.close()
    other_client.close()


def test_explicit_profile_overrides_environment_and_readiness_checks_only_presence(tmp_path, monkeypatch):
    from app.judgment import DecisionService, load_decision_profile
    monkeypatch.setenv("AGENT_GUI_DECISION_PROFILE", str(tmp_path / "unread.json"))
    monkeypatch.delenv("DECISION_TEST_KEY", raising=False)
    path = tmp_path / "active.json"
    path.write_text(json.dumps({"contract_version": "decision_profile.v1", "api_key_env": "DECISION_TEST_KEY"}), encoding="utf-8")
    assert load_decision_profile(path).mode == "shadow"
    service = DecisionService.from_environment(tmp_path / "session", profile_path=path)
    assert service.enabled and service.status()["mode"] == "shadow"
    assert service.readiness() == {"ready": False, "status": "not_connected"}
    monkeypatch.setenv("DECISION_TEST_KEY", "synthetic-secret")
    assert service.readiness() == {"ready": True, "status": "ready"}
    assert "synthetic-secret" not in json.dumps(service.status())
    assert not (tmp_path / "session").exists()
    service.close()
    assert service.readiness() == {"ready": False, "status": "closed"}


def test_missing_credential_result_is_saved_and_never_retries_after_key_appears(tmp_path, monkeypatch):
    service, calls, client = setup_service(tmp_path, monkeypatch)
    monkeypatch.delenv("DECISION_TEST_KEY", raising=False)
    args = arguments(tmp_path)
    result = service.evaluate(**args)
    assert result["status"] == "not_connected" and service.validate_result(result, **args)
    monkeypatch.setenv("DECISION_TEST_KEY", "synthetic-secret")
    assert service.evaluate(**args) == result and not calls
    client.close()


def test_tampered_image_or_changed_policy_invalidates_trusted_auto_result(tmp_path, monkeypatch):
    from app.judgment import DecisionService, DecisionProfile
    service, calls, client = setup_service(tmp_path, monkeypatch, mode="auto", conditions=["详情已打开"])
    args = arguments(tmp_path)
    result = service.evaluate(**args)
    path = tmp_path / "captures" / "current.png"
    original = path.read_bytes()
    path.write_bytes(original + b"changed")
    assert not service.validate_result(result, **args)
    assert service.evaluate(**args)["status"] == "rejected"
    path.write_bytes(original)
    shadow = DecisionService(tmp_path, profile=DecisionProfile())
    assert not shadow.validate_result(result, **args)
    assert shadow.evaluate(**args)["status"] == "conflict"
    assert len(calls) == 1
    client.close()


def test_persistence_authentication_failure_stops_dispatch_without_fallback(tmp_path, monkeypatch):
    import app.judgment.service as module
    service, calls, client = setup_service(tmp_path, monkeypatch)
    def fail(*args, **kwargs):
        raise OSError("synthetic-secret")
    monkeypatch.setattr(module, "_protect", fail)
    result = service.evaluate(**arguments(tmp_path))
    assert result["status"] == "error" and not result["adopted"] and not calls
    assert "synthetic-secret" not in json.dumps(result)
    client.close()


def test_learning_binding_and_scope_limit_are_independent_between_runs(tmp_path, monkeypatch):
    service, calls, client = setup_service(tmp_path, monkeypatch, request_cap=1)
    args = arguments(tmp_path, mode="learning", run_id="run-1", step_id="step-1")
    saved = service.evaluate(**args)
    assert saved["mode"] == "learning" and service.validate_result(saved, **args)
    assert service.evaluate(**{**args, "request_id": "judge-2", "step_id": "step-2"})["status"] == "limited"
    assert service.evaluate(**{**args, "request_id": "judge-3", "run_id": "run-2"})["status"] == "completed"
    assert not service.validate_result(saved, **{**args, "step_id": "changed"})
    assert service.evaluate(**{**args, "request_id": "judge-4", "step_id": None})["status"] == "rejected"
    assert len(calls) == 2
    client.close()


def test_execution_request_cap_is_shared_by_the_whole_session(tmp_path, monkeypatch):
    service, calls, client = setup_service(tmp_path, monkeypatch, request_cap=1)
    args = arguments(tmp_path)
    first = service.evaluate(**args)
    second_args = {**args, "request_id": "judge-2", "execution_request_id": "execute-2"}
    second = service.evaluate(**second_args)
    assert second["status"] == "limited" and service.validate_result(second, **second_args)
    assert service.evaluate(**args) == first and len(calls) == 1
    client.close()


@pytest.mark.parametrize("patch", [{"usage": {"input_tokens": -1, "output_tokens": 0, "total_tokens": 0}},
    {"http_elapsed_ms": float("nan")}, {"server_processing_ms": True}, {"click_point": [1, 2]},
    {"request_sha256": "wrong"}])
def test_service_revalidates_injected_provider_contract_before_adoption(tmp_path, patch):
    from app.judgment import DecisionProfile, DecisionService
    class InvalidProvider:
        ready = True
        def judge(self, payload):
            return {"request_sha256": payload["request_sha256"], "predicates": {
                "condition_met": {"type": "predicate", "probability": 0.99},
                "visible_error": {"type": "predicate", "probability": 0.01}},
                "usage": {"input_tokens": 12, "output_tokens": 0, "total_tokens": 12},
                "http_elapsed_ms": 1, "server_processing_ms": None, "provider_request_id": None, **patch}
    service = DecisionService(tmp_path, profile=DecisionProfile(mode="auto", auto_conditions=["详情已打开"]), provider=InvalidProvider())
    result = service.evaluate(**arguments(tmp_path))
    assert result["status"] == "error" and not result["adopted"] and result["verdict"] == "uncertain"


def test_service_close_during_response_does_not_adopt_result(tmp_path, monkeypatch):
    entered, release = Event(), Event()
    def handle(_):
        entered.set()
        assert release.wait(5)
        return httpx.Response(200, json=reply())
    service, calls, client = setup_service(tmp_path, monkeypatch, handler=handle, mode="auto", conditions=["详情已打开"])
    args = arguments(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(service.evaluate, **args)
        assert entered.wait(5)
        closing = pool.submit(service.close)
        release.set()
        result = pending.result(timeout=5)
        closing.result(timeout=5)
    assert result["status"] == "error" and not result["adopted"]
    assert service.evaluate(**args)["status"] == "error" and len(calls) == 1
    client.close()


def test_close_before_finalization_saves_uncertain_result_without_redispatch(tmp_path, monkeypatch):
    import app.judgment.service as module
    entered, release = Event(), Event()
    original_usage = module._usage_counts
    def usage(value):
        entered.set()
        assert release.wait(5)
        return original_usage(value)
    monkeypatch.setattr(module, "_usage_counts", usage)
    service, calls, client = setup_service(tmp_path, monkeypatch, mode="auto", conditions=["详情已打开"])
    args = arguments(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(service.evaluate, **args)
        try:
            assert entered.wait(5)
            pool.submit(service.close).result(timeout=5)
        finally:
            release.set()
        result = pending.result(timeout=5)
    assert result["status"] == "error" and result["verdict"] == "uncertain" and result["adopted"] is False
    assert not service.validate_result(result, **args)
    reopened, next_calls, next_client = setup_service(tmp_path, monkeypatch, mode="auto", conditions=["详情已打开"])
    assert reopened.evaluate(**args) == result and reopened.validate_result(result, **args)
    assert len(calls) == 1 and not next_calls
    client.close()
    next_client.close()


def test_finalization_before_close_commits_result_before_close_returns(tmp_path, monkeypatch):
    import app.judgment.service as module
    entered, release, close_started, close_returned = Event(), Event(), Event(), Event()
    original_protect = module._protect
    def protect(data, entropy, *, decrypt=False):
        if not decrypt and json.loads(data)["status"] == "completed":
            entered.set()
            assert release.wait(5)
        return original_protect(data, entropy, decrypt=decrypt)
    monkeypatch.setattr(module, "_protect", protect)
    service, calls, client = setup_service(tmp_path, monkeypatch, mode="auto", conditions=["详情已打开"])
    args = arguments(tmp_path)
    def close():
        close_started.set()
        service.close()
        close_returned.set()
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(service.evaluate, **args)
        try:
            assert entered.wait(5)
            closing = pool.submit(close)
            assert close_started.wait(5)
            assert not close_returned.wait(0.1)
            assert service.status()["closed"] is False
        finally:
            release.set()
        result = pending.result(timeout=5)
        closing.result(timeout=5)
    assert result["status"] == "completed" and result["verdict"] == "success" and result["adopted"] is True
    assert close_returned.is_set() and service.status()["closed"] is True
    assert not service.validate_result(result, **args)
    reopened, next_calls, next_client = setup_service(tmp_path, monkeypatch, mode="auto", conditions=["详情已打开"])
    assert reopened.evaluate(**args) == result and reopened.validate_result(result, **args)
    assert len(calls) == 1 and not next_calls
    client.close()
    next_client.close()


@pytest.mark.parametrize("database", ["missing_directory", "missing_file", "corrupt"])
def test_validation_without_valid_storage_is_readonly_and_never_connects(tmp_path, monkeypatch, database):
    import app.judgment.service as module
    from app.judgment import DecisionProfile, DecisionService
    session = tmp_path / "session #percent% spaces"
    args = arguments(session)
    if database != "missing_directory":
        (session / "judgments").mkdir()
    if database == "corrupt":
        (session / "judgments" / "decisions.sqlite3").write_bytes(b"invalid database")
    before = {path.relative_to(session).as_posix(): path.read_bytes() for path in session.rglob("*") if path.is_file()}
    service = DecisionService(session, profile=DecisionProfile(api_key_env="DECISION_VALIDATION_NEVER_READ"))
    def forbidden(*args, **kwargs):
        raise AssertionError("validation must not read credentials or create a provider")
    with monkeypatch.context() as guarded:
        guarded.setattr(module.os.environ, "get", forbidden)
        guarded.setattr(module, "OpenAIDecisionsProvider", forbidden)
        assert service.validate_result({}, **args) is False
    after = {path.relative_to(session).as_posix(): path.read_bytes() for path in session.rglob("*") if path.is_file()}
    assert after == before
    if database == "missing_directory":
        assert not (session / "judgments").exists()


@pytest.mark.parametrize("unknown", [False, True])
def test_authenticated_validation_preserves_all_source_bytes_and_uri_path(tmp_path, monkeypatch, unknown):
    import app.judgment.service as module
    session = tmp_path / "session #percent% spaces"
    def crash(_):
        raise KeyboardInterrupt()
    service, calls, client = setup_service(session, monkeypatch, mode="auto", conditions=["详情已打开"],
        handler=crash if unknown else None)
    args = arguments(session)
    if unknown:
        with pytest.raises(KeyboardInterrupt):
            service.evaluate(**args)
        result = service.evaluate(**args)
        assert result["status"] == "unknown" and result["adopted"] is False
    else:
        result = service.evaluate(**args)
        assert result["status"] == "completed" and result["adopted"] is True
    before = {path.relative_to(session).as_posix(): path.read_bytes() for path in session.rglob("*") if path.is_file()}
    def forbidden(*args, **kwargs):
        raise AssertionError("validation must not read credentials or create a provider")
    with monkeypatch.context() as guarded:
        guarded.setattr(module.os.environ, "get", forbidden)
        guarded.setattr(module, "OpenAIDecisionsProvider", forbidden)
        assert service.validate_result(result, **args) is True
    after = {path.relative_to(session).as_posix(): path.read_bytes() for path in session.rglob("*") if path.is_file()}
    assert before == after and len(calls) == 1
    service.close()
    client.close()
