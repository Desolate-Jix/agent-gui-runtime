from __future__ import annotations

import base64
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from app.learn.recognition.uei.canonical import seal_immutable

from app.learn.hybrid.benchmark_v2_pathless import (
    order_pathless_envelopes,
    pathless_artifact_ref,
    seal_pathless_envelope,
    seal_pathless_projection,
    validate_pathless_envelope,
    validate_pathless_recursive,
    validate_pathless_ref,
)


SAFETY = {
    "artifact_is_authorization": False,
    "execute_binding_enabled": False,
    "display_only": True,
}
SHA = "a" * 64


HOLDOUT_AUTHORIZATION_REF = {
    "authorization_id": "holdout-authorization/" + "1" * 64,
    "envelope_sha256": "2" * 64,
}
HOLDOUT_CLAIM_REF = {
    "id": "holdout-claim/" + "1" * 64,
    "envelope_sha256": "3" * 64,
}
HOLDOUT_ATTEMPT_REF = {
    "id": "holdout-runner-attempt/" + "4" * 64,
    "content_sha256": "5" * 64,
}


def _ref(identifier: str) -> dict[str, str]:
    return {"id": identifier, "content_sha256": SHA}


@pytest.mark.parametrize(
    ("contract_version", "prefix", "payload", "fields"),
    [
        (
            "benchmark_v2_holdout_runner_event_verified_projection_v1",
            "verified-holdout-runner-event",
            {
                "partition": "holdout",
                "event_kind": "opened",
                "sequence": 0,
                "attempt_ref": HOLDOUT_ATTEMPT_REF,
                "authorization_ref": HOLDOUT_AUTHORIZATION_REF,
                "claim_ref": HOLDOUT_CLAIM_REF,
                "previous_event_projection_ref": None,
                "raw_event_sha256": "6" * 64,
                "load_bearing_refs": {"attempt_ref": HOLDOUT_ATTEMPT_REF},
                "safety": SAFETY,
            },
            {
                "contract_version", "artifact_id", "partition", "event_kind",
                "sequence", "attempt_ref", "authorization_ref", "claim_ref",
                "previous_event_projection_ref", "raw_event_sha256",
                "load_bearing_refs", "safety", "content_sha256",
            },
        ),
        (
            "benchmark_v2_holdout_attempt_ledger_pre_result_verified_projection_v1",
            "verified-holdout-pre-result",
            {
                "partition": "holdout",
                "attempt_ref": HOLDOUT_ATTEMPT_REF,
                "authorization_ref": HOLDOUT_AUTHORIZATION_REF,
                "claim_ref": HOLDOUT_CLAIM_REF,
                "raw_pre_result_ref_sha256": "6" * 64,
                "raw_prefix_sha256": "7" * 64,
                "terminal_sequence": 2,
                "terminal_envelope_sha256": "8" * 64,
                "cleanup_event_projection_ref": _ref("verified-holdout-runner-event/cleanup"),
                "verified": True,
                "safety": SAFETY,
            },
            {
                "contract_version", "artifact_id", "partition", "attempt_ref",
                "authorization_ref", "claim_ref", "raw_pre_result_ref_sha256",
                "raw_prefix_sha256", "terminal_sequence",
                "terminal_envelope_sha256", "cleanup_event_projection_ref",
                "verified", "safety", "content_sha256",
            },
        ),
        (
            "benchmark_v2_holdout_attempt_ledger_prefix_verified_projection_v1",
            "verified-holdout-attempt-ledger-prefix",
            {
                "partition": "holdout",
                "authorization_ref": HOLDOUT_AUTHORIZATION_REF,
                "claim_ref": HOLDOUT_CLAIM_REF,
                "attempt_ref": HOLDOUT_ATTEMPT_REF,
                "raw_prefix_sha256": "7" * 64,
                "pre_result_verification_ref": _ref("verified-holdout-pre-result/one"),
                "terminal_sequence": 3,
                "terminal_event_projection_ref": _ref("verified-holdout-runner-event/result"),
                "event_projection_refs": [
                    _ref(f"verified-holdout-runner-event/{kind}")
                    for kind in ("opened", "body", "cleanup", "result")
                ],
                "selection_eligible": True,
                "safety": SAFETY,
            },
            {
                "contract_version", "artifact_id", "partition", "authorization_ref",
                "claim_ref", "attempt_ref", "raw_prefix_sha256",
                "pre_result_verification_ref", "terminal_sequence",
                "terminal_event_projection_ref", "event_projection_refs",
                "selection_eligible", "safety", "content_sha256",
            },
        ),
        (
            "benchmark_v2_holdout_projected_attempt_ledger_v1",
            "projected-holdout-attempt-ledger",
            {
                "benchmark_release_id": "portfolio-hybrid-v1-1-benchmark-v2",
                "partition": "holdout",
                "authorization_ref": HOLDOUT_AUTHORIZATION_REF,
                "claim_ref": HOLDOUT_CLAIM_REF,
                "raw_ledger_prefix_verification_ref": _ref("verified-holdout-attempt-ledger-prefix/one"),
                "pre_result_verification_ref": _ref("verified-holdout-pre-result/one"),
                "entries": [{
                    "sequence": 0,
                    "attempt_ref": HOLDOUT_ATTEMPT_REF,
                    "observed_state": "result",
                    "event_projection_refs": [
                        _ref(f"verified-holdout-runner-event/{kind}")
                        for kind in ("opened", "body", "cleanup", "result")
                    ],
                    "lifecycle_ref": _ref("verified-lifecycle/one"),
                    "selection_eligible": True,
                }],
                "selected_attempt_ref": HOLDOUT_ATTEMPT_REF,
                "selected_lifecycle_ref": _ref("verified-lifecycle/one"),
                "safety": SAFETY,
            },
            {
                "contract_version", "artifact_id", "benchmark_release_id",
                "partition", "authorization_ref", "claim_ref",
                "raw_ledger_prefix_verification_ref", "pre_result_verification_ref",
                "entries", "selected_attempt_ref", "selected_lifecycle_ref",
                "safety", "content_sha256",
            },
        ),
        (
            "benchmark_v2_holdout_actual_result_verified_projection_v1",
            "verified-holdout-actual-result",
            {
                "attempt_ref": HOLDOUT_ATTEMPT_REF,
                "result_contract_version": "benchmark_v2_holdout_runner_actual_result_v1",
                "raw_file_sha256": "6" * 64,
                "result_content_sha256": "7" * 64,
                "body_projection_ref": _ref("verified-actual-body/one"),
                "cleanup_projection_ref": _ref("verified-lifecycle/one"),
                "pre_result_verification_ref": _ref("verified-holdout-pre-result/one"),
                "runner_ledger_prefix_projection_ref": _ref("verified-holdout-attempt-ledger-prefix/one"),
                "result_event_projection_ref": _ref("verified-holdout-runner-event/result"),
                "verified": True,
                "safety": SAFETY,
            },
            {
                "contract_version", "artifact_id", "attempt_ref",
                "result_contract_version", "raw_file_sha256",
                "result_content_sha256", "body_projection_ref",
                "cleanup_projection_ref", "pre_result_verification_ref",
                "runner_ledger_prefix_projection_ref", "result_event_projection_ref",
                "verified", "safety", "content_sha256",
            },
        ),
    ],
)
def test_holdout_h5_distinct_pathless_contracts_use_exact_s11_identity(
    contract_version: str,
    prefix: str,
    payload: dict[str, object],
    fields: set[str],
) -> None:
    projection = seal_pathless_projection(
        contract_version=contract_version,
        semantic_payload=payload,
    )
    semantic_sha = hashlib.sha256(
        contract_version.encode("utf-8")
        + b"\0"
        + _canonical({"contract_version": contract_version, **payload})
    ).hexdigest()

    assert set(projection) == fields
    assert projection["artifact_id"] == f"{prefix}/{semantic_sha}"
    envelope = seal_pathless_envelope(projection)
    assert envelope["ref"] == pathless_artifact_ref(projection)
    assert base64.b64decode(envelope["canonical_bytes_b64"], validate=True) == _canonical(
        projection
    )


def test_h5_holdout_projected_ledger_rejects_bool_entry_sequence() -> None:
    with pytest.raises(ValueError, match="sequence|integer"):
        seal_pathless_projection(
            contract_version="benchmark_v2_holdout_projected_attempt_ledger_v1",
            semantic_payload={
                "benchmark_release_id": "portfolio-hybrid-v1-1-benchmark-v2",
                "partition": "holdout",
                "authorization_ref": HOLDOUT_AUTHORIZATION_REF,
                "claim_ref": HOLDOUT_CLAIM_REF,
                "raw_ledger_prefix_verification_ref": _ref(
                    "verified-holdout-attempt-ledger-prefix/one"
                ),
                "pre_result_verification_ref": _ref(
                    "verified-holdout-pre-result/one"
                ),
                "entries": [
                    {
                        "sequence": False,
                        "attempt_ref": HOLDOUT_ATTEMPT_REF,
                        "observed_state": "result",
                        "event_projection_refs": [
                            _ref(f"verified-holdout-runner-event/{kind}")
                            for kind in ("opened", "body", "cleanup", "result")
                        ],
                        "lifecycle_ref": _ref("verified-lifecycle/one"),
                        "selection_eligible": True,
                    }
                ],
                "selected_attempt_ref": HOLDOUT_ATTEMPT_REF,
                "selected_lifecycle_ref": _ref("verified-lifecycle/one"),
                "safety": SAFETY,
            },
        )


def test_h5_shared_cleanup_lifecycle_rejects_bool_zero_count() -> None:
    with pytest.raises(ValueError, match="resource|integer"):
        seal_pathless_projection(
            contract_version="benchmark_v2_lifecycle_verified_projection_v1",
            semantic_payload={
                "attempt_ref": HOLDOUT_ATTEMPT_REF,
                "lifecycle_kind": "cleanup",
                "raw_evidence_sha256": "1" * 64,
                "terminal_status": "stable_zero",
                "cleanup_stable_zero": True,
                "resource_counts": {
                    "service_operations": False,
                    "windows": 0,
                    "providers": 0,
                    "listeners": 0,
                    "leases": 0,
                },
                "started_request_count": 0,
                "terminal_or_unknown_request_count": 0,
                "parent_refs": {
                    "cleanup_receipt_ref": _ref("attempt-cleanup-receipt/one")
                },
                "safety": SAFETY,
            },
        )


def _case_ref() -> dict[str, str]:
    return {"case_id": "provider-case-one", "case_content_sha256": SHA}


def _nested_payload() -> dict[str, object]:
    return {
        "evidence_kind": "available_action",
        "case_ref": _case_ref(),
        "actual_screen_group_ref": _ref("actual-screen-group/one"),
        "canonical_value_sha256": "b" * 64,
        "safety": deepcopy(SAFETY),
    }


def _seal_nested() -> dict[str, object]:
    return seal_pathless_projection(
        contract_version="benchmark_v2_nested_provider_evidence_ref_v1",
        semantic_payload=_nested_payload(),
    )


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _raw_envelope(value: dict[str, object], *, prefix: str, domain: bytes) -> dict[str, object]:
    raw = _canonical(value)
    return {
        "ref": {
            "id": f"{prefix}/{hashlib.sha256(domain + raw).hexdigest()}",
            "content_sha256": hashlib.sha256(raw).hexdigest(),
        },
        "canonical_bytes_b64": base64.b64encode(raw).decode("ascii"),
    }


def test_seal_projection_uses_frozen_identity_and_exact_closed_shape() -> None:
    artifact = _seal_nested()
    semantic = {"contract_version": artifact["contract_version"], **_nested_payload()}
    semantic_sha = hashlib.sha256(
        b"benchmark_v2_nested_provider_evidence_ref_v1\0" + _canonical(semantic)
    ).hexdigest()
    assert artifact["artifact_id"] == f"nested-provider-evidence/{semantic_sha}"
    assert set(artifact) == {
        "contract_version",
        "artifact_id",
        "evidence_kind",
        "case_ref",
        "actual_screen_group_ref",
        "canonical_value_sha256",
        "safety",
        "content_sha256",
    }
    without_content = {key: value for key, value in artifact.items() if key != "content_sha256"}
    assert artifact["content_sha256"] == hashlib.sha256(_canonical(without_content)).hexdigest()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update({"artifact_id": "caller/value"}),
        lambda payload: payload.update({"content_sha256": SHA}),
        lambda payload: payload.update({"unknown": True}),
        lambda payload: payload.pop("case_ref"),
        lambda payload: payload.update({"safety": {**SAFETY, "display_only": False}}),
    ],
)
def test_seal_rejects_caller_identity_unknown_missing_and_unsafe_fields(mutation) -> None:
    payload = _nested_payload()
    mutation(payload)
    with pytest.raises(ValueError, match="closed|caller|safety"):
        seal_pathless_projection(
            contract_version="benchmark_v2_nested_provider_evidence_ref_v1",
            semantic_payload=payload,
        )


def test_unknown_contract_and_untyped_role_fail_closed() -> None:
    with pytest.raises(ValueError, match="unknown pathless contract"):
        seal_pathless_projection(contract_version="unknown_v1", semantic_payload={})
    with pytest.raises(ValueError, match="typed|unknown ref role"):
        validate_pathless_ref(role="artifact_ref", value=_ref("anything/value"), context={})


def test_artifact_ref_and_envelope_validate_both_hashes_and_canonical_bytes() -> None:
    artifact = _seal_nested()
    expected = {"id": artifact["artifact_id"], "content_sha256": artifact["content_sha256"]}
    assert pathless_artifact_ref(artifact) == expected
    envelope = seal_pathless_envelope(artifact)
    assert validate_pathless_envelope(
        role="benchmark_v2_nested_provider_evidence_ref_v1",
        envelope=envelope,
        context={},
    ) == artifact

    changed = deepcopy(envelope)
    decoded = json.loads(base64.b64decode(changed["canonical_bytes_b64"]))
    decoded["artifact_id"] = f"nested-provider-evidence/{'0' * 64}"
    changed["canonical_bytes_b64"] = base64.b64encode(_canonical(decoded)).decode("ascii")
    with pytest.raises(ValueError, match="identity|ref"):
        validate_pathless_envelope(
            role="benchmark_v2_nested_provider_evidence_ref_v1",
            envelope=changed,
            context={},
        )

    noncanonical = deepcopy(envelope)
    noncanonical["canonical_bytes_b64"] = base64.b64encode(
        json.dumps(artifact, ensure_ascii=False, indent=2).encode("utf-8")
    ).decode("ascii")
    with pytest.raises(ValueError, match="canonical"):
        validate_pathless_envelope(
            role="benchmark_v2_nested_provider_evidence_ref_v1",
            envelope=noncanonical,
            context={},
        )


@pytest.mark.parametrize(
    "unsafe",
    [
        Path("capture.json"),
        r"C:\Users\tester\capture.json",
        "/tmp/capture.json",
        "file:///tmp/capture.json",
        "capture/../escape",
        "capture/%2e%2e/escape",
        "capture/./escape",
    ],
)
def test_recursive_noncanonical_types_and_path_aliases_are_rejected(unsafe: object) -> None:
    payload = _nested_payload()
    payload["evidence_kind"] = unsafe
    with pytest.raises(ValueError, match="canonical JSON|path|alias|identifier|text"):
        seal_pathless_projection(
            contract_version="benchmark_v2_nested_provider_evidence_ref_v1",
            semantic_payload=payload,
        )


def test_opaque_raw_ref_requires_matching_validated_canonical_bytes(monkeypatch) -> None:
    raw = seal_immutable({
        "contract_version": "hybrid_vista_refinement_request_v1",
        "candidate_id": "candidate/one",
        "submission_status": "SUBMITTED",
        "candidate_bbox_ref": {"xyxy": [1, 2, 3, 4]},
    })
    monkeypatch.setattr(
        "app.learn.hybrid.vista_refinement._validated_request", lambda value: value
    )
    raw_bytes = _canonical(raw)
    expected = {
        "id": "submitted-vista-request/"
        + hashlib.sha256(b"benchmark-v2-submitted-vista-request\0" + raw_bytes).hexdigest(),
        "content_sha256": hashlib.sha256(raw_bytes).hexdigest(),
    }
    context = {
        "contract_version": "sealed_vista_request_v4",
        "opaque_raw_canonical_bytes": {"submitted_request_ref": raw_bytes},
    }
    assert validate_pathless_ref(
        role="submitted_request_ref", value=expected, context=context
    ) == expected
    with pytest.raises(ValueError, match="canonical bytes|required"):
        validate_pathless_ref(
            role="submitted_request_ref",
            value=expected,
            context={"contract_version": "sealed_vista_request_v4"},
        )
    wrong_contract = _canonical({**raw, "contract_version": "wrong_v1"})
    with pytest.raises(ValueError, match="raw contract"):
        validate_pathless_ref(
            role="submitted_request_ref",
            value=expected,
            context={
                "contract_version": "sealed_vista_request_v4",
                "opaque_raw_canonical_bytes": {"submitted_request_ref": wrong_contract},
            },
        )


def test_source_parent_semantic_discriminator_is_closed() -> None:
    nested = _seal_nested()
    nested_ref = pathless_artifact_ref(nested)
    artifact = seal_pathless_projection(
        contract_version="sealed_prediction_source_parent_v1",
        semantic_payload={
            "case_ref": _case_ref(),
            "arm_scope": ["qwen_only"],
            "source_kind": "incumbent_qwen_action",
            "evidence_refs": {
                "incumbent_response_ref": nested_ref,
                "available_action_ref": nested_ref,
            },
            "actual_screen_group_ref": _ref("actual-screen-group/one"),
            "capture_ref": _ref("capture/one"),
            "safety": deepcopy(SAFETY),
        },
    )
    assert artifact["artifact_id"].startswith("prediction-source-parent/")
    changed = {key: deepcopy(value) for key, value in artifact.items() if key not in {"artifact_id", "content_sha256", "contract_version"}}
    changed["evidence_refs"]["fusion_result_ref"] = _ref("fusion-result/one")
    with pytest.raises(ValueError, match="evidence refs"):
        seal_pathless_projection(
            contract_version="sealed_prediction_source_parent_v1",
            semantic_payload=changed,
        )


def test_lifecycle_discriminator_derives_closed_parent_roles() -> None:
    cleanup = seal_pathless_projection(
        contract_version="benchmark_v2_lifecycle_verified_projection_v1",
        semantic_payload={
            "attempt_ref": _ref("runner-attempt/one"),
            "lifecycle_kind": "cleanup",
            "raw_evidence_sha256": "b" * 64,
            "terminal_status": "stable_zero",
            "cleanup_stable_zero": True,
            "resource_counts": {
                "service_operations": 0,
                "windows": 0,
                "providers": 0,
                "listeners": 0,
                "leases": 0,
            },
            "started_request_count": 0,
            "terminal_or_unknown_request_count": 0,
            "parent_refs": {"cleanup_receipt_ref": _ref("attempt-cleanup-receipt/one")},
            "safety": deepcopy(SAFETY),
        },
    )
    assert cleanup["artifact_id"].startswith("verified-lifecycle/")
    semantic = {key: deepcopy(value) for key, value in cleanup.items() if key not in {"contract_version", "artifact_id", "content_sha256"}}
    semantic["parent_refs"]["actual_screen_group_ref"] = _ref("actual-screen-group/one")
    with pytest.raises(ValueError, match="parent refs"):
        seal_pathless_projection(
            contract_version="benchmark_v2_lifecycle_verified_projection_v1",
            semantic_payload=semantic,
        )


def test_runner_result_accepts_only_closed_logical_pre_result_ref() -> None:
    logical_ref = {
        "contract_version": "benchmark_v2_runner_ledger_pre_result_ref_v1",
        "id": f"runner-ledger-pre-result/{'9' * 64}",
        "attempt_ref": _ref("runner-attempt/one"),
        "terminal_sequence": 3,
        "terminal_envelope_sha256": "b" * 64,
        "prefix_sha256": "c" * 64,
    }
    event = seal_pathless_projection(
        contract_version="benchmark_v2_runner_event_verified_projection_v1",
        semantic_payload={
            "partition": "regression",
            "event_kind": "result",
            "sequence": 3,
            "attempt_ref": _ref("runner-attempt/one"),
            "previous_event_projection_ref": _ref(f"verified-runner-event/{'d' * 64}"),
            "raw_event_sha256": "e" * 64,
            "load_bearing_refs": {
                "result_file_ref": {"file_sha256": "f" * 64, "content_sha256": "1" * 64},
                "attempt_ledger_pre_result_ref": logical_ref,
            },
            "safety": deepcopy(SAFETY),
        },
    )
    assert event["load_bearing_refs"]["attempt_ledger_pre_result_ref"] == logical_ref
    changed = {key: deepcopy(value) for key, value in event.items() if key not in {"contract_version", "artifact_id", "content_sha256"}}
    changed["load_bearing_refs"]["attempt_ledger_pre_result_ref"]["unknown"] = True
    with pytest.raises(ValueError, match="ledger.*closed"):
        seal_pathless_projection(
            contract_version="benchmark_v2_runner_event_verified_projection_v1",
            semantic_payload=changed,
        )


def test_recursive_registry_resolves_internal_children_and_rejects_external_injection() -> None:
    nested = _seal_nested()
    nested_ref = pathless_artifact_ref(nested)
    source = seal_pathless_projection(
        contract_version="sealed_prediction_source_parent_v1",
        semantic_payload={
            "case_ref": _case_ref(),
            "arm_scope": ["qwen_only"],
            "source_kind": "incumbent_qwen_action",
            "evidence_refs": {
                "incumbent_response_ref": nested_ref,
                "available_action_ref": nested_ref,
            },
            "actual_screen_group_ref": _ref("actual-screen-group/one"),
            "capture_ref": _ref("capture/one"),
            "safety": deepcopy(SAFETY),
        },
    )
    envelopes = [seal_pathless_envelope(source), seal_pathless_envelope(nested)]
    external = {
        "benchmark_v2_nested_provider_evidence_ref_v1.case_ref": _case_ref(),
        "benchmark_v2_nested_provider_evidence_ref_v1.actual_screen_group_ref": _ref("actual-screen-group/one"),
        "sealed_prediction_source_parent_v1.case_ref": _case_ref(),
        "sealed_prediction_source_parent_v1.actual_screen_group_ref": _ref("actual-screen-group/one"),
        "sealed_prediction_source_parent_v1.capture_ref": _ref("capture/one"),
    }
    result = validate_pathless_recursive(
        registry_name="prediction_selection_v1",
        roots=[pathless_artifact_ref(source)],
        envelopes=envelopes,
        external_refs=external,
        context={},
    )
    assert [item["ref"] for item in result] == [
        pathless_artifact_ref(nested),
        pathless_artifact_ref(source),
    ]
    injected = deepcopy(external)
    injected["sealed_prediction_source_parent_v1.evidence_refs.available_action_ref"] = nested_ref
    with pytest.raises(ValueError, match="internal ref.*external"):
        validate_pathless_recursive(
            registry_name="prediction_selection_v1",
            roots=[pathless_artifact_ref(source)],
            envelopes=envelopes,
            external_refs=injected,
            context={},
        )


def test_recursive_registry_rejects_orphan_duplicate_and_cycle() -> None:
    first = _seal_nested()
    other_payload = _nested_payload()
    other_payload["evidence_kind"] = "omni_item"
    other = seal_pathless_projection(
        contract_version="benchmark_v2_nested_provider_evidence_ref_v1",
        semantic_payload=other_payload,
    )
    external = {
        "benchmark_v2_nested_provider_evidence_ref_v1.case_ref": _case_ref(),
        "benchmark_v2_nested_provider_evidence_ref_v1.actual_screen_group_ref": _ref("actual-screen-group/one"),
    }
    with pytest.raises(ValueError, match="orphan"):
        validate_pathless_recursive(
            registry_name="prediction_selection_v1",
            roots=[pathless_artifact_ref(first)],
            envelopes=[seal_pathless_envelope(first), seal_pathless_envelope(other)],
            external_refs=external,
            context={},
        )
    with pytest.raises(ValueError, match="duplicate"):
        validate_pathless_recursive(
            registry_name="prediction_selection_v1",
            roots=[pathless_artifact_ref(first)],
            envelopes=[seal_pathless_envelope(first), seal_pathless_envelope(first)],
            external_refs=external,
            context={},
        )


def test_ordering_uses_frozen_class_rank_not_caller_order() -> None:
    nested = _seal_nested()
    nested_ref = pathless_artifact_ref(nested)
    source = seal_pathless_projection(
        contract_version="sealed_prediction_source_parent_v1",
        semantic_payload={
            "case_ref": _case_ref(),
            "arm_scope": ["qwen_only"],
            "source_kind": "incumbent_qwen_action",
            "evidence_refs": {"incumbent_response_ref": nested_ref, "available_action_ref": nested_ref},
            "actual_screen_group_ref": _ref("actual-screen-group/one"),
            "capture_ref": _ref("capture/one"),
            "safety": deepcopy(SAFETY),
        },
    )
    ordered = order_pathless_envelopes(
        registry_name="prediction_selection_v1",
        envelopes=[seal_pathless_envelope(source), seal_pathless_envelope(nested)],
        context={},
    )
    assert [envelope["ref"] for envelope in ordered] == [
        pathless_artifact_ref(nested),
        pathless_artifact_ref(source),
    ]


def test_predictions_uses_shared_pathless_public_api_without_local_projection_minter() -> None:
    source = Path("app/learn/hybrid/benchmark_v2_predictions.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        and node.module == "app.learn.hybrid.benchmark_v2_pathless"
        for alias in node.names
    }
    assert {
        "pathless_artifact_ref",
        "seal_pathless_envelope",
        "seal_pathless_projection",
        "validate_pathless_ref",
    }.issubset(imports)
    local_functions = {
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert not {"_sealed_projection", "_projection_ref", "_validate_projection_identity"} & local_functions


def test_prediction_registry_orders_raw_provider_classes_and_invokes_closed_validators(monkeypatch) -> None:
    capture = {"capture_id": "capture-one"}
    omni = seal_immutable({"contract_version": "hybrid_omni_inventory_v1", "capture_identity": capture, "confidence": 0.5})
    qwen = seal_immutable({"contract_version": "hybrid_qwen_bindings_v1", "capture_identity": capture})
    fusion = seal_immutable({"contract_version": "hybrid_fusion_result_v1", "capture_identity": capture})
    request = seal_immutable({"contract_version": "hybrid_vista_refinement_request_v1", "candidate_id": "candidate-one"})
    calls: list[str] = []

    def validate_omni(value):
        calls.append("omni")
        return value

    def validate_qwen(value, inventory, **_kwargs):
        assert inventory["capture_identity"] == capture
        calls.append("qwen")
        return value

    def validate_fusion(value, inventory, bindings):
        assert inventory["capture_identity"] == bindings["capture_identity"] == capture
        calls.append("fusion")
        return value

    def validate_request(value):
        calls.append("request")
        return value

    monkeypatch.setattr("app.learn.hybrid.contracts.validate_omni_inventory", validate_omni)
    monkeypatch.setattr("app.learn.hybrid.contracts.validate_qwen_bindings", validate_qwen)
    monkeypatch.setattr("app.learn.hybrid.contracts.validate_fusion_result", validate_fusion)
    monkeypatch.setattr("app.learn.hybrid.vista_refinement._validated_request", validate_request)
    envelopes = [
        _raw_envelope(request, prefix="submitted-vista-request", domain=b"benchmark-v2-submitted-vista-request\0"),
        _raw_envelope(fusion, prefix="fusion-result", domain=b"benchmark-v2-fusion-result\0"),
        _raw_envelope(qwen, prefix="qwen-bindings", domain=b"benchmark-v2-qwen-bindings\0"),
        _raw_envelope(omni, prefix="omni-inventory", domain=b"benchmark-v2-omni-inventory\0"),
    ]
    ordered = order_pathless_envelopes(
        registry_name="prediction_run_v3", envelopes=envelopes, context={}
    )
    assert [item["ref"]["id"].split("/", 1)[0] for item in ordered] == [
        "omni-inventory",
        "qwen-bindings",
        "fusion-result",
        "submitted-vista-request",
    ]
    assert calls == ["omni", "qwen", "fusion", "request"]


def test_prediction_registry_resolves_raw_provider_as_internal_leaf(monkeypatch) -> None:
    capture = {"capture_id": "capture-one"}
    omni = seal_immutable(
        {
            "contract_version": "hybrid_omni_inventory_v1",
            "capture_identity": capture,
            "confidence": 0.5,
        }
    )
    monkeypatch.setattr(
        "app.learn.hybrid.contracts.validate_omni_inventory", lambda value: value
    )
    omni_envelope = _raw_envelope(
        omni,
        prefix="omni-inventory",
        domain=b"benchmark-v2-omni-inventory\0",
    )
    nested = _seal_nested()
    source = seal_pathless_projection(
        contract_version="sealed_prediction_source_parent_v1",
        semantic_payload={
            "case_ref": _case_ref(),
            "arm_scope": ["omni_only_discovery"],
            "source_kind": "omni_inventory_item",
            "evidence_refs": {
                "omni_inventory_ref": deepcopy(omni_envelope["ref"]),
                "omni_item_ref": pathless_artifact_ref(nested),
            },
            "actual_screen_group_ref": _ref("actual-screen-group/one"),
            "capture_ref": _ref("capture/one"),
            "safety": deepcopy(SAFETY),
        },
    )
    external = {
        "benchmark_v2_nested_provider_evidence_ref_v1.case_ref": _case_ref(),
        "benchmark_v2_nested_provider_evidence_ref_v1.actual_screen_group_ref": _ref("actual-screen-group/one"),
        "sealed_prediction_source_parent_v1.case_ref": _case_ref(),
        "sealed_prediction_source_parent_v1.actual_screen_group_ref": _ref("actual-screen-group/one"),
        "sealed_prediction_source_parent_v1.capture_ref": _ref("capture/one"),
    }
    ordered = validate_pathless_recursive(
        registry_name="prediction_run_v3",
        roots=[pathless_artifact_ref(source)],
        envelopes=[
            omni_envelope,
            seal_pathless_envelope(nested),
            seal_pathless_envelope(source),
        ],
        external_refs=external,
        context={},
    )
    assert [item["ref"] for item in ordered] == [
        omni_envelope["ref"],
        pathless_artifact_ref(nested),
        pathless_artifact_ref(source),
    ]


def test_prediction_graph_accepts_exact_r_zero_missing_row_closure(monkeypatch) -> None:
    from app.learn.hybrid.benchmark_v2_contracts import PARENT_REF
    from app.learn.hybrid.benchmark_v2_predictions import _prediction_external_refs
    from app.learn.hybrid.benchmark_v2_pathless import (
        _decode_envelope,
        _validate_prediction_graph,
        _validate_projected_ledger_graph,
    )

    monkeypatch.setattr(
        "app.learn.hybrid.contracts.validate_omni_inventory", lambda value: value
    )
    monkeypatch.setattr(
        "app.learn.hybrid.contracts.validate_qwen_bindings",
        lambda value, _inventory: value,
    )
    monkeypatch.setattr(
        "app.learn.hybrid.contracts.validate_fusion_result",
        lambda value, _inventory, _bindings: value,
    )
    dependencies = []
    raw_envelopes = []
    groups = {}
    cases = {}
    multiset = []
    rows = []
    arms = (
        "qwen_only",
        "omni_only_discovery",
        "omni_to_qwen",
        "omni_to_qwen_vista",
    )
    for group_index in range(12):
        capture_identity = {"capture_id": f"capture-{group_index:02d}"}
        raw_values = {
            "omni": seal_immutable(
                {
                    "contract_version": "hybrid_omni_inventory_v1",
                    "capture_identity": capture_identity,
                }
            ),
            "qwen": seal_immutable(
                {
                    "contract_version": "hybrid_qwen_bindings_v1",
                    "capture_identity": capture_identity,
                }
            ),
            "fusion": seal_immutable(
                {
                    "contract_version": "hybrid_fusion_result_v1",
                    "capture_identity": capture_identity,
                }
            ),
        }
        envelopes = {
            "omni": _raw_envelope(
                raw_values["omni"],
                prefix="omni-inventory",
                domain=b"benchmark-v2-omni-inventory\0",
            ),
            "qwen": _raw_envelope(
                raw_values["qwen"],
                prefix="qwen-bindings",
                domain=b"benchmark-v2-qwen-bindings\0",
            ),
            "fusion": _raw_envelope(
                raw_values["fusion"],
                prefix="fusion-result",
                domain=b"benchmark-v2-fusion-result\0",
            ),
        }
        raw_envelopes.extend(envelopes.values())
        group_id = f"provider-{group_index:02d}"
        dependency = {
            "actual_screen_group_ref": _ref(f"screen-{group_index:02d}"),
            "provider_group_ref": _ref(group_id),
            "capture_ref": _ref(f"capture-{group_index:02d}"),
            "pre_vista_evidence_ref": _ref(
                f"pre-vista-evidence/{group_index:064x}"
            ),
            "omni_inventory_ref": deepcopy(envelopes["omni"]["ref"]),
            "qwen_bindings_ref": deepcopy(envelopes["qwen"]["ref"]),
            "fusion_result_ref": deepcopy(envelopes["fusion"]["ref"]),
            "submitted_vista_request_refs": [],
        }
        dependencies.append(dependency)
        groups[group_id] = deepcopy(dependency)
        for case_offset in range(5):
            case_id = f"case-{group_index * 5 + case_offset:03d}"
            case_sha = hashlib.sha256(case_id.encode()).hexdigest()
            cases[case_id] = {
                "provider_group_id": group_id,
                "case_content_sha256": case_sha,
            }
            for arm in arms:
                multiset.append(
                    {
                        "case_id": case_id,
                        "case_content_sha256": case_sha,
                        "arm_id": arm,
                    }
                )
                rows.append(
                    {
                        "case_id": case_id,
                        "arm_id": arm,
                        "selection_status": "missing",
                        "eligibility": "INELIGIBLE",
                        "failure_reason": "target_not_present_pre_vista",
                    }
                )
    digest = hashlib.sha256(_canonical(multiset)).hexdigest()
    body_ref = _ref(f"verified-actual-body/{'1' * 64}")
    identity_source = {
        "benchmark_release_id": "release-one",
        "partition": "regression",
        "source_parent_ref": body_ref,
        "case_arm_multiset_sha256": digest,
        "provider_group_dependencies": dependencies,
        "rows": rows,
        "safety": deepcopy(SAFETY),
    }
    prediction_id = "prediction/" + hashlib.sha256(
        b"benchmark-v2-automatic-prediction-v3\0" + _canonical(identity_source)
    ).hexdigest()
    automatic = seal_pathless_projection(
        contract_version="automatic_prediction_v3",
        semantic_payload={"prediction_id": prediction_id, **identity_source},
    )
    attempt_ref = _ref("runner-attempt/one")
    cleanup_ref = _ref(f"verified-lifecycle/{'2' * 64}")
    selected_lifecycle_ref = _ref(f"verified-lifecycle/{'3' * 64}")
    logical_ref = {
        "contract_version": "benchmark_v2_runner_ledger_pre_result_ref_v1",
        "id": f"runner-ledger-pre-result/{'4' * 64}",
        "attempt_ref": attempt_ref,
        "terminal_sequence": 2,
        "terminal_envelope_sha256": "5" * 64,
        "prefix_sha256": "6" * 64,
    }
    event_payloads = (
        ("opened", {"attempt_ref": attempt_ref}),
        (
            "body_complete",
            {"body_file_ref": {"file_sha256": "7" * 64, "content_sha256": "8" * 64}},
        ),
        (
            "cleanup",
            {
                "cleanup_receipt_ref": _ref("attempt-cleanup-receipt/one"),
                "cleanup_projection_ref": cleanup_ref,
            },
        ),
        (
            "result",
            {
                "result_file_ref": {"file_sha256": "9" * 64, "content_sha256": "a" * 64},
                "attempt_ledger_pre_result_ref": logical_ref,
            },
        ),
    )
    events = []
    previous = None
    for sequence, (kind, refs) in enumerate(event_payloads):
        event = seal_pathless_projection(
            contract_version="benchmark_v2_runner_event_verified_projection_v1",
            semantic_payload={
                "partition": "regression",
                "event_kind": kind,
                "sequence": sequence,
                "attempt_ref": attempt_ref,
                "previous_event_projection_ref": previous,
                "raw_event_sha256": hashlib.sha256(kind.encode()).hexdigest(),
                "load_bearing_refs": refs,
                "safety": deepcopy(SAFETY),
            },
        )
        events.append(event)
        previous = pathless_artifact_ref(event)
    prefix_ref = _ref(f"verified-runner-ledger-prefix/{'b' * 64}")
    ledger = seal_pathless_projection(
        contract_version="benchmark_v2_projected_attempt_ledger_v1",
        semantic_payload={
            "benchmark_release_id": "release-one",
            "partition": "regression",
            "raw_ledger_prefix_verification_ref": prefix_ref,
            "entries": [
                {
                    "sequence": 0,
                    "attempt_ref": attempt_ref,
                    "observed_state": "result",
                    "event_projection_refs": [pathless_artifact_ref(item) for item in events],
                    "lifecycle_ref": selected_lifecycle_ref,
                    "selection_eligible": True,
                }
            ],
            "selected_attempt_ref": attempt_ref,
            "selected_lifecycle_ref": selected_lifecycle_ref,
            "safety": deepcopy(SAFETY),
        },
    )
    children = order_pathless_envelopes(
        registry_name="prediction_run_v3",
        envelopes=[
            *raw_envelopes,
            seal_pathless_envelope(automatic),
            *[seal_pathless_envelope(item) for item in events],
            seal_pathless_envelope(ledger),
        ],
        context={},
    )
    manifest_ref = {
        "contract_version": "portfolio_hybrid_v1_1_provider_manifest_v2_1",
        "relative_path": "benchmark-v2-provider-manifest.json",
        "file_sha256": "c" * 64,
    }
    corpus_ref = {
        "contract_version": "portfolio_hybrid_v1_1_provider_corpus_v2",
        "relative_path": "provider-corpus.v2.json",
        "file_sha256": "d" * 64,
        "content_sha256": "e" * 64,
        "source_parent_ref": deepcopy(PARENT_REF),
    }
    run = seal_pathless_projection(
        contract_version="benchmark_v2_prediction_run_v3",
        semantic_payload={
            "benchmark_release_id": "release-one",
            "partition": "regression",
            "corpus_parent_ref": deepcopy(PARENT_REF),
            "provider_manifest_ref": manifest_ref,
            "provider_corpus_ref": corpus_ref,
            "attempt_ref": attempt_ref,
            "projected_attempt_ledger_ref": pathless_artifact_ref(ledger),
            "raw_ledger_prefix_verification_ref": prefix_ref,
            "automatic_prediction_ref": pathless_artifact_ref(automatic),
            "selected_lifecycle_ref": selected_lifecycle_ref,
            "sealed_artifact_envelopes": children,
            "safety": deepcopy(SAFETY),
        },
    )
    external = _prediction_external_refs(
        prediction_run=run,
        automatic=automatic,
        artifacts=[],
        runner_and_ledger_envelopes=[
            *[seal_pathless_envelope(item) for item in events],
            seal_pathless_envelope(ledger),
        ],
    )
    result = validate_pathless_recursive(
        registry_name="prediction_run_v3",
        roots=[pathless_artifact_ref(run)],
        envelopes=[seal_pathless_envelope(run), *children],
        external_refs=external,
        context={
            "provider_groups": groups,
            "cases": cases,
            "actual_body_projection_ref": body_ref,
            "attempt_ref": attempt_ref,
            "raw_ledger_prefix_verification_ref": prefix_ref,
            "projected_attempt_ledger_ref": pathless_artifact_ref(ledger),
            "selected_lifecycle_ref": selected_lifecycle_ref,
        },
    )
    assert len(result) == 43
    swapped_groups = deepcopy(groups)
    swapped_groups["provider-00"]["capture_ref"] = deepcopy(
        groups["provider-01"]["capture_ref"]
    )
    with pytest.raises(ValueError, match="dependency.*authoritative|group.*context"):
        validate_pathless_recursive(
            registry_name="prediction_run_v3",
            roots=[pathless_artifact_ref(run)],
            envelopes=[seal_pathless_envelope(run), *children],
            external_refs=external,
            context={
                "provider_groups": swapped_groups,
                "cases": cases,
                "actual_body_projection_ref": body_ref,
                "attempt_ref": attempt_ref,
                "raw_ledger_prefix_verification_ref": prefix_ref,
                "projected_attempt_ledger_ref": pathless_artifact_ref(ledger),
                "selected_lifecycle_ref": selected_lifecycle_ref,
            },
        )

    by_ref = {}
    for envelope in [seal_pathless_envelope(run), *children]:
        _, item, _, _ = _decode_envelope(envelope)
        by_ref[_canonical(envelope["ref"])] = (item, envelope)

    detached_events = deepcopy(events)
    detached_events[1]["sequence"] = 2
    detached_events[2]["sequence"] = 3
    detached_events[3]["sequence"] = 4
    detached_by_ref = deepcopy(by_ref)
    for original, changed in zip(events, detached_events, strict=True):
        detached_by_ref[_canonical(pathless_artifact_ref(original))] = (changed, {})
    with pytest.raises(ValueError, match="contiguous|previous|prefix"):
        _validate_projected_ledger_graph(
            ledger, detached_by_ref, allow_external_lifecycle=True
        )

    wrong_predecessor = deepcopy(events)
    wrong_predecessor[2]["previous_event_projection_ref"] = pathless_artifact_ref(
        events[0]
    )
    predecessor_by_ref = deepcopy(by_ref)
    predecessor_by_ref[_canonical(pathless_artifact_ref(events[2]))] = (
        wrong_predecessor[2],
        {},
    )
    with pytest.raises(ValueError, match="previous|predecessor|prefix"):
        _validate_projected_ledger_graph(
            ledger, predecessor_by_ref, allow_external_lifecycle=True
        )

    automatic_key = _canonical(pathless_artifact_ref(automatic))
    fabricated_by_ref = deepcopy(by_ref)
    fabricated = deepcopy(automatic)
    fabricated["rows"][0]["case_id"] = "fabricated-case"
    fabricated_by_ref[automatic_key] = (fabricated, {})
    context = {
        "provider_groups": groups,
        "cases": cases,
        "actual_body_projection_ref": body_ref,
        "attempt_ref": attempt_ref,
        "raw_ledger_prefix_verification_ref": prefix_ref,
        "projected_attempt_ledger_ref": pathless_artifact_ref(ledger),
        "selected_lifecycle_ref": selected_lifecycle_ref,
    }
    with pytest.raises(ValueError, match="case.*authoritative|key set|multiset"):
        _validate_prediction_graph(run, fabricated_by_ref, context)


def test_prediction_registry_rejects_contract_version_only_raw_provider_object() -> None:
    invalid = seal_immutable(
        {"contract_version": "hybrid_omni_inventory_v1", "capture_identity": {}}
    )
    envelope = _raw_envelope(
        invalid,
        prefix="omni-inventory",
        domain=b"benchmark-v2-omni-inventory\0",
    )
    with pytest.raises(ValueError, match="Omni inventory.*closed"):
        order_pathless_envelopes(
            registry_name="prediction_run_v3", envelopes=[envelope], context={}
        )


def test_prediction_registry_rejects_legacy_automatic_prediction_v2() -> None:
    legacy = {
        "contract_version": "automatic_prediction_v2",
        "artifact_id": "automatic/legacy",
        "prediction_id": "prediction/legacy",
        "source_parent_ref": _ref("body/legacy"),
        "partition": "regression",
        "release_id": "release-one",
        "rows": [
            {
                "case_id": "case-one",
                "arm_id": "qwen_only",
                "selection_status": "missing",
                "eligibility": "INELIGIBLE",
                "failure_reason": "target_not_present_pre_vista",
            }
        ],
        "safety": deepcopy(SAFETY),
    }
    envelope = _raw_envelope(legacy, prefix="automatic", domain=b"")

    with pytest.raises(ValueError, match="automatic_prediction_v2|legacy|not allowed"):
        order_pathless_envelopes(
            registry_name="prediction_run_v3", envelopes=[envelope], context={}
        )


def test_automatic_prediction_v3_requires_frozen_identity_and_row_order() -> None:
    source_parent_ref = _ref(f"verified-actual-body/{'a' * 64}")
    dependencies = [
        {
            "actual_screen_group_ref": _ref(f"screen-{index:02d}"),
            "provider_group_ref": _ref(f"provider-{index:02d}"),
            "capture_ref": _ref(f"capture-{index:02d}"),
            "pre_vista_evidence_ref": _ref(f"pre-vista-evidence/{index:064x}"),
            "omni_inventory_ref": _ref(f"omni-inventory/{index:064x}"),
            "qwen_bindings_ref": _ref(f"qwen-bindings/{index:064x}"),
            "fusion_result_ref": _ref(f"fusion-result/{index:064x}"),
            "submitted_vista_request_refs": [],
        }
        for index in range(12)
    ]
    rows = [
        {
            "case_id": f"case-{case_index:03d}",
            "arm_id": arm,
            "selection_status": "missing",
            "eligibility": "INELIGIBLE",
            "failure_reason": "target_not_present_pre_vista",
        }
        for case_index in range(60)
        for arm in ("qwen_only", "omni_only_discovery", "omni_to_qwen", "omni_to_qwen_vista")
    ]
    semantic_without_prediction_id = {
        "benchmark_release_id": "release-one",
        "partition": "regression",
        "source_parent_ref": source_parent_ref,
        "case_arm_multiset_sha256": "b" * 64,
        "provider_group_dependencies": dependencies,
        "rows": rows,
        "safety": deepcopy(SAFETY),
    }
    prediction_id = "prediction/" + hashlib.sha256(
        b"benchmark-v2-automatic-prediction-v3\0"
        + json.dumps(
            semantic_without_prediction_id,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    automatic = seal_pathless_projection(
        contract_version="automatic_prediction_v3",
        semantic_payload={
            "prediction_id": prediction_id,
            **semantic_without_prediction_id,
        },
    )

    expected_artifact_id = "automatic/" + hashlib.sha256(
        b"automatic_prediction_v3\0"
        + json.dumps(
            {"prediction_id": prediction_id, **semantic_without_prediction_id},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert automatic["artifact_id"] == expected_artifact_id

    reordered = deepcopy({"prediction_id": prediction_id, **semantic_without_prediction_id})
    reordered["rows"] = list(reversed(reordered["rows"]))
    with pytest.raises(ValueError, match="row.*order|prediction identity"):
        seal_pathless_projection(
            contract_version="automatic_prediction_v3", semantic_payload=reordered
        )


def test_prediction_run_v3_task10_refs_are_typed_and_path_literals_are_frozen() -> None:
    from app.learn.hybrid.benchmark_v2_contracts import PARENT_REF

    manifest_ref = {
        "contract_version": "portfolio_hybrid_v1_1_provider_manifest_v2_1",
        "relative_path": "benchmark-v2-provider-manifest.json",
        "file_sha256": "b" * 64,
    }
    corpus_ref = {
        "contract_version": "portfolio_hybrid_v1_1_provider_corpus_v2",
        "relative_path": "provider-corpus.v2.json",
        "file_sha256": "c" * 64,
        "content_sha256": "d" * 64,
        "source_parent_ref": deepcopy(PARENT_REF),
    }
    context = {"contract_version": "benchmark_v2_prediction_run_v3"}
    assert validate_pathless_ref(
        role="corpus_parent_ref", value=PARENT_REF, context=context
    ) == PARENT_REF
    assert validate_pathless_ref(
        role="provider_manifest_ref", value=manifest_ref, context=context
    ) == manifest_ref
    assert validate_pathless_ref(
        role="provider_corpus_ref", value=corpus_ref, context=context
    ) == corpus_ref

    changed = deepcopy(corpus_ref)
    changed["relative_path"] = "../provider-corpus.v2.json"
    with pytest.raises(ValueError, match="logical identity|invalid"):
        validate_pathless_ref(
            role="provider_corpus_ref", value=changed, context=context
        )


@pytest.mark.parametrize(
    "contract_version",
    ["benchmark_v2_prediction_run_v3", "benchmark_v2_lifecycle_bundle_v3"],
)
def test_outer_v3_contract_rejects_empty_envelope_closure(contract_version: str) -> None:
    common = {
        "benchmark_release_id": "release-one",
        "partition": "regression",
        "attempt_ref": _ref("runner-attempt/one"),
        "projected_attempt_ledger_ref": _ref(f"projected-attempt-ledger/{'1' * 64}"),
        "raw_ledger_prefix_verification_ref": _ref(f"verified-runner-ledger-prefix/{'2' * 64}"),
        "selected_lifecycle_ref": _ref(f"verified-lifecycle/{'3' * 64}"),
        "sealed_artifact_envelopes": [],
        "safety": deepcopy(SAFETY),
    }
    if contract_version == "benchmark_v2_prediction_run_v3":
        payload = {
            **common,
            "corpus_parent_ref": _ref("corpus-parent/one"),
            "provider_manifest_ref": _ref("provider-manifest/one"),
            "provider_corpus_ref": _ref("provider-corpus/one"),
            "automatic_prediction_ref": _ref("automatic/one"),
        }
    else:
        payload = {
            **common,
            "attempt_cleanup_projection_ref": _ref(f"verified-lifecycle/{'4' * 64}"),
            "screen_group_lifecycle_projection_refs": [
                _ref(f"verified-lifecycle/{index:064x}") for index in range(12)
            ],
        }
    with pytest.raises(ValueError, match="closure.*empty"):
        seal_pathless_projection(contract_version=contract_version, semantic_payload=payload)


def test_outer_v3_contract_decodes_raw_envelope_and_rejects_private_path() -> None:
    leaked = {"contract_version": "hybrid_omni_inventory_v1", "private_path": "C:\\secret\\raw.json"}
    envelope = _raw_envelope(
        leaked, prefix="omni-inventory", domain=b"benchmark-v2-omni-inventory\0"
    )
    payload = {
        "benchmark_release_id": "release-one",
        "partition": "regression",
        "corpus_parent_ref": _ref("corpus-parent/one"),
        "provider_manifest_ref": _ref("provider-manifest/one"),
        "provider_corpus_ref": _ref("provider-corpus/one"),
        "attempt_ref": _ref("runner-attempt/one"),
        "projected_attempt_ledger_ref": _ref(f"projected-attempt-ledger/{'1' * 64}"),
        "raw_ledger_prefix_verification_ref": _ref(f"verified-runner-ledger-prefix/{'2' * 64}"),
        "automatic_prediction_ref": _ref("automatic/one"),
        "selected_lifecycle_ref": _ref(f"verified-lifecycle/{'3' * 64}"),
        "sealed_artifact_envelopes": [envelope],
        "safety": deepcopy(SAFETY),
    }
    with pytest.raises(ValueError, match="path"):
        seal_pathless_projection(
            contract_version="benchmark_v2_prediction_run_v3", semantic_payload=payload
        )


def _event_projection(
    *, kind: str, sequence: int, attempt_ref: dict[str, str], previous: dict[str, str] | None,
    cleanup_ref: dict[str, str], cleanup_projection_ref: dict[str, str], logical_ref: dict[str, object]
) -> dict[str, object]:
    refs: dict[str, object]
    if kind == "opened":
        refs = {"attempt_ref": attempt_ref}
    elif kind == "body_complete":
        refs = {"body_file_ref": {"file_sha256": "4" * 64, "content_sha256": "5" * 64}}
    elif kind == "cleanup":
        refs = {"cleanup_receipt_ref": cleanup_ref, "cleanup_projection_ref": cleanup_projection_ref}
    else:
        refs = {
            "result_file_ref": {"file_sha256": "6" * 64, "content_sha256": "7" * 64},
            "attempt_ledger_pre_result_ref": logical_ref,
        }
    return seal_pathless_projection(
        contract_version="benchmark_v2_runner_event_verified_projection_v1",
        semantic_payload={
            "partition": "regression",
            "event_kind": kind,
            "sequence": sequence,
            "attempt_ref": attempt_ref,
            "previous_event_projection_ref": previous,
            "raw_event_sha256": f"{8 + sequence:x}" * 64,
            "load_bearing_refs": refs,
            "safety": deepcopy(SAFETY),
        },
    )


def test_recursive_projected_ledger_rejects_cleanup_lifecycle_as_selected_attempt() -> None:
    attempt = _ref("runner-attempt/one")
    receipt = _ref("attempt-cleanup-receipt/one")
    cleanup = seal_pathless_projection(
        contract_version="benchmark_v2_lifecycle_verified_projection_v1",
        semantic_payload={
            "attempt_ref": attempt,
            "lifecycle_kind": "cleanup",
            "raw_evidence_sha256": "b" * 64,
            "terminal_status": "stable_zero",
            "cleanup_stable_zero": True,
            "resource_counts": {"service_operations": 0, "windows": 0, "providers": 0, "listeners": 0, "leases": 0},
            "started_request_count": 0,
            "terminal_or_unknown_request_count": 0,
            "parent_refs": {"cleanup_receipt_ref": receipt},
            "safety": deepcopy(SAFETY),
        },
    )
    cleanup_projection_ref = pathless_artifact_ref(cleanup)
    logical = {
        "contract_version": "benchmark_v2_runner_ledger_pre_result_ref_v1",
        "id": f"runner-ledger-pre-result/{'c' * 64}",
        "attempt_ref": attempt,
        "terminal_sequence": 2,
        "terminal_envelope_sha256": "d" * 64,
        "prefix_sha256": "e" * 64,
    }
    events: list[dict[str, object]] = []
    previous = None
    for sequence, kind in enumerate(("opened", "body_complete", "cleanup", "result")):
        event = _event_projection(
            kind=kind,
            sequence=sequence,
            attempt_ref=attempt,
            previous=previous,
            cleanup_ref=receipt,
            cleanup_projection_ref=cleanup_projection_ref,
            logical_ref=logical,
        )
        events.append(event)
        previous = pathless_artifact_ref(event)
    ledger = seal_pathless_projection(
        contract_version="benchmark_v2_projected_attempt_ledger_v1",
        semantic_payload={
            "benchmark_release_id": "release-one",
            "partition": "regression",
            "raw_ledger_prefix_verification_ref": _ref(f"verified-runner-ledger-prefix/{'f' * 64}"),
            "entries": [{
                "sequence": 0,
                "attempt_ref": attempt,
                "observed_state": "result",
                "event_projection_refs": [pathless_artifact_ref(item) for item in events],
                "lifecycle_ref": cleanup_projection_ref,
                "selection_eligible": True,
            }],
            "selected_attempt_ref": attempt,
            "selected_lifecycle_ref": cleanup_projection_ref,
            "safety": deepcopy(SAFETY),
        },
    )
    external = {
        "benchmark_v2_projected_attempt_ledger_v1.raw_ledger_prefix_verification_ref": _ref(f"verified-runner-ledger-prefix/{'f' * 64}"),
        "benchmark_v2_projected_attempt_ledger_v1.selected_attempt_ref": attempt,
        "benchmark_v2_projected_attempt_ledger_v1.entries.attempt_ref": attempt,
        "benchmark_v2_runner_event_verified_projection_v1.attempt_ref": attempt,
        "benchmark_v2_runner_event_verified_projection_v1.load_bearing_refs.attempt_ref": attempt,
        "benchmark_v2_runner_event_verified_projection_v1.load_bearing_refs.body_file_ref": {"file_sha256": "4" * 64, "content_sha256": "5" * 64},
        "benchmark_v2_runner_event_verified_projection_v1.load_bearing_refs.cleanup_receipt_ref": receipt,
        "benchmark_v2_runner_event_verified_projection_v1.load_bearing_refs.result_file_ref": {"file_sha256": "6" * 64, "content_sha256": "7" * 64},
        "benchmark_v2_runner_event_verified_projection_v1.load_bearing_refs.attempt_ledger_pre_result_ref": logical,
        "benchmark_v2_lifecycle_verified_projection_v1.attempt_ref": attempt,
        "benchmark_v2_lifecycle_verified_projection_v1.parent_refs.cleanup_receipt_ref": receipt,
    }
    with pytest.raises(ValueError, match="selected lifecycle.*attempt"):
        validate_pathless_recursive(
            registry_name="lifecycle_bundle_v3",
            roots=[pathless_artifact_ref(ledger)],
            envelopes=[seal_pathless_envelope(cleanup), *[seal_pathless_envelope(item) for item in events], seal_pathless_envelope(ledger)],
            external_refs=external,
            context={},
        )


@pytest.mark.parametrize(
    ("interleaved_complete", "select_later_complete"),
    [(False, False), (True, False), (True, True)],
)
def test_lifecycle_bundle_enforces_first_open_selection_and_cleanup_order(
    interleaved_complete: bool,
    select_later_complete: bool,
) -> None:
    prior_attempt = {
        "id": "runner-attempt/prior",
        "content_sha256": "b" * 64,
    }
    selected_attempt = {
        "id": "runner-attempt/selected",
        "content_sha256": "c" * 64,
    }
    prior_receipt = {
        "id": "attempt-cleanup-receipt/prior",
        "content_sha256": "d" * 64,
    }
    selected_receipt = {
        "id": "attempt-cleanup-receipt/selected",
        "content_sha256": "e" * 64,
    }

    def cleanup_lifecycle(attempt_ref, receipt_ref, marker):
        return seal_pathless_projection(
            contract_version="benchmark_v2_lifecycle_verified_projection_v1",
            semantic_payload={
                "attempt_ref": attempt_ref,
                "lifecycle_kind": "cleanup",
                "raw_evidence_sha256": marker * 64,
                "terminal_status": "stable_zero",
                "cleanup_stable_zero": True,
                "resource_counts": {"service_operations": 0, "windows": 0, "providers": 0, "listeners": 0, "leases": 0},
                "started_request_count": 0,
                "terminal_or_unknown_request_count": 0,
                "parent_refs": {"cleanup_receipt_ref": receipt_ref},
                "safety": deepcopy(SAFETY),
            },
        )

    prior_cleanup = cleanup_lifecycle(prior_attempt, prior_receipt, "2")
    selected_cleanup = cleanup_lifecycle(selected_attempt, selected_receipt, "1")
    prior_cleanup_ref = pathless_artifact_ref(prior_cleanup)
    selected_cleanup_ref = pathless_artifact_ref(selected_cleanup)
    assert prior_cleanup_ref["id"] > selected_cleanup_ref["id"]
    bundle_attempt = prior_attempt if select_later_complete else selected_attempt
    bundle_receipt = prior_receipt if select_later_complete else selected_receipt
    bundle_cleanup_ref = (
        prior_cleanup_ref if select_later_complete else selected_cleanup_ref
    )
    logical = {
        "contract_version": "benchmark_v2_runner_ledger_pre_result_ref_v1",
            "id": f"runner-ledger-pre-result/{'3' * 64}",
            "attempt_ref": bundle_attempt,
        "terminal_sequence": 4,
        "terminal_envelope_sha256": "4" * 64,
        "prefix_sha256": "5" * 64,
    }
    events: list[dict[str, object]] = []
    previous = None
    if interleaved_complete:
        raw_events = (
            (0, "opened", selected_attempt, selected_receipt, selected_cleanup_ref),
            (1, "opened", prior_attempt, prior_receipt, prior_cleanup_ref),
            (2, "body_complete", prior_attempt, prior_receipt, prior_cleanup_ref),
            (3, "cleanup", prior_attempt, prior_receipt, prior_cleanup_ref),
            (4, "result", prior_attempt, prior_receipt, prior_cleanup_ref),
            (5, "body_complete", selected_attempt, selected_receipt, selected_cleanup_ref),
            (6, "cleanup", selected_attempt, selected_receipt, selected_cleanup_ref),
            (7, "result", selected_attempt, selected_receipt, selected_cleanup_ref),
        )
        attempt_first_open_order = [selected_attempt, prior_attempt]
    else:
        raw_events = (
            (0, "opened", prior_attempt, prior_receipt, prior_cleanup_ref),
            (1, "cleanup", prior_attempt, prior_receipt, prior_cleanup_ref),
            (2, "opened", selected_attempt, selected_receipt, selected_cleanup_ref),
            (3, "body_complete", selected_attempt, selected_receipt, selected_cleanup_ref),
            (4, "cleanup", selected_attempt, selected_receipt, selected_cleanup_ref),
            (5, "result", selected_attempt, selected_receipt, selected_cleanup_ref),
        )
        attempt_first_open_order = [prior_attempt, selected_attempt]
    events_by_attempt: dict[str, list[dict[str, object]]] = {
        str(prior_attempt["content_sha256"]): [],
        str(selected_attempt["content_sha256"]): [],
    }
    for sequence, kind, attempt, receipt, cleanup_ref in raw_events:
        event = _event_projection(
            kind=kind,
            sequence=sequence,
            attempt_ref=attempt,
            previous=previous,
            cleanup_ref=receipt,
            cleanup_projection_ref=cleanup_ref,
            logical_ref=logical,
        )
        events.append(event)
        events_by_attempt[str(attempt["content_sha256"])].append(event)
        previous = pathless_artifact_ref(event)

    screens = []
    for index in range(12):
        screens.append(
            seal_pathless_projection(
                contract_version="benchmark_v2_lifecycle_verified_projection_v1",
                semantic_payload={
                        "attempt_ref": bundle_attempt,
                    "lifecycle_kind": "screen_group",
                    "raw_evidence_sha256": f"{10 + (index % 6):x}" * 64,
                    "terminal_status": "stable_zero",
                    "cleanup_stable_zero": True,
                    "resource_counts": {"service_operations": 0, "windows": 0, "providers": 0, "listeners": 0, "leases": 0},
                    "started_request_count": 0,
                    "terminal_or_unknown_request_count": 0,
                    "parent_refs": {
                        "actual_screen_group_ref": _ref(f"actual-screen-group/{index:02d}"),
                        "provider_group_ref": _ref(f"provider-group/{index:02d}"),
                    },
                    "safety": deepcopy(SAFETY),
                },
            )
        )
    terminal = seal_pathless_projection(
        contract_version="benchmark_v2_attempt_journal_terminal_event_verified_projection_v1",
        semantic_payload={
            "attempt_ref": bundle_attempt,
            "sequence": 0,
            "phase": "terminal",
            "event_kind": "attempt_terminal",
            "raw_event_sha256": "6" * 64,
            "predecessor_content_sha256": "7" * 64,
            "cleanup_receipt_ref": bundle_receipt,
            "cleanup_projection_ref": bundle_cleanup_ref,
            "safety": deepcopy(SAFETY),
        },
    )
    selected_lifecycle = seal_pathless_projection(
        contract_version="benchmark_v2_lifecycle_verified_projection_v1",
        semantic_payload={
            "attempt_ref": bundle_attempt,
            "lifecycle_kind": "attempt",
            "raw_evidence_sha256": "8" * 64,
            "terminal_status": "terminal",
            "cleanup_stable_zero": True,
            "resource_counts": {"service_operations": 0, "windows": 0, "providers": 0, "listeners": 0, "leases": 0},
            "started_request_count": 0,
            "terminal_or_unknown_request_count": 0,
            "parent_refs": {
                "attempt_journal_projection_ref": _ref(f"verified-attempt-journal/{'9' * 64}"),
                "cleanup_projection_ref": bundle_cleanup_ref,
                "terminal_event_ref": pathless_artifact_ref(terminal),
                "screen_group_lifecycle_projection_refs": [pathless_artifact_ref(item) for item in screens],
            },
            "safety": deepcopy(SAFETY),
        },
    )
    selected_lifecycle_ref = pathless_artifact_ref(selected_lifecycle)
    prefix_ref = _ref(f"verified-runner-ledger-prefix/{'a' * 64}")
    ledger = seal_pathless_projection(
        contract_version="benchmark_v2_projected_attempt_ledger_v1",
        semantic_payload={
            "benchmark_release_id": "release-one",
            "partition": "regression",
            "raw_ledger_prefix_verification_ref": prefix_ref,
            "entries": [
                {
                    "sequence": index,
                    "attempt_ref": attempt,
                    "observed_state": (
                        "result"
                        if attempt == bundle_attempt or interleaved_complete
                        else "cleanup"
                    ),
                    "event_projection_refs": [
                        pathless_artifact_ref(item)
                        for item in events_by_attempt[str(attempt["content_sha256"])]
                    ],
                    "lifecycle_ref": (
                        selected_lifecycle_ref if attempt == bundle_attempt else None
                    ),
                    "selection_eligible": attempt == bundle_attempt,
                }
                for index, attempt in enumerate(attempt_first_open_order)
            ],
            "selected_attempt_ref": bundle_attempt,
            "selected_lifecycle_ref": selected_lifecycle_ref,
            "safety": deepcopy(SAFETY),
        },
    )
    raw_envelopes = [
        *[seal_pathless_envelope(item) for item in screens],
        seal_pathless_envelope(selected_cleanup),
        seal_pathless_envelope(prior_cleanup),
        seal_pathless_envelope(terminal),
        seal_pathless_envelope(selected_lifecycle),
        *[seal_pathless_envelope(item) for item in events],
        seal_pathless_envelope(ledger),
    ]
    ordered = order_pathless_envelopes(
        registry_name="lifecycle_bundle_v3",
        envelopes=raw_envelopes,
        context={"attempt_first_open_order": attempt_first_open_order},
    )
    ordered_cleanup_refs = [
        envelope["ref"]
        for envelope in ordered
        if json.loads(base64.b64decode(envelope["canonical_bytes_b64"])).get("lifecycle_kind") == "cleanup"
    ]
    expected_cleanup_refs = [
        selected_cleanup_ref if attempt == selected_attempt else prior_cleanup_ref
        for attempt in attempt_first_open_order
    ]
    assert ordered_cleanup_refs == expected_cleanup_refs
    payload = {
        "benchmark_release_id": "release-one",
        "partition": "regression",
        "attempt_ref": bundle_attempt,
        "projected_attempt_ledger_ref": pathless_artifact_ref(ledger),
        "raw_ledger_prefix_verification_ref": prefix_ref,
        "selected_lifecycle_ref": selected_lifecycle_ref,
        "attempt_cleanup_projection_ref": bundle_cleanup_ref,
        "screen_group_lifecycle_projection_refs": [
            pathless_artifact_ref(item) for item in screens
        ],
        "sealed_artifact_envelopes": ordered,
        "safety": deepcopy(SAFETY),
    }
    if select_later_complete:
        with pytest.raises(ValueError, match="first raw-complete"):
            seal_pathless_projection(
                contract_version="benchmark_v2_lifecycle_bundle_v3",
                semantic_payload=payload,
            )
    else:
        bundle = seal_pathless_projection(
            contract_version="benchmark_v2_lifecycle_bundle_v3",
            semantic_payload=payload,
        )
        assert bundle["attempt_cleanup_projection_ref"] == bundle_cleanup_ref
