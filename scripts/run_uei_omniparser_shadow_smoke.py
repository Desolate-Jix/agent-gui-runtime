"""Offline-only synthetic-image smoke for the UEI OmniParser Shadow adapter."""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import statistics
import sys
import tempfile
from uuid import uuid4

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = ROOT / "artifacts" / "omniparser-smoke"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.learn.recognition.uei.canonical import seal_immutable
from app.learn.recognition.uei.omniparser_shadow_adapter import OmniParserShadowAdapter
from app.learn.recognition.uei.provider_adapters import ProviderRunBudget, RestrictedCaptureLease, TrustedProviderAdapterRegistry
from app.learn.recognition.uei.provider_runtime import ShadowProviderRuntime
from app.learn.recognition.uei.store import UEIObjectStore


def _put(store, value):
    return store.put(seal_immutable(value))


def _image(path: Path) -> dict[str, int]:
    image = Image.new("RGB", (800, 600), "#f4f6f8")
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 40, 760, 110), fill="#254478")
    draw.rectangle((80, 170, 720, 270), fill="white", outline="#738092", width=3)
    draw.rectangle((570, 390, 720, 470), fill="#1976d2")
    draw.text((70, 65), "Synthetic offline UI", fill="white")
    draw.text((100, 205), "Search", fill="#30343b")
    draw.text((600, 420), "Continue", fill="white")
    image.save(path, format="PNG")
    return {"width": image.width, "height": image.height}


def _runtime(root: Path, image: Path, size: dict[str, int]):
    adapter = OmniParserShadowAdapter(benchmark_mode=True)
    store = UEIObjectStore(root=root / "uei-shadow-store")
    raw = image.read_bytes(); digest = sha256(raw).hexdigest()
    artifact = _put(store, {"contract_version":"artifact_ref_v1","artifact_id":"artifact/smoke","artifact_sha256":digest,"media_type":"image/png","byte_length":len(raw),"restricted":True})
    capture = _put(store, {"contract_version":"capture_lineage_v1","capture_id":"capture/smoke","artifact_ref":artifact,"artifact_sha256":digest,"image_size":size,"capture_coordinate_space":"capture_pixel_xyxy","captured_at":"2026-08-21T00:00:00Z"})
    registration = _put(store, {"contract_version":"trusted_provider_registration_v1","registration_id":"registration/smoke","provider_id":adapter.provider_id,"profile_ids":[adapter.profile_id],"enabled":True,"allowed_modes":["Shadow"],"allowed_privacy_policies":["restricted"],"egress_policy":"local_only","wire_payload_policy":"restricted_store_only","safe_payload_limits":{"max_json_bytes":1048576,"max_depth":16,"max_array_items":10000,"max_object_properties":64,"max_string_chars":4096,"allowed_json_types":["object","array","string","number","boolean","null"]},"required_conformance_suite":"uei-v1-static-projection"})
    manifest = _put(store, {"contract_version":"provider_manifest_v1","manifest_id":"manifest/smoke","provider_id":adapter.provider_id,"provider_version":adapter.provider_version,"profiles":[{"profile_id":adapter.profile_id,"operation":"screen_parse","input_contract":"screen_parse_request_v1","output_contract":"provider_safe_result_v1","declared_output_kinds":["element","text","icon","structure"],"supported_coordinate_spaces":["image_pixel_xyxy"],"supports_capture_artifact":True,"privacy_capabilities":["restricted"],"mode_allowlist":["Shadow"]}]})
    runtime = ShadowProviderRuntime(store=store, registry=TrustedProviderAdapterRegistry([adapter]), trusted_profiles={(adapter.provider_id,adapter.profile_id):(registration,manifest)}, budget=ProviderRunBudget(timeout_ms=300000,max_output_bytes=1048576,max_element_count=10000,max_string_length=4096,resource_group="gpu_vision"))
    return runtime, adapter, store, capture, artifact, digest


def _p95(values: list[int]) -> int:
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, round(0.95 * (len(ordered) - 1))))]


def _success_report(*, reply: dict[str, object], receipt: dict[str, object], metrics: dict[str, object],
                    provider_version: str, digest: str) -> dict[str, object]:
    cleanup_status = receipt.get("cleanup_status")
    succeeded = receipt.get("status") == "succeeded" and cleanup_status == "clean"
    return {
        "contract_version": "uei_omniparser_shadow_smoke_report_v1",
        "status": "succeeded",
        "offline": True,
        "provider_id": receipt.get("provider_id"),
        "profile_id": receipt.get("profile_id"),
        "provider_version": provider_version,
        "invocation_id": reply.get("invocation_id"),
        "receipt_ref": reply.get("receipt_ref"),
        "result_ref": reply.get("result_ref"),
        "error_ref": reply.get("error_ref"),
        "cold_duration_ms": metrics.get("cold_ms"),
        "warm_duration_ms": metrics.get("warm_ms"),
        "warm_p50_ms": metrics.get("warm_p50_ms"),
        "warm_p95_ms": metrics.get("warm_p95_ms"),
        "item_counts": metrics.get("item_counts"),
        "invalid_item_counts": metrics.get("invalid_item_counts"),
        "resource_units": metrics.get("peak_mib"),
        "cleanup_status": cleanup_status,
        "worker_process_exit_verified": succeeded,
        "resource_lease_released": succeeded,
        "temporary_exchange_removed": succeeded,
        "stored_receipt_revalidated": True,
        "stored_result_revalidated": reply.get("result_ref") is not None,
        "synthetic_artifact_sha256": digest,
    }


def _persist_success_evidence(temporary_root: Path, report: dict[str, object]) -> dict[str, object]:
    store_root = temporary_root / "uei-shadow-store"
    if not store_root.is_dir():
        raise RuntimeError("smoke_store_missing")
    report_digest = sha256(json.dumps(report, ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":")).encode("utf-8")).hexdigest()
    evidence_name = f"uei-v1-shadow-runtime-{report_digest[:16]}"
    evidence_dir = EVIDENCE_ROOT / evidence_name
    report_path = evidence_dir / "report.json"
    persisted = dict(report)
    persisted["evidence_report_path"] = report_path.relative_to(ROOT).as_posix()
    persisted["evidence_store_path"] = (evidence_dir / "uei-shadow-store").relative_to(ROOT).as_posix()
    expected_bytes = json.dumps(persisted, ensure_ascii=False, sort_keys=True,
                                separators=(",", ":")).encode("utf-8")
    if evidence_dir.exists():
        if not report_path.is_file() or report_path.read_bytes() != expected_bytes:
            raise RuntimeError("smoke_evidence_collision")
        return persisted
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    staging = EVIDENCE_ROOT / f".{evidence_name}.{uuid4().hex}.tmp"
    try:
        staging.mkdir()
        shutil.copytree(store_root, staging / "uei-shadow-store")
        (staging / "report.json").write_bytes(expected_bytes)
        os.replace(staging, evidence_dir)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return persisted


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="uei-omniparser-shadow-smoke-") as directory:
        root = Path(directory)
        image = root / "synthetic-ui.png"; size = _image(image)
        runtime, adapter, store, capture_ref, artifact_ref, digest = _runtime(root, image, size)
        receipts, results = [], []
        for run_id in ("benchmark",):
            request = _put(store, {"contract_version":"screen_parse_request_v1","request_id":f"request/smoke/{run_id}","capture_lineage_ref":capture_ref,"requested_profiles":[{"provider_id":adapter.provider_id,"profile_id":adapter.profile_id,"mode":"Shadow"}],"privacy_policy":"restricted","requester_id":"server"})
            lease = RestrictedCaptureLease(request_ref=request,capture_lineage_ref=capture_ref,artifact_ref=artifact_ref,capture_id="capture/smoke",artifact_sha256=digest,image_size=size,local_path=image)
            reply = runtime.invoke(request_ref=request, capture_lease=lease)
            receipt = store.get(reply["receipt_ref"], contract_version="provider_runtime_receipt_v1")
            result = store.get(reply["result_ref"], contract_version="provider_safe_result_v1") if reply["result_ref"] else None
            if reply["error_ref"]: store.get(reply["error_ref"], contract_version="provider_error_v1")
            receipts.append(receipt); results.append(result)
            if receipt["status"] != "succeeded":
                print(json.dumps({"contract_version":"uei_omniparser_shadow_smoke_report_v1","status":"unavailable","offline":True,
                    "invocation_id":reply["invocation_id"],"receipt_ref":reply["receipt_ref"],"result_ref":reply["result_ref"],
                    "error_ref":reply["error_ref"],"stored_receipt_revalidated":True,
                    "reason_class":receipt["reason_class"],"cleanup_status":receipt["cleanup_status"],
                    "synthetic_artifact_sha256":digest}, ensure_ascii=True)); return 2
        metrics = adapter.last_benchmark
        if not isinstance(metrics, dict):
            print(json.dumps({"status":"unavailable","offline":True,"reason_class":"runtime_worker_invalid","synthetic_artifact_sha256":digest}, ensure_ascii=True)); return 2
        report = _success_report(reply=reply, receipt=receipts[0], metrics=metrics,
                                 provider_version=adapter.provider_version, digest=digest)
        report = _persist_success_evidence(root, report)
        print(json.dumps(report, ensure_ascii=True))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
