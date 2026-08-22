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
from app.agent.runtime_contracts import AgentObservationV1
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
    ExistingWindowsCurrentEvidenceVisibilityChecker,
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


class _SequencedScreenshotService(_ScreenshotService):
    def __init__(
        self,
        root: Path,
        *,
        colors: list[tuple[int, int, int]],
        fail_on_call: int | None = None,
    ) -> None:
        super().__init__(root)
        self.colors = colors
        self.fail_on_call = fail_on_call

    def capture_window(self, **kwargs: object) -> dict[str, object]:
        call_number = len(self.calls) + 1
        if call_number == self.fail_on_call:
            self.calls.append(dict(kwargs))
            raise RuntimeError("fresh capture failed")
        result = super().capture_window(**kwargs)
        color = self.colors[min(call_number - 1, len(self.colors) - 1)]
        Image.new("RGB", (self.width, self.height), color).save(str(result["image_path"]))
        return result


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


class _UIAProvider:
    def __init__(self, *, handle: int = 4242, process_id: int = 9001) -> None:
        self.handle = handle
        self.process_id = process_id
        self.calls: list[object] = []

    def snapshot_window(self, bound: object) -> dict[str, object]:
        self.calls.append(bound)
        return {
            "provider": "windows_uia",
            "provider_version": "windows_uia_provider_v1",
            "status": "ok",
            "window": {
                "handle": self.handle,
                "process_id": self.process_id,
                "bbox": {"x": 0, "y": 0, "w": 320, "h": 200},
            },
            "control_count": 0,
            "controls": [],
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
    score_parts: dict[str, float] = {}
    remaining = score
    for name, weight in (
        ("text_similarity", 0.38),
        ("policy_score", 0.18),
        ("role_score", 0.16),
        ("confidence_score", 0.14),
        ("screen_reading_score", 0.10),
        ("state_score", 0.08),
    ):
        value = min(1.0, max(0.0, remaining / weight))
        score_parts[name] = value
        remaining -= value * weight
    breakdown = ScoreBreakdown(**score_parts)
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
        score_breakdown=breakdown,
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
    uia: _UIAProvider | None = None,
    application_identity_key: str = "web:nz.seek.com",
) -> tuple[
    ExistingWindowsCurrentEvidenceAdapter,
    _WindowManager,
    _ScreenshotService,
    _OriginReader,
    _RecognitionRunner,
]:
    manager = manager or _WindowManager(_bound(), _bound(), _bound())
    screenshot = screenshot or _ScreenshotService(tmp_path)
    origin = origin or _OriginReader()
    runner = runner or _RecognitionRunner(_entry_payloads(asset))
    uia = uia or _UIAProvider()
    adapter = ExistingWindowsCurrentEvidenceAdapter(
        project_root=tmp_path,
        application_identity_key=application_identity_key,
        screenshot_service=screenshot,
        origin_reader=origin,
        window_manager=manager,
        recognition_runner=runner,
        uia_provider=uia,
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
    assert manager.calls == 3
    assert origin.calls == [4242, 4242]
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


def test_capture_pins_exact_uia_snapshot_and_revalidates_binding_epoch(tmp_path: Path) -> None:
    asset = _asset()
    manager = _WindowManager(_bound(), _bound(), _bound())
    runner = _RecognitionRunner(_entry_payloads(asset))
    uia = _UIAProvider()
    adapter = ExistingWindowsCurrentEvidenceAdapter(
        project_root=tmp_path,
        application_identity_key="web:nz.seek.com",
        screenshot_service=_ScreenshotService(tmp_path),
        origin_reader=_OriginReader(),
        window_manager=manager,
        recognition_runner=runner,
        uia_provider=uia,
    )

    adapter.capture_current(session_id="session-current", asset=asset, target_window_handle=4242)

    assert len(uia.calls) == 1
    assert runner.calls
    assert all(call["uia_snapshot"]["window"]["handle"] == 4242 for call in runner.calls)
    assert manager.calls == 3


@pytest.mark.parametrize(
    ("uia", "final_bound"),
    [(_UIAProvider(handle=9999), _bound()), (_UIAProvider(), _bound(process_id=9002))],
)
def test_capture_rejects_uia_or_final_binding_drift_before_cache(
    tmp_path: Path,
    uia: _UIAProvider,
    final_bound: object,
) -> None:
    asset = _asset()
    runner = _RecognitionRunner(_entry_payloads(asset))
    adapter = ExistingWindowsCurrentEvidenceAdapter(
        project_root=tmp_path,
        application_identity_key="web:nz.seek.com",
        screenshot_service=_ScreenshotService(tmp_path),
        origin_reader=_OriginReader(),
        window_manager=_WindowManager(_bound(), _bound(), final_bound),
        recognition_runner=runner,
        uia_provider=uia,
    )

    with pytest.raises(ValueError, match="UIA snapshot|binding drift"):
        adapter.capture_current(
            session_id="session-current",
            asset=asset,
            target_window_handle=4242,
        )

    if uia.handle != 4242:
        assert runner.calls == []


def test_capture_rejects_origin_drift_after_pinned_recognition(tmp_path: Path) -> None:
    asset = _asset()

    class DriftingOrigin(_OriginReader):
        def read_origin(self, target_window_handle: int) -> dict[str, object]:
            result = super().read_origin(target_window_handle)
            if len(self.calls) == 2:
                result["origin"] = "https://wrong.example"
            return result

    runner = _RecognitionRunner(_entry_payloads(asset))
    adapter = ExistingWindowsCurrentEvidenceAdapter(
        project_root=tmp_path,
        application_identity_key="web:nz.seek.com",
        screenshot_service=_ScreenshotService(tmp_path),
        origin_reader=DriftingOrigin(),
        window_manager=_WindowManager(_bound(), _bound(), _bound()),
        recognition_runner=runner,
        uia_provider=_UIAProvider(),
    )

    with pytest.raises(ValueError, match="origin drift"):
        adapter.capture_current(
            session_id="session-current",
            asset=asset,
            target_window_handle=4242,
        )

    assert runner.calls


@pytest.mark.parametrize(
    ("case", "expected_allowed", "expected_fresh_calls"),
    [
        ("unchanged", True, 2),
        ("changed_pixels", False, 2),
        ("resize", False, 1),
        ("wrong_session", False, 1),
        ("capture_failure", False, 2),
    ],
)
def test_pre_dispatch_visibility_requires_exact_cached_pixels(
    tmp_path: Path,
    case: str,
    expected_allowed: bool,
    expected_fresh_calls: int,
) -> None:
    asset = _asset()
    screenshot = _SequencedScreenshotService(
        tmp_path,
        colors=[(1, 20, 30), (200, 20, 30) if case == "changed_pixels" else (1, 20, 30)],
        fail_on_call=2 if case == "capture_failure" else None,
    )
    checker_bound = _bound(width=321) if case == "resize" else _bound()
    manager = _WindowManager(_bound(), _bound(), _bound(), checker_bound, checker_bound)
    adapter, _, _, _, runner = _adapter(
        tmp_path,
        asset,
        manager=manager,
        screenshot=screenshot,
    )
    current = adapter.capture_current(
        session_id="session-current",
        asset=asset,
        target_window_handle=4242,
    )
    recognition_call_count = len(runner.calls)
    checker = ExistingWindowsCurrentEvidenceVisibilityChecker(
        evidence_adapter=adapter,
        delegate=_Visibility(),
    )

    result = checker.check(
        session_id="session-other" if case == "wrong_session" else "session-current",
        capture_lineage={
            "capture_id": current["capture_id"],
            "screenshot_sha256": current["screenshot_sha256"],
            "viewport_size": current["viewport_size"],
        },
        target_window_handle=4242,
        click_point=(100.0, 100.0),
    )

    assert result["point_visibility"]["allowed"] is expected_allowed
    assert len(screenshot.calls) == expected_fresh_calls
    assert len(runner.calls) == recognition_call_count
    if expected_fresh_calls == 2:
        assert screenshot.calls[-1] == {
            "save_image": True,
            "focus_window": False,
            "purpose": "runtime-pre-dispatch-freshness",
        }


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload["candidate_result"]["candidates"][0].update(score=0.99),
        lambda payload: payload["candidate_result"]["candidates"][0].update(rank=2),
        lambda payload: payload["candidate_result"].update(
            recommended_candidate_id="candidate-forged"
        ),
        lambda payload: payload["candidate_result"]["candidates"][0]["element"].update(
            element_id="element-forged"
        ),
    ],
)
def test_recognition_parser_rejects_forged_ranking_authority(mutation) -> None:
    import app.agent.live_runtime_composition as composition

    payload = _recognition("Quick Apply", role="button")
    mutation(payload)

    with pytest.raises(ValueError):
        composition._parse_recognition(payload)


def test_recognition_parser_recomputes_serialized_margin() -> None:
    import app.agent.live_runtime_composition as composition

    payload = _recognition("Quick Apply", role="button", score=0.83)
    payload["candidate_result"]["margin_to_second"] = 1.0

    candidates, _ = composition._parse_recognition(payload)

    assert candidates.margin_to_second == pytest.approx(0.83)


@pytest.mark.parametrize("case", ["zero_score", "low_local_confidence", "low_margin"])
def test_anchor_evidence_requires_server_grounding_thresholds(tmp_path: Path, case: str) -> None:
    asset = _asset()
    payloads = _entry_payloads(asset)
    state = next(item for item in asset["states"] if item["state_id"] == asset["entry_state_id"])
    target = state["identity_anchors"][0]
    payload = payloads[target["label"]]
    if case == "zero_score":
        payloads[target["label"]] = _recognition(
            target["label"],
            role=_role(target["kind"]),
            score=0.0,
        )
    elif case == "low_local_confidence":
        payload["narrow_search_result"]["results"][0]["confidence"] = 0.1
    else:
        second = _recognition("Different control", role="button", score=0.94)
        second_candidate = second["candidate_result"]["candidates"][0]
        second_candidate["rank"] = 2
        payload["candidate_result"]["candidates"].append(second_candidate)
        payload["candidate_result"]["margin_to_second"] = 1.0
        payload["narrow_search_result"]["results"].append(
            second["narrow_search_result"]["results"][0]
        )

    adapter, *_ = _adapter(tmp_path, asset, runner=_RecognitionRunner(payloads))
    current = adapter.capture_current(
        session_id=f"session-{case}",
        asset=asset,
        target_window_handle=4242,
    )

    assert target["anchor_id"] not in {
        item["anchor_id"] for item in current["observed_anchor_evidence"]
    }


def test_create_initial_projects_geometry_free_observation_from_exact_asset(tmp_path: Path) -> None:
    asset, _ = _server_asset(tmp_path)
    adapter, *_ = _adapter(
        tmp_path,
        asset,
        manager=_WindowManager(_bound(), _bound(), _bound()),
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


def test_capture_projected_uses_one_capture_for_raw_and_agent_observation(
    tmp_path: Path,
) -> None:
    asset, _ = _server_asset(tmp_path)
    workflow = _workflow(asset, "workflow_agent_evidence")
    adapter, manager, screenshot, origin, runner = _adapter(
        tmp_path,
        asset,
        manager=_WindowManager(_bound(), _bound(), _bound()),
        origin=_OriginReader(origin="https://example.test"),
        runner=_RecognitionRunner(_entry_payloads(asset)),
        application_identity_key="web:example.test",
    )

    projected = adapter.capture_projected(
        session_id="session-projected",
        workflow=workflow,
        asset=asset,
        target_window_handle=4242,
    )

    assert len(screenshot.calls) == 1
    assert manager.calls == 3
    assert origin.calls == [4242, 4242]
    assert runner.calls
    assert isinstance(projected.agent_observation, AgentObservationV1)
    assert projected.agent_observation.session_id == "session-projected"
    assert projected.agent_observation.workflow.model_dump(mode="json") == workflow
    assert projected.agent_observation.application.identity_ref == "application:web:example.test"
    assert projected.current_observation["asset_id"] == asset["asset_id"]
    assert projected.current_observation["capture_id"] == (
        projected.agent_observation.current_capture.capture_id
    )
    assert projected.current_observation["screenshot_sha256"] == (
        projected.agent_observation.current_capture.screenshot_sha256
    )
    assert projected.target_window_handle == 4242
    assert projected.target_process_id == 9001
    assert projected.artifact_is_authorization is False
    assert projected.grants_action_authority is False
    encoded = json.dumps(
        {
            "current_observation": projected.current_observation,
            "agent_observation": projected.agent_observation.model_dump(mode="json"),
            "artifact_is_authorization": projected.artifact_is_authorization,
            "grants_action_authority": projected.grants_action_authority,
        },
        ensure_ascii=False,
    ).casefold()
    assert "authority_token" not in encoded


def test_capture_projected_projection_failure_fails_closed_after_one_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.agent.live_runtime_composition as composition

    asset, _ = _server_asset(tmp_path)
    screenshot = _ScreenshotService(tmp_path)
    adapter, *_ = _adapter(
        tmp_path,
        asset,
        manager=_WindowManager(_bound(), _bound(), _bound()),
        screenshot=screenshot,
        origin=_OriginReader(origin="https://example.test"),
        runner=_RecognitionRunner(_entry_payloads(asset)),
        application_identity_key="web:example.test",
    )

    def fail_projection(**_kwargs: object) -> object:
        raise ValueError("projection provider failed")

    monkeypatch.setattr(
        composition,
        "adapt_reviewed_context_to_agent_observation_v1",
        fail_projection,
    )

    with pytest.raises(ValueError, match="projection"):
        adapter.capture_projected(
            session_id="session-projected",
            workflow=_workflow(asset, "workflow_agent_evidence"),
            asset=asset,
            target_window_handle=4242,
        )
    assert len(screenshot.calls) == 1


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

    result = adapter.resolve(
        session_id="session-current",
        selection=selection,
        current_observation=current,
    )

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
    assert missing.resolve(
        session_id="session-current",
        selection=selection,
        current_observation=current,
    )["status"] == "stale"
    stale = deepcopy(current)
    stale["screenshot_sha256"] = "0" * 64
    assert adapter.resolve(
        session_id="session-current",
        selection=selection,
        current_observation=stale,
    )["status"] == "stale"

    assert adapter.resolve(
        session_id="session-other",
        selection=selection,
        current_observation=current,
    )["status"] == "stale"

    target = next(
        anchor
        for state in asset["states"]
        for anchor in state["identity_anchors"]
        if anchor["anchor_id"] == selection["element_ref"]
    )
    ambiguous_payloads = _entry_payloads(asset)
    first = _recognition(target["label"], role=_role(target["kind"]), candidate_id="candidate-a")
    second = _recognition(
        target["label"],
        role=_role(target["kind"]),
        candidate_id="candidate-b",
        element_id="current-target-b",
    )
    second_candidate = second["candidate_result"]["candidates"][0]
    second_candidate["rank"] = 2
    first["candidate_result"]["candidates"].append(second_candidate)
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
        session_id="session-ambiguous",
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
        session_id="session-malformed",
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
    assert isinstance(
        controller._window_visibility_checker,
        ExistingWindowsCurrentEvidenceVisibilityChecker,
    )
    assert (
        controller._window_visibility_checker._evidence_adapter
        is controller._observation_source
    )
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


@pytest.mark.parametrize("case", ["dispatch", "gate_block", "changed_pixels"])
def test_factory_graph_checks_freshness_after_gate_before_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    import app.agent.live_runtime_composition as composition
    import app.core.screenshot as screenshot_module
    import app.core.window_manager as window_module
    import app.operation.screen_reading.uia_provider as uia_module
    from app.agent.desktop_backend import DeterministicFakeBackend
    from app.agent.live_controller import ServerWorkflowBinding
    from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore
    from app.agent.reviewed_workflow_gate import ReviewedWorkflowGateAdapter
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    asset, _ = _server_asset(tmp_path)
    ReviewedWorkflowAssetStore(project_root=tmp_path).publish(
        asset,
        expected_registry_revision=0,
    )
    backend = DeterministicFakeBackend()
    manager = _WindowManager(*[_bound() for _ in range(8)])
    screenshot = _SequencedScreenshotService(
        tmp_path,
        colors=[
            (1, 20, 30),
            (1, 20, 30),
            (200, 20, 30) if case == "changed_pixels" else (1, 20, 30),
        ],
    )
    monkeypatch.setattr(screenshot_module, "screenshot_service", screenshot)
    monkeypatch.setattr(window_module, "window_manager", manager)
    monkeypatch.setattr(uia_module, "uia_provider", _UIAProvider())
    monkeypatch.setattr(
        composition,
        "WindowsUIAOriginReader",
        lambda **_kwargs: _OriginReader(origin="https://example.test"),
    )
    monkeypatch.setattr(
        composition,
        "_run_existing_read_only_recognition",
        _RecognitionRunner(_entry_payloads(asset)),
    )
    monkeypatch.setattr(composition, "ExistingWindowsBackendAdapter", lambda: backend)
    monkeypatch.setattr(composition, "ExistingWindowManagerVisibilityChecker", _Visibility)
    if case == "gate_block":
        monkeypatch.setattr(
            composition,
            "ReviewedWorkflowGateAdapter",
            lambda **_kwargs: ReviewedWorkflowGateAdapter(min_candidate_score=0.99),
        )
    controller = build_existing_windows_live_controller(
        tmp_path,
        ServerWorkflowBinding(
            workflow_id="workflow_agent_evidence",
            asset_id=asset["asset_id"],
            application_identity_key="web:example.test",
            target_window_handle=4242,
        ),
    )
    session = controller.start_session()
    action = next(
        item
        for item in session.current_observation.available_actions
        if item.action_id != "runtime.safe_stop"
    )

    payload = {
        "contract_version": "agent_intent_v1",
        "intent_id": f"factory-intent-{case}",
        "session_id": session.session_id,
        "observation_id": session.current_observation.observation_id,
        "workflow": session.workflow.model_dump(mode="json"),
        "action_id": action.action_id,
    }
    receipt = controller.submit_intent(payload)

    expected_outcome = "DISPATCHED" if case == "dispatch" else "BLOCKED"
    assert receipt.outcome == expected_outcome
    assert backend.dispatch_count == (1 if case == "dispatch" else 0)
    assert len(screenshot.calls) == (2 if case == "gate_block" else 3)
    screenshot_call_count = len(screenshot.calls)
    duplicate = controller.submit_intent(payload)
    assert duplicate == receipt
    assert backend.dispatch_count == (1 if case == "dispatch" else 0)
    assert len(screenshot.calls) == screenshot_call_count
    persisted = RuntimeReceiptStore(project_root=tmp_path).load_by_receipt_id(receipt.receipt_id)
    assert persisted.runtime_receipt == receipt
    if case == "dispatch":
        assert receipt.reason_code == "verification_pending"
        assert receipt.effect_status == "not_evaluated"
        assert receipt.destination_status == "not_evaluated"
    if case == "changed_pixels":
        assert receipt.reason_code == "target_occluded"


def test_default_recognition_wrapper_is_read_only_unseeded_and_exact_image_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.agent.live_runtime_composition as composition
    import app.api.vision as vision_api

    image_path = tmp_path / "exact.png"
    Image.new("RGB", (20, 10), (1, 2, 3)).save(image_path)
    requests: list[object] = []
    observed_snapshots: list[dict] = []
    pinned_snapshot = {
        "status": "ok",
        "window": {"handle": 4242, "process_id": 9001},
        "controls": [],
    }

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
        observed_snapshots.append(vision_api.uia_provider.snapshot_bound_window())
        return Response()

    monkeypatch.setattr(vision_api, "recognition_plan", fake_recognition)

    result = composition._run_existing_read_only_recognition(
        image_path=str(image_path),
        goal="Quick Apply",
        provider_mode="test-provider",
        uia_snapshot=pinned_snapshot,
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
    assert observed_snapshots == [pinned_snapshot]


class _AssetLoader:
    def __init__(self, asset: dict) -> None:
        self.asset = asset

    def load_active(self, _asset_id: str) -> dict:
        return deepcopy(self.asset)


class _Visibility:
    def check(
        self,
        *,
        session_id: str,
        capture_lineage: dict,
        target_window_handle: int,
        click_point: tuple[float, float],
    ) -> dict:
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
        manager=_WindowManager(*[_bound() for _ in range(6)]),
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
