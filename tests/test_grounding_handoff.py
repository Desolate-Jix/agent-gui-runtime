"""异步识别只持久化关联结果，不把候选冒充已派发动作。"""
import hashlib

from PIL import Image
import pytest

from app.vision.grounding_handoff import GroundingHandoffStore, GroundingHandoffError
from app.vision.recognition_source import ClientVisionCapabilities, RecognitionSourceConfig


@pytest.fixture
def handoff(tmp_path):
    frame = tmp_path / "frame.png"
    Image.new("RGB", (100, 80), "white").save(frame)
    store = GroundingHandoffStore(tmp_path, owner_id="connection-1")
    capture = {"capture_id": "capture-1", "image_path": str(frame),
        "sha256": hashlib.sha256(frame.read_bytes()).hexdigest(),
        "window_identity": {"handle": 100, "process_id": 200, "process_create_time": 1.5}}
    config = RecognitionSourceConfig(source="agent_current")
    caps = ClientVisionCapabilities(image_transport="supported", current_vision="supported")
    return store, capture, config, caps


def prepare(handoff):
    store, capture, config, caps = handoff
    return store.prepare("ground-1", goal="Search", capture=capture, configuration=config, capabilities=caps)


def found():
    return {"schema_version": "grounding.v1", "request_id": "ground-1", "capture_id": "capture-1",
        "status": "found", "coordinate_space": "capture_image_pixels",
        "image_size": {"width": 100, "height": 80},
        "candidates": [{"id": "one", "label": "Search", "bbox": {"x": 10, "y": 20, "width": 50, "height": 20},
            "click_point": {"x": 35, "y": 30}, "evidence_source": "agent_visual"}],
        "selected_candidate_id": "one"}


def test_prepare_returns_pending_without_input_or_local_models(handoff):
    pending = prepare(handoff)
    assert pending["phase"] == "awaiting_grounding"
    assert pending["input_dispatched"] is False
    assert pending["capture"]["image_size"] == {"width": 100, "height": 80}
    assert pending["configuration"]["source"] == "agent_current"
    assert pending["next_action"] == "inspect_image_and_submit_grounding"


def test_capture_diagnostics_survive_handoff_and_reopen(handoff):
    metadata = {"capture_visibility": {"allowed": True, "masked": True,
        "visible_fraction": 0.9, "occluded_regions": [{"x": 0, "y": 0, "width": 10, "height": 80}]},
        "capture_timings": {"total_ms": 42, "steps": []},
        "capture_purpose": "live-latency-observation", "roi": None,
        "window_size": {"width": 100, "height": 80}}
    handoff[1].update(metadata)
    handoff[1]["unrelated_private_field"] = "must not propagate"
    pending = prepare(handoff)
    for key, value in metadata.items():
        assert pending["capture"][key] == value
    assert "unrelated_private_field" not in pending["capture"]
    metadata["capture_visibility"]["allowed"] = False
    reopened = GroundingHandoffStore(handoff[0].session_root, owner_id="connection-1")
    assert reopened.get("ground-1")["capture"]["capture_visibility"]["allowed"] is True


def test_result_persists_across_store_reopen_but_is_not_execution(handoff):
    prepare(handoff)
    result = handoff[0].resolve("ground-1", found())
    reopened = GroundingHandoffStore(handoff[0].session_root, owner_id="connection-1")
    assert reopened.get("ground-1") == result
    assert result["phase"] == "grounding_ready"
    assert result["input_dispatched"] is False
    assert result["requires_live_revalidation"] is True
    assert result["next_action"] == "execute_via_common_action_entry"


def test_identical_prepare_and_result_are_idempotent(handoff):
    first = prepare(handoff)
    assert prepare(handoff) == first
    resolved = handoff[0].resolve("ground-1", found())
    assert prepare(handoff) == resolved
    assert handoff[0].resolve("ground-1", found()) == resolved


def test_conflicting_id_cannot_replace_original_intent(handoff):
    prepare(handoff)
    store, capture, config, caps = handoff
    with pytest.raises(GroundingHandoffError, match="request_conflict"):
        store.prepare("ground-1", goal="Cancel", capture=capture, configuration=config, capabilities=caps)
    assert store.get("ground-1")["goal"] == "Search"


def test_conflicting_result_does_not_replace_resolved_candidate(handoff):
    prepare(handoff)
    original = handoff[0].resolve("ground-1", found())
    changed = found()
    changed["candidates"][0]["click_point"]["x"] += 1
    with pytest.raises(GroundingHandoffError, match="result_conflict"):
        handoff[0].resolve("ground-1", changed)
    assert handoff[0].get("ground-1") == original


def test_cancel_rejects_late_result_and_does_not_revive(handoff):
    prepare(handoff)
    stopped = handoff[0].cancel("ground-1")
    assert stopped["phase"] == "cancelled"
    assert handoff[0].cancel("ground-1") == stopped
    with pytest.raises(GroundingHandoffError, match="request_cancelled"):
        handoff[0].resolve("ground-1", found())


def test_different_connection_cannot_adopt_pending_handoff(handoff):
    prepare(handoff)
    other = GroundingHandoffStore(handoff[0].session_root, owner_id="connection-2")
    with pytest.raises(GroundingHandoffError, match="owner_mismatch"):
        other.resolve("ground-1", found())


def test_caller_mutation_cannot_change_saved_capture(handoff):
    pending = prepare(handoff)
    handoff[1]["window_identity"]["handle"] = 999
    pending["capture"]["window_identity"]["handle"] = 888
    assert handoff[0].get("ground-1")["capture"]["window_identity"]["handle"] == 100


def test_modified_capture_cannot_resolve(handoff):
    prepare(handoff)
    Image.new("RGB", (100, 80), "black").save(handoff[1]["image_path"])
    with pytest.raises(GroundingHandoffError, match="capture_digest_mismatch"):
        handoff[0].resolve("ground-1", found())


def test_foreign_capture_is_rejected_without_copy(handoff, tmp_path):
    frame = tmp_path.parent / (tmp_path.name + "-foreign.png")
    Image.new("RGB", (100, 80)).save(frame)
    store, capture, config, caps = handoff
    capture["image_path"] = str(frame)
    with pytest.raises(GroundingHandoffError, match="capture_outside_session"):
        store.prepare("ground-1", goal="Search", capture=capture, configuration=config, capabilities=caps)


@pytest.mark.parametrize("request_id", ["../escape", "UPPER", "", "a" * 81])
def test_invalid_id_never_creates_request(handoff, request_id):
    store, capture, config, caps = handoff
    with pytest.raises(GroundingHandoffError, match="request_id_invalid"):
        store.prepare(request_id, goal="Search", capture=capture, configuration=config, capabilities=caps)


@pytest.mark.parametrize("status", ["absent", "unsupported", "error"])
def test_no_target_results_never_become_grounding_ready(handoff, status):
    prepare(handoff)
    result = found()
    result.update(status=status, candidates=[], selected_candidate_id=None)
    receipt = handoff[0].resolve("ground-1", result)
    assert receipt["phase"] == status
    assert receipt["input_dispatched"] is False


def test_invalid_schema_keeps_request_pending_for_diagnosis(handoff):
    prepare(handoff)
    bad = found()
    bad["capture_id"] = "another-frame"
    with pytest.raises(GroundingHandoffError, match="grounding_invalid"):
        handoff[0].resolve("ground-1", bad)
    assert handoff[0].get("ground-1")["phase"] == "awaiting_grounding"


def test_unsupported_route_does_not_create_request(handoff):
    store, capture, config, _ = handoff
    with pytest.raises(GroundingHandoffError, match="vision_unsupported"):
        store.prepare("ground-1", goal="Search", capture=capture, configuration=config,
                      capabilities=ClientVisionCapabilities(current_vision="unsupported"))
    assert not (store.session_root / "grounding" / "ground-1.json").exists()


def test_agent_cannot_claim_local_provider_provenance(handoff):
    prepare(handoff)
    result = found()
    result["candidates"][0]["evidence_source"] = "local_visual"
    with pytest.raises(GroundingHandoffError, match="source_mismatch"):
        handoff[0].resolve("ground-1", result)


def test_expired_result_is_not_reactivated(handoff):
    now = [1000.0]
    store = GroundingHandoffStore(handoff[0].session_root, owner_id="connection-1",
                                 clock=lambda: now[0], ttl_seconds=10)
    prepare((store, *handoff[1:]))
    now[0] += 11
    with pytest.raises(GroundingHandoffError, match="request_expired"):
        store.resolve("ground-1", found())
    assert store.get("ground-1")["phase"] == "expired"


def test_identical_receipt_retry_survives_frame_change_and_capability_change(handoff):
    prepare(handoff)
    store, capture, config, caps = handoff
    resolved = store.resolve("ground-1", found())
    Image.new("RGB", (100, 80), "black").save(capture["image_path"])
    assert store.resolve("ground-1", found()) == resolved
    assert store.prepare("ground-1", goal="Search", capture=capture, configuration=config,
                         capabilities=ClientVisionCapabilities()) == resolved


def test_ambiguous_candidates_expire_too(handoff):
    now = [1000.0]
    store = GroundingHandoffStore(handoff[0].session_root, owner_id="connection-1",
                                 clock=lambda: now[0], ttl_seconds=10)
    prepare((store, *handoff[1:]))
    result = found()
    result["status"] = "ambiguous"
    result["selected_candidate_id"] = None
    result["candidates"].append({**result["candidates"][0], "id": "two"})
    store.resolve("ground-1", result)
    now[0] += 11
    assert store.get("ground-1")["phase"] == "expired"


def test_execution_claim_is_durable_and_never_replayed(handoff):
    prepare(handoff)
    store = handoff[0]
    store.resolve("ground-1", found())
    claimed = store.claim_execution("ground-1", "execute-1")
    assert claimed["phase"] == "executing"
    reopened = GroundingHandoffStore(store.session_root, owner_id="connection-1")
    for execution_id in ("execute-1", "execute-2"):
        with pytest.raises(GroundingHandoffError, match="execution_already_claimed"):
            reopened.claim_execution("ground-1", execution_id)
    with pytest.raises(GroundingHandoffError, match="execution_already_claimed"):
        store.cancel("ground-1")
    receipt = {"phase": "returned", "response": {"success": True}}
    done = store.finish_execution("ground-1", "execute-1", receipt, input_attempted=True)
    assert done["phase"] == "completed"
    assert done["input_attempted"] is True
    assert done["input_dispatched"] is None
    assert done["execution_result"] == receipt
    with pytest.raises(GroundingHandoffError, match="execution_already_claimed"):
        store.claim_execution("ground-1", "execute-3")
    assert store.finish_execution("ground-1", "execute-1", receipt, input_attempted=True) == done


@pytest.mark.parametrize("phase", ["awaiting_grounding", "absent", "cancelled", "expired"])
def test_execution_requires_ready_state(handoff, phase):
    prepare(handoff)
    store = handoff[0]
    if phase == "absent":
        result = found()
        result.update(status="absent", candidates=[], selected_candidate_id=None)
        store.resolve("ground-1", result)
    elif phase == "cancelled":
        store.cancel("ground-1")
    elif phase == "expired":
        store._clock = lambda: float("inf")
    with pytest.raises(GroundingHandoffError, match="execution_not_ready"):
        store.claim_execution("ground-1", "execute-1")


def test_execution_claim_rechecks_frame_and_finish_cannot_be_forged(handoff):
    prepare(handoff)
    store = handoff[0]
    store.resolve("ground-1", found())
    with pytest.raises(GroundingHandoffError, match="execution_not_owned"):
        store.finish_execution("ground-1", "execute-1", {}, input_attempted=False)
    Image.new("RGB", (100, 80), "black").save(handoff[1]["image_path"])
    with pytest.raises(GroundingHandoffError, match="capture_digest_mismatch"):
        store.claim_execution("ground-1", "execute-1")
