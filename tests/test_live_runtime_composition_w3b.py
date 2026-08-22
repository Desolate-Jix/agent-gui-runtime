from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
import pytest

from app.agent.reviewed_workflow_asset import content_sha256
from app.agent.reviewed_workflow_replay import resolve_current_state, select_verified_transition
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
from tests.test_agent_observation_adapter_v1 import _server_asset
from tests.test_reviewed_workflow_asset_v2 import _asset

from app.agent.live_runtime_composition import (
    ExistingWindowsCurrentEvidenceAdapter,
    build_existing_windows_live_controller,
)


def _bound(*, handle: int = 4242, process_id: int = 9001, width: int = 320, height: int = 200):
    return SimpleNamespace(
        handle=handle,
        process_id=process_id,
        rect=SimpleNamespace(left=10, top=20, right=10 + width, bottom=20 + height),
    )


class _WindowManager:
    def __init__(self, *snapshots: object) -> None:
        self.snapshots = list(snapshots)
        self.calls = 0

    def get_bound_window(self):
        self.calls += 1
        if not self.snapshots:
            return None
        return self.snapshots.pop(0)


class _ScreenshotService:
    def __init__(
        self,
        root: Path,
        *,
        width: int = 320,
        height: int = 200,
        reported_width: int | None = None,
    ) -> None:
        self.root = root
        self.width = width
        self.height = height
        self.reported_width = reported_width
        self.calls: list[dict[str, object]] = []
        self.paths: list[Path] = []

    def capture_window(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(dict(kwargs))
        path = self.root / f"capture-{len(self.calls)}.png"
        Image.new("RGB", (self.width, self.height), (len(self.calls), 20, 30)).save(path)
        self.paths.append(path)
        width = self.width if self.reported_width is None else self.reported_width
        return {
            "image_path": str(path),
            "image_width": width,
            "image_height": self.height,
            "roi": None,
            "roi_adjusted": False,
            "capture_purpose": kwargs.get("purpose"),
            "window_size": {"width": width, "height": self.height},
        }


class _OriginReader:
    def __init__(self, *, status: str = "observed", origin: str | None = "https://nz.seek.com") -> None:
        self.status = status
        self.origin = origin
        self.calls: list[int] = []

    def read_origin(self, target_window_handle: int) -> dict[str, object]:
        self.calls.append(target_window_handle)
        return {
            "status": self.status,
            "origin": self.origin,
            "target_window_handle": target_window_handle,
            "bound_process_id": 9001,
        }


class _RecognitionRunner:
    def __init__(self, payloads: dict[str, dict]) -> None:
        self.payloads = payloads
        self.calls: list[dict[str, object]] = []

    def __call__(self, **kwargs: object) -> dict:
        self.calls.append(dict(kwargs))
        return deepcopy(self.payloads.get(str(kwargs.get("goal")), _empty_recognition(str(kwargs.get("goal")))))


def _recognition(
    label: str,
    *,
    role: str,
    candidate_id: str | None = None,
    element_id: str | None = None,
    bbox: tuple[int, int, int, int] = (40, 50, 120, 40),
    score: float = 0.95,
    eligible: bool = True,
) -> dict:
    candidate_id = candidate_id or f"candidate-{label.casefold().replace(' ', '-')}"
    element_id = element_id or f"current-{label.casefold().replace(' ', '-')}"
    box = BBox(x=bbox[0], y=bbox[1], w=bbox[2], h=bbox[3])
    point = {"x": bbox[0] + bbox[2] // 2, "y": bbox[1] + bbox[3] // 2}
    candidate = RecognitionCandidate(
        candidate_id=candidate_id,
        rank=1,
        element_id=element_id,
        label=label,
        role=role,
        text=label,
        score=score,
        eligible=eligible,
        reasons=["current_test_evidence"],
        score_breakdown=ScoreBreakdown(
            text_similarity=1.0,
            role_score=1.0,
            policy_score=1.0,
            confidence_score=1.0,
        ),
        element=PageElement(
            element_id=element_id,
            label=label,
            role=role,
            interaction_type="click",
            description=label,
            text=label,
            bbox=box,
            semantic_bbox=None,
            click_point=point,
            click_strategy="center",
            possible_destinations=[],
            verification_hints=VerificationHints(),
            interaction_policy=InteractionPolicy(allowed=True),
            fusion_confidence=score,
            coordinate_confidence="high",
            memory_key="",
            sources=["current_test"],
        ),
    )
    candidates = CandidateRankResult(
        goal=label,
        top_k=5,
        candidates=[candidate],
        recommended_candidate_id=candidate_id,
        margin_to_second=1.0,
        summary={"source": "current_test"},
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
                refined_click_point=point,
                coordinate_source="current_test",
                confidence=score,
                matched_text=label,
                matched_text_bbox=box.to_dict(),
                reasons=["current_test_evidence"],
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
            "selected_click_point": {"x": 9999, "y": 9999},
        },
    }


def _empty_recognition(goal: str) -> dict:
    return {
        "contract_version": "recognition_plan_v1",
        "candidate_result": CandidateRankResult(goal=goal).to_dict(),
        "narrow_search_result": LocalGroundingResult(goal=goal).to_dict(),
        "pre_click_decision": {"allowed": True, "selected_click_point": {"x": 9999, "y": 9999}},
    }


def _role(kind: str) -> str:
    return {"control": "button", "text": "text", "region": "region"}.get(kind, kind)


def _entry_payloads(asset: dict) -> dict[str, dict]:
    state = next(item for item in asset["states"] if item["state_id"] == asset["entry_state_id"])
    return {
        anchor["label"]: _recognition(anchor["label"], role=_role(anchor["kind"]))
        for anchor in state["identity_anchors"]
    }


def _workflow(asset: dict, workflow_id: str) -> dict[str, str]:
    return {
        "workflow_id": workflow_id,
        "asset_id": asset["asset_id"],
        "asset_content_sha256": content_sha256(asset),
        "source_workflow_sha256": asset["source_review_lineage"]["source_workflow_sha256"],
        "reviewed_revision_hash": asset["source_review_lineage"]["reviewed_revision_hash"],
    }


def _adapter(
    tmp_path: Path,
    asset: dict,
    *,
    manager: _WindowManager | None = None,
    screenshot: _ScreenshotService | None = None,
    origin: _OriginReader | None = None,
    runner: _RecognitionRunner | None = None,
    application_identity_key: str = "web:nz.seek.com",
) -> tuple[
    ExistingWindowsCurrentEvidenceAdapter,
    _WindowManager,
    _ScreenshotService,
    _OriginReader,
    _RecognitionRunner,
]:
    manager = manager or _WindowManager(_bound(), _bound())
    screenshot = screenshot or _ScreenshotService(tmp_path)
    origin = origin or _OriginReader()
    runner = runner or _RecognitionRunner(_entry_payloads(asset))
    adapter = ExistingWindowsCurrentEvidenceAdapter(
        project_root=tmp_path,
        application_identity_key=application_identity_key,
        screenshot_service=screenshot,
        origin_reader=origin,
        window_manager=manager,
        recognition_runner=runner,
    )
    return adapter, manager, screenshot, origin, runner


def test_capture_current_uses_passive_exact_image_bytes_and_current_anchor_refs(tmp_path: Path) -> None:
    asset = _asset()
    adapter, manager, screenshot, origin, runner = _adapter(tmp_path, asset)

    current = adapter.capture_current(
        session_id="session-current",
        asset=asset,
        target_window_handle=4242,
    )

    assert screenshot.calls == [
        {
            "save_image": True,
            "focus_window": False,
            "purpose": "runtime-observation",
        }
    ]
    assert manager.calls == 2
    assert origin.calls == [4242]
    assert current["screenshot_sha256"] == sha256(screenshot.paths[0].read_bytes()).hexdigest()
    assert current["viewport_size"] == {"width": 320, "height": 200}
    assert current["origin"] == "https://nz.seek.com"
    assert current["capture_id"].startswith("runtime-capture.")
    assert {item["anchor_id"] for item in current["observed_anchor_evidence"]} == {
        item["anchor_id"]
        for state in asset["states"]
        if state["state_id"] == asset["entry_state_id"]
        for item in state["identity_anchors"]
    }
    assert all(current["capture_id"] in item["evidence_ref"] for item in current["observed_anchor_evidence"])
    assert all(call["image_path"] == str(screenshot.paths[0].resolve()) for call in runner.calls)
    assert all(call["provider_mode"] is None for call in runner.calls)


@pytest.mark.parametrize(
    ("origin_status", "observed_origin"),
    [("unavailable", None), ("observed", "https://wrong.example")],
)
def test_origin_unavailable_or_wrong_stays_unresolved_and_skips_recognition(
    tmp_path: Path,
    origin_status: str,
    observed_origin: str | None,
) -> None:
    asset = _asset()
    origin = _OriginReader(status=origin_status, origin=observed_origin)
    adapter, _, _, _, runner = _adapter(tmp_path, asset, origin=origin)

    current = adapter.capture_current(session_id="session-current", asset=asset, target_window_handle=4242)

    assert resolve_current_state(asset, current)["status"] != "resolved"
    assert current["observed_anchor_evidence"] == []
    assert runner.calls == []


def test_binding_drift_and_viewport_mismatch_fail_before_recognition(tmp_path: Path) -> None:
    asset = _asset()
    drift = _WindowManager(_bound(), _bound(process_id=9002))
    adapter, _, _, _, runner = _adapter(tmp_path, asset, manager=drift)
    with pytest.raises(ValueError, match="binding drift"):
        adapter.capture_current(session_id="session-current", asset=asset, target_window_handle=4242)
    assert runner.calls == []

    mismatch = _ScreenshotService(tmp_path, reported_width=319)
    adapter, _, _, _, runner = _adapter(tmp_path, asset, screenshot=mismatch)
    with pytest.raises(ValueError, match="viewport"):
        adapter.capture_current(session_id="session-current", asset=asset, target_window_handle=4242)
    assert runner.calls == []


def test_capture_rejects_saved_image_change_during_recognition(tmp_path: Path) -> None:
    asset = _asset()

    class MutatingRunner(_RecognitionRunner):
        def __call__(self, **kwargs: object) -> dict:
            result = super().__call__(**kwargs)
            Image.new("RGB", (320, 200), (200, 100, 50)).save(str(kwargs["image_path"]))
            return result

    runner = MutatingRunner(_entry_payloads(asset))
    adapter, *_ = _adapter(tmp_path, asset, runner=runner)

    with pytest.raises(ValueError, match="screenshot changed during recognition"):
        adapter.capture_current(session_id="session-current", asset=asset, target_window_handle=4242)


def test_create_initial_projects_geometry_free_observation_from_exact_asset(tmp_path: Path) -> None:
    asset, _ = _server_asset(tmp_path)
    adapter, *_ = _adapter(
        tmp_path,
        asset,
        manager=_WindowManager(_bound(), _bound()),
        origin=_OriginReader(origin="https://example.test"),
        runner=_RecognitionRunner(_entry_payloads(asset)),
        application_identity_key="web:example.test",
    )

    observation = adapter.create_initial(
        session_id="session-current",
        workflow=_workflow(asset, "workflow_agent_evidence"),
        asset=asset,
        target_window_handle=4242,
    )

    assert observation.state.status == "matched"
    assert observation.workflow.asset_content_sha256 == content_sha256(asset)
    payload = observation.model_dump(mode="json")
    encoded = json.dumps(payload, ensure_ascii=False).casefold()
    for token in ("bbox", "click_point", "coordinates", "viewport", "approved_to_click"):
        assert token not in encoded


def _selected(asset: dict, current: dict) -> dict:
    resolution = resolve_current_state(asset, current)
    transition_id = next(
        item["transition_id"]
        for item in asset["transitions"]
        if item["source_state_id"] == resolution["state_id"]
    )
    return select_verified_transition(
        asset,
        resolution,
        transition_id=transition_id,
        current_observation=current,
    )


def test_resolver_returns_strict_typed_current_gate_evidence_and_ignores_serialized_decision(
    tmp_path: Path,
) -> None:
    asset = _asset()
    adapter, *_ = _adapter(tmp_path, asset)
    current = adapter.capture_current(session_id="session-current", asset=asset, target_window_handle=4242)
    selection = _selected(asset, current)

    result = adapter.resolve(selection=selection, current_observation=current)

    assert result["status"] == "resolved"
    assert isinstance(result["gate_context"]["candidates"], CandidateRankResult)
    assert isinstance(result["gate_context"]["local_grounding"], LocalGroundingResult)
    grounding = result["grounding"]
    assert grounding["capture_id"] == current["capture_id"]
    assert grounding["screenshot_sha256"] == current["screenshot_sha256"]
    assert grounding["viewport_size"] == current["viewport_size"]
    assert grounding["element_ref"] == selection["element_ref"]
    assert grounding["click_point"] != {"x": 9999, "y": 9999}
    assert result["gate_context"]["candidates"].candidates[0].element_id == selection["element_ref"]
    assert result["gate_context"]["local_grounding"].results[0].element_id == selection["element_ref"]


def test_resolver_rejects_missing_stale_ambiguous_and_malformed_current_evidence(tmp_path: Path) -> None:
    asset = _asset()
    adapter, *_ = _adapter(tmp_path, asset)
    current = adapter.capture_current(session_id="session-current", asset=asset, target_window_handle=4242)
    selection = _selected(asset, current)

    missing, *_ = _adapter(tmp_path, asset)
    assert missing.resolve(selection=selection, current_observation=current)["status"] == "stale"
    stale = deepcopy(current)
    stale["screenshot_sha256"] = "0" * 64
    assert adapter.resolve(selection=selection, current_observation=stale)["status"] == "stale"

    target = next(
        anchor
        for state in asset["states"]
        for anchor in state["identity_anchors"]
        if anchor["anchor_id"] == selection["element_ref"]
    )
    ambiguous_payloads = _entry_payloads(asset)
    first = _recognition(target["label"], role=_role(target["kind"]), candidate_id="candidate-a")
    second = _recognition(target["label"], role=_role(target["kind"]), candidate_id="candidate-b")
    first["candidate_result"]["candidates"].append(second["candidate_result"]["candidates"][0])
    first["narrow_search_result"]["results"].append(second["narrow_search_result"]["results"][0])
    ambiguous_payloads[target["label"]] = first
    ambiguous, *_ = _adapter(tmp_path, asset, runner=_RecognitionRunner(ambiguous_payloads))
    ambiguous_current = ambiguous.capture_current(
        session_id="session-ambiguous",
        asset=asset,
        target_window_handle=4242,
    )
    ambiguous_selection = _selected(asset, ambiguous_current)
    assert ambiguous.resolve(
        selection=ambiguous_selection,
        current_observation=ambiguous_current,
    )["status"] == "ambiguous"

    malformed_payloads = _entry_payloads(asset)
    malformed_payloads[target["label"]] = {
        "contract_version": "recognition_plan_v1",
        "candidate_result": {"candidates": "caller geometry"},
        "narrow_search_result": {},
    }
    malformed, *_ = _adapter(tmp_path, asset, runner=_RecognitionRunner(malformed_payloads))
    malformed_current = malformed.capture_current(
        session_id="session-malformed",
        asset=asset,
        target_window_handle=4242,
    )
    malformed_selection = _selected(asset, malformed_current)
    malformed_result = malformed.resolve(
        selection=malformed_selection,
        current_observation=malformed_current,
    )
    assert malformed_result["status"] == "unresolved"
    assert malformed_result["reason"] == "malformed_current_recognition"


def test_factory_wires_internal_existing_windows_runtime_without_route(tmp_path: Path) -> None:
    from app.agent.desktop_backend import ExistingWindowsBackendAdapter
    from app.agent.live_controller import LiveController, ServerWorkflowBinding
    from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore
    from app.agent.reviewed_workflow_gate import ReviewedWorkflowGateAdapter
    from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore

    binding = ServerWorkflowBinding(
        workflow_id="workflow.seek.portfolio",
        asset_id="seek_homepage_quick_apply",
        application_identity_key="web:nz.seek.com",
        target_window_handle=4242,
    )

    controller = build_existing_windows_live_controller(project_root=tmp_path, binding=binding)

    assert isinstance(controller, LiveController)
    assert isinstance(controller._asset_loader, ReviewedWorkflowAssetStore)
    assert isinstance(controller._observation_source, ExistingWindowsCurrentEvidenceAdapter)
    assert controller._observation_source is controller._target_resolver
    assert isinstance(controller._gate, ReviewedWorkflowGateAdapter)
    assert isinstance(controller._backend, ExistingWindowsBackendAdapter)
    assert isinstance(controller._intent_claim_store, RuntimeIntentClaimStore)
    assert controller._grounding_policy == {
        "minimum_confidence": 0.45,
        "minimum_score_margin": 0.06,
    }
    source = inspect.getsource(__import__("app.agent.live_runtime_composition", fromlist=["*"]))
    assert "APIRouter" not in source
    assert "execute_" + "recognition_plan" not in source


def test_default_recognition_wrapper_is_read_only_unseeded_and_exact_image_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.agent.live_runtime_composition as composition
    import app.api.vision as vision_api

    image_path = tmp_path / "exact.png"
    Image.new("RGB", (20, 10), (1, 2, 3)).save(image_path)
    requests: list[object] = []

    class Response:
        def model_dump(self, **_: object) -> dict:
            return {
                "success": True,
                "data": {
                    "result": {
                        "contract_version": "recognition_plan_v1",
                        "image_path": str(image_path),
                    }
                },
            }

    def fake_recognition(request):
        requests.append(request)
        return Response()

    monkeypatch.setattr(vision_api, "recognition_plan", fake_recognition)

    result = composition._run_existing_read_only_recognition(
        image_path=str(image_path),
        goal="Quick Apply",
        provider_mode="test-provider",
    )

    assert result["image_path"] == str(image_path)
    assert len(requests) == 1
    request = requests[0]
    assert request.image_path == str(image_path)
    assert request.metadata == {}
    assert request.observe_trace_path is None
    assert request.write_policy.model_dump() == {
        "path_graph": False,
        "element_memory": False,
        "trace": False,
    }


class _AssetLoader:
    def __init__(self, asset: dict) -> None:
        self.asset = asset

    def load_active(self, _asset_id: str) -> dict:
        return deepcopy(self.asset)


class _Visibility:
    def check(self, *, target_window_handle: int, click_point: tuple[float, float]) -> dict:
        return {
            "bound_window_handle": target_window_handle,
            "point_visibility": {"allowed": True, "click_point": click_point},
        }


@pytest.mark.parametrize(
    ("gate_score", "expected_outcome", "dispatches"),
    [(0.45, "DISPATCHED", 1), (0.99, "BLOCKED", 0)],
)
def test_live_controller_vertical_slice_dispatches_once_or_gate_blocks(
    tmp_path: Path,
    gate_score: float,
    expected_outcome: str,
    dispatches: int,
) -> None:
    from app.agent.desktop_backend import DeterministicFakeBackend
    from app.agent.live_controller import LiveController, ServerWorkflowBinding
    from app.agent.reviewed_workflow_gate import ReviewedWorkflowGateAdapter
    from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    asset, _ = _server_asset(tmp_path)
    runner = _RecognitionRunner(_entry_payloads(asset))
    adapter, _, screenshot, _, _ = _adapter(
        tmp_path,
        asset,
        manager=_WindowManager(_bound(), _bound(), _bound(), _bound()),
        screenshot=_ScreenshotService(tmp_path),
        origin=_OriginReader(origin="https://example.test"),
        runner=runner,
        application_identity_key="web:example.test",
    )
    backend = DeterministicFakeBackend()
    receipt_store = RuntimeReceiptStore(project_root=tmp_path)
    controller = LiveController(
        binding=ServerWorkflowBinding(
            workflow_id="workflow_agent_evidence",
            asset_id=asset["asset_id"],
            application_identity_key="web:example.test",
            target_window_handle=4242,
        ),
        asset_loader=_AssetLoader(asset),
        observation_source=adapter,
        target_resolver=adapter,
        gate=ReviewedWorkflowGateAdapter(min_candidate_score=gate_score),
        window_visibility_checker=_Visibility(),
        backend=backend,
        intent_claim_store=RuntimeIntentClaimStore(project_root=tmp_path, receipt_store=receipt_store),
        grounding_policy={"minimum_confidence": 0.45, "minimum_score_margin": 0.06},
    )
    session = controller.start_session()
    action = next(
        item
        for item in session.current_observation.available_actions
        if item.action_id != "runtime.safe_stop"
    )

    intent = {
        "contract_version": "agent_intent_v1",
        "intent_id": f"intent-{gate_score}",
        "session_id": session.session_id,
        "observation_id": session.current_observation.observation_id,
        "workflow": session.workflow.model_dump(mode="json"),
        "action_id": action.action_id,
    }
    receipt = controller.submit_intent(intent)

    assert receipt.outcome == expected_outcome
    assert backend.dispatch_count == dispatches
    if expected_outcome == "DISPATCHED":
        assert receipt.reason_code == "verification_pending"
        assert receipt.effect_status == "not_evaluated"
        assert receipt.destination_status == "not_evaluated"
        assert receipt.next_observation_id is None
        restarted_backend = DeterministicFakeBackend()
        restarted = LiveController(
            binding=controller._binding,
            asset_loader=_AssetLoader(asset),
            observation_source=adapter,
            target_resolver=adapter,
            gate=ReviewedWorkflowGateAdapter(),
            window_visibility_checker=_Visibility(),
            backend=restarted_backend,
            intent_claim_store=RuntimeIntentClaimStore(
                project_root=tmp_path,
                receipt_store=RuntimeReceiptStore(project_root=tmp_path),
            ),
            grounding_policy={"minimum_confidence": 0.45, "minimum_score_margin": 0.06},
        )
        duplicate = restarted.submit_intent(intent)
        assert duplicate.outcome == "DISPATCHED"
        assert restarted_backend.dispatch_count == 0
        assert len(screenshot.calls) == 2
