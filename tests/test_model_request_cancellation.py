from __future__ import annotations

import json
import base64
import os
import socket
import urllib.error
from copy import deepcopy
from threading import Event, Thread
import time

import pytest
import psutil

from app.core import model_server
from app.learn.recognition.uei.canonical import seal_immutable


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        raw = json.dumps(self._payload).encode("utf-8")
        return raw if size < 0 else raw[:size]


def _server_readiness(
    *,
    started: bool,
    pid: int = 9101,
    created_ns: int = 123456789,
    model_id: str = "qwen",
    base_url: str = "http://127.0.0.1:13240/v1",
) -> dict:
    observation = {
        "status": "running",
        "base_url": base_url,
        "model_id": model_id,
        "server_process_identity": {
            "pid": pid,
            "create_time_ns": created_ns,
        },
    }
    return {"started": started, "after" if started else "before": observation}


def _valid_binding_artifacts() -> tuple[dict, dict]:
    from app.learn.hybrid.qwen_binding import parse_qwen_candidate_bindings
    from test_learn_hybrid_contracts import inventory_fixture

    inventory = seal_immutable(inventory_fixture())
    candidate_id = inventory["candidates"][0]["candidate_id"]
    parsed = parse_qwen_candidate_bindings(
        {
            "bindings": [{
                "candidate_id": candidate_id,
                "role": "button",
                "label": "申请职位",
                "description": "打开申请流程",
                "semantic_confidence": 0.94,
                "task_relevance": 0.88,
                "relation": "primary_action",
                "ambiguity": None,
            }],
            "orphan_semantics": [],
        },
        inventory,
    )
    return inventory, seal_immutable(parsed)


def test_cancel_model_request_verifies_vista_request_termination(monkeypatch) -> None:
    requested: list[dict] = []
    profile = {
        "profile_id": "vista",
        "role": ["grounding", "locate"],
        "endpoint": "http://127.0.0.1:13244/v1/chat/completions",
        "request_cancel_supported": True,
        "request_cancel_endpoint": "http://127.0.0.1:13244/v1/cancel",
    }
    monkeypatch.setattr(model_server, "load_model_profiles", lambda: [profile])

    def fake_urlopen(request, timeout):
        requested.append(
            {
                "url": request.full_url,
                "body": json.loads(request.data.decode("utf-8")),
                "timeout": timeout,
            }
        )
        return _FakeResponse(
            {
                "contract_version": "model_request_cancel_response_v1",
                "status": "cancellation_acknowledged",
                "request_id": "learn-worker-123",
            }
        )

    monkeypatch.setattr(model_server.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        model_server,
        "check_model_server",
        lambda profile, timeout=1.0: {
            "status": "running",
            "health": {"status": "ok", "active_request": None},
        },
    )

    result = model_server.cancel_model_request(
        request_id="learn-worker-123",
        task_kind="vision_locate_target",
        payload={"provider_mode": "local_grounding"},
    )

    assert requested == [
        {
            "url": "http://127.0.0.1:13244/v1/cancel",
            "body": {"request_id": "learn-worker-123"},
            "timeout": 1.0,
        }
    ]
    assert result["status"] == "terminated"
    assert result["model_service_compute_termination"] == "terminated"
    assert result["provider_results"][0]["profile_id"] == "vista"


def test_cancel_model_request_reports_unsupported_without_guessing(monkeypatch) -> None:
    monkeypatch.setattr(model_server, "load_model_profiles", lambda: [])

    result = model_server.cancel_model_request(
        request_id="learn-worker-456",
        task_kind="panel_learning_model_review_repair",
        payload={},
    )

    assert result["status"] == "not_supported"
    assert result["model_service_compute_termination"] == "not_supported"
    assert result["provider_results"] == []


def test_calibration_sequence_cancellation_uses_nested_locate_payload(
    monkeypatch,
) -> None:
    profile = {
        "profile_id": "vista",
        "role": ["grounding", "locate"],
        "request_cancel_supported": True,
        "request_cancel_endpoint": "http://127.0.0.1:13244/v1/cancel",
    }
    monkeypatch.setattr(model_server, "load_model_profiles", lambda: [profile])

    profiles = model_server._request_cancel_profiles(
        task_kind="panel_learning_calibration_sequence",
        payload={
            "contract_version": "learning_calibration_sequence_request_v1",
            "locate_payload": {"provider_mode": "local_grounding"},
        },
    )

    assert profiles == [profile]


def test_qwen_cancellation_uses_exact_request_endpoint_and_retains_other_operation(
    tmp_path,
    monkeypatch,
) -> None:
    profile = {
        "profile_id": "qwen3_vl_8b_q4_k_m",
        "role": ["understanding", "learning"],
        "provider_mode": "local_understanding",
        "endpoint": "http://127.0.0.1:13240/v1/chat/completions",
        "request_cancel_supported": True,
        "request_cancel_endpoint": "http://127.0.0.1:13240/v1/cancel",
    }
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    lease_a = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="learn-qwen-a",
        readiness=_server_readiness(started=True),
    )
    lease_b = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="learn-qwen-b",
        readiness=_server_readiness(started=False),
    )
    changed_profile = {**profile, "request_cancel_endpoint": "http://127.0.0.1:13240/v1/should-not-use"}
    monkeypatch.setattr(model_server, "profile_for_stage", lambda stage, profile_id=None: changed_profile)
    requested: list[dict] = []

    def fake_urlopen(request, timeout):
        requested.append({"url": request.full_url, "body": json.loads(request.data), "timeout": timeout})
        return _FakeResponse({
            "contract_version": "model_request_cancel_response_v1",
            "status": "cancellation_acknowledged",
            "request_id": "learn-qwen-a",
        })

    monkeypatch.setattr(model_server.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(model_server, "check_model_server", lambda selected, timeout=1.0: {
        "status": "running",
        "base_url": "http://127.0.0.1:13240/v1",
        "model_id": "qwen",
        "health": {"status": "ok", "active_request": {"request_id": "learn-qwen-b"}},
    })
    monkeypatch.setattr(model_server, "stop_model_server", lambda selected: pytest.fail("shared server stopped"))

    result = model_server.cancel_model_request(
        request_id="learn-qwen-a",
        task_kind="panel_learning_hybrid_qwen_binding",
        payload={},
    )

    assert result["status"] == "terminated"
    assert requested == [{
        "url": profile["request_cancel_endpoint"],
        "body": {"request_id": "learn-qwen-a"},
        "timeout": 1.0,
    }]
    assert result["provider_results"][0]["lease"]["lease_id"] == lease_a["lease_id"]
    assert result["provider_results"][0]["shared_server_retained"] is True
    assert model_server.qwen_model_lease_is_active(lease_b) is True
    assert model_server.qwen_model_lease_is_active(lease_a) is False


@pytest.mark.parametrize(
    "second_profile,second_readiness",
    [
        (
            {"profile_id": "qwen", "endpoint": "http://127.0.0.1:14000/v1/chat/completions"},
            _server_readiness(started=False, base_url="http://127.0.0.1:14000/v1"),
        ),
        (
            {"profile_id": "qwen", "endpoint": "http://127.0.0.1:13240/v1/chat/completions", "model_name": "other"},
            _server_readiness(started=False, model_id="other"),
        ),
        (
            {"profile_id": "qwen", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"},
            _server_readiness(started=False, pid=9202, created_ns=987654321),
        ),
    ],
)
def test_same_profile_id_rejects_incompatible_server_incarnation(
    tmp_path,
    monkeypatch,
    second_profile,
    second_readiness,
) -> None:
    profile = {"profile_id": "qwen", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="request-a",
        readiness=_server_readiness(started=True),
    )

    with pytest.raises(ValueError, match="server incarnation mismatch"):
        model_server.acquire_qwen_model_lease(
            profile=second_profile,
            request_id="request-b",
            readiness=second_readiness,
        )


def test_different_profile_id_cannot_partition_same_qwen_listener_process(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    first = {
        "profile_id": "qwen-before-rename",
        "endpoint": "http://127.0.0.1:13240/v1/chat/completions",
    }
    renamed = {**first, "profile_id": "qwen-after-rename"}
    readiness = _server_readiness(started=True, pid=9101, created_ns=111)
    model_server.acquire_qwen_model_lease(
        profile=first,
        request_id="request-a",
        readiness=readiness,
    )

    with pytest.raises(ValueError, match="server incarnation mismatch"):
        model_server.acquire_qwen_model_lease(
            profile=renamed,
            request_id="request-b",
            readiness={**readiness, "started": False},
        )


def test_qwen_cancellation_finds_lease_by_owner_when_current_profile_id_changes(
    tmp_path,
    monkeypatch,
) -> None:
    acquired = {
        "profile_id": "qwen-acquired",
        "role": ["understanding"],
        "provider_mode": "local_understanding",
        "endpoint": "http://127.0.0.1:13240/v1/chat/completions",
        "request_cancel_supported": True,
        "request_cancel_endpoint": "http://127.0.0.1:13240/v1/cancel",
    }
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    lease = model_server.acquire_qwen_model_lease(
        profile=acquired,
        request_id="owner-request",
        readiness=_server_readiness(started=False),
    )
    monkeypatch.setattr(model_server, "profile_for_stage", lambda *args, **kwargs: {
        **acquired,
        "profile_id": "qwen-current-other",
        "request_cancel_endpoint": "http://127.0.0.1:13240/v1/wrong",
    })
    requested: list[str] = []
    monkeypatch.setattr(model_server.urllib.request, "urlopen", lambda request, timeout: requested.append(request.full_url) or _FakeResponse({
        "status": "request_not_active",
        "request_id": "owner-request",
    }))

    result = model_server.cancel_model_request(
        request_id="owner-request",
        task_kind="panel_learning_hybrid_qwen_binding",
        payload={},
    )

    assert requested == [acquired["request_cancel_endpoint"]]
    assert result["provider_results"][0]["profile_id"] == "qwen-acquired"
    assert model_server.qwen_model_lease_is_active(lease) is False


def test_no_endpoint_shared_cancel_stays_owned_pending(
    tmp_path,
    monkeypatch,
) -> None:
    profile = deepcopy(model_server.profile_for_stage("understanding"))
    assert profile["profile_id"] == "qwen3_vl_8b_q4_k_m"
    assert not profile.get("request_cancel_endpoint")
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    lease_a = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="request-a",
        readiness=_server_readiness(started=True),
    )
    lease_b = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="request-b",
        readiness=_server_readiness(started=False),
    )
    monkeypatch.setattr(model_server, "stop_model_server", lambda selected: pytest.fail("shared server stopped"))

    result = model_server.cancel_model_request(
        request_id="request-a",
        task_kind="panel_learning_hybrid_qwen_binding",
        payload={},
    )

    assert result["status"] == "cancellation_acknowledged_pending"
    assert result["model_service_compute_termination"] == "cancellation_acknowledged_pending"
    provider = result["provider_results"][0]
    assert provider["pending_reason"] == "request_cancel_endpoint_unavailable"
    assert provider["capability_blocker"] == "request_cancel_endpoint_unavailable"
    assert provider["reconciliation_trigger"] == "worker_http_completion_or_explicit_retry"
    with model_server._qwen_lease_lock():
        state = model_server._load_qwen_lease_state(lease_a["incarnation_id"])
        exact = model_server._find_exact_lease(state, lease_a)
    assert exact["pending_reason"] == "request_cancel_endpoint_unavailable"
    assert exact["capability_blocker"] == "request_cancel_endpoint_unavailable"
    assert exact["reconciliation_trigger"] == "worker_http_completion_or_explicit_retry"
    assert model_server.qwen_model_lease_is_active(lease_a) is True
    assert model_server.qwen_model_lease_is_active(lease_b) is True


def test_qwen_finalization_token_is_single_owner_during_release_cancel_race(
    tmp_path,
    monkeypatch,
) -> None:
    inventory, artifact = _valid_binding_artifacts()
    profile = {
        "profile_id": "qwen",
        "provider_mode": "local_understanding",
        "endpoint": "http://127.0.0.1:13240/v1/chat/completions",
    }
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="release-cancel-owner",
        readiness=_server_readiness(started=True, pid=9101, created_ns=111),
    )
    entered = Event()
    finish = Event()
    terminations: list[dict] = []

    def terminate(expected):
        terminations.append(expected)
        entered.set()
        finish.wait(timeout=2.0)
        return {"status": "proven_absent", "method": "terminate_wait"}

    monkeypatch.setattr(
        model_server,
        "_probe_exact_qwen_process",
        lambda expected: {"status": "exact_live", "identity": expected},
    )
    monkeypatch.setattr(model_server, "_terminate_exact_qwen_server_process", terminate)
    monkeypatch.setattr(
        model_server,
        "check_model_server",
        lambda selected, timeout=1.0: {"status": "unreachable"},
    )
    released: dict[str, object] = {}
    worker = Thread(
        target=lambda: released.update(
            model_server.release_qwen_model_server(
                sealed_artifact=artifact,
                omni_inventory=inventory,
                model_lease=lease,
            )
        )
    )
    worker.start()
    assert entered.wait(timeout=1.0) is True

    concurrent = model_server.cancel_model_request(
        request_id="release-cancel-owner",
        task_kind="panel_learning_hybrid_qwen_binding",
        payload={},
    )
    assert concurrent["status"] == "cancellation_acknowledged_pending"
    assert concurrent["provider_results"][0]["server_termination"] == "finalization_pending"
    assert len(terminations) == 1

    finish.set()
    worker.join(timeout=2.0)
    assert worker.is_alive() is False
    assert released["server_termination"] == "verified_exact_process_exited"
    assert len(terminations) == 1
    retry = model_server.cancel_model_request(
        request_id="release-cancel-owner",
        task_kind="panel_learning_hybrid_qwen_binding",
        payload={},
    )
    assert retry["status"] == "request_not_active"
    assert retry["provider_results"][0]["owner_receipt"]["status"] == "finalized"


def test_existing_qwen_finalization_token_is_immutable_and_never_stops_twice(
    tmp_path,
    monkeypatch,
) -> None:
    profile = {"profile_id": "qwen", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="existing-token-owner",
        readiness=_server_readiness(started=True, pid=9101, created_ns=111),
    )
    with model_server._qwen_lease_lock():
        state = model_server._load_qwen_lease_state(lease["incarnation_id"])
        state["revision"] += 1
        state["finalization"] = {
            "token": "immutable-token",
            "revision": state["revision"],
            "lease_id": lease["lease_id"],
            "phase": "stop_pending",
            "reason": "completed",
        }
        model_server._write_qwen_lease_state(state)
    monkeypatch.setattr(
        model_server,
        "_terminate_exact_qwen_server_process",
        lambda expected: pytest.fail("second finalizer attempted exact termination"),
    )

    pending = model_server._release_exact_qwen_lease(lease, reason="cancelled")

    assert pending["status"] == "cancellation_acknowledged_pending"
    assert pending["finalization"]["token"] == "immutable-token"
    with model_server._qwen_lease_lock():
        persisted = model_server._load_qwen_lease_state(lease["incarnation_id"])
    assert persisted["finalization"]["token"] == "immutable-token"


def test_qwen_failure_reconciliation_persists_timeout_pending_and_removes_completed_parser_lease(
    tmp_path,
    monkeypatch,
) -> None:
    profile = {"profile_id": "qwen", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    timeout_lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="timeout-request",
        readiness=_server_readiness(started=True),
    )
    parser_lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="parser-request",
        readiness=_server_readiness(started=False),
    )

    pending = model_server.reconcile_qwen_model_lease_failure(
        model_lease=timeout_lease,
        compute_completed=False,
        reason="timeout",
    )
    assert pending["status"] == "cancellation_acknowledged_pending"
    assert model_server.qwen_model_lease_is_active(timeout_lease) is True

    completed = model_server.reconcile_qwen_model_lease_failure(
        model_lease=parser_lease,
        compute_completed=True,
        reason="parser_rejection",
    )
    assert completed["status"] == "released"
    assert completed["shared_server_retained"] is True
    assert model_server.qwen_model_lease_is_active(parser_lease) is False
    assert model_server.qwen_model_lease_is_active(timeout_lease) is True


def test_qwen_pending_cancel_then_real_finalizer_retry_uses_owner_tombstone(
    tmp_path,
    monkeypatch,
) -> None:
    profile = {
        "profile_id": "qwen",
        "provider_mode": "local_understanding",
        "endpoint": "http://127.0.0.1:13240/v1/chat/completions",
    }
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    pending_lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="pending-owner",
        readiness=_server_readiness(started=True),
    )
    retained = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="retained-owner",
        readiness=_server_readiness(started=False),
    )
    monkeypatch.setattr(
        model_server,
        "_terminate_exact_qwen_server_process",
        lambda expected: pytest.fail("shared process must not be terminated"),
    )

    first = model_server.cancel_model_request(
        request_id="pending-owner",
        task_kind="panel_learning_hybrid_qwen_binding",
        payload={},
    )
    assert first["status"] == "cancellation_acknowledged_pending"

    finalized = model_server.reconcile_qwen_model_lease_failure(
        model_lease=pending_lease,
        compute_completed=True,
        reason="worker_http_completed_after_cancel",
    )
    assert finalized["status"] == "released"
    assert model_server.qwen_model_lease_is_active(pending_lease) is False
    assert model_server.qwen_model_lease_is_active(retained) is True

    retry = model_server.cancel_model_request(
        request_id="pending-owner",
        task_kind="panel_learning_hybrid_qwen_binding",
        payload={},
    )
    assert retry["status"] == "request_not_active"
    assert retry["model_service_compute_termination"] == "request_not_active"
    assert retry["provider_results"][0]["owner_receipt"]["status"] == "finalized"


def test_qwen_timeout_finalizer_stops_only_sole_exact_owned_incarnation(
    tmp_path,
    monkeypatch,
) -> None:
    profile = {"profile_id": "qwen", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="timeout-request",
        readiness=_server_readiness(started=True, pid=9101, created_ns=111),
    )
    monkeypatch.setattr(
        model_server,
        "_probe_exact_qwen_process",
        lambda expected: {"status": "exact_live", "identity": expected},
    )
    monkeypatch.setattr(
        model_server,
        "_terminate_exact_qwen_server_process",
        lambda expected: {"status": "proven_absent", "identity": None},
    )
    monkeypatch.setattr(model_server, "check_model_server", lambda selected, timeout=1.0: {"status": "unreachable"})

    reconciled = model_server.reconcile_qwen_model_lease_failure(
        model_lease=lease,
        compute_completed=False,
        reason="timeout",
    )
    assert reconciled["server_termination"] == "verified_exact_process_exited"
    assert model_server.qwen_model_lease_is_active(lease) is False


def test_invalid_http_json_marks_compute_complete_before_failure_reconciliation(
    tmp_path,
    monkeypatch,
) -> None:
    profile = {"profile_id": "qwen", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    failed = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="invalid-json-request",
        readiness=_server_readiness(started=True),
    )
    active = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="active-request",
        readiness=_server_readiness(started=False),
    )
    monkeypatch.setattr(model_server, "_current_process_identity", lambda pid: {
        "pid": 9101,
        "create_time_ns": 123456789,
    })

    class InvalidResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, size=-1):
            return b"not-json"

    monkeypatch.setattr(model_server.urllib.request, "urlopen", lambda *args, **kwargs: InvalidResponse())
    with pytest.raises(ValueError):
        model_server.run_qwen_binding_model(
            request={},
            screenshot_bytes=b"same-bytes",
            screenshot_media_type="image/png",
            screenshot_sha256=__import__("hashlib").sha256(b"same-bytes").hexdigest(),
            model_lease=failed,
        )

    reconciled = model_server.reconcile_qwen_model_lease_failure(
        model_lease=failed,
        compute_completed=False,
        reason="invalid_json",
    )
    assert reconciled["status"] == "released"
    assert model_server.qwen_model_lease_is_active(failed) is False
    assert model_server.qwen_model_lease_is_active(active) is True


def test_qwen_release_refcounts_and_stops_only_after_last_runtime_owned_lease(
    tmp_path,
    monkeypatch,
) -> None:
    inventory, artifact = _valid_binding_artifacts()
    stopped: list[dict] = []
    profile = {"profile_id": "qwen3_vl_8b_q4_k_m", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    lease_a = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="request-a",
        readiness=_server_readiness(started=True),
    )
    lease_b = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="request-b",
        readiness=_server_readiness(started=False),
    )
    monkeypatch.setattr(
        model_server,
        "_probe_exact_qwen_process",
        lambda expected: {"status": "exact_live", "identity": expected},
    )
    monkeypatch.setattr(
        model_server,
        "_terminate_exact_qwen_server_process",
        lambda expected: stopped.append(expected)
        or {"status": "proven_absent", "reason": "terminate_wait"},
    )
    monkeypatch.setattr(model_server, "check_model_server", lambda selected, timeout=1.0: {"status": "unreachable"})

    first = model_server.release_qwen_model_server(
        sealed_artifact=artifact,
        omni_inventory=inventory,
        model_lease=lease_a,
    )
    assert first["status"] == "released"
    assert first["shared_server_retained"] is True
    assert stopped == []
    assert model_server.qwen_model_lease_is_active(lease_b) is True

    second = model_server.release_qwen_model_server(
        sealed_artifact=artifact,
        omni_inventory=inventory,
        model_lease=lease_b,
    )
    assert second["status"] == "released"
    assert second["server_termination"] == "verified_exact_process_exited"
    assert stopped == [lease_b["server_process_identity"]]


def test_qwen_last_request_cancel_stops_owned_server_then_new_external_lease_is_retained(
    tmp_path,
    monkeypatch,
) -> None:
    inventory, artifact = _valid_binding_artifacts()
    profile = {
        "profile_id": "qwen3_vl_8b_q4_k_m",
        "role": ["understanding"],
        "provider_mode": "local_understanding",
        "endpoint": "http://127.0.0.1:13240/v1/chat/completions",
        "request_cancel_supported": True,
        "request_cancel_endpoint": "http://127.0.0.1:13240/v1/cancel",
    }
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    monkeypatch.setattr(model_server, "profile_for_stage", lambda stage, profile_id=None: profile)
    first = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="owned-request",
        readiness=_server_readiness(started=True),
    )
    stopped: list[dict] = []
    monkeypatch.setattr(model_server.urllib.request, "urlopen", lambda request, timeout: _FakeResponse({
        "status": "cancellation_acknowledged",
        "request_id": "owned-request",
    }))
    monkeypatch.setattr(
        model_server,
        "_probe_exact_qwen_process",
        lambda expected: {"status": "exact_live", "identity": expected},
    )
    monkeypatch.setattr(
        model_server,
        "_terminate_exact_qwen_server_process",
        lambda expected: stopped.append(expected)
        or {"status": "proven_absent", "reason": "terminate_wait"},
    )
    monkeypatch.setattr(model_server, "check_model_server", lambda selected, timeout=1.0: {
        "status": "unreachable",
        "health": {"active_request": None},
    })

    cancelled = model_server.cancel_model_request(
        request_id="owned-request",
        task_kind="panel_learning_hybrid_qwen_binding",
        payload={},
    )
    assert cancelled["status"] == "terminated"
    assert cancelled["provider_results"][0]["server_termination"] == "verified_exact_process_exited"
    assert stopped == [first["server_process_identity"]]
    assert model_server.qwen_model_lease_is_active(first) is False

    external = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="external-request",
        readiness=_server_readiness(started=False),
    )
    stopped.clear()
    released = model_server.release_qwen_model_server(
        sealed_artifact=artifact,
        omni_inventory=inventory,
        model_lease=external,
    )
    assert released["server_termination"] == "not_owned"
    assert stopped == []


def test_qwen_release_rejects_forged_or_wrong_capture_artifact(
    tmp_path,
    monkeypatch,
) -> None:
    inventory, artifact = _valid_binding_artifacts()
    profile = {"profile_id": "qwen3_vl_8b_q4_k_m", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="request-a",
        readiness=_server_readiness(started=False),
    )

    with pytest.raises(ValueError, match="sealed Qwen binding"):
        model_server.release_qwen_model_server(
            sealed_artifact=seal_immutable({"contract_version": "hybrid_qwen_bindings_v1"}),
            omni_inventory=inventory,
            model_lease=lease,
        )

    with pytest.raises(ValueError, match="exact Qwen model lease"):
        model_server.release_qwen_model_server(
            sealed_artifact=artifact,
            omni_inventory=inventory,
            model_lease={
                "lease_id": lease["lease_id"],
                "incarnation_id": lease["incarnation_id"],
            },
        )

    omitted = seal_immutable({
        **{key: deepcopy(value) for key, value in artifact.items() if key != "content_sha256"},
        "bindings": [],
    })
    with pytest.raises(ValueError, match="coverage|sealed Qwen binding"):
        model_server.release_qwen_model_server(
            sealed_artifact=omitted,
            omni_inventory=inventory,
            model_lease=lease,
        )

    wrong_inventory = seal_immutable({
        **{key: value for key, value in inventory.items() if key != "content_sha256"},
        "capture_identity": {**inventory["capture_identity"], "screenshot_sha256": "0" * 64},
    })
    with pytest.raises(ValueError, match="capture|screenshot|sealed Qwen binding"):
        model_server.release_qwen_model_server(
            sealed_artifact=artifact,
            omni_inventory=wrong_inventory,
            model_lease=lease,
        )


def test_qwen_stop_script_success_but_server_running_is_not_released(
    tmp_path,
    monkeypatch,
) -> None:
    inventory, artifact = _valid_binding_artifacts()
    profile = {"profile_id": "qwen3_vl_8b_q4_k_m", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="request-a",
        readiness=_server_readiness(started=True),
    )
    monkeypatch.setattr(
        model_server,
        "_probe_exact_qwen_process",
        lambda expected: {"status": "exact_live", "identity": expected},
    )
    monkeypatch.setattr(
        model_server,
        "_terminate_exact_qwen_server_process",
        lambda expected: {"status": "exact_live", "identity": expected},
    )
    monkeypatch.setattr(model_server, "check_model_server", lambda selected, timeout=1.0: {"status": "running", "model_id": "qwen"})

    with pytest.raises(RuntimeError, match="still running"):
        model_server.release_qwen_model_server(
            sealed_artifact=artifact,
            omni_inventory=inventory,
            model_lease=lease,
        )
    assert model_server.qwen_model_lease_is_active(lease) is True


def test_qwen_release_never_stops_replacement_process(
    tmp_path,
    monkeypatch,
) -> None:
    inventory, artifact = _valid_binding_artifacts()
    profile = {"profile_id": "qwen", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="request-a",
        readiness=_server_readiness(started=True, pid=9101, created_ns=111),
    )
    monkeypatch.setattr(
        model_server,
        "_probe_exact_qwen_process",
        lambda expected: {
            "status": "proven_absent",
            "identity": {"pid": 9101, "create_time_ns": 222},
            "reason": "pid_reused",
        },
    )
    monkeypatch.setattr(
        model_server,
        "_terminate_exact_qwen_server_process",
        lambda expected: pytest.fail("replacement stopped"),
    )

    with pytest.raises(RuntimeError, match="server incarnation ownership changed"):
        model_server.release_qwen_model_server(
            sealed_artifact=artifact,
            omni_inventory=inventory,
            model_lease=lease,
        )
    assert model_server.qwen_model_lease_is_active(lease) is True


def test_qwen_post_stop_access_denied_remains_owned_pending(
    tmp_path,
    monkeypatch,
) -> None:
    inventory, artifact = _valid_binding_artifacts()
    profile = {"profile_id": "qwen", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="access-denied-owner",
        readiness=_server_readiness(started=True, pid=9101, created_ns=111),
    )

    class AccessDeniedProcess:
        pid = 9101

        def is_running(self):
            return True

        def status(self):
            return "running"

        def create_time(self):
            return 111 / 1_000_000_000

        def terminate(self):
            return None

        def wait(self, timeout):
            del timeout
            raise psutil.AccessDenied(pid=9101)

    monkeypatch.setattr(model_server.psutil, "Process", lambda pid: AccessDeniedProcess())

    with pytest.raises(RuntimeError, match="process exit is unobservable"):
        model_server.release_qwen_model_server(
            sealed_artifact=artifact,
            omni_inventory=inventory,
            model_lease=lease,
        )
    assert model_server.qwen_model_lease_is_active(lease) is True
    with model_server._qwen_lease_lock():
        state = model_server._load_qwen_lease_state(lease["incarnation_id"])
    assert state["finalization"]["phase"] == "owned_pending"
    assert state["finalization"]["failure_reason"] == "process_exit_unobservable"


def test_exact_qwen_termination_never_kills_pid_replacement(monkeypatch) -> None:
    expected = {"pid": 9101, "create_time_ns": 111}
    killed: list[int] = []

    class OriginalProcess:
        pid = 9101

        def is_running(self):
            return True

        def status(self):
            return "running"

        def create_time(self):
            return 111 / 1_000_000_000

        def terminate(self):
            return None

        def wait(self, timeout):
            del timeout
            raise psutil.TimeoutExpired(seconds=0.1, pid=9101)

        def kill(self):
            killed.append(self.pid)

    probes = iter([
        {"status": "exact_live", "identity": expected},
        {
            "status": "proven_absent",
            "identity": {"pid": 9101, "create_time_ns": 222},
            "reason": "pid_reused",
        },
    ])
    monkeypatch.setattr(model_server.psutil, "Process", lambda pid: OriginalProcess())
    monkeypatch.setattr(model_server, "_probe_exact_qwen_process", lambda identity: next(probes))

    result = model_server._terminate_exact_qwen_server_process(expected)

    assert result["status"] == "proven_absent"
    assert result["reason"] == "pid_reused"
    assert killed == []


def test_qwen_global_acquisition_transaction_serializes_first_start_and_publication(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    profile = {"profile_id": "qwen", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    first_started = Event()
    release_first = Event()
    active_calls = 0
    max_active_calls = 0
    call_lock = __import__("threading").Lock()
    ensure_calls = 0

    def ensure(**kwargs):
        nonlocal active_calls, max_active_calls, ensure_calls
        del kwargs
        with call_lock:
            active_calls += 1
            max_active_calls = max(max_active_calls, active_calls)
            ensure_calls += 1
            call_number = ensure_calls
        if call_number == 1:
            first_started.set()
            release_first.wait(timeout=2.0)
        with call_lock:
            active_calls -= 1
        return _server_readiness(
            started=call_number == 1,
            pid=9101,
            created_ns=111,
        )

    monkeypatch.setattr(model_server, "ensure_model_server", ensure)
    leases: list[dict] = []

    def acquire(owner):
        leases.append(model_server.ensure_and_acquire_qwen_model_lease(
            stage="understanding",
            profile_id=None,
            profile=profile,
            request_id=owner,
            wait_seconds=1.0,
        ))

    one = Thread(target=acquire, args=("owner-a",))
    two = Thread(target=acquire, args=("owner-b",))
    one.start()
    assert first_started.wait(timeout=1.0) is True
    two.start()
    time.sleep(0.05)
    assert ensure_calls == 1
    release_first.set()
    one.join(timeout=2.0)
    two.join(timeout=2.0)

    assert max_active_calls == 1
    assert len(leases) == 2
    assert leases[0]["incarnation_id"] == leases[1]["incarnation_id"]


def test_qwen_final_stop_runs_outside_os_state_lock_and_proves_exact_pid_exit(
    tmp_path,
    monkeypatch,
) -> None:
    inventory, artifact = _valid_binding_artifacts()
    profile = {"profile_id": "qwen", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="request-a",
        readiness=_server_readiness(started=True, pid=9101, created_ns=111),
    )
    monkeypatch.setattr(
        model_server,
        "_probe_exact_qwen_process",
        lambda expected: {"status": "exact_live", "identity": expected},
    )
    stop_observed_lock = Event()

    def stop(expected):
        with model_server._qwen_lease_lock():
            stop_observed_lock.set()
        return {"status": "proven_absent", "identity": None, "expected": expected}

    monkeypatch.setattr(model_server, "_terminate_exact_qwen_server_process", stop)
    monkeypatch.setattr(model_server, "check_model_server", lambda selected, timeout=1.0: {"status": "unreachable"})

    released = model_server.release_qwen_model_server(
        sealed_artifact=artifact,
        omni_inventory=inventory,
        model_lease=lease,
    )
    assert stop_observed_lock.is_set() is True
    assert released["server_termination"] == "verified_exact_process_exited"


def test_qwen_os_lock_is_not_stolen_from_live_owner(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    owner_entered = Event()
    release_owner = Event()
    waiter_entered = Event()

    def owner():
        with model_server._qwen_lease_lock():
            lock_path = tmp_path / ".lease-state.lock"
            old = time.time() - 31.0
            os.utime(lock_path, (old, old))
            owner_entered.set()
            release_owner.wait(timeout=2.0)

    def waiter():
        owner_entered.wait(timeout=2.0)
        with model_server._qwen_lease_lock():
            waiter_entered.set()

    first = Thread(target=owner)
    second = Thread(target=waiter)
    first.start()
    second.start()
    assert owner_entered.wait(timeout=1.0) is True
    time.sleep(0.05)
    assert waiter_entered.is_set() is False
    release_owner.set()
    first.join(timeout=1.0)
    second.join(timeout=1.0)
    assert waiter_entered.is_set() is True


def test_qwen_binding_runner_reuses_understanding_endpoint_and_request_id(
    tmp_path,
    monkeypatch,
) -> None:
    profile = {
        "profile_id": "qwen3_vl_8b_q4_k_m",
        "model_name": "Qwen3VL-8B-Instruct-Q4_K_M.gguf",
        "endpoint": "http://127.0.0.1:13240/v1/chat/completions",
    }
    seen: dict = {}
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="learn-qwen-request",
        readiness=_server_readiness(started=False, model_id=profile["model_name"]),
    )
    changed_profile = {**profile, "endpoint": "http://127.0.0.1:13240/v1/should-not-use"}
    monkeypatch.setattr(model_server, "profile_for_stage", lambda stage: changed_profile)
    monkeypatch.setattr(model_server, "_current_process_identity", lambda pid: {
        "pid": 9101,
        "create_time_ns": 123456789,
    })
    monkeypatch.setenv("AGENT_GUI_MODEL_REQUEST_ID", "learn-qwen-request")
    screenshot_bytes = b"controlled-task2-image-bytes"

    def fake_urlopen(request, timeout):
        seen.update(
            url=request.full_url,
            headers=dict(request.headers),
            body=json.loads(request.data.decode("utf-8")),
            timeout=timeout,
        )
        return _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"bindings": [], "orphan_semantics": []},
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr(model_server.urllib.request, "urlopen", fake_urlopen)
    result = model_server.run_qwen_binding_model(
        request={"label": "申请职位"},
        screenshot_bytes=screenshot_bytes,
        screenshot_media_type="image/png",
        screenshot_sha256=__import__("hashlib").sha256(screenshot_bytes).hexdigest(),
        model_lease=lease,
        timeout_seconds=3.0,
    )

    assert result == {"bindings": [], "orphan_semantics": []}
    assert seen["url"] == profile["endpoint"]
    assert seen["timeout"] == 3.0
    assert seen["body"]["request_id"] == "learn-qwen-request"
    assert seen["body"]["model"] == profile["model_name"]
    assert "申请职位" in seen["body"]["messages"][1]["content"][0]["text"]
    image_url = seen["body"]["messages"][1]["content"][1]["image_url"]["url"]
    assert base64.b64decode(image_url.split(",", 1)[1]) == screenshot_bytes


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("direct timeout"),
        socket.timeout("socket timeout"),
        urllib.error.URLError(socket.timeout("wrapped timeout")),
    ],
)
def test_qwen_binding_runner_normalizes_timeout_types(monkeypatch, error) -> None:
    profile = {"profile_id": "qwen", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    monkeypatch.setattr(model_server, "profile_for_stage", lambda stage: profile)
    monkeypatch.setattr(model_server.urllib.request, "urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(error))

    with pytest.raises(model_server.QwenModelRequestTimeout):
        model_server.run_qwen_binding_model(
            request={},
            screenshot_bytes=b"same-bytes",
            screenshot_media_type="image/png",
            screenshot_sha256=__import__("hashlib").sha256(b"same-bytes").hexdigest(),
            timeout_seconds=0.1,
        )


def test_qwen_binding_runner_rejects_oversized_http_body(monkeypatch) -> None:
    profile = {"profile_id": "qwen", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    monkeypatch.setattr(model_server, "profile_for_stage", lambda stage: profile)

    class OversizedResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, size=-1):
            return b"x" * size

    monkeypatch.setattr(model_server.urllib.request, "urlopen", lambda *args, **kwargs: OversizedResponse())
    with pytest.raises(ValueError, match="response byte limit"):
        model_server.run_qwen_binding_model(
            request={},
            screenshot_bytes=b"same-bytes",
            screenshot_media_type="image/png",
            screenshot_sha256=__import__("hashlib").sha256(b"same-bytes").hexdigest(),
        )


def test_qwen_http_event_set_and_cancelled_transport_use_typed_cancellation(monkeypatch) -> None:
    profile = {"profile_id": "qwen", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    monkeypatch.setattr(model_server, "profile_for_stage", lambda stage: profile)
    cancellation = Event()
    cancellation.set()
    with pytest.raises(model_server.QwenModelRequestCancelled):
        model_server.run_qwen_binding_model(
            request={},
            screenshot_bytes=b"same-bytes",
            screenshot_media_type="image/png",
            screenshot_sha256=__import__("hashlib").sha256(b"same-bytes").hexdigest(),
            cancellation_event=cancellation,
        )

    cancellation.clear()

    def cancelled_transport(*args, **kwargs):
        del args, kwargs
        cancellation.set()
        raise urllib.error.URLError("cancelled transport")

    monkeypatch.setattr(model_server.urllib.request, "urlopen", cancelled_transport)
    with pytest.raises(model_server.QwenModelRequestCancelled):
        model_server.run_qwen_binding_model(
            request={},
            screenshot_bytes=b"same-bytes",
            screenshot_media_type="image/png",
            screenshot_sha256=__import__("hashlib").sha256(b"same-bytes").hexdigest(),
            cancellation_event=cancellation,
        )


def test_qwen_runner_rejects_replaced_server_incarnation_before_http(
    tmp_path,
    monkeypatch,
) -> None:
    profile = {"profile_id": "qwen", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="request-a",
        readiness=_server_readiness(started=False, pid=9101, created_ns=111),
    )
    monkeypatch.setattr(model_server, "_current_process_identity", lambda pid: {
        "pid": 9101,
        "create_time_ns": 222,
    })
    monkeypatch.setattr(model_server.urllib.request, "urlopen", lambda *args, **kwargs: pytest.fail("replacement received request"))

    with pytest.raises(RuntimeError, match="server incarnation ownership changed"):
        model_server.run_qwen_binding_model(
            request={},
            screenshot_bytes=b"same-bytes",
            screenshot_media_type="image/png",
            screenshot_sha256=__import__("hashlib").sha256(b"same-bytes").hexdigest(),
            model_lease=lease,
        )
