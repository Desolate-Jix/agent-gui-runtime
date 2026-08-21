from __future__ import annotations

import json
from pathlib import Path


def _ref(name: str) -> dict[str, str]:
    return {"id": name, "content_sha256": (name[-1] * 64)}


def test_success_report_keeps_revalidated_refs_metrics_and_closed_cleanup_evidence():
    from scripts.run_uei_omniparser_shadow_smoke import _success_report

    reply = {
        "invocation_id": "invocation/" + "a" * 64,
        "result_ref": _ref("result/b"),
        "error_ref": None,
        "receipt_ref": _ref("receipt/c"),
    }
    receipt = {
        "provider_id": "local.runtime/omniparser",
        "profile_id": "local.runtime/omniparser/shadow-v2",
        "cleanup_status": "clean",
        "status": "succeeded",
    }
    metrics = {
        "cold_ms": 100, "warm_ms": [20, 21, 19], "warm_p50_ms": 20, "warm_p95_ms": 21,
        "item_counts": [4, 4, 4, 4], "invalid_item_counts": [0, 0, 0, 0], "peak_mib": 2048,
    }

    report = _success_report(reply=reply, receipt=receipt, metrics=metrics,
                             provider_version="v2.0.1+benchmark-cold1-warm3", digest="d" * 64)

    assert report["receipt_ref"] == reply["receipt_ref"]
    assert report["result_ref"] == reply["result_ref"]
    assert report["invocation_id"] == reply["invocation_id"]
    assert report["worker_process_exit_verified"] is True
    assert report["resource_lease_released"] is True
    assert report["temporary_exchange_removed"] is True
    assert report["stored_receipt_revalidated"] is True
    assert report["stored_result_revalidated"] is True
    serialized = json.dumps(report)
    assert "local_path" not in serialized and "command" not in serialized and "stdout" not in serialized


def test_success_evidence_persists_store_and_report_outside_temporary_root(tmp_path: Path, monkeypatch):
    from scripts import run_uei_omniparser_shadow_smoke as smoke

    temporary_root = tmp_path / "temporary"
    store_root = temporary_root / "uei-shadow-store"
    object_path = store_root / "objects" / "provider_runtime_receipt_v1" / ("a" * 64 + ".json")
    object_path.parent.mkdir(parents=True)
    object_path.write_text('{"sealed":true}', encoding="utf-8")
    evidence_root = tmp_path / "artifacts" / "omniparser-smoke"
    monkeypatch.setattr(smoke, "ROOT", tmp_path)
    monkeypatch.setattr(smoke, "EVIDENCE_ROOT", evidence_root)
    report = {
        "status": "succeeded",
        "receipt_ref": _ref("receipt/c"),
        "synthetic_artifact_sha256": "d" * 64,
    }

    persisted = smoke._persist_success_evidence(temporary_root, report)

    report_path = tmp_path / persisted["evidence_report_path"]
    store_path = tmp_path / persisted["evidence_store_path"]
    assert report_path.is_file()
    assert (store_path / object_path.relative_to(store_root)).read_text(encoding="utf-8") == '{"sealed":true}'
    assert json.loads(report_path.read_text(encoding="utf-8")) == persisted
    assert str(tmp_path) not in json.dumps(persisted)
