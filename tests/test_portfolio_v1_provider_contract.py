from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

from PIL import Image
import pytest

from app.learn.draft_review import load_learning_draft_review
from app.learn.recognition.uei.canonical import seal_immutable
from app.learn.recognition.uei.provider_adapters import (
    ProviderRunBudget,
    RestrictedCaptureLease,
    TrustedProviderAdapterRegistry,
)
from app.learn.recognition.uei.provider_runtime import ShadowProviderRuntime
from app.learn.recognition.uei.store import UEIObjectStore
from app.learn.workflow_contracts import RecognitionTaskInput
from app.learn.workflow_tasks.recognition import (
    _attach_uei_shadow_result_ref_to_draft,
    run_recognition_task,
)
from app.operation.observe.contracts import (
    ObserveScreenReadResult,
    ObserveScreenTaskInput,
)
from app.learn.workflow_tasks.observe import run_observe_task


_FIXTURES = Path(__file__).parent / "fixtures" / "uei-v1"
_PROOF = Path(__file__).parents[1] / "release" / "portfolio-v1" / "provider-contract-proof.json"


def _fixture(name: str) -> dict[str, object]:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _put(store: UEIObjectStore, value: dict[str, object]) -> dict[str, str]:
    return store.put(seal_immutable(value))

def test_fixed_builtin_capture_can_be_sealed_as_review_only_uei(tmp_path: Path) -> None:
    from app.learn.recognition.uei.builtin_learning_projection import (
        seal_builtin_ocr_evidence,
    )

    image_path = tmp_path / "captures" / "fixed.png"
    image_path.parent.mkdir()
    Image.new("RGB", (8, 6), color=(10, 20, 30)).save(image_path)

    result_ref = seal_builtin_ocr_evidence(
        project_root=tmp_path,
        image_path=image_path,
        capture_id="capture/portfolio-v1/fixed",
        captured_at="2026-08-22T00:00:00Z",
        ocr_result={"image_path": "client-supplied-path-must-not-be-trusted.png", **_fixture("portfolio-v1-builtin-fixed-output.json")},
    )

    assert set(result_ref) == {"id", "content_sha256"}

    task = run_recognition_task(
        RecognitionTaskInput(
            app_name="portfolio_builtin",
            state_hint="job_detail",
            observation_evidence={
                "screen_size": {"width": 8, "height": 6},
                "uei_shadow_result_ref": result_ref,
            },
        ),
        project_root=tmp_path,
        trial_builder=lambda **_kwargs: {
            "status": "ready",
            "screen_inventory": [],
            "classification": {"summary": {}},
            "learning_draft": {
                "workflow_draft": {
                    "states": [],
                    "action_templates": [],
                    "verification_rules": [],
                },
                "interface_draft": {"regions": []},
                "blockers": [],
                "safety": {},
            },
        },
        grounding_adapter=lambda **_kwargs: {},
        trace_writer=lambda **_kwargs: "logs/traces/provider-contract.json",
    )

    assert task.outcome == "completed"
    trial_path = tmp_path / str(task.payload["trial_path"])
    review = load_learning_draft_review(trial_path, project_root=tmp_path)
    summary = review["uei_shadow_provider_summary"]
    assert summary["provider_id"] == "local.runtime/builtin-ocr"
    assert summary["status"] == "success"
    assert summary["review_only"] is True
    assert summary["execution_authorized"] is False
    assert summary["action_candidates"] == []


def test_builtin_projection_rejects_path_escape_and_server_capture_mismatch(tmp_path: Path) -> None:
    from app.learn.recognition.uei.builtin_learning_projection import seal_builtin_ocr_evidence

    outside = tmp_path.parent / "outside.png"
    Image.new("RGB", (2, 2), color=(1, 2, 3)).save(outside)
    fixture = _fixture("portfolio-v1-builtin-fixed-output.json")
    with pytest.raises(ValueError, match="inside project root"):
        seal_builtin_ocr_evidence(project_root=tmp_path, image_path=outside, capture_id="capture/outside",
                                  captured_at="2026-08-22T00:00:00Z", ocr_result=fixture)

    inside = tmp_path / "inside.png"
    Image.new("RGB", (2, 2), color=(1, 2, 3)).save(inside)
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        seal_builtin_ocr_evidence(project_root=tmp_path, image_path=inside, capture_id="capture/mismatch",
                                  captured_at="2026-08-22T00:00:00Z", ocr_result=fixture,
                                  expected_image_sha256="0" * 64)
    with pytest.raises(ValueError, match="dimensions mismatch"):
        seal_builtin_ocr_evidence(project_root=tmp_path, image_path=inside, capture_id="capture/mismatch-size",
                                  captured_at="2026-08-22T00:00:00Z", ocr_result=fixture,
                                  expected_image_size={"width": 3, "height": 2})


def test_observe_owner_mints_only_a_server_checked_builtin_ref(tmp_path: Path) -> None:
    from app.api.vision import _attach_server_owned_builtin_uei_ref

    image = tmp_path / "capture.png"
    Image.new("RGB", (8, 6), color=(10, 20, 30)).save(image)
    observed: dict[str, object] = {
        "image_path": str(image),
        "live_capture": {
            "capture_id": "capture/server-owned",
            "captured_at": "2026-08-22T00:00:00Z",
            "sha256": sha256(image.read_bytes()).hexdigest(),
            "image_size": {"width": 8, "height": 6},
        },
        "ocr_result": _fixture("portfolio-v1-builtin-fixed-output.json"),
    }
    _attach_server_owned_builtin_uei_ref(observed, project_root=tmp_path)
    reference = observed["uei_shadow_result_ref"]
    assert isinstance(reference, dict)
    assert set(reference) == {"id", "content_sha256"}
    assert "ocr_result" in observed
    assert "items" not in reference and "source_bbox" not in reference


def test_normal_live_capture_is_enriched_and_observed_texts_mint_uei_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.vision import (
        VisionObserveScreenRequestModel,
        _attach_server_owned_builtin_uei_ref,
        _learning_observe_image_source,
    )

    image = tmp_path / "artifacts" / "screenshots" / "live.png"
    image.parent.mkdir(parents=True)
    Image.new("RGB", (8, 6), color=(10, 20, 30)).save(image)
    monkeypatch.setattr(
        "app.api.vision.screenshot_service.capture_window",
        lambda **_kwargs: {"image_path": str(image), "image_width": 8, "image_height": 6,
                            "roi": None, "window_size": {"width": 8, "height": 6}},
    )
    request = VisionObserveScreenRequestModel(capture_live=True, agent_mode="learn")
    image_path, live_capture = _learning_observe_image_source(request)
    result = run_observe_task(
        ObserveScreenTaskInput.model_validate(request.model_dump()),
        project_root=tmp_path,
        image_source_resolver=lambda _task: (image_path, live_capture),
        screen_reader=lambda _read: ObserveScreenReadResult(
            success=True, message="ok", payload={"image_path": image_path, "texts": [{
                "id": "text/1", "text": "Quick Apply", "bbox": {"x": 1, "y": 1, "width": 4, "height": 2},
                "confidence": 0.9, "source": "ocr", "source_index": 0,
            }]}, error=None, model_io=None,
        ),
        trace_writer=lambda **_kwargs: "logs/observe.json",
    )
    assert result.outcome == "completed"
    observed = result.payload
    _attach_server_owned_builtin_uei_ref(observed, project_root=tmp_path)
    reference = observed["uei_shadow_result_ref"]
    assert set(reference) == {"id", "content_sha256"}
    assert observed["live_capture"]["capture_id"].startswith("capture/builtin/")
    assert observed["live_capture"]["sha256"] == sha256(image.read_bytes()).hexdigest()


def test_execute_mode_observe_route_does_not_store_learning_uei_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.vision as vision

    image = tmp_path / "artifacts" / "screenshots" / "route-live.png"
    image.parent.mkdir(parents=True)
    Image.new("RGB", (8, 6), color=(10, 20, 30)).save(image)
    module_path = tmp_path / "app" / "api" / "vision.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text("# test root\n", encoding="utf-8")
    monkeypatch.setattr(vision, "__file__", str(module_path))
    monkeypatch.setattr(
        vision.screenshot_service,
        "capture_window",
        lambda **_kwargs: {"image_path": str(image), "image_width": 8, "image_height": 6,
                            "roi": None, "window_size": {"width": 8, "height": 6}},
    )
    monkeypatch.setattr(
        vision,
        "screen_reading",
        lambda _request: vision.APIResponse(
            success=True, message="ok", data={"result": {"image_path": str(image), "texts": [{
                "id": "text/1", "text": "Quick Apply", "bbox": {"x": 1, "y": 1, "width": 4, "height": 2},
                "confidence": 0.9, "source": "ocr", "source_index": 0,
            }]}}, error=None,
        ),
    )
    response = vision.observe_screen(vision.VisionObserveScreenRequestModel(capture_live=True, agent_mode="execute"))
    assert response.success is True
    observed = response.data["result"]
    assert "uei_shadow_result_ref" not in observed
    assert "capture_id" not in observed["live_capture"]


def test_shared_capture_source_does_not_enrich_non_learning_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.vision as vision

    image = tmp_path / "locate.png"
    Image.new("RGB", (2, 2), color=(1, 2, 3)).save(image)
    monkeypatch.setattr(vision.screenshot_service, "capture_window", lambda **_kwargs: {"image_path": str(image)})
    monkeypatch.setattr(
        vision,
        "_enrich_server_owned_live_capture",
        lambda _capture: (_ for _ in ()).throw(AssertionError("non-learning path must not enrich")),
    )
    image_path, capture = vision._image_path_for_live_or_saved(
        capture_live=True, image_path=None, purpose="locate_target", app_name="sample",
    )
    assert image_path == str(image.resolve())
    assert capture == {"image_path": str(image)}


def test_incomplete_or_stale_capture_never_mints_a_uei_ref(tmp_path: Path) -> None:
    from app.api.vision import _attach_server_owned_builtin_uei_ref

    image = tmp_path / "capture.png"
    Image.new("RGB", (8, 6), color=(10, 20, 30)).save(image)
    base: dict[str, object] = {
        "image_path": str(image),
        "texts": [{"text": "Quick Apply", "bbox": {"x": 1, "y": 1, "width": 4, "height": 2}, "confidence": 0.9}],
        "live_capture": {"capture_id": "capture/builtin/test", "captured_at": "2026-08-22T00:00:00Z",
                         "sha256": sha256(image.read_bytes()).hexdigest(), "image_size": {"width": 8, "height": 6}},
    }
    incomplete = {**base, "live_capture": {"capture_id": "capture/incomplete"}}
    _attach_server_owned_builtin_uei_ref(incomplete, project_root=tmp_path)
    assert "uei_shadow_result_ref" not in incomplete
    stale = {**base, "live_capture": {**base["live_capture"], "sha256": "0" * 64}}
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        _attach_server_owned_builtin_uei_ref(stale, project_root=tmp_path)
    assert "uei_shadow_result_ref" not in stale


def test_tracked_provider_contract_proof_is_honest_and_reverifiable() -> None:
    script_source = (Path(__file__).parents[1] / "scripts" / "build_portfolio_v1_provider_contract_proof.py").read_text(encoding="utf-8")
    assert "tests/test_" not in script_source
    assert "_test_support" not in script_source
    proof = json.loads(_PROOF.read_text(encoding="utf-8"))
    assert proof["fixed_or_recorded_evidence"] is True
    assert proof["live_omniparser_inference"] is False
    assert proof["execution_authorized"] is False
    assert proof["provider_accuracy_proven"] is False
    for case in ("success", "failure"):
        receipt = proof["recorded_omniparser"][case]
        assert receipt["receipt_contract"] == "provider_runtime_receipt_v1"
        assert receipt["result_contract"] == "provider_safe_result_v1"
        assert str(receipt["fixture"]).startswith("tests/fixtures/uei-v1/portfolio-v1-")
        assert receipt["reverify"] == "uv run python scripts/build_portfolio_v1_provider_contract_proof.py"
        assert set(receipt["receipt_ref"]) == {"id", "content_sha256"}
        assert set(receipt["result_ref"]) == {"id", "content_sha256"}
        assert receipt["reference_resolution"] == "generated_rebuilt_at_test_not_directly_resolvable"
    assert set(proof["recorded_omniparser"]["failure"]["error_ref"]) == {"id", "content_sha256"}


def test_provider_contract_proof_script_rebuilds_identical_bytes_without_test_imports() -> None:
    script = Path(__file__).parents[1] / "scripts" / "build_portfolio_v1_provider_contract_proof.py"
    subprocess.run([sys.executable, str(script)], check=True, cwd=script.parents[1])
    first = _PROOF.read_bytes()
    subprocess.run([sys.executable, str(script)], check=True, cwd=script.parents[1])
    assert _PROOF.read_bytes() == first


class _RecordedProcess:
    pid = 1
    _uei_fake_process = True

    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.returncode = 0

    def poll(self) -> int:
        return self.returncode

    def kill(self) -> None:
        self.returncode = -9

    def wait(self, timeout: float) -> int:
        del timeout
        return self.returncode


def _recorded_popen(process: _RecordedProcess):
    def spawn(command: list[str], **_kwargs: object) -> _RecordedProcess:
        output_path = Path(command[command.index("--output-json") + 1])
        output_path.write_text(json.dumps(process.payload), encoding="utf-8")
        return process
    return spawn


def _omni_configuration(tmp_path: Path):
    from app.learn.recognition.uei.omniparser_shadow_adapter import TrustedOmniParserConfiguration

    interpreter = tmp_path / "recorded-python.exe"
    worker = tmp_path / "recorded-worker.py"
    code, weights, cache = tmp_path / "code", tmp_path / "weights", tmp_path / "cache"
    interpreter.write_text("recorded", encoding="utf-8")
    worker.write_text("recorded", encoding="utf-8")
    for directory in (code, weights, cache):
        directory.mkdir()
    return TrustedOmniParserConfiguration(
        interpreter=interpreter, worker_script=worker, code_path=code,
        weights_path=weights, cache_path=cache, minimum_free_gpu_gib=0,
    )


def _recorded_omni_runtime(tmp_path: Path, *, worker_payload: object):
    from app.learn.recognition.uei.omniparser_shadow_adapter import (
        OmniParserShadowAdapter,
        PROFILE_ID,
        PROVIDER_ID,
        PROVIDER_VERSION,
    )

    store = UEIObjectStore(root=tmp_path / "artifacts" / "uei-shadow-store")
    image = tmp_path / "capture.png"
    Image.new("RGB", (8, 6), color=(10, 20, 30)).save(image)
    image_hash = sha256(image.read_bytes()).hexdigest()
    artifact_ref = _put(store, {"contract_version": "artifact_ref_v1", "artifact_id": "artifact/recorded/omni",
                                "artifact_sha256": image_hash, "media_type": "image/png", "byte_length": image.stat().st_size, "restricted": True})
    capture_ref = _put(store, {"contract_version": "capture_lineage_v1", "capture_id": "capture/recorded/omni",
                               "artifact_ref": artifact_ref, "artifact_sha256": image_hash, "image_size": {"width": 8, "height": 6},
                               "capture_coordinate_space": "capture_pixel_xyxy", "captured_at": "2026-08-22T00:00:00Z"})
    request_ref = _put(store, {"contract_version": "screen_parse_request_v1", "request_id": "request/recorded/omni",
                               "capture_lineage_ref": capture_ref, "requested_profiles": [{"provider_id": PROVIDER_ID, "profile_id": PROFILE_ID, "mode": "Shadow"}],
                               "privacy_policy": "restricted", "requester_id": "server"})
    registration_ref = _put(store, {"contract_version": "trusted_provider_registration_v1", "registration_id": "registration/recorded/omni",
                                    "provider_id": PROVIDER_ID, "profile_ids": [PROFILE_ID], "enabled": True, "allowed_modes": ["Shadow"],
                                    "allowed_privacy_policies": ["restricted"], "egress_policy": "local_only", "wire_payload_policy": "restricted_store_only",
                                    "safe_payload_limits": {"max_json_bytes": 4096, "max_depth": 8, "max_array_items": 16, "max_object_properties": 32, "max_string_chars": 256,
                                                            "allowed_json_types": ["object", "array", "string", "number", "boolean", "null"]},
                                    "required_conformance_suite": "uei-v1-static-projection"})
    manifest_ref = _put(store, {"contract_version": "provider_manifest_v1", "manifest_id": "manifest/recorded/omni", "provider_id": PROVIDER_ID,
                                "provider_version": PROVIDER_VERSION, "profiles": [{"profile_id": PROFILE_ID, "operation": "screen_parse",
                                "input_contract": "screen_parse_request_v1", "output_contract": "provider_safe_result_v1", "declared_output_kinds": ["text"],
                                "supported_coordinate_spaces": ["capture_pixel_xyxy"], "supports_capture_artifact": True,
                                "privacy_capabilities": ["restricted"], "mode_allowlist": ["Shadow"]}]})
    adapter = OmniParserShadowAdapter(configuration=_omni_configuration(tmp_path), gpu_free_gib=lambda: 99)
    runtime = ShadowProviderRuntime(store=store, registry=TrustedProviderAdapterRegistry([adapter]),
                                    trusted_profiles={(PROVIDER_ID, PROFILE_ID): (registration_ref, manifest_ref)},
                                    budget=ProviderRunBudget(timeout_ms=100, max_output_bytes=4096, max_element_count=16,
                                                             max_string_length=256, resource_group="recorded"))
    lease = RestrictedCaptureLease(request_ref=request_ref, capture_lineage_ref=capture_ref, artifact_ref=artifact_ref,
                                   capture_id="capture/recorded/omni", artifact_sha256=image_hash, image_size={"width": 8, "height": 6}, local_path=image)
    return store, runtime, request_ref, lease, capture_ref, _RecordedProcess(worker_payload)


def _review_for_result(tmp_path: Path, *, result_ref: dict[str, str], capture_ref: dict[str, str], name: str) -> dict[str, object]:
    draft: dict[str, object] = {"contract_version": "learning_template_draft_v1", "states": [], "regions": [], "action_templates": [],
                                "capture_lineage_ref": capture_ref, "page_details": {}}
    holder = {"learning_draft": draft}
    _attach_uei_shadow_result_ref_to_draft(holder, {"uei_shadow_result_ref": result_ref})
    source = tmp_path / "artifacts" / "learning-runs" / name / "trial.json"
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps(draft), encoding="utf-8")
    return load_learning_draft_review(source, project_root=tmp_path)


@pytest.mark.parametrize(("fixture_name", "expected_status"), [
    ("portfolio-v1-omniparser-recorded-success.json", "succeeded"),
    ("portfolio-v1-omniparser-recorded-failure.json", "failed"),
])
def test_recorded_omniparser_adapter_runtime_emits_reverifiable_non_authorizing_review_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fixture_name: str, expected_status: str,
) -> None:
    store, runtime, request_ref, lease, capture_ref, process = _recorded_omni_runtime(
        tmp_path, worker_payload=_fixture(fixture_name),
    )
    monkeypatch.setattr("app.learn.recognition.uei.omniparser_shadow_adapter.subprocess.Popen", _recorded_popen(process))
    reply = runtime.invoke(request_ref=request_ref, capture_lease=lease)
    receipt = store.get(reply["receipt_ref"], contract_version="provider_runtime_receipt_v1")
    result = store.get(reply["result_ref"], contract_version="provider_safe_result_v1")
    assert receipt["status"] == expected_status
    assert receipt["result_ref"] == reply["result_ref"]
    assert result["review_only"] is True
    assert result["provider_id"] == "local.runtime/omniparser"
    if expected_status == "failed":
        assert reply["error_ref"] is not None
        assert receipt["error_ref"] == reply["error_ref"]
        store.get(reply["error_ref"], contract_version="provider_error_v1")
    review = _review_for_result(tmp_path, result_ref=reply["result_ref"], capture_ref=capture_ref, name=expected_status)
    summary = review["uei_shadow_provider_summary"]
    assert summary["status"] == ("success" if expected_status == "succeeded" else "failed")
    assert summary["execution_authorized"] is False
    assert summary["action_candidates"] == []
    rendered = json.dumps({"receipt": receipt, "result": result, "review": review}, ensure_ascii=False)
    assert str(tmp_path) not in rendered
    assert "Authorization: Bearer" not in rendered
