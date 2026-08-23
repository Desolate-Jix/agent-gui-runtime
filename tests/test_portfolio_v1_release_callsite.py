from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from app.agent.desktop_backend import DeterministicFakeBackend
from app.agent.live_runtime_composition import ExistingWindowsCurrentEvidenceAdapter
from app.agent.reviewed_workflow_asset import (
    ReviewedWorkflowAssetStore,
    content_sha256,
    validate_reviewed_workflow_asset,
)
from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
from app.agent.runtime_receipt_store import RuntimeReceiptStore
from app.api.agent_runtime import (
    LocalAgentRuntimeCallsite,
    get_agent_runtime_callsite,
    router as agent_runtime_router,
)
from app.learn.interface_workflow_review import load_interface_workflow_agent_context
from app.operation.page_structure.schemas import (
    InteractionPolicy,
    PageElement,
    VerificationHints,
)
from app.operation.recognition.schemas import (
    CandidateRankResult,
    LocalGroundingCandidateResult,
    LocalGroundingResult,
    RecognitionCandidate,
    ScoreBreakdown,
)
from app.vision.schemas import BBox


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "portfolio_v1_release_callsite"
ASSET_ID = "workflow_portfolio_v1_seek_apply_entry_fe297b5738f8c17790429e925ceab6f0"
ASSET_SHA256 = "a9eb42d9439568770735f69ff109e6d93b86085507414d62ee49cfef33bb1d1b"
SOURCE_WORKFLOW_ID = "portfolio_v1_seek_apply_entry"
SOURCE_WORKFLOW_SHA256 = "9ca9de68ae7a6dcd9f18c10384f2cefb63b6d83648ea10a95e1c5ef9c4283968"
SOURCE_SCREENSHOT_SHA256 = "274658095317e1aed1a9a68d6a3e7a80a6edddcde2e3d94bb11937932258ff1b"
HUMAN_REVIEW_OVERLAY_SHA256 = "27478cff6c05724a6e5929c7b725764d79f2c5864ecf9c7d61bef503fac877cb"
EXPECTED_RELEASE_MANIFEST: dict[str, Any] = {
    "contract_version": "portfolio_v1_release_callsite_fixture_v1",
    "asset_id": ASSET_ID,
    "asset_content_sha256": ASSET_SHA256,
    "source_workflow_id": SOURCE_WORKFLOW_ID,
    "source_workflow_sha256": SOURCE_WORKFLOW_SHA256,
    "reviewed_revision_hash": (
        "8e512cb94091ad8fd1c67afeba55ff68477c542da28de9da8f05de6416ce4ed7"
    ),
    "current_revision_hash": (
        "8e512cb94091ad8fd1c67afeba55ff68477c542da28de9da8f05de6416ce4ed7"
    ),
    "evidence_sha256": (
        "a201d537ebba727167bc0005e1a246213a5b6aa4a105fdbfb2ea011078a41fab"
    ),
    "job_detail_node_revision_hash": (
        "4d58e3774612275359a5627753e159697b036c66c614103d272b44c7612432c1"
    ),
    "source_screenshot_sha256": SOURCE_SCREENSHOT_SHA256,
    "human_review_overlay_sha256": HUMAN_REVIEW_OVERLAY_SHA256,
    "application_identity_key": "web:nz.seek.com",
    "canonical_origin": "https://nz.seek.com",
    "application_identity": {
        "contract_version": "application_identity_v1",
        "identity_schema_version": 1,
        "kind": "web",
        "identity_key": "web:nz.seek.com",
        "identity_status": "resolved",
        "name": "nz.seek.com",
        "display_name": "nz.seek.com",
        "canonical_domain": "nz.seek.com",
        "canonical_origin": "https://nz.seek.com",
        "executable_identity": None,
        "product_identity": None,
        "source_evidence": {
            "url_or_domain_provided": True,
            "browser_process_detected": False,
        },
        "artifact_is_authorization": False,
    },
    "human_approved_node_ids": ["job_detail"],
    "reviewed_state_source_node_id": "job_detail",
    "stop_boundary_source_node_id": "apply_entry",
    "semantic_action": "open_apply_flow",
    "requires_user_confirmation": True,
    "artifact_is_authorization": False,
    "execute_binding_enabled": False,
    "fixture_is_live_proof": False,
}


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    assert isinstance(value, dict)
    return value


def _validate_release_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    assert manifest == EXPECTED_RELEASE_MANIFEST
    return manifest


def _load_release_fixture() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    manifest = _validate_release_manifest(_json(FIXTURE_ROOT / "manifest.json"))
    workflow = _json(FIXTURE_ROOT / "reviewed_workflow.json")
    asset = validate_reviewed_workflow_asset(
        _json(FIXTURE_ROOT / "reviewed_workflow_asset_v2.json")
    )
    return manifest, workflow, asset


def _materialized_fixture_path(project_root: Path, declared_path: object) -> Path:
    declared_text = str(declared_path or "").strip()
    assert declared_text
    relative_path = Path(declared_text)
    assert not relative_path.is_absolute()
    resolved = (project_root / relative_path).resolve()
    assert project_root == resolved or project_root in resolved.parents
    return resolved


def _materialize_release_project(
    tmp_path: Path,
) -> tuple[dict[str, Any], ReviewedWorkflowAssetStore]:
    project_root = tmp_path.resolve()
    manifest, workflow, asset = _load_release_fixture()

    materialized_workflow_path = (
        project_root
        / "artifacts"
        / "interface-workflow-reviews"
        / SOURCE_WORKFLOW_ID
        / "reviewed_workflow.json"
    )
    materialized_workflow_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(
        FIXTURE_ROOT / "reviewed_workflow.json",
        materialized_workflow_path,
    )
    assert (
        sha256(materialized_workflow_path.read_bytes()).hexdigest()
        == SOURCE_WORKFLOW_SHA256
    )

    job_detail = next(
        node for node in workflow["nodes"] if node.get("node_id") == "job_detail"
    )
    evidence = job_detail["evidence"]
    for evidence_key in (
        "source_screenshot_path",
        "review_revision_source_screenshot_path",
    ):
        destination = _materialized_fixture_path(
            project_root,
            evidence[evidence_key],
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURE_ROOT / "source_screenshot.png", destination)
        assert sha256(destination.read_bytes()).hexdigest() == SOURCE_SCREENSHOT_SHA256
    for evidence_key in (
        "human_review_overlay_path",
        "review_revision_human_review_overlay_path",
    ):
        destination = _materialized_fixture_path(
            project_root,
            evidence[evidence_key],
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURE_ROOT / "human_review_overlay.png", destination)
        assert (
            sha256(destination.read_bytes()).hexdigest()
            == HUMAN_REVIEW_OVERLAY_SHA256
        )

    normalized_source_paths = [
        str(value or "").strip()
        for value in job_detail["source_paths"]
        if str(value or "").strip()
    ]
    expected_source_paths_sha256 = sha256(
        json.dumps(
            normalized_source_paths,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    registry = {
        "contract_version": "interface_workflow_library_registry_v1",
        "registry_revision": 1,
        "applications": {
            "web:nz.seek.com": {
                "application_identity": deepcopy(manifest["application_identity"]),
                "workflow_ids": [SOURCE_WORKFLOW_ID],
                "artifact_is_authorization": False,
            }
        },
        "workflows": {
            SOURCE_WORKFLOW_ID: {
                "path": str(materialized_workflow_path),
                "application_identity_key": "web:nz.seek.com",
                "goal": workflow["workflow"]["goal"],
                "node_count": 2,
                "edge_count": 1,
                "reviewed_node_revision_hashes": {
                    "job_detail": manifest["job_detail_node_revision_hash"],
                },
                "reviewed_node_evidence_sha256": {
                    "job_detail": {
                        "source_paths_sha256": expected_source_paths_sha256,
                        "human_review_overlay_path": HUMAN_REVIEW_OVERLAY_SHA256,
                        "review_revision_human_review_overlay_path": (
                            HUMAN_REVIEW_OVERLAY_SHA256
                        ),
                        "review_revision_source_screenshot_path": (
                            SOURCE_SCREENSHOT_SHA256
                        ),
                        "source_screenshot_path": SOURCE_SCREENSHOT_SHA256,
                    }
                },
                "source_asset_sha256": SOURCE_WORKFLOW_SHA256,
                "review_status": "needs_human_review",
                "published": False,
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            }
        },
        "artifact_is_authorization": False,
    }
    registry_path = (
        project_root / "artifacts" / "interface-workflow-reviews" / "registry.json"
    )
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_bytes(
        (json.dumps(registry, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )

    asset_before_publish = deepcopy(asset)
    store = ReviewedWorkflowAssetStore(project_root=project_root)
    publish_result = store.publish(asset, expected_registry_revision=0)
    assert publish_result["status"] == "published"
    assert publish_result["object_sha256"] == ASSET_SHA256
    assert publish_result["content_sha256"] == ASSET_SHA256
    assert asset == asset_before_publish
    return asset, store


class _ReleaseWindowManager:
    def __init__(self) -> None:
        self.bound = SimpleNamespace(
            handle=4242,
            process_id=9001,
            is_active=True,
            title="Deterministic release window",
            process_name="release-fixture.exe",
            rect=SimpleNamespace(left=10, top=20, right=330, bottom=220),
        )
        self.bound_window_calls = 0
        self.visibility_checks: list[dict[str, Any]] = []

    def get_bound_window(self) -> object:
        self.bound_window_calls += 1
        return self.bound

    def validate_bound_point_visibility(
        self,
        *,
        bound: object,
        x: int,
        y: int,
    ) -> dict[str, Any]:
        assert bound is self.bound
        click_point = (int(x), int(y))
        self.visibility_checks.append(
            {
                "bound_handle": int(bound.handle),
                "click_point": click_point,
            }
        )
        return {
            "contract_version": "bound_point_visibility_v1",
            "window_point": {"x": click_point[0], "y": click_point[1]},
            "screen_point": {
                "x": int(bound.rect.left) + click_point[0],
                "y": int(bound.rect.top) + click_point[1],
            },
            "bound_window": {
                "handle": int(bound.handle),
                "title": bound.title,
                "process_id": int(bound.process_id),
                "process_name": bound.process_name,
            },
            "allowed": True,
            "reason": "target_point_owned_by_bound_window",
            "hit_window": {
                "handle": int(bound.handle),
                "root_handle": int(bound.handle),
                "root_owner_handle": int(bound.handle),
                "title": bound.title,
                "process_id": int(bound.process_id),
                "process_name": bound.process_name,
            },
        }


class _ReleaseScreenshotSequence:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.colors = [
            (10, 20, 30),
            (20, 30, 40),
            (30, 40, 50),
            (30, 40, 50),
            (60, 70, 80),
        ]
        self.calls: list[dict[str, Any]] = []
        self.paths: list[Path] = []

    def capture_window(self, **kwargs: object) -> dict[str, Any]:
        call_index = len(self.calls)
        assert call_index < len(self.colors), "unexpected runtime capture"
        self.calls.append(dict(kwargs))
        path = self.root / f"portfolio-runtime-capture-{call_index + 1}.png"
        Image.new("RGB", (320, 200), self.colors[call_index]).save(path)
        self.paths.append(path)
        return {
            "image_path": str(path),
            "image_width": 320,
            "image_height": 200,
            "roi": None,
            "roi_adjusted": False,
            "capture_purpose": kwargs.get("purpose"),
            "window_size": {"width": 320, "height": 200},
        }


class _ReleaseOriginReader:
    def __init__(self) -> None:
        self.calls: list[int] = []

    def read_origin(self, target_window_handle: int) -> dict[str, Any]:
        self.calls.append(target_window_handle)
        return {
            "status": "observed",
            "origin": "https://nz.seek.com",
            "target_window_handle": target_window_handle,
            "bound_process_id": 9001,
        }


class _ReleaseUIAProvider:
    def __init__(self) -> None:
        self.calls: list[object] = []

    def snapshot_window(self, bound: object) -> dict[str, Any]:
        self.calls.append(bound)
        return {
            "provider": "windows_uia",
            "provider_version": "windows_uia_provider_v1",
            "status": "ok",
            "window": {
                "handle": 4242,
                "process_id": 9001,
                "bbox": {"x": 0, "y": 0, "w": 320, "h": 200},
            },
            "control_count": 0,
            "controls": [],
        }


def _release_role(kind: str) -> str:
    return {"control": "button", "text": "text", "region": "region"}.get(
        kind,
        kind,
    )


def _release_recognition(anchor: dict[str, Any]) -> dict[str, Any]:
    label = str(anchor["label"])
    anchor_id = str(anchor["anchor_id"])
    candidate_id = f"candidate:{anchor_id}"
    element_id = f"current:{anchor_id}"
    box = BBox(x=40, y=50, w=120, h=40)
    click_point = {"x": 100, "y": 70}
    candidate = RecognitionCandidate(
        candidate_id=candidate_id,
        rank=1,
        element_id=element_id,
        label=label,
        role=_release_role(str(anchor["kind"])),
        text=label,
        score=0.95,
        eligible=True,
        reasons=["exact_release_anchor_current_evidence"],
        score_breakdown=ScoreBreakdown(
            text_similarity=1.0,
            policy_score=1.0,
            role_score=1.0,
            confidence_score=1.0,
            screen_reading_score=0.9,
            state_score=0.0,
        ),
        element=PageElement(
            element_id=element_id,
            label=label,
            role=_release_role(str(anchor["kind"])),
            interaction_type="click",
            description=label,
            text=label,
            bbox=box,
            semantic_bbox=None,
            click_point=click_point,
            click_strategy="center",
            possible_destinations=[],
            verification_hints=VerificationHints(),
            interaction_policy=InteractionPolicy(allowed=True),
            fusion_confidence=0.95,
            coordinate_confidence="high",
            memory_key="",
            sources=["exact_release_anchor_current_evidence"],
        ),
    )
    candidates = CandidateRankResult(
        goal=label,
        top_k=5,
        candidates=[candidate],
        recommended_candidate_id=candidate_id,
        margin_to_second=1.0,
        summary={"source": "exact_release_anchor_current_evidence"},
    )
    local = LocalGroundingResult(
        goal=label,
        results=[
            LocalGroundingCandidateResult(
                candidate_id=candidate_id,
                element_id=element_id,
                status="grounded",
                crop_path=None,
                crop_bbox=box.to_dict(),
                refined_click_point=click_point,
                coordinate_source="current_release_fixture",
                confidence=0.95,
                matched_text=label,
                matched_text_bbox=box.to_dict(),
                reasons=["exact_release_anchor_current_evidence"],
            )
        ],
        recommended_candidate_id=candidate_id,
        summary={"status": "completed"},
    )
    return {
        "contract_version": "recognition_plan_v1",
        "candidate_result": candidates.to_dict(),
        "narrow_search_result": local.to_dict(),
        "pre_click_decision": {
            "allowed": True,
            "selected_click_point": click_point,
        },
    }


def _release_empty_recognition(goal: str) -> dict[str, Any]:
    return {
        "contract_version": "recognition_plan_v1",
        "candidate_result": CandidateRankResult(goal=goal).to_dict(),
        "narrow_search_result": LocalGroundingResult(goal=goal).to_dict(),
        "pre_click_decision": {
            "allowed": True,
            "selected_click_point": {"x": 100, "y": 70},
        },
    }


def _release_state_payloads(
    asset: dict[str, Any],
    *,
    source_node_id: str,
) -> dict[str, dict[str, Any]]:
    state = next(
        item for item in asset["states"] if item["source_node_id"] == source_node_id
    )
    payloads: dict[str, dict[str, Any]] = {}
    for anchor in state["identity_anchors"]:
        payloads.setdefault(str(anchor["label"]), _release_recognition(anchor))
    return payloads


class _ReleaseRecognitionSequence:
    def __init__(self, asset: dict[str, Any]) -> None:
        job_detail = _release_state_payloads(asset, source_node_id="job_detail")
        apply_entry = _release_state_payloads(asset, source_node_id="apply_entry")
        self.payloads_by_capture = [job_detail, job_detail, job_detail, apply_entry]
        self.capture_paths: list[str] = []
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: object) -> dict[str, Any]:
        image_path = str(kwargs.get("image_path") or "")
        if image_path not in self.capture_paths:
            assert len(self.capture_paths) < len(self.payloads_by_capture)
            self.capture_paths.append(image_path)
        capture_index = self.capture_paths.index(image_path)
        self.calls.append(dict(kwargs))
        goal = str(kwargs.get("goal") or "")
        payload = self.payloads_by_capture[capture_index].get(goal)
        return deepcopy(payload or _release_empty_recognition(goal))


def _install_release_runtime_doubles(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    asset: dict[str, Any],
) -> tuple[
    DeterministicFakeBackend,
    _ReleaseWindowManager,
    _ReleaseScreenshotSequence,
    _ReleaseRecognitionSequence,
]:
    import app.agent.live_runtime_composition as composition
    import app.core.screenshot as screenshot_module
    import app.core.window_manager as window_module
    import app.operation.screen_reading.uia_provider as uia_module

    fake_backend = DeterministicFakeBackend()
    window_manager = _ReleaseWindowManager()
    screenshot_service = _ReleaseScreenshotSequence(tmp_path)
    origin_reader = _ReleaseOriginReader()
    uia_provider = _ReleaseUIAProvider()
    recognition_runner = _ReleaseRecognitionSequence(asset)

    monkeypatch.setattr(screenshot_module, "screenshot_service", screenshot_service)
    monkeypatch.setattr(window_module, "window_manager", window_manager)
    monkeypatch.setattr(uia_module, "uia_provider", uia_provider)
    monkeypatch.setattr(
        composition,
        "WindowsUIAOriginReader",
        lambda **_kwargs: origin_reader,
    )
    monkeypatch.setattr(
        composition,
        "_run_existing_read_only_recognition",
        recognition_runner,
    )
    monkeypatch.setattr(
        composition,
        "ExistingWindowsBackendAdapter",
        lambda: fake_backend,
    )
    return fake_backend, window_manager, screenshot_service, recognition_runner


def _new_release_callsite(
    project_root: Path,
    window_manager: _ReleaseWindowManager,
) -> LocalAgentRuntimeCallsite:
    receipt_store = RuntimeReceiptStore(project_root=project_root)
    claim_store = RuntimeIntentClaimStore(
        project_root=project_root,
        receipt_store=receipt_store,
    )
    return LocalAgentRuntimeCallsite(
        project_root=project_root,
        asset_store=ReviewedWorkflowAssetStore(project_root=project_root),
        window_manager=window_manager,
        claim_store=claim_store,
    )


def _release_runtime_client(callsite: LocalAgentRuntimeCallsite) -> TestClient:
    app = FastAPI()
    app.include_router(agent_runtime_router)
    app.dependency_overrides[get_agent_runtime_callsite] = lambda: callsite
    return TestClient(app, client=("127.0.0.1", 50000))


def test_exact_portfolio_release_fixture_is_content_addressed_and_non_authorizing() -> None:
    manifest_path = FIXTURE_ROOT / "manifest.json"
    workflow_path = FIXTURE_ROOT / "reviewed_workflow.json"
    asset_path = FIXTURE_ROOT / "reviewed_workflow_asset_v2.json"
    source_path = FIXTURE_ROOT / "source_screenshot.png"
    overlay_path = FIXTURE_ROOT / "human_review_overlay.png"

    manifest, workflow, asset = _load_release_fixture()
    assert sha256(workflow_path.read_bytes()).hexdigest() == SOURCE_WORKFLOW_SHA256
    assert sha256(asset_path.read_bytes()).hexdigest() == ASSET_SHA256
    assert content_sha256(asset) == ASSET_SHA256
    assert sha256(source_path.read_bytes()).hexdigest() == SOURCE_SCREENSHOT_SHA256
    assert sha256(overlay_path.read_bytes()).hexdigest() == HUMAN_REVIEW_OVERLAY_SHA256
    assert manifest["asset_id"] == asset["asset_id"] == ASSET_ID
    assert asset["source_review_lineage"]["source_workflow_id"] == SOURCE_WORKFLOW_ID
    assert (
        asset["source_review_lineage"]["source_workflow_sha256"]
        == SOURCE_WORKFLOW_SHA256
    )
    assert asset["safety"] == {
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "final_submit_forbidden": True,
        "fresh_grounding_required": True,
        "historical_coordinates_used": False,
        "post_action_verification_required": True,
        "real_action_requires_gate": True,
    }
    assert workflow["workflow"]["workflow_id"] == SOURCE_WORKFLOW_ID

    states = {item["source_node_id"]: item for item in asset["states"]}
    assert states["job_detail"]["availability"] == "reviewed"
    assert states["apply_entry"]["availability"] == "stop_boundary"
    assert states["apply_entry"]["allowed_transition_ids"] == []
    assert len(asset["transitions"]) == 1
    transition = asset["transitions"][0]
    assert transition["semantic_action"] == "open_apply_flow"
    assert transition["source_state_id"] == states["job_detail"]["state_id"]
    assert transition["target_state_id"] == states["apply_entry"]["state_id"]
    assert transition["risk_policy"]["requires_user_confirmation"] is True
    assert transition["risk_policy"]["automatic_execution_allowed"] is False
    assert asset["source_review_lineage"]["human_approved_node_ids"] == [
        "job_detail"
    ]
    assert ASSET_ID != SOURCE_WORKFLOW_ID


def test_release_manifest_rejects_frozen_contract_drift() -> None:
    manifest = deepcopy(_json(FIXTURE_ROOT / "manifest.json"))
    manifest["application_identity"]["canonical_origin"] = "https://example.invalid"

    with pytest.raises(AssertionError):
        _validate_release_manifest(manifest)


def test_release_fixture_materializes_exact_active_asset_and_agent_context(
    tmp_path: Path,
) -> None:
    asset, store = _materialize_release_project(tmp_path)
    registry = store.registry()
    assert registry["registry_revision"] == 1
    assert registry["active_by_asset"] == {ASSET_ID: ASSET_SHA256}
    assert content_sha256(store.load_active(ASSET_ID)) == ASSET_SHA256

    context = load_interface_workflow_agent_context(
        project_root=tmp_path,
        application_identity_key="web:nz.seek.com",
    )
    assert context["artifact_is_authorization"] is False
    assert context["execute_binding_enabled"] is False
    assert context["agent_usable_interfaces"] == [
        {
            "workflow_id": SOURCE_WORKFLOW_ID,
            "interface_id": "job_detail",
            "display_name": "Job Detail",
            "agent_usable": True,
        }
    ]
    assert any(
        item.get("interface_id") == "apply_entry"
        for item in context["blocked_interfaces"]
    )


def test_exact_release_asset_runs_through_local_callsite_and_safe_stops(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset, asset_store = _materialize_release_project(tmp_path)
    assert asset["asset_id"] == ASSET_ID
    assert content_sha256(asset_store.load_active(ASSET_ID)) == ASSET_SHA256
    fake_backend, window_manager, screenshot_service, recognition_runner = (
        _install_release_runtime_doubles(monkeypatch, tmp_path, asset)
    )

    first_callsite = _new_release_callsite(tmp_path, window_manager)
    first_client = _release_runtime_client(first_callsite)
    started_response = first_client.post("/runtime/agent/session/start", json={})
    assert started_response.status_code == 200, started_response.text
    observation = started_response.json()["data"]
    assert isinstance(
        first_callsite._controller._observation_source,
        ExistingWindowsCurrentEvidenceAdapter,
    )
    assert (
        first_callsite._controller._observation_source
        is first_callsite._controller._target_resolver
    )
    assert first_callsite._controller._backend is fake_backend
    assert observation["workflow"] == {
        "workflow_id": SOURCE_WORKFLOW_ID,
        "asset_id": ASSET_ID,
        "asset_content_sha256": ASSET_SHA256,
        "source_workflow_sha256": SOURCE_WORKFLOW_SHA256,
        "reviewed_revision_hash": (
            "8e512cb94091ad8fd1c67afeba55ff68477c542da28de9da8f05de6416ce4ed7"
        ),
    }
    assert observation["workflow"]["workflow_id"] != observation["workflow"]["asset_id"]
    assert observation["state"]["source_interface_id"] == "job_detail"
    assert [
        item["semantic_action"] for item in observation["available_actions"]
    ] == ["open_apply_flow", "safe_stop"]
    open_apply_action = next(
        item
        for item in observation["available_actions"]
        if item["semantic_action"] == "open_apply_flow"
    )
    transition = asset["transitions"][0]
    assert open_apply_action["action_id"] == transition["transition_id"]
    assert open_apply_action["action_id"] != "open_apply_flow"

    intent_payload = {
        "intent_id": "intent.portfolio-release-open-apply",
        "session_id": observation["session_id"],
        "observation_id": observation["observation_id"],
        "action_id": open_apply_action["action_id"],
    }
    assert set(intent_payload) == {
        "intent_id",
        "session_id",
        "observation_id",
        "action_id",
    }
    pending_response = first_client.post(
        "/runtime/agent/intent/submit",
        json=intent_payload,
    )
    assert pending_response.status_code == 200, pending_response.text
    pending = pending_response.json()["data"]
    assert pending["status"] == "NEEDS_REVIEW"
    assert pending["reason_code"] == "human_confirmation_required"
    confirmation_id = pending["confirmation_id"]
    assert confirmation_id
    assert fake_backend.attempt_count == 0
    assert fake_backend.dispatch_count == 0
    assert fake_backend.commands == []
    assert len(screenshot_service.calls) == 2
    assert len(recognition_runner.capture_paths) == 2

    first_client.close()
    restarted_callsite = _new_release_callsite(tmp_path, window_manager)
    assert restarted_callsite._controller is None
    assert restarted_callsite._observation is None
    restarted_client = _release_runtime_client(restarted_callsite)
    approved_response = restarted_client.post(
        "/runtime/agent/confirmation/decide",
        json={"confirmation_id": confirmation_id, "decision": "approved"},
    )
    assert approved_response.status_code == 200, approved_response.text
    receipt = approved_response.json()["data"]
    assert receipt["workflow"] == observation["workflow"]
    assert receipt["action"] == {
        "action_id": open_apply_action["action_id"],
        "semantic_action": "open_apply_flow",
    }
    assert receipt["outcome"] == "SAFE_STOP"
    assert receipt["reason_code"] == "stop_boundary"
    assert receipt["attempt_count"] == 1
    assert receipt["gate_status"] == "allowed"
    assert receipt["dispatch_status"] == "dispatched"
    assert receipt["effect_status"] == "verified"
    assert receipt["destination_status"] == "verified"
    assert receipt["safe_stop"] == {
        "required": True,
        "reason_code": "stop_boundary",
    }
    assert receipt["next_observation_id"]
    for evidence_key in (
        "state_resolution_ref",
        "selection_ref",
        "candidate_ref",
        "gate_decision_ref",
        "backend_receipt_ref",
        "verification_ref",
    ):
        assert receipt["evidence"][evidence_key]

    assert fake_backend.attempt_count == 1
    assert fake_backend.dispatch_count == 1
    assert len(fake_backend.commands) == 1
    command = fake_backend.commands[0]
    assert command.semantic_action == "open_apply_flow"
    assert command.target_window_handle == 4242
    assert command.capture_id in receipt["evidence"]["candidate_ref"]
    assert command.candidate_id in receipt["evidence"]["candidate_ref"]
    assert len(window_manager.visibility_checks) == 1
    assert window_manager.visibility_checks[0]["click_point"] == (
        int(command.click_point[0]),
        int(command.click_point[1]),
    )
    assert [item["purpose"] for item in screenshot_service.calls] == [
        "runtime-observation",
        "runtime-observation",
        "runtime-observation",
        "runtime-pre-dispatch-freshness",
        "runtime-observation",
    ]
    assert len(screenshot_service.paths) == 5
    assert all(
        tmp_path.resolve() in path.resolve().parents
        for path in screenshot_service.paths
    )
    assert (
        sha256(screenshot_service.paths[2].read_bytes()).hexdigest()
        == sha256(screenshot_service.paths[3].read_bytes()).hexdigest()
    )
    assert (
        sha256(screenshot_service.paths[4].read_bytes()).hexdigest()
        != sha256(screenshot_service.paths[3].read_bytes()).hexdigest()
    )
    assert recognition_runner.capture_paths == [
        str(screenshot_service.paths[index]) for index in (0, 1, 2, 4)
    ]

    apply_entry_state_id = next(
        state["state_id"]
        for state in asset["states"]
        if state["source_node_id"] == "apply_entry"
    )
    persisted = RuntimeReceiptStore(project_root=tmp_path).load_by_receipt_id(
        receipt["receipt_id"]
    )
    assert persisted.runtime_receipt.model_dump(mode="json") == receipt
    assert (
        persisted.backend_receipt.receipt_ref
        == receipt["evidence"]["backend_receipt_ref"]
    )
    assert persisted.verification_evidence["status"] == "verified"
    assert (
        persisted.verification_evidence["post_state_resolution"]["state_id"]
        == apply_entry_state_id
    )
    assert persisted.next_observation.observation_id == receipt["next_observation_id"]
    assert persisted.next_observation.state.status == "stop_boundary"
    assert persisted.next_observation.state.state_availability == "stop_boundary"
    assert [
        item.semantic_action for item in persisted.next_observation.available_actions
    ] == ["safe_stop"]
    terminal_projection = json.dumps(
        {
            "receipt": receipt,
            "next_observation": persisted.next_observation.model_dump(mode="json"),
        },
        ensure_ascii=False,
    )
    for forbidden_action in (
        "fill_field",
        "continue_next_step",
        "final_submit",
        "submit_application",
        "upload_document",
    ):
        assert forbidden_action not in terminal_projection

    capture_count = len(screenshot_service.calls)
    recognition_call_count = len(recognition_runner.calls)
    recognition_capture_count = len(recognition_runner.capture_paths)
    backend_attempt_count = fake_backend.attempt_count
    backend_dispatch_count = fake_backend.dispatch_count
    restarted_client.close()

    replay_callsite = _new_release_callsite(tmp_path, window_manager)
    assert replay_callsite._controller is None
    assert replay_callsite._observation is None
    replay_client = _release_runtime_client(replay_callsite)
    repeated_approval = replay_client.post(
        "/runtime/agent/confirmation/decide",
        json={"confirmation_id": confirmation_id, "decision": "approved"},
    )
    repeated_intent = replay_client.post(
        "/runtime/agent/intent/submit",
        json=intent_payload,
    )
    assert repeated_approval.status_code == repeated_intent.status_code == 200
    assert repeated_approval.json()["data"] == receipt
    assert repeated_intent.json()["data"] == receipt
    assert len(screenshot_service.calls) == capture_count
    assert len(recognition_runner.calls) == recognition_call_count
    assert len(recognition_runner.capture_paths) == recognition_capture_count
    assert fake_backend.attempt_count == backend_attempt_count
    assert fake_backend.dispatch_count == backend_dispatch_count
    replay_client.close()
