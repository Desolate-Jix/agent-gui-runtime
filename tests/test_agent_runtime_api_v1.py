from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent.live_controller import (
    LiveControllerDecision,
    LiveSessionSnapshot,
    ServerWorkflowBinding,
)
from app.agent.reviewed_workflow_asset import content_sha256
from app.agent.runtime_contracts import (
    AgentIntentV1,
    RuntimeResultReceiptV1,
    validate_agent_observation_v1,
)
from app.agent.runtime_intent_claim_store import (
    RuntimeIntentClaimStore,
    RuntimeIntentClaimStoreError,
)
from app.agent.runtime_receipt_store import RuntimeReceiptStore
from app.api.agent_runtime import (
    LocalAgentRuntimeCallsite,
    get_agent_runtime_callsite,
    router,
)
from tests.test_reviewed_workflow_asset_v2 import _asset as _reviewed_asset_fixture
from tests.test_runtime_intent_claim_store_w3b import (
    _binding as _confirmation_binding,
    _confirmation_intent,
    _confirmation_observation,
    _confirmation_request_inputs,
)


OPAQUE_APPLY_ACTION_ID = (
    "transition_detail_to_apply_entry_0123456789abcdef0123456789abcdef"
)


def _reviewed_asset(asset_id: str = "portfolio.seek") -> dict[str, object]:
    asset = deepcopy(_reviewed_asset_fixture())
    asset["asset_id"] = asset_id
    return asset


def _workflow(
    asset_id: str = "portfolio.seek",
    *,
    asset: dict[str, object] | None = None,
) -> dict[str, object]:
    asset = asset or _reviewed_asset(asset_id)
    return {
        "workflow_id": asset_id,
        "asset_id": asset_id,
        "asset_content_sha256": content_sha256(asset),
        "source_workflow_sha256": asset["source_review_lineage"]["source_workflow_sha256"],
        "reviewed_revision_hash": asset["source_review_lineage"]["reviewed_revision_hash"],
    }


def _observation(
    *,
    workflow: dict[str, object] | None = None,
    semantic_action: str = "open_apply_flow",
):
    action_requires_confirmation = semantic_action == "open_apply_flow"
    return validate_agent_observation_v1(
        {
            "contract_version": "agent_observation_v1",
            "observation_id": "observation.initial",
            "session_id": "session.initial",
            "workflow": workflow or _workflow(),
            "application": {
                "identity_ref": "application:web:nz.seek.com",
                "kind": "web",
                "display_name": "nz.seek.com",
            },
            "state_resolution_ref": "state-resolution:initial",
            "current_capture": {
                "capture_id": "capture.initial",
                "screenshot_sha256": "d" * 64,
                "evidence_ref": "capture:initial",
            },
            "state": {
                "status": "matched",
                "state_id": "job-detail",
                "state_availability": "reviewed",
                "resolution_sha256": "e" * 64,
                "source_interface_id": "interface.job-detail",
                "display_name": "Job Detail",
                "surface_type": "web_page",
                "responsibility": "Open the reviewed application entry.",
            },
            "semantic_facts": [],
            "evidence_refs": ["state-resolution:initial", "capture:initial"],
            "blockers": [],
            "available_actions": [
                {
                    "action_id": OPAQUE_APPLY_ACTION_ID,
                    "semantic_action": semantic_action,
                    "description": "Open the reviewed application entry.",
                    "target_state_id": "apply-entry",
                    "expected_effect": "Reach the reviewed application entry.",
                    "verification_rule_refs": ["workflow-rule:apply-entry"],
                    "risk_level": "medium" if action_requires_confirmation else "low",
                    "requires_user_confirmation": action_requires_confirmation,
                },
                {
                    "action_id": "runtime.safe_stop",
                    "semantic_action": "safe_stop",
                    "description": "Stop without dispatch.",
                    "target_state_id": None,
                    "expected_effect": "Stop without dispatch.",
                    "verification_rule_refs": [],
                    "risk_level": "low",
                    "requires_user_confirmation": False,
                },
            ],
            "safe_stop": {"required": False, "reason_code": "none"},
            "artifact_is_authorization": False,
        }
    )


def _receipt(intent: AgentIntentV1) -> RuntimeResultReceiptV1:
    return RuntimeResultReceiptV1.model_validate(
        {
            "contract_version": "runtime_result_receipt_v1",
            "receipt_id": f"receipt.{intent.intent_id}",
            "issued_at": "2026-08-22T01:02:03Z",
            "session_id": intent.session_id,
            "observation_id": intent.observation_id,
            "intent_id": intent.intent_id,
            "workflow": intent.workflow.model_dump(mode="json"),
            "action": {
                "action_id": intent.action_id,
                "semantic_action": "open_apply_flow",
            },
            "outcome": "VERIFIED",
            "reason_code": "none",
            "attempt_count": 1,
            "gate_status": "allowed",
            "dispatch_status": "dispatched",
            "effect_status": "verified",
            "destination_status": "verified",
            "evidence": {
                "state_resolution_ref": "state-resolution:initial",
                "selection_ref": "selection:verified",
                "candidate_ref": "candidate:verified",
                "gate_decision_ref": "gate:verified",
                "backend_receipt_ref": "backend-receipt:verified",
                "verification_ref": "verification:verified",
                "trace_refs": ["trace:verified"],
            },
            "next_observation_id": "observation.apply-entry",
            "safe_stop": {"required": False, "reason_code": "none"},
            "artifact_is_authorization": False,
        }
    )


@dataclass
class _Claim:
    phase: str
    observation: Any
    intent: AgentIntentV1
    server_binding: Any
    confirmation: Any = None


class _Claims:
    def __init__(self) -> None:
        self.claim: _Claim | None = None
        self.corrupt = False

    def list_unresolved_claims(self):
        if self.corrupt:
            raise RuntimeIntentClaimStoreError("tampered claim")
        if self.claim is None or self.claim.phase in {"terminal", "confirmation_denied", "confirmation_closed"}:
            return ()
        return (self.claim,)

    def find_for_observation(self, *, session_id: str, observation_id: str):
        claim = self.claim
        if claim is None:
            return None
        if claim.observation.session_id != session_id or claim.observation.observation_id != observation_id:
            return None
        return claim

    def get_for_confirmation(self, *, confirmation_id: str):
        claim = self.claim
        if claim is None or claim.confirmation is None or claim.confirmation.confirmation_id != confirmation_id:
            raise RuntimeIntentClaimStoreError("confirmation request not found")
        return claim

    def record_confirmation_decision(self, *, confirmation_id: str, decision: str):
        claim = self.get_for_confirmation(confirmation_id=confirmation_id)
        existing = claim.confirmation.decision
        if existing is not None and existing != decision:
            raise RuntimeIntentClaimStoreError("confirmation decision conflict")
        claim.confirmation.decision = decision
        claim.phase = (
            "confirmation_approved" if decision == "approved" else "confirmation_denied"
        )
        return claim

    def load_terminal_receipt(self, *, session_id: str, observation_id: str):
        claim = self.find_for_observation(
            session_id=session_id,
            observation_id=observation_id,
        )
        if claim is None or claim.phase != "terminal":
            raise RuntimeIntentClaimStoreError("terminal receipt not found")
        return _receipt(claim.intent)


class _Assets:
    def __init__(self, count: int = 1) -> None:
        self.assets = {
            f"portfolio.seek{index if count > 1 else ''}": _reviewed_asset(
                f"portfolio.seek{index if count > 1 else ''}"
            )
            for index in range(count)
        }
        self.active = {
            asset_id: content_sha256(asset) for asset_id, asset in self.assets.items()
        }
        self.load_count = 0

    def registry(self):
        return {"active_by_asset": dict(self.active)}

    def load_active(self, asset_id: str):
        self.load_count += 1
        return deepcopy(self.assets[asset_id])


class _WindowManager:
    def __init__(self, *, present: bool = True, active: bool = True, pid: int | None = 1234) -> None:
        self.bound = (
            SimpleNamespace(handle=77, process_id=pid, is_active=active)
            if present
            else None
        )

    def get_bound_window(self):
        return self.bound


class _Controller:
    def __init__(
        self,
        claims: _Claims,
        *,
        requires_confirmation: bool,
        workflow: dict[str, object],
        semantic_action: str = "open_apply_flow",
    ) -> None:
        self.claims = claims
        self.observation = _observation(
            workflow=workflow,
            semantic_action=semantic_action,
        )
        self.requires_confirmation = requires_confirmation
        self.submissions: list[dict[str, object]] = []
        self.attempts = 0
        self.decisions: dict[str, str] = {}

    def start_session(self):
        return LiveSessionSnapshot(
            session_id=self.observation.session_id,
            workflow=self.observation.workflow,
            current_observation=self.observation,
            target_window_handle=77,
        )

    def submit_intent(self, payload):
        self.submissions.append(dict(payload))
        intent = AgentIntentV1.model_validate(payload)
        if self.claims.claim is None:
            confirmation = (
                SimpleNamespace(
                    confirmation_id="confirmation." + "a" * 64,
                    target_process_id=1234,
                    decision=None,
                    closed_reason_code=None,
                )
                if self.requires_confirmation
                else None
            )
            self.claims.claim = _Claim(
                phase="confirmation_pending" if confirmation else "claimed",
                observation=self.observation,
                intent=intent,
                server_binding=SimpleNamespace(
                    to_dict=lambda: {
                        "workflow_id": "portfolio.seek",
                        "asset_id": "portfolio.seek",
                        "application_identity_key": "web:nz.seek.com",
                        "target_window_handle": 77,
                    }
                ),
                confirmation=confirmation,
            )
        if self.claims.claim.phase == "terminal":
            return _receipt(self.claims.claim.intent)
        if self.claims.claim.phase == "confirmation_pending":
            return LiveControllerDecision(
                "CONFIRMATION_REQUIRED",
                "human_confirmation_required",
                self.claims.claim.confirmation.confirmation_id,
            )
        if self.claims.claim.phase == "confirmation_denied":
            return LiveControllerDecision(
                "REJECTED",
                "confirmation_denied",
                self.claims.claim.confirmation.confirmation_id,
            )
        self.attempts += 1
        self.claims.claim.phase = "terminal"
        return _receipt(intent)

    def record_confirmation_decision(self, *, confirmation_id: str, decision: str):
        claim = self.claims.get_for_confirmation(confirmation_id=confirmation_id)
        existing = self.decisions.get(confirmation_id) or claim.confirmation.decision
        if existing is not None and existing != decision:
            return LiveControllerDecision(
                "REJECTED", "confirmation_decision_conflict", confirmation_id
            )
        self.decisions[confirmation_id] = decision
        claim.confirmation.decision = decision
        if decision == "denied":
            claim.phase = "confirmation_denied"
            return LiveControllerDecision("REJECTED", "confirmation_denied", confirmation_id)
        if claim.phase != "terminal":
            claim.phase = "confirmation_approved"
        return LiveControllerDecision("APPROVED", "confirmation_approved", confirmation_id)


def _factory(
    *,
    assets: _Assets,
    requires_confirmation: bool = False,
    workflow: dict[str, object] | None = None,
    semantic_action: str = "open_apply_flow",
):
    claims = _Claims()
    controllers: list[_Controller] = []
    bindings: list[ServerWorkflowBinding] = []

    def build(binding: ServerWorkflowBinding):
        bindings.append(binding)
        controller = _Controller(
            claims,
            requires_confirmation=requires_confirmation,
            workflow=workflow or _workflow(asset=assets.assets[binding.asset_id]),
            semantic_action=semantic_action,
        )
        controllers.append(controller)
        return controller

    return claims, controllers, bindings, build


def _callsite(
    *,
    requires_confirmation: bool = False,
    assets: _Assets | None = None,
    windows: _WindowManager | None = None,
    workflow: dict[str, object] | None = None,
    semantic_action: str = "open_apply_flow",
):
    assets = assets or _Assets()
    claims, controllers, bindings, build = _factory(
        assets=assets,
        requires_confirmation=requires_confirmation,
        workflow=workflow,
        semantic_action=semantic_action,
    )
    service = LocalAgentRuntimeCallsite(
        project_root=Path("."),
        asset_store=assets,
        window_manager=windows or _WindowManager(),
        claim_store=claims,
        controller_factory=build,
    )
    return service, claims, controllers, bindings


def _app(service: LocalAgentRuntimeCallsite) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_agent_runtime_callsite] = lambda: service
    return app


def _client(service: LocalAgentRuntimeCallsite, host: str = "127.0.0.1") -> TestClient:
    return TestClient(_app(service), client=(host, 50000))


def _start(client: TestClient):
    response = client.post("/runtime/agent/session/start", json={})
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _intent_payload() -> dict[str, str]:
    return {
        "intent_id": "intent.open-apply",
        "session_id": "session.initial",
        "observation_id": "observation.initial",
        "action_id": OPAQUE_APPLY_ACTION_ID,
    }


def test_routes_are_registered() -> None:
    service, _, _, _ = _callsite()
    paths = {route.path for route in _app(service).routes}
    assert {
        "/runtime/agent/session/start",
        "/runtime/agent/intent/submit",
        "/runtime/agent/confirmation/decide",
    }.issubset(paths)


def test_routes_are_registered_on_main_app() -> None:
    from app.main import app

    paths = {route.path for route in app.routes}
    assert "/runtime/agent/session/start" in paths
    assert "/runtime/agent/intent/submit" in paths
    assert "/runtime/agent/confirmation/decide" in paths


@pytest.mark.parametrize(
    "field,value",
    [
        ("asset_id", "client.asset"),
        ("path", "C:/unsafe.json"),
        ("backend", "fake"),
        ("target_window_handle", 77),
        ("target_process_id", 1234),
        ("click_point", [10, 20]),
    ],
)
def test_start_rejects_client_binding_injection(field: str, value: object) -> None:
    service, _, controllers, _ = _callsite()
    response = _client(service).post(
        "/runtime/agent/session/start", json={field: value}
    )
    assert response.status_code == 422
    assert controllers == []


def test_start_requires_exactly_one_asset_and_active_positive_pid_window() -> None:
    cases = [
        (_Assets(0), _WindowManager(), "agent_runtime_no_active_asset"),
        (_Assets(2), _WindowManager(), "agent_runtime_active_asset_ambiguous"),
        (_Assets(), _WindowManager(present=False), "agent_runtime_bound_window_required"),
        (_Assets(), _WindowManager(active=False), "agent_runtime_bound_window_inactive"),
        (_Assets(), _WindowManager(pid=0), "agent_runtime_bound_window_invalid"),
    ]
    for assets, windows, code in cases:
        service, _, controllers, _ = _callsite(assets=assets, windows=windows)
        response = _client(service).post("/runtime/agent/session/start", json={})
        assert response.status_code == 412
        assert response.json()["error"]["code"] == code
        assert controllers == []


def test_start_uses_server_binding_and_second_start_conflicts() -> None:
    service, _, _, bindings = _callsite()
    observation = _start(_client(service))
    assert observation["contract_version"] == "agent_observation_v1"
    assert observation["available_actions"][0]["action_id"] == OPAQUE_APPLY_ACTION_ID
    assert observation["available_actions"][0]["semantic_action"] == "open_apply_flow"
    assert bindings == [
        ServerWorkflowBinding(
            workflow_id="portfolio.seek",
            asset_id="portfolio.seek",
            application_identity_key="web:nz.seek.com",
            target_window_handle=77,
        )
    ]
    second = _client(service).post("/runtime/agent/session/start", json={})
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "agent_runtime_session_active"


def test_start_rejects_controller_forged_workflow_hashes() -> None:
    assets = _Assets()
    forged = _workflow(asset=assets.assets["portfolio.seek"])
    forged.update(
        {
            "asset_content_sha256": "9" * 64,
            "source_workflow_sha256": "8" * 64,
            "reviewed_revision_hash": "7" * 64,
        }
    )
    service, _, controllers, _ = _callsite(assets=assets, workflow=forged)
    response = _client(service).post("/runtime/agent/session/start", json={})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "agent_runtime_recovery_required"
    assert len(controllers) == 1


def test_start_fails_closed_when_active_asset_republishes_during_start() -> None:
    assets = _Assets()
    original_workflow = _workflow(asset=assets.assets["portfolio.seek"])
    claims = _Claims()
    controllers: list[_Controller] = []

    def republishing_factory(binding: ServerWorkflowBinding):
        controller = _Controller(
            claims,
            requires_confirmation=False,
            workflow=original_workflow,
        )
        controllers.append(controller)
        replacement = deepcopy(assets.assets[binding.asset_id])
        replacement["source_review_lineage"]["current_revision_hash"] = "9" * 64
        replacement["source_review_lineage"]["reviewed_revision_hash"] = "9" * 64
        assets.assets[binding.asset_id] = replacement
        assets.active[binding.asset_id] = content_sha256(replacement)
        return controller

    service = LocalAgentRuntimeCallsite(
        project_root=Path("."),
        asset_store=assets,
        window_manager=_WindowManager(),
        claim_store=claims,
        controller_factory=republishing_factory,
    )
    response = _client(service).post("/runtime/agent/session/start", json={})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "agent_runtime_recovery_required"
    assert len(controllers) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("workflow", _workflow()),
        ("asset_content_sha256", "a" * 64),
        ("reviewed_revision_hash", "c" * 64),
        ("semantic_action", "open_apply_flow"),
        ("evidence_refs", ["client:evidence"]),
        ("authority", "client"),
        ("click_point", [10, 20]),
        ("target_window_handle", 77),
        ("backend", "fake"),
    ],
)
def test_intent_rejects_authority_and_binding_injection(field: str, value: object) -> None:
    service, _, controllers, _ = _callsite()
    client = _client(service)
    _start(client)
    response = client.post(
        "/runtime/agent/intent/submit", json={**_intent_payload(), field: value}
    )
    assert response.status_code == 422
    assert controllers[0].submissions == []


def test_terminal_intent_is_server_completed_and_duplicate_does_not_redispatch() -> None:
    windows = _WindowManager()
    service, _, controllers, _ = _callsite(windows=windows)
    client = _client(service)
    observation = _start(client)
    first = client.post("/runtime/agent/intent/submit", json=_intent_payload())
    windows.bound = None
    second = client.post("/runtime/agent/intent/submit", json=_intent_payload())
    assert first.status_code == second.status_code == 200
    assert first.json()["data"] == second.json()["data"]
    assert controllers[0].submissions[0]["workflow"] == observation["workflow"]
    assert sum(controller.attempts for controller in controllers) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("session_id", "session.wrong"),
        ("observation_id", "observation.wrong"),
        ("action_id", "transition_unknown_0123456789abcdef"),
    ],
)
def test_wrong_intent_identity_is_rejected_without_consuming(field: str, value: str) -> None:
    service, _, controllers, _ = _callsite()
    client = _client(service)
    _start(client)
    rejected = client.post(
        "/runtime/agent/intent/submit", json={**_intent_payload(), field: value}
    )
    assert rejected.status_code == 409
    assert controllers[0].submissions == []
    accepted = client.post("/runtime/agent/intent/submit", json=_intent_payload())
    assert accepted.status_code == 200


def test_intent_requires_open_apply_flow_semantic_action_not_only_matching_id() -> None:
    service, _, controllers, _ = _callsite(semantic_action="open_detail")
    client = _client(service)
    _start(client)
    response = client.post("/runtime/agent/intent/submit", json=_intent_payload())
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "agent_runtime_invalid_intent"
    assert controllers[0].submissions == []


def test_confirmation_deny_is_idempotent_conflicting_decision_is_rejected_and_never_dispatches() -> None:
    windows = _WindowManager()
    service, _, controllers, _ = _callsite(
        requires_confirmation=True,
        windows=windows,
    )
    client = _client(service)
    _start(client)
    pending = client.post("/runtime/agent/intent/submit", json=_intent_payload())
    assert pending.json()["data"]["status"] == "NEEDS_REVIEW"
    confirmation_id = pending.json()["data"]["confirmation_id"]
    denied = {"confirmation_id": confirmation_id, "decision": "denied"}
    first = client.post("/runtime/agent/confirmation/decide", json=denied)
    windows.bound = None
    second = client.post("/runtime/agent/confirmation/decide", json=denied)
    conflict = client.post(
        "/runtime/agent/confirmation/decide",
        json={"confirmation_id": confirmation_id, "decision": "approved"},
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["data"] == second.json()["data"]
    assert conflict.status_code == 409
    assert sum(controller.attempts for controller in controllers) == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("intent", _intent_payload()),
        ("session_id", "session.initial"),
        ("asset_id", "portfolio.seek"),
        ("evidence_ref", "client:evidence"),
        ("target_window_handle", 77),
    ],
)
def test_confirmation_rejects_client_intent_and_binding_fields(
    field: str,
    value: object,
) -> None:
    service, _, controllers, _ = _callsite(requires_confirmation=True)
    client = _client(service)
    _start(client)
    pending = client.post("/runtime/agent/intent/submit", json=_intent_payload()).json()["data"]
    response = client.post(
        "/runtime/agent/confirmation/decide",
        json={
            "confirmation_id": pending["confirmation_id"],
            "decision": "approved",
            field: value,
        },
    )
    assert response.status_code == 422
    assert sum(controller.attempts for controller in controllers) == 0
    assert client.post("/runtime/agent/session/start", json={}).status_code == 409


def test_confirmation_process_drift_fails_closed_without_dispatch() -> None:
    windows = _WindowManager()
    service, _, controllers, _ = _callsite(
        requires_confirmation=True,
        windows=windows,
    )
    client = _client(service)
    _start(client)
    pending = client.post("/runtime/agent/intent/submit", json=_intent_payload()).json()["data"]
    windows.bound.process_id = 4321
    response = client.post(
        "/runtime/agent/confirmation/decide",
        json={"confirmation_id": pending["confirmation_id"], "decision": "approved"},
    )
    assert response.status_code == 412
    assert response.json()["error"]["code"] == "agent_runtime_binding_mismatch"
    assert sum(controller.attempts for controller in controllers) == 0


def test_first_denial_remains_recordable_after_bound_window_disappears() -> None:
    windows = _WindowManager()
    service, claims, controllers, _ = _callsite(
        requires_confirmation=True,
        windows=windows,
    )
    client = _client(service)
    _start(client)
    pending = client.post("/runtime/agent/intent/submit", json=_intent_payload()).json()["data"]
    windows.bound = None
    response = client.post(
        "/runtime/agent/confirmation/decide",
        json={"confirmation_id": pending["confirmation_id"], "decision": "denied"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["reason_code"] == "confirmation_denied"
    assert claims.claim.phase == "confirmation_denied"
    assert sum(controller.attempts for controller in controllers) == 0


@pytest.mark.parametrize("seconds_after_expiry", [0, 17])
def test_first_and_repeated_denial_at_or_after_expiry_are_stable_without_runtime_dependencies(
    tmp_path: Path,
    seconds_after_expiry: int,
) -> None:
    now = [datetime(2026, 8, 22, 1, 2, 3, tzinfo=timezone.utc)]
    store = RuntimeIntentClaimStore(
        project_root=tmp_path,
        receipt_store=RuntimeReceiptStore(project_root=tmp_path),
        clock=lambda: now[0],
    )
    store.claim(
        observation=_confirmation_observation(),
        intent=_confirmation_intent(),
        server_binding=_confirmation_binding(),
    )
    pending = store.mark_confirmation_pending(**_confirmation_request_inputs())
    confirmation_id = pending.confirmation.confirmation_id
    now[0] += timedelta(minutes=5, seconds=seconds_after_expiry)

    class _ForbiddenDependency:
        def __getattr__(self, name):
            raise AssertionError(f"runtime dependency must not be used for denial: {name}")

    def forbidden_controller(_binding):
        raise AssertionError("controller must not be constructed for denial")

    service = LocalAgentRuntimeCallsite(
        project_root=tmp_path,
        asset_store=_ForbiddenDependency(),
        window_manager=_ForbiddenDependency(),
        claim_store=store,
        controller_factory=forbidden_controller,
    )
    client = _client(service)
    payload = {"confirmation_id": confirmation_id, "decision": "denied"}
    first = client.post("/runtime/agent/confirmation/decide", json=payload)
    repeated = client.post("/runtime/agent/confirmation/decide", json=payload)

    assert first.status_code == repeated.status_code == 200
    assert first.json()["data"] == repeated.json()["data"]
    assert first.json()["data"] == {
        "status": "REJECTED",
        "reason_code": "confirmation_expired",
        "confirmation_id": confirmation_id,
    }
    assert store.list_unresolved_claims() == ()


def test_confirmation_approve_uses_persisted_exact_intent_once() -> None:
    windows = _WindowManager()
    service, claims, controllers, _ = _callsite(
        requires_confirmation=True,
        windows=windows,
    )
    client = _client(service)
    _start(client)
    pending = client.post("/runtime/agent/intent/submit", json=_intent_payload())
    confirmation_id = pending.json()["data"]["confirmation_id"]
    persisted = claims.claim.intent.model_dump(mode="json")
    approved = client.post(
        "/runtime/agent/confirmation/decide",
        json={"confirmation_id": confirmation_id, "decision": "approved"},
    )
    windows.bound = None
    repeated = client.post(
        "/runtime/agent/confirmation/decide",
        json={"confirmation_id": confirmation_id, "decision": "approved"},
    )
    assert approved.status_code == repeated.status_code == 200
    assert approved.json()["data"] == repeated.json()["data"]
    assert controllers[0].submissions[-1] == persisted
    assert sum(controller.attempts for controller in controllers) == 1


def test_restart_blocks_new_start_but_recovers_confirmation_from_persisted_claim() -> None:
    first, claims, controllers, _ = _callsite(requires_confirmation=True)
    client = _client(first)
    _start(client)
    pending = client.post("/runtime/agent/intent/submit", json=_intent_payload()).json()["data"]

    recovered_controllers: list[_Controller] = []
    recovered_assets = _Assets()

    def recovered_factory(binding: ServerWorkflowBinding):
        controller = _Controller(
            claims,
            requires_confirmation=True,
            workflow=_workflow(asset=recovered_assets.assets[binding.asset_id]),
        )
        recovered_controllers.append(controller)
        return controller

    restarted = LocalAgentRuntimeCallsite(
        project_root=Path("."),
        asset_store=recovered_assets,
        window_manager=_WindowManager(),
        claim_store=claims,
        controller_factory=recovered_factory,
    )
    restarted_client = _client(restarted)
    blocked = restarted_client.post("/runtime/agent/session/start", json={})
    assert blocked.status_code == 412
    assert blocked.json()["error"]["code"] == "agent_runtime_unresolved_claim_exists"
    approved = restarted_client.post(
        "/runtime/agent/confirmation/decide",
        json={"confirmation_id": pending["confirmation_id"], "decision": "approved"},
    )
    assert approved.status_code == 200
    assert recovered_controllers[0].submissions == [claims.claim.intent.model_dump(mode="json")]
    assert sum(item.attempts for item in controllers + recovered_controllers) == 1


def test_opaque_reviewed_transition_id_is_accepted_and_preserved_through_restart_approval() -> None:
    action_id = OPAQUE_APPLY_ACTION_ID
    assets = _Assets()
    workflow = _workflow(asset=assets.assets["portfolio.seek"])
    payload = _observation(workflow=workflow).model_dump(mode="json")
    payload["available_actions"][0]["action_id"] = action_id
    observation = validate_agent_observation_v1(payload)
    claims = _Claims()
    controllers: list[_Controller] = []

    def controller_factory(_binding: ServerWorkflowBinding):
        controller = _Controller(
            claims,
            requires_confirmation=True,
            workflow=workflow,
        )
        controller.observation = observation
        controllers.append(controller)
        return controller

    first = LocalAgentRuntimeCallsite(
        project_root=Path("."),
        asset_store=assets,
        window_manager=_WindowManager(),
        claim_store=claims,
        controller_factory=controller_factory,
    )
    first_client = _client(first)
    _start(first_client)
    intent_payload = {
        "intent_id": "intent.opaque-transition",
        "session_id": observation.session_id,
        "observation_id": observation.observation_id,
        "action_id": action_id,
    }
    pending = first_client.post(
        "/runtime/agent/intent/submit",
        json=intent_payload,
    )
    assert pending.status_code == 200
    assert pending.json()["data"]["status"] == "NEEDS_REVIEW"
    assert claims.claim.intent.action_id == action_id

    restarted = LocalAgentRuntimeCallsite(
        project_root=Path("."),
        asset_store=assets,
        window_manager=_WindowManager(),
        claim_store=claims,
        controller_factory=controller_factory,
    )
    approved = _client(restarted).post(
        "/runtime/agent/confirmation/decide",
        json={
            "confirmation_id": pending.json()["data"]["confirmation_id"],
            "decision": "approved",
        },
    )
    assert approved.status_code == 200
    assert approved.json()["data"]["action"]["action_id"] == action_id
    assert sum(controller.attempts for controller in controllers) == 1


def test_restart_confirmation_approve_rejects_persisted_semantic_action_bypass_before_runtime_dependencies() -> None:
    assets = _Assets()
    observation = _observation(
        workflow=_workflow(asset=assets.assets["portfolio.seek"]),
        semantic_action="open_detail",
    )
    intent = AgentIntentV1.model_validate(
        {
            "contract_version": "agent_intent_v1",
            "intent_id": "intent.semantic-bypass",
            "session_id": observation.session_id,
            "observation_id": observation.observation_id,
            "workflow": observation.workflow.model_dump(mode="json"),
            "action_id": OPAQUE_APPLY_ACTION_ID,
        }
    )
    confirmation_id = "confirmation." + "b" * 64
    claims = _Claims()
    claims.claim = _Claim(
        phase="confirmation_pending",
        observation=observation,
        intent=intent,
        server_binding=SimpleNamespace(
            to_dict=lambda: {
                "workflow_id": "portfolio.seek",
                "asset_id": "portfolio.seek",
                "application_identity_key": "web:nz.seek.com",
                "target_window_handle": 77,
            }
        ),
        confirmation=SimpleNamespace(
            confirmation_id=confirmation_id,
            target_process_id=1234,
            decision=None,
            closed_reason_code=None,
        ),
    )

    class _ForbiddenRuntimeDependency:
        def __getattr__(self, name):
            raise AssertionError(f"runtime dependency must not be used: {name}")

    controller_calls: list[ServerWorkflowBinding] = []

    def forbidden_controller(binding: ServerWorkflowBinding):
        controller_calls.append(binding)
        raise AssertionError("controller must not be constructed")

    service = LocalAgentRuntimeCallsite(
        project_root=Path("."),
        asset_store=_ForbiddenRuntimeDependency(),
        window_manager=_ForbiddenRuntimeDependency(),
        claim_store=claims,
        controller_factory=forbidden_controller,
    )
    response = _client(service).post(
        "/runtime/agent/confirmation/decide",
        json={"confirmation_id": confirmation_id, "decision": "approved"},
    )
    submit_response = _client(service).post(
        "/runtime/agent/intent/submit",
        json={
            "intent_id": intent.intent_id,
            "session_id": intent.session_id,
            "observation_id": intent.observation_id,
            "action_id": intent.action_id,
        },
    )

    assert response.status_code in {409, 412}
    assert response.json()["error"]["code"] in {
        "agent_runtime_invalid_intent",
        "agent_runtime_binding_mismatch",
    }
    assert submit_response.status_code == 412
    assert submit_response.json()["error"]["code"] == "agent_runtime_binding_mismatch"
    assert controller_calls == []
    assert claims.claim.phase == "confirmation_pending"
    assert claims.claim.confirmation.decision is None


def test_loopback_guard_ignores_forwarded_headers() -> None:
    service, _, controllers, _ = _callsite()
    response = _client(service, host="203.0.113.10").post(
        "/runtime/agent/session/start",
        json={},
        headers={"X-Forwarded-For": "127.0.0.1"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "agent_runtime_loopback_required"
    assert controllers == []


def test_errors_are_sanitized() -> None:
    service, _, _, _ = _callsite(assets=_Assets(2))
    response = _client(service).post("/runtime/agent/session/start", json={})
    serialized = response.text
    assert "C:/" not in serialized
    assert "target_window_handle" not in serialized
    assert "nz.seek.com" not in serialized


def test_controller_failure_is_sanitized_and_holds_active_slot() -> None:
    service, _, controllers, _ = _callsite()
    app = _app(service)
    with TestClient(
        app,
        client=("127.0.0.1", 50000),
        raise_server_exceptions=False,
    ) as client:
        _start(client)

        def fail(_payload):
            raise RuntimeError("C:/private/backend-secret")

        controllers[0].submit_intent = fail
        response = client.post("/runtime/agent/intent/submit", json=_intent_payload())
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "agent_runtime_recovery_required"
        assert "backend-secret" not in response.text
        blocked = client.post("/runtime/agent/session/start", json={})
        assert blocked.status_code == 409


def test_default_production_factory_can_be_replaced_without_physical_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claims = _Claims()
    created: list[ServerWorkflowBinding] = []
    assets = _Assets()

    def fake_composition(project_root, binding):
        created.append(binding)
        return _Controller(
            claims,
            requires_confirmation=False,
            workflow=_workflow(asset=assets.assets[binding.asset_id]),
        )

    monkeypatch.setattr(
        "app.api.agent_runtime.build_existing_windows_live_controller",
        fake_composition,
    )
    service = LocalAgentRuntimeCallsite(
        project_root=Path("."),
        asset_store=assets,
        window_manager=_WindowManager(),
        claim_store=claims,
    )
    assert _client(service).post("/runtime/agent/session/start", json={}).status_code == 200
    assert len(created) == 1


def test_list_unresolved_claims_empty_and_corruption_fails_closed(tmp_path: Path) -> None:
    store = RuntimeIntentClaimStore(
        project_root=tmp_path,
        receipt_store=RuntimeReceiptStore(project_root=tmp_path),
    )
    assert store.list_unresolved_claims() == ()
    observation = _observation()
    intent = AgentIntentV1.model_validate(
        {
            "contract_version": "agent_intent_v1",
            "intent_id": "intent.persisted",
            "session_id": observation.session_id,
            "observation_id": observation.observation_id,
            "workflow": observation.workflow.model_dump(mode="json"),
            "action_id": OPAQUE_APPLY_ACTION_ID,
        }
    )
    store.claim(
        observation=observation,
        intent=intent,
        server_binding={
            "workflow_id": "portfolio.seek",
            "asset_id": "portfolio.seek",
            "application_identity_key": "web:nz.seek.com",
            "target_window_handle": 77,
        },
    )
    unresolved = store.list_unresolved_claims()
    assert len(unresolved) == 1
    assert unresolved[0].phase == "claimed"
    (store.claims_root / ("a" * 64 + ".json")).write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeIntentClaimStoreError):
        store.list_unresolved_claims()
