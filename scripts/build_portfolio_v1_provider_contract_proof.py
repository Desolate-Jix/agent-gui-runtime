"""生成可跟踪、非实时的 Portfolio v1 provider contract 证明。"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.learn.recognition.uei.builtin_learning_projection import seal_builtin_ocr_evidence
from app.learn.recognition.uei.canonical import seal_immutable
from app.learn.recognition.uei.omniparser_shadow_adapter import OmniParserShadowAdapter, PROFILE_ID, PROVIDER_ID, PROVIDER_VERSION, TrustedOmniParserConfiguration
from app.learn.recognition.uei.provider_adapters import ProviderRunBudget, RestrictedCaptureLease, TrustedProviderAdapterRegistry
from app.learn.recognition.uei.provider_runtime import ShadowProviderRuntime
from app.learn.recognition.uei.store import UEIObjectStore


FIXTURES = ROOT / "tests" / "fixtures" / "uei-v1"
OUTPUT = ROOT / "release" / "portfolio-v1" / "provider-contract-proof.json"


def _fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _digest(name: str) -> str:
    return sha256((FIXTURES / name).read_bytes()).hexdigest()


def _put(store: UEIObjectStore, value: dict[str, object]) -> dict[str, str]:
    return store.put(seal_immutable(value))


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


def _configuration(root: Path) -> TrustedOmniParserConfiguration:
    interpreter, worker = root / "recorded-python.exe", root / "recorded-worker.py"
    code, weights, cache = root / "code", root / "weights", root / "cache"
    interpreter.write_text("recorded", encoding="utf-8")
    worker.write_text("recorded", encoding="utf-8")
    for directory in (code, weights, cache):
        directory.mkdir()
    return TrustedOmniParserConfiguration(interpreter=interpreter, worker_script=worker, code_path=code, weights_path=weights, cache_path=cache, minimum_free_gpu_gib=0)


def _recorded_receipt(*, fixture_name: str) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="portfolio-v1-provider-proof-") as directory:
        root = Path(directory)
        store = UEIObjectStore(root=root / "artifacts" / "uei-shadow-store")
        image = root / "capture.png"
        Image.new("RGB", (8, 6), color=(10, 20, 30)).save(image)
        image_hash = sha256(image.read_bytes()).hexdigest()
        artifact_ref = _put(store, {"contract_version": "artifact_ref_v1", "artifact_id": "artifact/recorded/omni", "artifact_sha256": image_hash, "media_type": "image/png", "byte_length": image.stat().st_size, "restricted": True})
        capture_ref = _put(store, {"contract_version": "capture_lineage_v1", "capture_id": "capture/recorded/omni", "artifact_ref": artifact_ref, "artifact_sha256": image_hash, "image_size": {"width": 8, "height": 6}, "capture_coordinate_space": "capture_pixel_xyxy", "captured_at": "2026-08-22T00:00:00Z"})
        request_ref = _put(store, {"contract_version": "screen_parse_request_v1", "request_id": "request/recorded/omni", "capture_lineage_ref": capture_ref, "requested_profiles": [{"provider_id": PROVIDER_ID, "profile_id": PROFILE_ID, "mode": "Shadow"}], "privacy_policy": "restricted", "requester_id": "server"})
        registration_ref = _put(store, {"contract_version": "trusted_provider_registration_v1", "registration_id": "registration/recorded/omni", "provider_id": PROVIDER_ID, "profile_ids": [PROFILE_ID], "enabled": True, "allowed_modes": ["Shadow"], "allowed_privacy_policies": ["restricted"], "egress_policy": "local_only", "wire_payload_policy": "restricted_store_only", "safe_payload_limits": {"max_json_bytes": 4096, "max_depth": 8, "max_array_items": 16, "max_object_properties": 32, "max_string_chars": 256, "allowed_json_types": ["object", "array", "string", "number", "boolean", "null"]}, "required_conformance_suite": "uei-v1-static-projection"})
        manifest_ref = _put(store, {"contract_version": "provider_manifest_v1", "manifest_id": "manifest/recorded/omni", "provider_id": PROVIDER_ID, "provider_version": PROVIDER_VERSION, "profiles": [{"profile_id": PROFILE_ID, "operation": "screen_parse", "input_contract": "screen_parse_request_v1", "output_contract": "provider_safe_result_v1", "declared_output_kinds": ["text"], "supported_coordinate_spaces": ["capture_pixel_xyxy"], "supports_capture_artifact": True, "privacy_capabilities": ["restricted"], "mode_allowlist": ["Shadow"]}]})
        adapter = OmniParserShadowAdapter(configuration=_configuration(root), gpu_free_gib=lambda: 99)
        runtime = ShadowProviderRuntime(store=store, registry=TrustedProviderAdapterRegistry([adapter]), trusted_profiles={(PROVIDER_ID, PROFILE_ID): (registration_ref, manifest_ref)}, budget=ProviderRunBudget(timeout_ms=100, max_output_bytes=4096, max_element_count=16, max_string_length=256, resource_group="recorded"))
        lease = RestrictedCaptureLease(request_ref=request_ref, capture_lineage_ref=capture_ref, artifact_ref=artifact_ref, capture_id="capture/recorded/omni", artifact_sha256=image_hash, image_size={"width": 8, "height": 6}, local_path=image)
        process = _RecordedProcess(_fixture(fixture_name))
        with patch("app.learn.recognition.uei.omniparser_shadow_adapter.subprocess.Popen", _recorded_popen(process)):
            reply = runtime.invoke(request_ref=request_ref, capture_lease=lease)
        receipt = store.get(reply["receipt_ref"], contract_version="provider_runtime_receipt_v1")
        result = store.get(reply["result_ref"], contract_version="provider_safe_result_v1")
        output: dict[str, object] = {"receipt_ref": reply["receipt_ref"], "result_ref": reply["result_ref"], "receipt_status": receipt["status"], "result_status": result["status"], "receipt_contract": receipt["contract_version"], "result_contract": result["contract_version"], "reference_resolution": "generated_rebuilt_at_test_not_directly_resolvable"}
        if reply.get("error_ref") is not None:
            error = store.get(reply["error_ref"], contract_version="provider_error_v1")
            output["error_ref"] = reply["error_ref"]
            output["error_contract"] = error["contract_version"]
        return output


def _built_in_result_ref() -> dict[str, str]:
    with tempfile.TemporaryDirectory(prefix="portfolio-v1-builtin-proof-") as directory:
        root = Path(directory)
        image = root / "capture.png"
        Image.new("RGB", (8, 6), color=(10, 20, 30)).save(image)
        return seal_builtin_ocr_evidence(project_root=root, image_path=image, capture_id="capture/portfolio-v1/proof", captured_at="2026-08-22T00:00:00Z", ocr_result=_fixture("portfolio-v1-builtin-fixed-output.json"))


def main() -> None:
    success = _recorded_receipt(fixture_name="portfolio-v1-omniparser-recorded-success.json")
    failure = _recorded_receipt(fixture_name="portfolio-v1-omniparser-recorded-failure.json")
    proof = {"contract_version": "portfolio_v1_provider_contract_proof_v1", "fixed_or_recorded_evidence": True, "live_omniparser_inference": False, "execution_authorized": False, "provider_accuracy_proven": False, "scope": "provider-neutral UEI-to-Review conformance only", "built_in": {"provider_id": "local.runtime/builtin-ocr", "fixture": "tests/fixtures/uei-v1/portfolio-v1-builtin-fixed-output.json", "fixture_sha256": _digest("portfolio-v1-builtin-fixed-output.json"), "result_contract": "provider_safe_result_v1", "result_ref": _built_in_result_ref(), "reference_resolution": "generated_rebuilt_at_test_not_directly_resolvable", "review_contract": "uei_shadow_provider_summary_v1"}, "recorded_omniparser": {"provider_id": "local.runtime/omniparser", "adapter": "OmniParserShadowAdapter", "runtime": "ShadowProviderRuntime", "success": {"fixture": "tests/fixtures/uei-v1/portfolio-v1-omniparser-recorded-success.json", "fixture_sha256": _digest("portfolio-v1-omniparser-recorded-success.json"), **success, "reverify": "uv run python scripts/build_portfolio_v1_provider_contract_proof.py"}, "failure": {"fixture": "tests/fixtures/uei-v1/portfolio-v1-omniparser-recorded-failure.json", "fixture_sha256": _digest("portfolio-v1-omniparser-recorded-failure.json"), **failure, "reverify": "uv run python scripts/build_portfolio_v1_provider_contract_proof.py"}}, "boundaries": {"panel_forwards_only": ["id", "content_sha256"], "provider_native_payload_exposed": False, "geometry_exposed": False, "action_candidates": []}, "not_proven": ["live provider inference", "provider accuracy", "remote provider support", "runtime execution authorization"]}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
