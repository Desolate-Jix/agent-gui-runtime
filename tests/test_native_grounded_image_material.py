from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
import pytest

from app.agent.desktop_backend import DeterministicFakeBackend
from app.agent.live_controller import LiveController
from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore, content_sha256
from app.agent.reviewed_workflow_gate import ReviewedWorkflowGateAdapter
from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
from app.agent.runtime_receipt_store import RuntimeReceiptStore
from app.agent.runtime_session_selection import RuntimeSessionSelection
from app.api.agent_runtime import (
    AgentRuntimeCallsiteError,
    AgentRuntimeIntentRequest,
    LocalAgentRuntimeCallsite,
)
from tests.test_live_controller_w4 import _WindowVisibilityChecker
from tests.test_live_runtime_composition_w3b import (
    _ScreenshotService,
    _WindowManager,
    _adapter,
    _bound,
    _synthetic_portfolio_apply_entry_asset,
)


@pytest.fixture
def grounded_image_runtime(tmp_path: Path):
    asset, _source = _synthetic_portfolio_apply_entry_asset(tmp_path)
    assets = ReviewedWorkflowAssetStore(project_root=tmp_path)
    assets.publish(asset, expected_registry_revision=0)
    claims = RuntimeIntentClaimStore(
        project_root=tmp_path,
        receipt_store=RuntimeReceiptStore(project_root=tmp_path),
    )
    evidence_windows = _WindowManager(*[_bound() for _ in range(12)])
    screenshot = _ScreenshotService(tmp_path)
    evidence, *_ = _adapter(
        tmp_path,
        asset,
        manager=evidence_windows,
        screenshot=screenshot,
    )
    selected_window = SimpleNamespace(handle=4242, process_id=9001, is_active=True)
    windows = SimpleNamespace(bound=selected_window)
    windows.get_bound_window = lambda: windows.bound
    controllers: list[LiveController] = []
    backends: list[DeterministicFakeBackend] = []

    def build(binding):
        backend = DeterministicFakeBackend()
        controller = LiveController(
            binding=binding,
            asset_loader=assets,
            observation_source=evidence,
            target_resolver=evidence,
            gate=ReviewedWorkflowGateAdapter(),
            window_visibility_checker=_WindowVisibilityChecker(
                bound_window_handle=4242
            ),
            backend=backend,
            intent_claim_store=claims,
            grounding_policy={
                "minimum_confidence": 0.9,
                "minimum_score_margin": 0.2,
            },
        )
        controllers.append(controller)
        backends.append(backend)
        return controller

    service = LocalAgentRuntimeCallsite(
        project_root=tmp_path,
        asset_store=assets,
        window_manager=windows,
        claim_store=claims,
        controller_factory=build,
        selection=RuntimeSessionSelection(
            asset["asset_id"], content_sha256(asset), 4242, 9001
        ),
    )
    runtime = SimpleNamespace(
        service=service,
        evidence=evidence,
        screenshot=screenshot,
        controllers=controllers,
        backends=backends,
    )
    try:
        yield runtime
    finally:
        for controller in controllers:
            for session_id in list(controller._sessions):
                try:
                    controller.cancel_grounded_review(session_id=session_id)
                except (RuntimeError, ValueError):
                    controller.abandon_session(session_id=session_id)


def _pending(runtime):
    observation = runtime.service.start_session()
    action = next(
        item
        for item in observation.available_actions
        if item.semantic_action != "safe_stop"
    )
    request = AgentRuntimeIntentRequest(
        intent_id="intent.native-grounded-image",
        session_id=observation.session_id,
        observation_id=observation.observation_id,
        action_id=action.action_id,
    )
    pending = runtime.service.request_grounded_confirmation(request)
    return observation, pending


def test_callsite_reads_exact_cached_png_for_pending_and_approved_without_capture_or_dispatch(
    grounded_image_runtime,
) -> None:
    runtime = grounded_image_runtime
    observation, pending = _pending(runtime)
    grounded = pending.grounded_confirmation
    capture_calls = len(runtime.screenshot.calls)

    pending_png = runtime.service.get_local_grounded_image(
        confirmation_id=grounded.confirmation_id
    )
    approved = runtime.service.decide_grounded_confirmation(
        confirmation_id=grounded.confirmation_id,
        decision="approved",
    )
    approved_png = runtime.service.get_local_grounded_image(
        confirmation_id=grounded.confirmation_id
    )

    assert pending_png == approved_png == runtime.screenshot.paths[-1].read_bytes()
    assert sha256(pending_png).hexdigest() == (
        grounded.preview.to_dict()["grounding_preview"]["capture_lineage"]
        ["screenshot_sha256"]
    )
    assert len(runtime.screenshot.calls) == capture_calls
    assert runtime.backends[0].attempt_count == 0
    assert approved.phase == "grounded_confirmation_approved"
    runtime.service.cancel_grounded_review(session_id=observation.session_id)


def test_cached_image_reader_rejects_tampered_png_wrong_dimensions_and_cache_miss(
    grounded_image_runtime,
) -> None:
    runtime = grounded_image_runtime
    observation, pending = _pending(runtime)
    preview = pending.grounded_confirmation.preview.to_dict()
    grounding = preview["grounding_preview"]
    lineage = deepcopy(grounding["capture_lineage"])
    arguments = {
        "session_id": preview["session_id"],
        "asset_id": grounding["asset_id"],
        "asset_content_sha256": grounding["asset_content_sha256"],
        "target_window_handle": preview["target_window_handle"],
        "target_process_id": preview["target_process_id"],
        "capture_lineage": lineage,
    }
    capture_calls = len(runtime.screenshot.calls)

    wrong_dimensions = deepcopy(arguments)
    wrong_dimensions["capture_lineage"] = deepcopy(lineage)
    wrong_dimensions["capture_lineage"]["viewport_size"]["width"] += 1
    with pytest.raises(ValueError, match="image|cache|viewport"):
        runtime.evidence.read_cached_grounded_image(**wrong_dimensions)

    missing = deepcopy(arguments)
    missing["capture_lineage"] = deepcopy(lineage)
    missing["capture_lineage"]["capture_id"] = "runtime-capture.missing"
    with pytest.raises(ValueError, match="image|cache"):
        runtime.evidence.read_cached_grounded_image(**missing)

    image_path = runtime.screenshot.paths[-1]
    with Image.open(image_path) as image:
        changed = image.copy()
    changed.putpixel((0, 0), (255, 0, 0))
    changed.save(image_path, "PNG")
    with pytest.raises(ValueError, match="image|hash"):
        runtime.evidence.read_cached_grounded_image(**arguments)

    assert len(runtime.screenshot.calls) == capture_calls
    assert runtime.backends[0].attempt_count == 0
    runtime.service.cancel_grounded_review(session_id=observation.session_id)


@pytest.mark.parametrize("malformed", ["wrong_dimensions", "not_png"])
def test_cached_image_reader_validates_actual_png_material(
    grounded_image_runtime,
    malformed: str,
) -> None:
    runtime = grounded_image_runtime
    observation, pending = _pending(runtime)
    preview = pending.grounded_confirmation.preview.to_dict()
    grounding = preview["grounding_preview"]
    lineage = deepcopy(grounding["capture_lineage"])
    with runtime.evidence._lock:
        original = next(reversed(runtime.evidence._cache.values()))
    if malformed == "wrong_dimensions":
        buffer = BytesIO()
        Image.new("RGB", (321, 200), color=(10, 20, 30)).save(buffer, "PNG")
        material = buffer.getvalue()
    else:
        material = b"this is not a PNG"
    digest = sha256(material).hexdigest()
    Path(original.image_path).write_bytes(material)
    changed = replace(original, screenshot_sha256=digest)
    with runtime.evidence._lock:
        runtime.evidence._cache.clear()
        runtime.evidence._cache[
            (changed.session_id, changed.capture_id, changed.screenshot_sha256)
        ] = changed
    lineage["screenshot_sha256"] = digest

    with pytest.raises(ValueError, match="image|PNG|viewport"):
        runtime.evidence.read_cached_grounded_image(
            session_id=preview["session_id"],
            asset_id=grounding["asset_id"],
            asset_content_sha256=grounding["asset_content_sha256"],
            target_window_handle=preview["target_window_handle"],
            target_process_id=preview["target_process_id"],
            capture_lineage=lineage,
        )

    assert runtime.backends[0].attempt_count == 0
    runtime.service.cancel_grounded_review(session_id=observation.session_id)


def test_callsite_rejects_foreign_confirmation_before_cached_image_read(
    grounded_image_runtime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = grounded_image_runtime
    observation, _pending_claim = _pending(runtime)
    reads: list[dict] = []
    original = runtime.evidence.read_cached_grounded_image

    def tracked(**kwargs):
        reads.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(runtime.evidence, "read_cached_grounded_image", tracked)
    capture_calls = len(runtime.screenshot.calls)
    with pytest.raises(AgentRuntimeCallsiteError):
        runtime.service.get_local_grounded_image(
            confirmation_id="grounded-confirmation." + "f" * 64
        )

    assert reads == []
    assert len(runtime.screenshot.calls) == capture_calls
    assert runtime.backends[0].attempt_count == 0
    runtime.service.cancel_grounded_review(session_id=observation.session_id)
