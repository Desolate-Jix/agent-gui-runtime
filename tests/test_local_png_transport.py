"""可信本地原图的有界出站传输不改变外部上传权限。"""

from __future__ import annotations

import base64
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
from threading import Lock
from types import SimpleNamespace

from PIL import Image
import pytest

from app.agent_link import contracts, mcp_bridge
from app.desktop_review import interface_relearning_gateway, learning_observation


LOCAL_PNG_LIMIT = 32 * 1024 * 1024
LOCAL_RESPONSE_LIMIT = 48 * 1024 * 1024


@pytest.fixture(scope="module")
def large_png():
    stream = BytesIO()
    Image.new("RGB", (1536, 1536), (17, 38, 59)).save(stream, format="PNG", compress_level=0)
    raw = stream.getvalue()
    assert 2 * 1024 * 1024 < len(raw) < LOCAL_PNG_LIMIT
    return raw


def _screenshot(raw):
    with Image.open(BytesIO(raw)) as image:
        width, height = image.size
    return {"mime_type": "image/png", "sha256": sha256(raw).hexdigest(),
            "width": width, "height": height,
            "png_base64": base64.b64encode(raw).decode("ascii")}


def _response(family, raw):
    screenshot = _screenshot(raw)
    if family == "reviewed":
        return {
            "contract_version": "agent_reviewed_learning_action_v1",
            "segment_id": "segment.synthetic", "preparation_id": "preparation.synthetic",
            "intent_id": "intent.synthetic", "action_id": "action.synthetic",
            "phase": "terminal", "claim_phase": "terminal",
            "receipt": {"status": "unavailable", "reason_code": "terminal_not_committed"},
            "after_observation": {"status": "available", "observation_id": "observation.synthetic",
                                  "capture_id": "capture.synthetic", "screenshot": screenshot},
            "artifact_is_authorization": False, "operation_dispatches_input": False,
            "execution_ready": False,
        }
    if family == "fresh":
        return {"contract_version": "agent_fresh_learning_runtime_v1", "screenshot": screenshot,
                "artifact_is_authorization": False, "operation_dispatches_input": False,
                "execution_ready": False}
    result = {"contract_version": "agent_learning_observation_v1", "screenshot": screenshot,
              "artifact_is_authorization": False, "execute_binding_enabled": False,
              "action_executed": False}
    if family == "relearning":
        result.update(contract_version="agent_interface_relearning_v1", issue={}, baseline={}, candidates=[])
    return result


@pytest.mark.parametrize("family", ["observation", "fresh", "reviewed", "relearning"])
def test_large_local_original_is_exact_and_not_duplicated_in_metadata(family, large_png):
    source = _response(family, large_png)
    original = deepcopy(source)
    result = mcp_bridge._observation_mcp_result(source)
    image = next(item for item in result.content if item.type == "image")
    assert base64.b64decode(image.data, validate=True) == large_png
    assert source == original
    text = next(item.text for item in result.content if item.type == "text")
    assert image.data not in text
    assert "png_base64" not in text
    metadata = result.structured_content
    screenshot = metadata["after_observation"]["screenshot"] if family == "reviewed" else metadata["screenshot"]
    assert screenshot == {key: value for key, value in _screenshot(large_png).items() if key != "png_base64"}


@pytest.mark.parametrize("family", ["observation", "fresh", "reviewed", "relearning"])
@pytest.mark.parametrize("changed", ["sha256", "dimensions", "authority", "format"])
def test_large_local_original_retains_image_and_authority_checks(family, changed, large_png):
    response = _response(family, large_png)
    screenshot = response["after_observation"]["screenshot"] if family == "reviewed" else response["screenshot"]
    if changed == "sha256":
        screenshot["sha256"] = "0" * 64
    elif changed == "dimensions":
        screenshot["width"] += 1
    elif changed == "authority":
        response["artifact_is_authorization"] = True
    else:
        screenshot.update(png_base64=base64.b64encode(b"not PNG").decode("ascii"),
                          sha256=sha256(b"not PNG").hexdigest())
    with pytest.raises(RuntimeError, match="observation response is invalid"):
        mcp_bridge._observation_mcp_result(response)


def test_local_decoder_checks_encoded_budget_before_allocating(monkeypatch, large_png):
    assert contracts.MAX_LOCAL_PNG_BYTES == LOCAL_PNG_LIMIT
    monkeypatch.setattr(contracts, "MAX_LOCAL_PNG_BYTES", len(large_png) - 1)
    response = _response("observation", large_png)
    response["screenshot"]["png_base64"] += "AAAA"
    monkeypatch.setattr(base64, "b64decode", lambda *args, **kwargs: pytest.fail("over-budget data must not be decoded"))
    with pytest.raises(RuntimeError, match="observation response is invalid"):
        mcp_bridge._observation_mcp_result(response)


def test_local_decoder_checks_decoded_budget_even_with_same_base64_length(monkeypatch, large_png):
    monkeypatch.setattr(contracts, "MAX_LOCAL_PNG_BYTES", len(large_png) - 1)
    assert 4 * ((len(large_png) + 2) // 3) == 4 * ((len(large_png) + 1) // 3)
    with pytest.raises(RuntimeError, match="observation response is invalid"):
        mcp_bridge._observation_mcp_result(_response("observation", large_png))


def test_decoded_image_over_actual_32_mib_limit_is_rejected_before_hash(monkeypatch, large_png):
    import hashlib

    response = _response("observation", large_png)
    encoded_size = 4 * ((LOCAL_PNG_LIMIT + 2) // 3)
    assert encoded_size // 4 * 3 == LOCAL_PNG_LIMIT + 1
    response["screenshot"]["png_base64"] = "A" * encoded_size
    monkeypatch.setattr(hashlib, "sha256", lambda *args: pytest.fail("over-budget bytes must be rejected before hashing"))
    with pytest.raises(RuntimeError, match="observation response is invalid"):
        mcp_bridge._observation_mcp_result(response)


@pytest.mark.parametrize("operation", ["observe_learning_screen", "get_learning_action_result",
    "prepare_fresh_learning_runtime", "request_fresh_learning_action", "get_fresh_learning_runtime",
    "cancel_fresh_learning_runtime", "get_interface_relearning_feedback"])
def test_local_image_responses_use_shared_bounded_transport_budget(operation):
    assert mcp_bridge._response_limit(operation) == LOCAL_RESPONSE_LIMIT


@pytest.mark.parametrize("operation", ["status", "get_learning_runtime", "submit_batch",
    "submit_interface_relearning_candidate", "list_interface_relearning_feedback"])
def test_other_response_budgets_remain_unchanged(operation):
    assert mcp_bridge._response_limit(operation) == 2_500_000


def test_transport_reads_bounded_large_image_response_and_keeps_request_limit(monkeypatch, large_png):
    source = _response("observation", large_png)
    raw = json.dumps(source).encode("utf-8")
    assert 8_000_000 < len(raw) < LOCAL_RESPONSE_LIMIT
    reads = []

    class Response(BytesIO):
        def read(self, size=-1):
            reads.append(size)
            return super().read(size)

    def open_response(request, timeout):
        assert request.data == b"{}"
        return Response(raw)

    monkeypatch.setattr(mcp_bridge, "build_opener", lambda *args: SimpleNamespace(open=open_response))
    assert mcp_bridge._call("http://127.0.0.1:9000", "synthetic-token-12345", "observe_learning_screen", {}) == source
    assert reads == [LOCAL_RESPONSE_LIMIT + 1]
    with pytest.raises(RuntimeError, match="request exceeds limit"):
        mcp_bridge._call("http://127.0.0.1:9000", "synthetic-token-12345", "observe_learning_screen", {"data": "x" * 2_500_000})
    assert reads == [LOCAL_RESPONSE_LIMIT + 1]


def test_transport_rejects_response_above_shared_budget(monkeypatch):
    assert contracts.MAX_LOCAL_IMAGE_RESPONSE_BYTES == LOCAL_RESPONSE_LIMIT
    monkeypatch.setattr(mcp_bridge, "MAX_LOCAL_IMAGE_RESPONSE_BYTES", 1024)
    reads = []

    class Response(BytesIO):
        def read(self, size=-1):
            reads.append(size)
            return super().read(size)

    monkeypatch.setattr(mcp_bridge, "build_opener", lambda *args: SimpleNamespace(
        open=lambda *args, **kwargs: Response(b"x" * 2048)))
    with pytest.raises(RuntimeError, match="service response exceeds limit"):
        mcp_bridge._call("http://127.0.0.1:9000", "synthetic-token-12345", "observe_learning_screen", {})
    assert reads == [1025]


def _provider(raw):
    screenshot = _screenshot(raw)
    packet = SimpleNamespace(png_bytes=raw, evidence=lambda: {"capture": {
        "screenshot_sha256": screenshot["sha256"],
        "viewport_size": {"width": screenshot["width"], "height": screenshot["height"]}}})
    provider = object.__new__(learning_observation.LearningObservationProvider)
    provider._capture_guard = Lock()
    provider._managed_observer = lambda **kwargs: packet
    provider.source_owner = SimpleNamespace(
        segments=SimpleNamespace(get=lambda **kwargs: {"status": "active", "observations": []},
                                 store=SimpleNamespace(read=lambda reader: reader({"batches": {}}))),
        stage=lambda **kwargs: {"batch_id": "batch.synthetic", "source": {"reference": "archive.synthetic"},
                               "artifact_is_authorization": False, "execute_binding_enabled": False,
                               "action_executed": False},
        facade=SimpleNamespace(import_interface_content=lambda *args: {"interface_id": "interface.synthetic"}))
    return provider


def _observe(provider):
    return provider.observe(connection_id="connection.synthetic", task_id="task.synthetic",
        segment_id="segment.synthetic", idempotency_key="observe.synthetic",
        application_identity={"kind": "web", "canonical_origin": "https://synthetic.example"},
        target_window_handle=100, target_process_id=200, title="Synthetic", meaning="Synthetic local evidence",
        goal="Inspect synthetic page")


def test_observation_provider_emits_one_large_original_with_bounded_metadata(large_png):
    response = _observe(_provider(large_png))
    encoded = base64.b64encode(large_png).decode("ascii")
    serialized = json.dumps(response).encode("utf-8")
    assert 8_000_000 < len(serialized) < LOCAL_RESPONSE_LIMIT
    assert serialized.count(encoded.encode("ascii")) == 1
    assert response["screenshot"]["png_base64"] == encoded


def test_observation_provider_retains_total_response_budget(monkeypatch, large_png):
    monkeypatch.setattr(learning_observation, "MAX_OBSERVATION_RESPONSE_BYTES", 1000)
    with pytest.raises(contracts.AgentLinkError) as error:
        _observe(_provider(large_png))
    assert error.value.code == "observation_too_large"


def _gateway(tmp_path, raw):
    image_path = tmp_path / "verified-local.png"
    image_path.write_bytes(raw)
    screenshot = _screenshot(raw)
    evidence = {key: screenshot[key] for key in ("sha256", "width", "height")}
    evidence["image_path"] = "verified-local.png"
    calls = []
    issue = {"task_id": "task.synthetic", "issue_id": "issue.synthetic", "interface_id": "interface.synthetic",
             "baseline_revision": 1, "baseline_content_sha256": "1" * 64, "region_ids": [],
             "message": "Synthetic feedback", "status": "open", "candidate_ids": [], "issue_sha256": "2" * 64}

    def load_evidence(interface_id, version_id):
        calls.append((interface_id, version_id))
        return deepcopy(evidence)

    gateway = object.__new__(interface_relearning_gateway.InterfaceRelearningGateway)
    gateway.service = SimpleNamespace(read=lambda issue_id: deepcopy(issue))
    gateway.facade = SimpleNamespace(get_interface_memory=lambda *args: {"version_id": args[-1]},
        load_interface_content_evidence=load_evidence, _artifact_file=lambda *args: image_path)
    return gateway, evidence, calls


def test_relearning_emits_only_verified_pinned_local_original(tmp_path, large_png):
    gateway, evidence, calls = _gateway(tmp_path, large_png)
    response = gateway.get("task.synthetic", "issue.synthetic")
    assert calls == [("interface.synthetic", "interface-version-" + "1" * 64)]
    assert base64.b64decode(response["screenshot"]["png_base64"], validate=True) == large_png
    assert response["screenshot"]["sha256"] == evidence["sha256"]
    assert "image_path" not in json.dumps(response)
    assert all(response[key] is False for key in ("artifact_is_authorization", "execute_binding_enabled", "action_executed"))
    mcp_bridge._observation_mcp_result(response)


@pytest.mark.parametrize("changed", ["sha256", "size", "task"])
def test_relearning_keeps_local_source_and_ownership_checks(tmp_path, monkeypatch, large_png, changed):
    gateway, evidence, calls = _gateway(tmp_path, large_png)
    if changed == "sha256":
        evidence["sha256"] = "0" * 64
    elif changed == "size":
        monkeypatch.setattr(interface_relearning_gateway, "MAX_LOCAL_PNG_BYTES", len(large_png) - 1)
    expected = contracts.AgentLinkError if changed == "task" else interface_relearning_gateway.DesktopReviewError
    with pytest.raises(expected):
        gateway.get("foreign.synthetic" if changed == "task" else "task.synthetic", "issue.synthetic")
    if changed == "task":
        assert calls == []


def test_external_batch_png_limit_does_not_inherit_local_output_budget():
    assert contracts.MAX_PNG_BYTES == 2 * 1024 * 1024
    stream = BytesIO()
    Image.new("RGB", (1024, 768), (17, 38, 59)).save(stream, format="PNG", compress_level=0)
    raw = stream.getvalue()
    assert contracts.MAX_PNG_BYTES < len(raw)
    batch = {"contract_version": "agent_link_v1", "idempotency_key": "external.synthetic",
        "batch_id": "batch.synthetic", "title": "Synthetic external batch", "learning_outcome": "partial",
        "outcome_reason": "Synthetic negative control",
        "screenshots": [{"screenshot_id": "screenshot.synthetic", "png_base64": base64.b64encode(raw).decode("ascii")}],
        "interfaces": [{"interface_id": "interface.synthetic", "screenshot_id": "screenshot.synthetic",
                        "meaning": "Synthetic", "regions": []}],
        "relationships": [], "steps": [], "issues": []}
    with pytest.raises(contracts.AgentLinkError) as error:
        contracts.validate_batch(batch)
    assert error.value.code == "invalid_png"
