from __future__ import annotations

import ast
import base64
from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from app.learn.hybrid import benchmark_v2_incumbent_operation as incumbent
from app.learn.hybrid import benchmark_v2_actual as actual
from app.learn.hybrid import benchmark_v2_lifecycle as benchmark_lifecycle
from app.learn.hybrid import benchmark_v2_predictions as benchmark_predictions
from app.learn.hybrid.benchmark_v2_actual import (
    WorkflowServicePort,
    run_screen_group,
)
from app.learn.hybrid.benchmark_v2_contracts import content_sha256
from app.learn.hybrid.benchmark_v2_predictions import (
    PredictionRunV3Materialization,
    materialize_prediction_run_v3,
)
from app.learn.hybrid.vista_refinement import build_vista_requests
from app.learn.recognition.uei.canonical import seal_immutable
from tests.test_learn_hybrid_vista_refinement import _authoritative_inputs


SHA_A = "a" * 64
SHA_B = "b" * 64


def _offline_file_bytes(value: Mapping[str, object]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def _offline_fixed_raw_graph(
    source: Mapping[str, object],
    *,
    cleanup_receipt: Mapping[str, object] | None = None,
) -> dict[str, object]:
    from app.learn.hybrid import benchmark_v2_lifecycle as lifecycle
    from app.learn.hybrid.benchmark_v2_contracts import canonical_json_bytes
    from tests.test_portfolio_hybrid_v1_1_benchmark_v2_lifecycle import (
        _s13_append_runner_event,
        _s13_journal,
        _s13_journal_projection,
        _s13_runner_payload,
        _s13_runner_prefix_projection,
    )

    attempt = deepcopy(source["attempt"])
    body = deepcopy(source["body"])
    cleanup = deepcopy(cleanup_receipt or source["cleanup"])
    attempt_dir = Path(
        f"C:\\private\\benchmark\\{attempt['attempt_id']}"
    ).resolve()
    body_bytes = _offline_file_bytes(body)
    cleanup_bytes = _offline_file_bytes(cleanup)
    body_ref = {
        "path": str((attempt_dir / "body.json").resolve()),
        "file_sha256": hashlib.sha256(body_bytes).hexdigest(),
        "content_sha256": body["content_sha256"],
    }
    cleanup_ref = {
        "path": str((attempt_dir / "cleanup.json").resolve()),
        "file_sha256": hashlib.sha256(cleanup_bytes).hexdigest(),
        "content_sha256": cleanup["content_sha256"],
    }
    ledger: list[dict[str, object]] = []
    _s13_append_runner_event(
        ledger,
        event_type="regression_attempt",
        payload=_s13_runner_payload(
            attempt=attempt,
            status="opened",
            contract_version="benchmark_v2_runner_regression_attempt_payload_v1",
        ),
    )
    _s13_append_runner_event(
        ledger,
        event_type="regression_attempt",
        payload=_s13_runner_payload(
            attempt=attempt,
            status="body_complete",
            contract_version="benchmark_v2_runner_regression_attempt_payload_v1",
            output_ref=body_ref,
        ),
    )
    _s13_append_runner_event(
        ledger,
        event_type="cleanup",
        payload=_s13_runner_payload(
            attempt=attempt,
            status="terminal",
            contract_version="benchmark_v2_runner_cleanup_payload_v1",
            cleanup_receipt_ref=cleanup_ref,
        ),
    )
    raw_prefix = b"".join(canonical_json_bytes(item) + b"\n" for item in ledger)
    pre_result_ref = {
        "contract_version": "benchmark_v2_runner_ledger_pre_result_ref_v1",
        "id": "runner-ledger-pre-result/"
        + hashlib.sha256(
            b"benchmark-v2-runner-ledger-pre-result\0" + raw_prefix
        ).hexdigest(),
        "attempt_ref": attempt,
        "terminal_sequence": 2,
        "terminal_envelope_sha256": hashlib.sha256(
            canonical_json_bytes(ledger[-1])
        ).hexdigest(),
        "prefix_sha256": hashlib.sha256(raw_prefix).hexdigest(),
    }
    result = seal_immutable(
        {
            "contract_version": "benchmark_v2_runner_actual_result_v2",
            "attempt_ref": attempt,
            "attempt_dir": str(attempt_dir),
            "body_ref": body_ref,
            "cleanup_receipt_ref": cleanup_ref,
            "attempt_ledger_pre_result_ref": pre_result_ref,
            "screen_group_count": 12,
            "status": "terminal",
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    result_bytes = _offline_file_bytes(result)
    _s13_append_runner_event(
        ledger,
        event_type="result",
        payload=_s13_runner_payload(
            attempt=attempt,
            status="terminal",
            contract_version="benchmark_v2_runner_result_payload_v1",
            output_ref={
                "path": str((attempt_dir / "result.json").resolve()),
                "file_sha256": hashlib.sha256(result_bytes).hexdigest(),
                "content_sha256": result["content_sha256"],
            },
        ),
    )
    cleanup_projection = lifecycle.project_benchmark_v2_cleanup_lifecycle(
        attempt_ref=attempt, cleanup_receipt=cleanup
    )
    journal = _s13_journal(attempt=attempt, cleanup=cleanup)
    terminal = lifecycle.project_benchmark_v2_attempt_journal_terminal_event(
        attempt_ref=attempt,
        journal_events=journal,
        cleanup_receipt=cleanup,
        cleanup_projection=cleanup_projection,
    )
    journal_projection = _s13_journal_projection(
        attempt=attempt,
        journal=journal,
        terminal_projection=terminal,
        cleanup_projection=cleanup_projection,
    )
    screens = lifecycle.project_benchmark_v2_screen_group_lifecycles(
        attempt_ref=attempt,
        screen_group_projections=body["screen_group_results"],
    )
    attempt_lifecycle = lifecycle.project_benchmark_v2_attempt_lifecycle(
        attempt_ref=attempt,
        journal_events=journal,
        attempt_journal_projection=journal_projection,
        cleanup_projection=cleanup_projection,
        terminal_event_projection=terminal,
        screen_group_lifecycle_projections=screens,
    )
    events = lifecycle.project_benchmark_v2_runner_events(
        partition="regression",
        runner_ledger_events=ledger,
        actual_body=body,
        actual_result=result,
        cleanup_receipt=cleanup,
        cleanup_projection=cleanup_projection,
    )
    prefix = _s13_runner_prefix_projection(ledger=ledger, events=events)
    return {
        "attempt": attempt,
        "body": body,
        "cleanup": cleanup,
        "result": result,
        "ledger": ledger,
        "cleanup_projection": cleanup_projection,
        "journal": journal,
        "terminal": terminal,
        "journal_projection": journal_projection,
        "screens": screens,
        "attempt_lifecycle": attempt_lifecycle,
        "events": events,
        "prefix": prefix,
        "attempt_dir": attempt_dir,
        "body_bytes": body_bytes,
        "cleanup_bytes": cleanup_bytes,
        "result_bytes": result_bytes,
    }


def test_prediction_run_v3_materializer_is_byte_only_and_rejects_legacy_body() -> None:
    signature = inspect.signature(materialize_prediction_run_v3)
    assert list(signature.parameters) == [
        "actual_body_bytes",
        "provider_manifest_bytes",
        "provider_corpus_bytes",
        "actual_body_verified_projection",
        "lifecycle_bundle_v3",
    ]
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in signature.parameters.values()
    )
    assert PredictionRunV3Materialization.__dataclass_params__.frozen is True
    legacy_body = {
        "contract_version": "benchmark_v2_runner_actual_body_v0",
        "content_sha256": "a" * 64,
    }
    legacy_bytes = (
        json.dumps(
            legacy_body,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    with pytest.raises(ValueError, match="actual body contract"):
        materialize_prediction_run_v3(
            actual_body_bytes=legacy_bytes,
            provider_manifest_bytes=b"{}\n",
            provider_corpus_bytes=b"{}\n",
            actual_body_verified_projection={},
            lifecycle_bundle_v3={},
        )


def _offline_c3_inputs(monkeypatch):
    from app.learn.hybrid import benchmark_v2_lifecycle as lifecycle
    from app.learn.hybrid import benchmark_v2_predictions as predictions
    from app.learn.hybrid.benchmark_v2_contracts import (
        ARM_ORDER,
        BENCHMARK_RELEASE_ID,
        PARENT_REF,
    )
    from app.learn.hybrid.benchmark_v2_pathless import seal_pathless_projection
    from tests.test_portfolio_hybrid_v1_1_benchmark_v2_lifecycle import (
        _s13_complete_graph,
    )

    graph = _offline_fixed_raw_graph(_s13_complete_graph())
    ledger = lifecycle.project_benchmark_v2_attempt_ledger(
        benchmark_release_id=BENCHMARK_RELEASE_ID,
        partition="regression",
        runner_ledger_events=graph["ledger"],
        runner_event_projections=graph["events"],
        raw_ledger_prefix_projection=graph["prefix"],
        attempt_lifecycle_projections=[graph["attempt_lifecycle"]],
    )
    bundle = lifecycle.compose_benchmark_v2_lifecycle_bundle_v3(
        benchmark_release_id=BENCHMARK_RELEASE_ID,
        partition="regression",
        attempt_ref=graph["attempt"],
        raw_ledger_prefix_projection=graph["prefix"],
        projected_attempt_ledger=ledger,
        selected_attempt_lifecycle_projection=graph["attempt_lifecycle"],
        cleanup_lifecycle_projection=graph["cleanup_projection"],
        journal_terminal_event_projection=graph["terminal"],
        attempt_journal_projection=graph["journal_projection"],
        screen_group_lifecycle_projections=graph["screens"],
        runner_event_projections=graph["events"],
        cleanup_receipt=graph["cleanup"],
    )
    body = deepcopy(graph["body"])
    body_bytes = (
        json.dumps(
            body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        + b"\n"
    )
    case_context = {}
    provider_cases = {}
    multiset = []
    group_images = {}
    for group_index, screen in enumerate(body["screen_group_results"]):
        group_id = str(screen["screen_group"])
        group_images[group_id] = {
            "path": f"artifacts/benchmark/offline-{group_index:02d}.png",
            "sha256": f"{group_index + 1:064x}",
            "width": 1280,
            "height": 720,
        }
        seen = set()
        for row in screen["rows"]:
            case_ref = row["case_ref"]
            case_id = str(case_ref["case_id"])
            if case_id in seen:
                continue
            seen.add(case_id)
            case_context[case_id] = {
                "provider_group_id": group_id,
                "case_content_sha256": str(case_ref["case_content_sha256"]),
            }
            provider_cases[case_id] = {
                "case_id": case_id,
                "partition": "regression",
                "screen_group": group_id,
                "goal": "Select the button labeled 'missing'",
                "image": deepcopy(group_images[group_id]),
                "layout": {},
            }
            for arm_id in ARM_ORDER:
                multiset.append(
                    {
                        "case_id": case_id,
                        "case_content_sha256": str(case_ref["case_content_sha256"]),
                        "arm_id": arm_id,
                    }
                )
    arm_rank = {arm: index for index, arm in enumerate(ARM_ORDER)}
    multiset.sort(key=lambda item: (item["case_id"], arm_rank[item["arm_id"]]))
    digest = hashlib.sha256(
        json.dumps(
            multiset,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    dependency_by_group = {}
    material_by_group = {}
    for group_index, screen in enumerate(body["screen_group_results"]):
        group_id = str(screen["screen_group"])
        capture_ref = deepcopy(screen["shared_parent_refs"]["capture_ref"])
        capture_identity = {
            "capture_id": capture_ref["id"],
            "capture_lineage_ref": {
                "id": capture_ref["id"],
                "content_sha256": capture_ref["content_sha256"],
            },
            "screenshot_sha256": group_images[group_id]["sha256"],
            "image_size": {
                "width": group_images[group_id]["width"],
                "height": group_images[group_id]["height"],
            },
        }
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

        def raw_envelope(value, prefix, domain):
            raw = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            return {
                "ref": {
                    "id": f"{prefix}/{hashlib.sha256(domain + raw).hexdigest()}",
                    "content_sha256": hashlib.sha256(raw).hexdigest(),
                },
                "canonical_bytes_b64": base64.b64encode(raw).decode("ascii"),
            }

        envelopes = {
            "omni": raw_envelope(
                raw_values["omni"],
                "omni-inventory",
                b"benchmark-v2-omni-inventory\0",
            ),
            "qwen": raw_envelope(
                raw_values["qwen"],
                "qwen-bindings",
                b"benchmark-v2-qwen-bindings\0",
            ),
            "fusion": raw_envelope(
                raw_values["fusion"],
                "fusion-result",
                b"benchmark-v2-fusion-result\0",
            ),
        }
        provider_group_ref = deepcopy(screen["pre_vista_evidence"]["provider_group_ref"])
        pre_vista_evidence = seal_immutable(
            {
                "contract_version": "benchmark_v2_actual_pre_vista_evidence_v1",
                "provider_group_ref": provider_group_ref,
                "omni_inventory_envelope": envelopes["omni"],
                "qwen_bindings_envelope": envelopes["qwen"],
                "fusion_result_envelope": envelopes["fusion"],
                "submitted_vista_request_envelopes": [],
                "safety": deepcopy(predictions.SAFETY),
            }
        )
        dependency = {
            "actual_screen_group_ref": {
                "id": group_id,
                "content_sha256": str(screen["content_sha256"]),
            },
            "provider_group_ref": provider_group_ref,
            "capture_ref": capture_ref,
            "pre_vista_evidence_ref": predictions._pre_vista_evidence_ref(
                pre_vista_evidence
            ),
            "omni_inventory_ref": deepcopy(envelopes["omni"]["ref"]),
            "qwen_bindings_ref": deepcopy(envelopes["qwen"]["ref"]),
            "fusion_result_ref": deepcopy(envelopes["fusion"]["ref"]),
            "submitted_vista_request_refs": [],
        }
        missing_rows = [
            {
                "case_id": case_id,
                "arm_id": arm_id,
                "selection_status": "missing",
                "eligibility": "INELIGIBLE",
                "failure_reason": "target_not_present_pre_vista",
            }
            for case_id, case in case_context.items()
            if case["provider_group_id"] == group_id
            for arm_id in ARM_ORDER
        ]
        dependency_by_group[group_id] = dependency
        material_by_group[group_id] = (
            dependency,
            missing_rows,
            [],
            {"raw_envelopes": list(envelopes.values())},
        )

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
    def parse_provider_inputs(**inputs):
        if (
            inputs.get("provider_manifest_bytes") != b"offline-manifest"
            or inputs.get("provider_corpus_bytes") != b"offline-corpus"
        ):
            raise ValueError("trusted provider bytes differ")
        return (
            {},
            {"cases": [deepcopy(item) for item in provider_cases.values()]},
            manifest_ref,
            corpus_ref,
        )

    monkeypatch.setattr(predictions, "_parse_provider_inputs", parse_provider_inputs)

    def provider_case_index(_corpus, *, partition="regression"):
        assert partition == "regression"
        return provider_cases, case_context, digest

    monkeypatch.setattr(
        predictions,
        "_provider_case_index",
        provider_case_index,
    )
    monkeypatch.setattr(
        predictions,
        "_screen_group_material",
        lambda **kwargs: deepcopy(material_by_group[str(kwargs["screen"]["screen_group"])]),
    )
    monkeypatch.setattr(
        "app.learn.hybrid.contracts.validate_omni_inventory", lambda value: value
    )
    monkeypatch.setattr(
        "app.learn.hybrid.contracts.validate_qwen_bindings",
        lambda value, _inventory, **_kwargs: value,
    )
    monkeypatch.setattr(
        "app.learn.hybrid.contracts.validate_fusion_result",
        lambda value, _inventory, _bindings, **_kwargs: value,
    )
    public_attempt_ref = lifecycle._s13_public_attempt_ref(graph["attempt"])
    projection = seal_pathless_projection(
        contract_version="benchmark_v2_actual_body_verified_projection_v1",
        semantic_payload={
            "attempt_ref": public_attempt_ref,
            "body_contract_version": "benchmark_v2_runner_actual_body_v1",
            "raw_file_sha256": hashlib.sha256(body_bytes).hexdigest(),
            "body_content_sha256": str(body["content_sha256"]),
            "screen_group_count": 12,
            "case_arm_multiset_sha256": digest,
            "pre_vista_evidence_refs": [
                deepcopy(dependency_by_group[group]["pre_vista_evidence_ref"])
                for group in sorted(dependency_by_group)
            ],
            "verified": True,
            "safety": deepcopy(predictions.SAFETY),
        },
    )
    return {
        "actual_body_bytes": body_bytes,
        "provider_manifest_bytes": b"offline-manifest",
        "provider_corpus_bytes": b"offline-corpus",
        "actual_body_verified_projection": projection,
        "lifecycle_bundle_v3": bundle,
    }, body, graph


def test_prediction_run_v3_materializer_succeeds_deterministically_offline(monkeypatch) -> None:
    kwargs, _, _ = _offline_c3_inputs(monkeypatch)
    first = materialize_prediction_run_v3(**kwargs)
    second = materialize_prediction_run_v3(**kwargs)
    assert first == second
    assert first.automatic_prediction["contract_version"] == "automatic_prediction_v3"
    assert first.prediction_run["contract_version"] == "benchmark_v2_prediction_run_v3"
    assert first.prediction_run_envelope["ref"] == {
        "id": first.prediction_run["artifact_id"],
        "content_sha256": first.prediction_run["content_sha256"],
    }


def test_prediction_run_v3_rejects_resealed_body_not_bound_to_lifecycle(monkeypatch) -> None:
    kwargs, body, _ = _offline_c3_inputs(monkeypatch)
    changed = deepcopy(body)
    changed_screen = changed["screen_group_results"][0]
    changed_screen["request_ref"] = {
        "id": "request/resealed-body",
        "content_sha256": "e" * 64,
    }
    changed_screen["content_sha256"] = content_sha256(changed_screen)
    changed["content_sha256"] = content_sha256(changed)
    changed_bytes = (
        json.dumps(
            changed, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        + b"\n"
    )
    from app.learn.hybrid import benchmark_v2_lifecycle as lifecycle
    from app.learn.hybrid import benchmark_v2_predictions as predictions
    from app.learn.hybrid.benchmark_v2_pathless import seal_pathless_projection

    prior_projection = kwargs["actual_body_verified_projection"]
    changed_projection = seal_pathless_projection(
        contract_version="benchmark_v2_actual_body_verified_projection_v1",
        semantic_payload={
            "attempt_ref": deepcopy(prior_projection["attempt_ref"]),
            "body_contract_version": "benchmark_v2_runner_actual_body_v1",
            "raw_file_sha256": hashlib.sha256(changed_bytes).hexdigest(),
            "body_content_sha256": str(changed["content_sha256"]),
            "screen_group_count": 12,
            "case_arm_multiset_sha256": str(
                prior_projection["case_arm_multiset_sha256"]
            ),
            "pre_vista_evidence_refs": deepcopy(
                prior_projection["pre_vista_evidence_refs"]
            ),
            "verified": True,
            "safety": deepcopy(predictions.SAFETY),
        },
    )
    del lifecycle
    with pytest.raises(ValueError, match="body_file_ref|body file|lifecycle.*body"):
        materialize_prediction_run_v3(
            **{
                **kwargs,
                "actual_body_bytes": changed_bytes,
                "actual_body_verified_projection": changed_projection,
            }
        )


def test_c4_accepted_regression_materializer_api_is_available() -> None:
    from app.learn.hybrid.benchmark_v2_predictions import (
        materialize_benchmark_v2_accepted_regression_score_input_v2,
        project_benchmark_v2_actual_body,
        project_benchmark_v2_actual_result,
        validate_benchmark_v2_accepted_regression_score_input_v2,
    )

    assert callable(project_benchmark_v2_actual_body)
    assert callable(project_benchmark_v2_actual_result)
    assert callable(validate_benchmark_v2_accepted_regression_score_input_v2)
    assert callable(materialize_benchmark_v2_accepted_regression_score_input_v2)


def _offline_actual_result_projection(kwargs, graph):
    from app.learn.hybrid.benchmark_v2_pathless import (
        pathless_artifact_ref,
        seal_pathless_projection,
    )
    from app.learn.hybrid.benchmark_v2_predictions import SAFETY

    prefix = graph["prefix"]
    result_event = next(
        item for item in graph["events"] if item["event_kind"] == "result"
    )
    return seal_pathless_projection(
        contract_version="benchmark_v2_actual_result_verified_projection_v1",
        semantic_payload={
            "attempt_ref": deepcopy(prefix["attempt_ref"]),
            "result_contract_version": "benchmark_v2_runner_actual_result_v2",
            "raw_file_sha256": prefix["result_file_ref"]["file_sha256"],
            "result_content_sha256": prefix["result_file_ref"]["content_sha256"],
            "body_projection_ref": pathless_artifact_ref(
                kwargs["actual_body_verified_projection"]
            ),
            "cleanup_projection_ref": pathless_artifact_ref(
                graph["cleanup_projection"]
            ),
            "attempt_ledger_pre_result_ref": deepcopy(
                prefix["attempt_ledger_pre_result_ref"]
            ),
            "runner_ledger_prefix_projection_ref": pathless_artifact_ref(prefix),
            "result_event_projection_ref": pathless_artifact_ref(result_event),
            "verified": True,
            "safety": deepcopy(SAFETY),
        },
    )


def test_c4_accepted_regression_materializes_deterministically_offline(monkeypatch) -> None:
    from app.learn.hybrid.benchmark_v2_predictions import (
        materialize_benchmark_v2_accepted_regression_score_input_v2,
        validate_benchmark_v2_accepted_regression_score_input_v2,
    )

    kwargs, _, graph = _offline_c3_inputs(monkeypatch)
    accepted_kwargs = {
        "actual_body_bytes": kwargs["actual_body_bytes"],
        "actual_result_bytes": graph["result_bytes"],
        "cleanup_receipt_bytes": graph["cleanup_bytes"],
        "expected_attempt_dir": graph["attempt_dir"],
        "provider_manifest_bytes": kwargs["provider_manifest_bytes"],
        "provider_corpus_bytes": kwargs["provider_corpus_bytes"],
        "runner_ledger_prefix_projection": graph["prefix"],
        "attempt_journal_projection": graph["journal_projection"],
        "actual_body_projection": kwargs["actual_body_verified_projection"],
        "actual_result_projection": _offline_actual_result_projection(kwargs, graph),
        "lifecycle_bundle_v3": kwargs["lifecycle_bundle_v3"],
    }
    first = materialize_benchmark_v2_accepted_regression_score_input_v2(
        **accepted_kwargs
    )
    second = materialize_benchmark_v2_accepted_regression_score_input_v2(
        **accepted_kwargs
    )
    assert first == second
    assert (
        validate_benchmark_v2_accepted_regression_score_input_v2(
            first,
            actual_body_bytes=kwargs["actual_body_bytes"],
            actual_result_bytes=graph["result_bytes"],
            cleanup_receipt_bytes=graph["cleanup_bytes"],
            expected_attempt_dir=graph["attempt_dir"],
            provider_manifest_bytes=kwargs["provider_manifest_bytes"],
            provider_corpus_bytes=kwargs["provider_corpus_bytes"],
        )
        == first
    )
    assert set(first) == {
        "contract_version", "content_sha256", "benchmark_release_id", "partition",
        "corpus_parent_ref", "provider_manifest_ref", "provider_corpus_ref",
        "selection_policy", "attempt_ref", "attempt_ledger_ref",
        "automatic_prediction_ref", "selected_lifecycle_ref",
        "verified_parent_projections", "prediction_run_envelope",
        "lifecycle_bundle_envelope", "safety",
    }
    serialized = json.dumps(first, ensure_ascii=False, sort_keys=True)
    assert "C:\\private" not in serialized
    assert '"path"' not in serialized

    legacy = deepcopy(first)
    legacy["contract_version"] = "benchmark_v2_accepted_regression_score_input_v1"
    with pytest.raises(ValueError, match="accepted regression score input contract"):
        validate_benchmark_v2_accepted_regression_score_input_v2(
            legacy,
            actual_body_bytes=kwargs["actual_body_bytes"],
            actual_result_bytes=graph["result_bytes"],
            cleanup_receipt_bytes=graph["cleanup_bytes"],
            expected_attempt_dir=graph["attempt_dir"],
            provider_manifest_bytes=kwargs["provider_manifest_bytes"],
            provider_corpus_bytes=kwargs["provider_corpus_bytes"],
        )
    wrong_hash = deepcopy(first)
    wrong_hash["content_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="accepted regression score input contract"):
        validate_benchmark_v2_accepted_regression_score_input_v2(
            wrong_hash,
            actual_body_bytes=kwargs["actual_body_bytes"],
            actual_result_bytes=graph["result_bytes"],
            cleanup_receipt_bytes=graph["cleanup_bytes"],
            expected_attempt_dir=graph["attempt_dir"],
            provider_manifest_bytes=kwargs["provider_manifest_bytes"],
            provider_corpus_bytes=kwargs["provider_corpus_bytes"],
        )
    leaked = deepcopy(first)
    leaked["path"] = "C:\\private\\body.json"
    with pytest.raises(ValueError, match="accepted regression score input contract"):
        validate_benchmark_v2_accepted_regression_score_input_v2(
            leaked,
            actual_body_bytes=kwargs["actual_body_bytes"],
            actual_result_bytes=graph["result_bytes"],
            cleanup_receipt_bytes=graph["cleanup_bytes"],
            expected_attempt_dir=graph["attempt_dir"],
            provider_manifest_bytes=kwargs["provider_manifest_bytes"],
            provider_corpus_bytes=kwargs["provider_corpus_bytes"],
        )

    from app.learn.hybrid import benchmark_v2_lifecycle as lifecycle
    from app.learn.hybrid.benchmark_v2_pathless import seal_pathless_envelope
    from tests.test_portfolio_hybrid_v1_1_benchmark_v2_lifecycle import (
        _s13_complete_attempt_artifacts,
        _s13_project_multi_attempt_events,
    )

    alternate_ledger = []
    alternate = _s13_complete_attempt_artifacts(
        alternate_ledger, attempt_id="attempt-regression-shared-drift"
    )
    alternate_events = _s13_project_multi_attempt_events(
        ledger=alternate_ledger, complete=[alternate]
    )
    alternate_materialized = lifecycle.materialize_benchmark_v2_attempt_ledger_projections(
        benchmark_release_id="portfolio_hybrid_v1_1_benchmark_v2_release_1",
        partition="regression",
        runner_ledger_events=alternate_ledger,
        runner_event_projections=alternate_events,
        attempt_lifecycle_projections=[alternate["attempt_lifecycle"]],
    )
    alternate_bundle = lifecycle.compose_benchmark_v2_lifecycle_bundle_v3(
        benchmark_release_id="portfolio_hybrid_v1_1_benchmark_v2_release_1",
        partition="regression",
        attempt_ref=alternate["attempt"],
        raw_ledger_prefix_projection=alternate_materialized.runner_ledger_prefix_projection,
        projected_attempt_ledger=alternate_materialized.projected_attempt_ledger,
        selected_attempt_lifecycle_projection=alternate["attempt_lifecycle"],
        cleanup_lifecycle_projection=alternate["cleanup_projection"],
        journal_terminal_event_projection=alternate["terminal"],
        attempt_journal_projection=alternate["journal_projection"],
        screen_group_lifecycle_projections=alternate["screens"],
        runner_event_projections=alternate_events,
        cleanup_receipt=alternate["cleanup"],
    )
    drifted = deepcopy(first)
    drifted["lifecycle_bundle_envelope"] = seal_pathless_envelope(alternate_bundle)
    drifted["content_sha256"] = hashlib.sha256(
        json.dumps(
            {key: value for key, value in drifted.items() if key != "content_sha256"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    with pytest.raises(ValueError, match="shared closure differs"):
        validate_benchmark_v2_accepted_regression_score_input_v2(
            drifted,
            actual_body_bytes=kwargs["actual_body_bytes"],
            actual_result_bytes=graph["result_bytes"],
            cleanup_receipt_bytes=graph["cleanup_bytes"],
            expected_attempt_dir=graph["attempt_dir"],
            provider_manifest_bytes=kwargs["provider_manifest_bytes"],
            provider_corpus_bytes=kwargs["provider_corpus_bytes"],
        )


def test_c4_persisted_accepted_revalidates_authoritative_prediction_graph(
    monkeypatch,
) -> None:
    from app.learn.hybrid import benchmark_v2_predictions as predictions
    from app.learn.hybrid.benchmark_v2_pathless import (
        order_pathless_envelopes,
        pathless_artifact_ref,
        seal_pathless_envelope,
        seal_pathless_projection,
    )

    kwargs, _, graph = _offline_c3_inputs(monkeypatch)
    accepted = predictions.materialize_benchmark_v2_accepted_regression_score_input_v2(
        actual_body_bytes=kwargs["actual_body_bytes"],
        actual_result_bytes=graph["result_bytes"],
        cleanup_receipt_bytes=graph["cleanup_bytes"],
        expected_attempt_dir=graph["attempt_dir"],
        provider_manifest_bytes=kwargs["provider_manifest_bytes"],
        provider_corpus_bytes=kwargs["provider_corpus_bytes"],
        runner_ledger_prefix_projection=graph["prefix"],
        attempt_journal_projection=graph["journal_projection"],
        actual_body_projection=kwargs["actual_body_verified_projection"],
        actual_result_projection=_offline_actual_result_projection(kwargs, graph),
        lifecycle_bundle_v3=kwargs["lifecycle_bundle_v3"],
    )

    run_envelope = deepcopy(accepted["prediction_run_envelope"])
    run = json.loads(
        base64.b64decode(run_envelope["canonical_bytes_b64"], validate=True)
    )
    children = deepcopy(run["sealed_artifact_envelopes"])
    automatic_index = next(
        index
        for index, envelope in enumerate(children)
        if json.loads(
            base64.b64decode(envelope["canonical_bytes_b64"], validate=True)
        ).get("contract_version")
        == "automatic_prediction_v3"
    )
    automatic = json.loads(
        base64.b64decode(
            children[automatic_index]["canonical_bytes_b64"], validate=True
        )
    )
    changed_rows = deepcopy(automatic["rows"])
    replaced_case = changed_rows[0]["case_id"]
    for row in changed_rows:
        if row["case_id"] == replaced_case:
            row["case_id"] = "fabricated-missing-case"
    arm_rank = {
        arm: index
        for index, arm in enumerate(
            ("qwen_only", "omni_only_discovery", "omni_to_qwen", "omni_to_qwen_vista")
        )
    }
    changed_rows.sort(key=lambda row: (row["case_id"], arm_rank[row["arm_id"]]))
    changed_automatic = predictions._seal_automatic_prediction_v3(
        benchmark_release_id=automatic["benchmark_release_id"],
        partition=automatic["partition"],
        source_parent_ref=automatic["source_parent_ref"],
        case_arm_multiset_sha256=automatic["case_arm_multiset_sha256"],
        provider_group_dependencies=automatic["provider_group_dependencies"],
        rows=changed_rows,
    )
    children[automatic_index] = seal_pathless_envelope(changed_automatic)
    children = order_pathless_envelopes(
        registry_name="prediction_run_v3", envelopes=children, context={}
    )
    changed_run_semantic = {
        key: deepcopy(value)
        for key, value in run.items()
        if key not in {"contract_version", "artifact_id", "content_sha256"}
    }
    changed_run_semantic["automatic_prediction_ref"] = pathless_artifact_ref(
        changed_automatic
    )
    changed_run_semantic["sealed_artifact_envelopes"] = children
    changed_run = seal_pathless_projection(
        contract_version="benchmark_v2_prediction_run_v3",
        semantic_payload=changed_run_semantic,
    )
    changed = deepcopy(accepted)
    changed["automatic_prediction_ref"] = pathless_artifact_ref(changed_automatic)
    changed["prediction_run_envelope"] = seal_pathless_envelope(changed_run)
    changed["content_sha256"] = hashlib.sha256(
        json.dumps(
            {key: value for key, value in changed.items() if key != "content_sha256"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    with pytest.raises(ValueError, match="authoritative|case|multiset|prediction"):
        predictions.validate_benchmark_v2_accepted_regression_score_input_v2(
            changed,
            actual_body_bytes=kwargs["actual_body_bytes"],
            actual_result_bytes=graph["result_bytes"],
            cleanup_receipt_bytes=graph["cleanup_bytes"],
            expected_attempt_dir=graph["attempt_dir"],
            provider_manifest_bytes=kwargs["provider_manifest_bytes"],
            provider_corpus_bytes=kwargs["provider_corpus_bytes"],
        )

    with pytest.raises(ValueError, match="provider|trusted"):
        predictions.validate_benchmark_v2_accepted_regression_score_input_v2(
            accepted,
            actual_body_bytes=kwargs["actual_body_bytes"],
            actual_result_bytes=graph["result_bytes"],
            cleanup_receipt_bytes=graph["cleanup_bytes"],
            expected_attempt_dir=graph["attempt_dir"],
            provider_manifest_bytes=b"drifted-manifest",
            provider_corpus_bytes=kwargs["provider_corpus_bytes"],
        )


def test_c4_persisted_accepted_rejects_coherently_reminted_result_graph(
    monkeypatch,
) -> None:
    from app.learn.hybrid import benchmark_v2_lifecycle as lifecycle
    from app.learn.hybrid import benchmark_v2_predictions as predictions
    from app.learn.hybrid.benchmark_v2_contracts import BENCHMARK_RELEASE_ID

    kwargs, _, original = _offline_c3_inputs(monkeypatch)
    changed_cleanup = deepcopy(original["cleanup"])
    changed_cleanup.pop("content_sha256")
    changed_cleanup["reason"] = "coherently reminted cleanup"
    changed_cleanup = seal_immutable(changed_cleanup)
    reminted = _offline_fixed_raw_graph(
        original, cleanup_receipt=changed_cleanup
    )
    projected = lifecycle.project_benchmark_v2_attempt_ledger(
        benchmark_release_id=BENCHMARK_RELEASE_ID,
        partition="regression",
        runner_ledger_events=reminted["ledger"],
        runner_event_projections=reminted["events"],
        raw_ledger_prefix_projection=reminted["prefix"],
        attempt_lifecycle_projections=[reminted["attempt_lifecycle"]],
    )
    reminted_bundle = lifecycle.compose_benchmark_v2_lifecycle_bundle_v3(
        benchmark_release_id=BENCHMARK_RELEASE_ID,
        partition="regression",
        attempt_ref=reminted["attempt"],
        raw_ledger_prefix_projection=reminted["prefix"],
        projected_attempt_ledger=projected,
        selected_attempt_lifecycle_projection=reminted["attempt_lifecycle"],
        cleanup_lifecycle_projection=reminted["cleanup_projection"],
        journal_terminal_event_projection=reminted["terminal"],
        attempt_journal_projection=reminted["journal_projection"],
        screen_group_lifecycle_projections=reminted["screens"],
        runner_event_projections=reminted["events"],
        cleanup_receipt=reminted["cleanup"],
    )
    reminted_result_projection = predictions.project_benchmark_v2_actual_result(
        actual_result_bytes=reminted["result_bytes"],
        cleanup_receipt_bytes=reminted["cleanup_bytes"],
        expected_attempt_dir=reminted["attempt_dir"],
        actual_body_projection=kwargs["actual_body_verified_projection"],
        cleanup_projection=reminted["cleanup_projection"],
        runner_ledger_prefix_projection=reminted["prefix"],
        result_event_projection=next(
            item for item in reminted["events"] if item["event_kind"] == "result"
        ),
    )
    accepted = predictions.materialize_benchmark_v2_accepted_regression_score_input_v2(
        actual_body_bytes=kwargs["actual_body_bytes"],
        actual_result_bytes=reminted["result_bytes"],
        cleanup_receipt_bytes=reminted["cleanup_bytes"],
        expected_attempt_dir=reminted["attempt_dir"],
        provider_manifest_bytes=kwargs["provider_manifest_bytes"],
        provider_corpus_bytes=kwargs["provider_corpus_bytes"],
        runner_ledger_prefix_projection=reminted["prefix"],
        attempt_journal_projection=reminted["journal_projection"],
        actual_body_projection=kwargs["actual_body_verified_projection"],
        actual_result_projection=reminted_result_projection,
        lifecycle_bundle_v3=reminted_bundle,
    )
    with pytest.raises(ValueError, match="result|cleanup|trusted|projection"):
        predictions.validate_benchmark_v2_accepted_regression_score_input_v2(
            accepted,
            actual_body_bytes=kwargs["actual_body_bytes"],
            actual_result_bytes=original["result_bytes"],
            cleanup_receipt_bytes=original["cleanup_bytes"],
            expected_attempt_dir=original["attempt_dir"],
            provider_manifest_bytes=kwargs["provider_manifest_bytes"],
            provider_corpus_bytes=kwargs["provider_corpus_bytes"],
        )


def test_c4_actual_result_projection_closes_raw_body_prefix_and_event(tmp_path, monkeypatch) -> None:
    from app.learn.hybrid.benchmark_v2_pathless import (
        pathless_artifact_ref,
        seal_pathless_projection,
    )
    from app.learn.hybrid.benchmark_v2_predictions import (
        project_benchmark_v2_actual_result,
    )

    kwargs, _, graph = _offline_c3_inputs(monkeypatch)
    body_projection = kwargs["actual_body_verified_projection"]
    attempt_dir = (tmp_path / str(graph["attempt"]["attempt_id"])).resolve()
    cleanup_receipt_bytes = (
        json.dumps(
            graph["cleanup"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    public_pre_result = deepcopy(graph["prefix"]["attempt_ledger_pre_result_ref"])
    native_pre_result = deepcopy(public_pre_result)
    native_pre_result["attempt_ref"] = deepcopy(graph["attempt"])
    result = seal_immutable(
        {
            "contract_version": "benchmark_v2_runner_actual_result_v2",
            "attempt_ref": deepcopy(graph["attempt"]),
            "attempt_dir": str(attempt_dir),
            "body_ref": {
                "path": str((attempt_dir / "body.json").resolve()),
                "file_sha256": body_projection["raw_file_sha256"],
                "content_sha256": body_projection["body_content_sha256"],
            },
            "cleanup_receipt_ref": {
                "path": str((attempt_dir / "cleanup.json").resolve()),
                "file_sha256": hashlib.sha256(cleanup_receipt_bytes).hexdigest(),
                "content_sha256": graph["cleanup"]["content_sha256"],
            },
            "attempt_ledger_pre_result_ref": native_pre_result,
            "screen_group_count": 12,
            "status": "terminal",
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    result_bytes = (
        json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        + b"\n"
    )
    result_file_ref = {
        "file_sha256": hashlib.sha256(result_bytes).hexdigest(),
        "content_sha256": result["content_sha256"],
    }
    result_event = seal_pathless_projection(
        contract_version="benchmark_v2_runner_event_verified_projection_v1",
        semantic_payload={
            key: deepcopy(value)
            for key, value in next(
                item for item in graph["events"] if item["event_kind"] == "result"
            ).items()
            if key not in {"contract_version", "artifact_id", "content_sha256", "load_bearing_refs"}
        }
        | {
            "load_bearing_refs": {
                "result_file_ref": result_file_ref,
                "attempt_ledger_pre_result_ref": public_pre_result,
            }
        },
    )
    prefix_semantic = {
        key: deepcopy(value)
        for key, value in graph["prefix"].items()
        if key not in {"contract_version", "artifact_id", "content_sha256"}
    }
    prefix_semantic["result_file_ref"] = result_file_ref
    prefix_semantic["result_event_projection_ref"] = pathless_artifact_ref(result_event)
    prefix = seal_pathless_projection(
        contract_version="benchmark_v2_runner_ledger_prefix_verified_projection_v1",
        semantic_payload=prefix_semantic,
    )
    projected = project_benchmark_v2_actual_result(
        actual_result_bytes=result_bytes,
        cleanup_receipt_bytes=cleanup_receipt_bytes,
        expected_attempt_dir=attempt_dir,
        actual_body_projection=body_projection,
        cleanup_projection=graph["cleanup_projection"],
        runner_ledger_prefix_projection=prefix,
        result_event_projection=result_event,
    )
    assert projected["result_event_projection_ref"] == pathless_artifact_ref(result_event)
    assert projected["runner_ledger_prefix_projection_ref"] == pathless_artifact_ref(prefix)

    changed = bytearray(result_bytes)
    changed[-2] = ord(" ")
    with pytest.raises(ValueError, match="canonical|lineage|UTF-8"):
        project_benchmark_v2_actual_result(
            actual_result_bytes=bytes(changed),
            cleanup_receipt_bytes=cleanup_receipt_bytes,
            expected_attempt_dir=attempt_dir,
            actual_body_projection=body_projection,
            cleanup_projection=graph["cleanup_projection"],
            runner_ledger_prefix_projection=prefix,
            result_event_projection=result_event,
        )
    swapped_event = deepcopy(result_event)
    swapped_event["load_bearing_refs"]["attempt_ledger_pre_result_ref"]["prefix_sha256"] = "f" * 64
    swapped_event = seal_pathless_projection(
        contract_version="benchmark_v2_runner_event_verified_projection_v1",
        semantic_payload={
            key: deepcopy(value)
            for key, value in swapped_event.items()
            if key not in {"contract_version", "artifact_id", "content_sha256"}
        },
    )
    with pytest.raises(ValueError, match="verified parent lineage"):
        project_benchmark_v2_actual_result(
            actual_result_bytes=result_bytes,
            cleanup_receipt_bytes=cleanup_receipt_bytes,
            expected_attempt_dir=attempt_dir,
            actual_body_projection=body_projection,
            cleanup_projection=graph["cleanup_projection"],
            runner_ledger_prefix_projection=prefix,
            result_event_projection=swapped_event,
        )

    changed_cleanup = deepcopy(graph["cleanup"])
    changed_cleanup.pop("content_sha256")
    changed_cleanup["reason"] = "resealed foreign cleanup"
    changed_cleanup = seal_immutable(changed_cleanup)
    changed_cleanup_bytes = (
        json.dumps(
            changed_cleanup,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    changed_result = deepcopy(result)
    changed_result.pop("content_sha256")
    changed_result["cleanup_receipt_ref"] = {
        "path": str((attempt_dir / "cleanup.json").resolve()),
        "file_sha256": hashlib.sha256(changed_cleanup_bytes).hexdigest(),
        "content_sha256": changed_cleanup["content_sha256"],
    }
    changed_result = seal_immutable(changed_result)
    changed_result_bytes = (
        json.dumps(
            changed_result,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    changed_result_file_ref = {
        "file_sha256": hashlib.sha256(changed_result_bytes).hexdigest(),
        "content_sha256": changed_result["content_sha256"],
    }
    changed_result_event = seal_pathless_projection(
        contract_version="benchmark_v2_runner_event_verified_projection_v1",
        semantic_payload={
            key: deepcopy(value)
            for key, value in result_event.items()
            if key
            not in {
                "contract_version",
                "artifact_id",
                "content_sha256",
                "load_bearing_refs",
            }
        }
        | {
            "load_bearing_refs": {
                "result_file_ref": changed_result_file_ref,
                "attempt_ledger_pre_result_ref": public_pre_result,
            }
        },
    )
    changed_prefix_semantic = {
        key: deepcopy(value)
        for key, value in prefix.items()
        if key not in {"contract_version", "artifact_id", "content_sha256"}
    }
    changed_prefix_semantic["result_file_ref"] = changed_result_file_ref
    changed_prefix_semantic["result_event_projection_ref"] = pathless_artifact_ref(
        changed_result_event
    )
    changed_prefix = seal_pathless_projection(
        contract_version="benchmark_v2_runner_ledger_prefix_verified_projection_v1",
        semantic_payload=changed_prefix_semantic,
    )
    with pytest.raises(ValueError, match="cleanup"):
        project_benchmark_v2_actual_result(
            actual_result_bytes=changed_result_bytes,
            cleanup_receipt_bytes=changed_cleanup_bytes,
            expected_attempt_dir=attempt_dir,
            actual_body_projection=body_projection,
            cleanup_projection=graph["cleanup_projection"],
            runner_ledger_prefix_projection=changed_prefix,
            result_event_projection=changed_result_event,
        )


def _identity(identity: str, digest: str = SHA_A) -> dict[str, object]:
    return {"id": identity, "content_sha256": digest}


def _sealed_parent(kind: str, digest: str = SHA_A) -> dict[str, object]:
    value: dict[str, object] = {"kind": kind, "parent_sha256": digest}
    value["content_sha256"] = content_sha256(value)
    return value


def _provider_group() -> dict[str, object]:
    _, capture_bundle, _, _, _ = _authoritative_inputs()
    return incumbent.compose_benchmark_v2_hybrid_screen_group_start(
        attempt_ref=_sealed_parent("attempt"),
        partition="regression",
        screen_group="screen-group-1",
        provider_corpus_ref=_sealed_parent("provider-corpus"),
        case_refs=[
            {"case_id": f"case-{index}", "case_content_sha256": SHA_A}
            for index in range(5)
        ],
        hybrid_capture_bundle_ref=_identity("capture-bundle"),
        request_ref=_identity("request-1"),
        registration_ref=_identity("registration-1"),
        manifest_ref=_identity("manifest-1"),
        capture_image_path="artifacts/benchmark/screen-group-1.png",
        hybrid_config={"mode": "hybrid_v1_1"},
        capture_bundle=capture_bundle,
    )


def _window_binding() -> dict[str, object]:
    return incumbent.compose_benchmark_v2_workflow_window_binding(
        run_id="run-actual-1",
        operation_id="operation-actual-1",
        window_binding_ref=_identity("window-1"),
        capture_ref=_identity("capture-1", SHA_B),
        owner_journal_ref=_sealed_parent("owner-journal"),
        expected_uia_root_ref=_sealed_parent("uia-root"),
    )


def _operation_ref(
    *,
    mode: str,
    operation_id: str,
    request_ref: Mapping[str, object],
    window_binding: Mapping[str, object],
    worker_ref: Mapping[str, object],
    status: str,
    revision: int,
    predecessor: Mapping[str, object] | None,
    run_id: str | None = None,
    predecessor_content_sha256: str | None = None,
    workflow_content_sha256: str | None = None,
) -> dict[str, object]:
    operation_run_id = run_id or str(window_binding["run_id"])
    return incumbent.compose_benchmark_v2_workflow_service_operation_ref(
        mode=mode,
        run_id=operation_run_id,
        stage=str(window_binding["stage"]),
        operation_id=operation_id,
        workflow_state_ref={
            "run_id": operation_run_id,
            "revision": revision,
            "content_sha256": workflow_content_sha256
            or f"{revision % 10}" * 64,
        },
        stage_execution_ref={
            "run_id": operation_run_id,
            "stage": str(window_binding["stage"]),
            "operation_id": operation_id,
            "revision": revision,
            "content_sha256": f"{(revision + 5) % 10}" * 64,
        },
        request_ref=request_ref,
        window_binding_ref=window_binding["window_binding_ref"],
        capture_ref=window_binding["capture_ref"],
        worker_ref=worker_ref,
        status=status,
        predecessor_operation_ref=predecessor,
        predecessor_content_sha256=predecessor_content_sha256,
    )


def _projection(
    *,
    mode: str,
    operation_ref: Mapping[str, object],
    response: Mapping[str, object],
    terminal: bool,
) -> dict[str, object]:
    suffix = str(operation_ref["operation_id"])
    parents = {
        "terminal_receipt": _sealed_parent(f"terminal-{suffix}"),
        "window_adoption_ref": _sealed_parent(f"window-adoption-{suffix}"),
        "worker_cleanup_ref": _sealed_parent(f"worker-cleanup-{suffix}"),
        "provider_cleanup_ref": _sealed_parent(f"provider-cleanup-{suffix}"),
    }
    if not terminal:
        parents = {name: None for name in parents}
    return incumbent.compose_benchmark_v2_adopted_result_projection(
        mode=mode,
        run_id=str(operation_ref["run_id"]),
        stage=str(operation_ref["stage"]),
        operation_id=str(operation_ref["operation_id"]),
        worker_ref=operation_ref["worker_ref"],
        model_request_ref=_identity(f"model-{suffix}"),
        payload_ref={"content_sha256": SHA_A},
        result_ref={"content_sha256": SHA_B},
        adoption_ref=_sealed_parent(f"adoption-{suffix}"),
        response=response,
        **parents,
    )


def _step(
    operation_ref: Mapping[str, object],
    *,
    task_kind: str,
    projection: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return incumbent.compose_benchmark_v2_workflow_service_step(
        operation_ref=operation_ref,
        observed_task_kind=task_kind,
        adopted_result_projection=projection,
        terminal_receipt=(projection or {}).get("terminal_receipt"),
        cleanup_refs={
            "worker_cleanup_ref": (projection or {}).get("worker_cleanup_ref"),
            "provider_cleanup_ref": (projection or {}).get("provider_cleanup_ref"),
        },
    )


def test_incumbent_child_identity_keeps_parent_window_capture_and_case_authority() -> None:
    binding = _window_binding()
    request_ref = _identity("case-child")
    child = _operation_ref(
        mode="incumbent_qwen_only",
        operation_id="incumbent-child-operation",
        request_ref=request_ref,
        window_binding=binding,
        worker_ref=_sealed_parent("incumbent-child-worker"),
        status="pending",
        revision=1,
        predecessor=None,
        run_id="incumbent-child-run",
    )
    step = _step(child, task_kind="vision_observe_screen")

    assert actual._validated_service_step(
        step,
        expected_mode="incumbent_qwen_only",
        binding=binding,
        request_ref=request_ref,
        expected_run_id=None,
        expected_operation_id=None,
        predecessor_step=None,
    ) == step


@pytest.mark.parametrize("fault", ("window", "capture", "request", "child_switch"))
def test_incumbent_child_lineage_drift_is_rejected(fault: str) -> None:
    binding = _window_binding()
    request_ref = _identity("case-child")
    child = _operation_ref(
        mode="incumbent_qwen_only",
        operation_id="incumbent-child-operation",
        request_ref=request_ref,
        window_binding=binding,
        worker_ref=_sealed_parent("incumbent-child-worker"),
        status="pending",
        revision=1,
        predecessor=None,
        run_id="incumbent-child-run",
    )
    predecessor = _step(child, task_kind="vision_observe_screen")
    changed_binding = deepcopy(binding)
    changed_request = request_ref
    next_run_id = str(child["run_id"])
    next_operation_id = str(child["operation_id"])
    if fault == "window":
        changed_binding["window_binding_ref"] = _identity("other-window")
    elif fault == "capture":
        changed_binding["capture_ref"] = _identity("other-capture")
    elif fault == "request":
        changed_request = _identity("other-case")
    else:
        next_run_id = "different-child-run"
        next_operation_id = "different-child-operation"
    successor = _operation_ref(
        mode="incumbent_qwen_only",
        operation_id=next_operation_id,
        request_ref=changed_request,
        window_binding=changed_binding,
        worker_ref=child["worker_ref"],
        status="advanced",
        revision=2,
        predecessor=child,
        run_id=next_run_id,
    )

    with pytest.raises(ValueError, match="window|capture|request|identity|stale"):
        actual._validated_service_step(
            _step(successor, task_kind="vision_observe_screen"),
            expected_mode="incumbent_qwen_only",
            binding=binding,
            request_ref=request_ref,
            expected_run_id=str(child["run_id"]),
            expected_operation_id=str(child["operation_id"]),
            predecessor_step=predecessor,
        )


def _durable_projection_case(
    *, mode: str = "incumbent_qwen_only"
) -> tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
    binding = _window_binding()
    request_ref = _identity(f"{mode}-durable-projection")
    worker_ref = _sealed_parent(f"{mode}-durable-worker")
    current = _operation_ref(
        mode=mode,
        operation_id=(
            str(binding["operation_id"])
            if mode == "hybrid_v1_1"
            else "incumbent-durable-operation"
        ),
        request_ref=request_ref,
        window_binding=binding,
        worker_ref=worker_ref,
        status="advanced",
        revision=7,
        predecessor=None,
        run_id=None if mode == "hybrid_v1_1" else "incumbent-durable-run",
    )
    return binding, request_ref, worker_ref, current


def _validate_durable_projection_step(
    *,
    binding: Mapping[str, object],
    request_ref: Mapping[str, object],
    current: Mapping[str, object],
    successor: Mapping[str, object],
) -> dict[str, object]:
    return actual._validated_service_step(
        _step(successor, task_kind="vision_observe_screen"),
        expected_mode=str(current["mode"]),
        binding=binding,
        request_ref=request_ref,
        expected_run_id=str(current["run_id"]),
        expected_operation_id=str(current["operation_id"]),
        predecessor_step=_step(current, task_kind="vision_observe_screen"),
    )


@pytest.mark.parametrize(("status", "revision"), (("advanced", 8), ("complete", 11)))
def test_incumbent_durable_projection_accepts_monotonic_successor(
    status: str, revision: int
) -> None:
    binding, request_ref, worker_ref, current = _durable_projection_case()
    successor = _operation_ref(
        mode="incumbent_qwen_only",
        operation_id=str(current["operation_id"]),
        request_ref=request_ref,
        window_binding=binding,
        worker_ref=worker_ref,
        status=status,
        revision=revision,
        predecessor=None,
        run_id=str(current["run_id"]),
        predecessor_content_sha256="d" * 64,
    )

    assert _validate_durable_projection_step(
        binding=binding,
        request_ref=request_ref,
        current=current,
        successor=successor,
    )["operation_ref"] == successor


@pytest.mark.parametrize(
    "fault",
    (
        "same_revision",
        "decreasing_revision",
        "unchanged_state_hash",
        "changed_worker",
        "regressive_status",
    ),
)
def test_incumbent_durable_projection_rejects_lineage_fault(fault: str) -> None:
    binding, request_ref, worker_ref, current = _durable_projection_case()
    revision = {"same_revision": 7, "decreasing_revision": 6}.get(fault, 8)
    successor = _operation_ref(
        mode="incumbent_qwen_only",
        operation_id=str(current["operation_id"]),
        request_ref=request_ref,
        window_binding=binding,
        worker_ref=(
            _sealed_parent("different-incumbent-worker")
            if fault == "changed_worker"
            else worker_ref
        ),
        status="pending" if fault == "regressive_status" else "advanced",
        revision=revision,
        predecessor=None,
        run_id=str(current["run_id"]),
        predecessor_content_sha256="d" * 64,
        workflow_content_sha256=(
            str(current["workflow_state_ref"]["content_sha256"])
            if fault == "unchanged_state_hash"
            else None
        ),
    )

    with pytest.raises(ValueError, match="predecessor.*stale"):
        _validate_durable_projection_step(
            binding=binding,
            request_ref=request_ref,
            current=current,
            successor=successor,
        )


@pytest.mark.parametrize("successor_status", ("advanced", "complete"))
def test_incumbent_cleanup_pending_cannot_resume_adoption(
    successor_status: str,
) -> None:
    binding, request_ref, worker_ref, _ = _durable_projection_case()
    current = _operation_ref(
        mode="incumbent_qwen_only",
        operation_id="incumbent-durable-operation",
        request_ref=request_ref,
        window_binding=binding,
        worker_ref=worker_ref,
        status="cleanup_pending",
        revision=8,
        predecessor=None,
        run_id="incumbent-durable-run",
    )
    successor = _operation_ref(
        mode="incumbent_qwen_only",
        operation_id=str(current["operation_id"]),
        request_ref=request_ref,
        window_binding=binding,
        worker_ref=worker_ref,
        status=successor_status,
        revision=9,
        predecessor=None,
        run_id=str(current["run_id"]),
        predecessor_content_sha256="d" * 64,
    )

    with pytest.raises(ValueError, match="predecessor.*stale"):
        _validate_durable_projection_step(
            binding=binding,
            request_ref=request_ref,
            current=current,
            successor=successor,
        )


def test_hybrid_projection_keeps_strict_public_predecessor_chain() -> None:
    binding, request_ref, worker_ref, current = _durable_projection_case(
        mode="hybrid_v1_1"
    )
    successor = _operation_ref(
        mode="hybrid_v1_1",
        operation_id=str(current["operation_id"]),
        request_ref=request_ref,
        window_binding=binding,
        worker_ref=worker_ref,
        status="advanced",
        revision=8,
        predecessor=None,
        predecessor_content_sha256="d" * 64,
    )

    with pytest.raises(ValueError, match="predecessor.*stale"):
        _validate_durable_projection_step(
            binding=binding,
            request_ref=request_ref,
            current=current,
            successor=successor,
        )


class _FakeWorkflowService:
    def __init__(
        self,
        *,
        duplicate_reads: bool = False,
        pending_replays: int = 0,
        never_complete_hybrid: bool = False,
        stale_hybrid: bool = False,
        early_safe_stop: bool = False,
        quality_safe_stop: bool = False,
        successor_fault: str | None = None,
    ) -> None:
        self.pending_replays = max(pending_replays, 1 if duplicate_reads else 0)
        self.never_complete_hybrid = never_complete_hybrid
        self.stale_hybrid = stale_hybrid
        self.early_safe_stop = early_safe_stop
        self.quality_safe_stop = quality_safe_stop
        self.successor_fault = successor_fault
        self.successor_fault_used = False
        self.window_binding: dict[str, object] | None = None
        self.provider_group: dict[str, object] | None = None
        self.hybrid_start_calls = 0
        self.hybrid_continue_calls = 0
        self.hybrid_producer_count = 0
        self.incumbent_start_calls = 0
        self.incumbent_poll_calls = 0
        self.incumbent_adopt_calls = 0
        self.incumbent_poll_transitions: list[
            tuple[dict[str, object], dict[str, object]]
        ] = []
        self.cancel_calls = 0
        self.downstream_incumbent_starts = 0
        self.active_ops: dict[str, dict[str, object]] = {}
        self.active_workers: set[str] = set()
        self._hybrid_index = 0
        self._hybrid_replays: dict[str, int] = {}
        self._incumbent: dict[str, dict[str, Any]] = {}

    def _hybrid_response(self) -> dict[str, object]:
        assert self.provider_group is not None
        fusion, capture_bundle, inventory, bindings, cleanup_receipt = (
            _authoritative_inputs()
        )
        vista_requests = build_vista_requests(
            fusion,
            capture_bundle,
            omni_inventory=inventory,
            qwen_bindings=bindings,
            qwen_cleanup_receipt=cleanup_receipt,
            expected_workflow_revision=int(capture_bundle["workflow_revision"]),
        )
        return {
            "contract_version": "learning_hybrid_managed_stage_result_v1",
            "learning_pipeline_mode": "hybrid_v1_1",
            "task_kind": "panel_learning_hybrid_review_projection",
            "outcome": "completed",
            "result": {
                "contract_version": "hybrid_review_projection_v1",
                "outcome": "completed",
                "review_status": "REVIEW_REQUIRED",
                "automatic_acceptance": False,
                "proposals": [
                    {
                        "candidate_id": request["candidate_id"],
                        "status": "validated",
                    }
                    for request in vista_requests
                ],
                "execute_binding_enabled": False,
                "no_live_click_authorization": True,
            },
            "orchestration": {
                "hybrid_capture_bundle_ref": deepcopy(
                    self.provider_group["hybrid_capture_bundle_ref"]
                ),
                "capture_bundle": deepcopy(capture_bundle),
                "omni_inventory": deepcopy(inventory),
                "qwen_bindings": deepcopy(bindings),
                "fusion_result": deepcopy(fusion),
                "qwen_cleanup_receipt": deepcopy(cleanup_receipt),
                "workflow_revision": capture_bundle["workflow_revision"],
                "hybrid_vista_requests": deepcopy(vista_requests),
                "benchmark_v2_provider_dispatch_receipt_refs": [
                    {"provider": "omni", "content_sha256": "1" * 64},
                    {"provider": "qwen", "content_sha256": "2" * 64},
                    {"provider": "vista", "content_sha256": "3" * 64},
                ],
            },
            "supervisor_lineage": {"kind": "managed"},
            "lifecycle_evidence": {},
        }

    def _quality_safe_stop_response(self) -> dict[str, object]:
        response = self._hybrid_response()
        orchestration = response["orchestration"]
        fusion = deepcopy(orchestration["fusion_result"])
        fusion.pop("content_sha256")
        for candidate in fusion["candidates"]:
            candidate["state"] = "UNBOUND"
            candidate["vista_eligible"] = False
            candidate["review_required"] = True
            candidate["reason"] = "semantic_provider_did_not_bind"
        fusion = seal_immutable(fusion)
        orchestration["fusion_result"] = fusion
        orchestration.pop("hybrid_vista_requests")
        orchestration["benchmark_v2_provider_dispatch_receipt_refs"] = [
            {"provider": "omni", "content_sha256": "1" * 64},
            {"provider": "qwen", "content_sha256": "2" * 64},
        ]
        response["task_kind"] = "panel_learning_hybrid_fusion"
        response["result"] = deepcopy(fusion)
        return response

    def _hybrid_step(self, *, status: str) -> dict[str, object]:
        assert self.window_binding is not None
        assert self.provider_group is not None
        worker_ref = _sealed_parent(f"hybrid-worker-{self._hybrid_index}")
        predecessor = self.active_ops.get("hybrid")
        operation_ref = _operation_ref(
            mode="hybrid_v1_1",
            operation_id=str(self.window_binding["operation_id"]),
            request_ref=self.provider_group["request_ref"],
            window_binding=self.window_binding,
            worker_ref=worker_ref,
            status=status,
            revision=10 + self._hybrid_index,
            predecessor=predecessor,
        )
        projection = None
        if status == "complete":
            projection = _projection(
                mode="hybrid_v1_1",
                operation_ref=operation_ref,
                response=self._hybrid_response(),
                terminal=False,
            )
        step = _step(
            operation_ref,
            task_kind=f"server-managed-hybrid-{self._hybrid_index}",
            projection=projection,
        )
        self.active_ops["hybrid"] = deepcopy(operation_ref)
        self.active_workers.add(str(worker_ref["content_sha256"]))
        return step

    def start_hybrid_operation(self, *, screen_group, window_binding):
        self.hybrid_start_calls += 1
        self.provider_group = deepcopy(dict(screen_group))
        self.window_binding = deepcopy(dict(window_binding))
        self.hybrid_producer_count += 1
        return self._hybrid_step(status="pending")

    def continue_hybrid_operation(self, *, operation_ref):
        self.hybrid_continue_calls += 1
        if dict(operation_ref) != self.active_ops.get("hybrid"):
            raise ValueError("stale hybrid operation ref")
        digest = str(operation_ref["content_sha256"])
        if self.stale_hybrid:
            stale = deepcopy(dict(operation_ref))
            stale["capture_ref"] = _identity("capture-stale")
            stale["content_sha256"] = content_sha256(stale)
            return _step(stale, task_kind="server-managed-stale")
        replay_count = self._hybrid_replays.get(digest, 0)
        if self.never_complete_hybrid or replay_count < self.pending_replays:
            self._hybrid_replays[digest] = replay_count + 1
            return _step(operation_ref, task_kind=f"server-managed-hybrid-{self._hybrid_index}")
        if self.early_safe_stop:
            assert self.window_binding is not None
            assert self.provider_group is not None
            consumed = deepcopy(self.active_ops["hybrid"])
            stopped = _operation_ref(
                mode="hybrid_v1_1",
                operation_id=str(self.window_binding["operation_id"]),
                request_ref=self.provider_group["request_ref"],
                window_binding=self.window_binding,
                worker_ref=consumed["worker_ref"],
                status="safe_stopped",
                revision=int(consumed["workflow_state_ref"]["revision"]) + 1,
                predecessor=consumed,
            )
            self.active_workers.discard(
                str(consumed["worker_ref"]["content_sha256"])
            )
            self.active_ops["hybrid"] = deepcopy(stopped)
            return _step(stopped, task_kind="server-managed-hybrid-safe-stop")
        if self.quality_safe_stop:
            assert self.window_binding is not None
            assert self.provider_group is not None
            consumed = deepcopy(self.active_ops["hybrid"])
            stopped = _operation_ref(
                mode="hybrid_v1_1",
                operation_id=str(self.window_binding["operation_id"]),
                request_ref=self.provider_group["request_ref"],
                window_binding=self.window_binding,
                worker_ref=consumed["worker_ref"],
                status="safe_stopped",
                revision=int(consumed["workflow_state_ref"]["revision"]) + 1,
                predecessor=consumed,
            )
            projection = _projection(
                mode="hybrid_v1_1",
                operation_ref=stopped,
                response=self._quality_safe_stop_response(),
                terminal=False,
            )
            self.active_workers.discard(str(consumed["worker_ref"]["content_sha256"]))
            self.active_ops["hybrid"] = deepcopy(stopped)
            return _step(
                stopped,
                task_kind="panel_learning_hybrid_fusion",
                projection=projection,
            )
        if self.successor_fault is not None and not self.successor_fault_used:
            self.successor_fault_used = True
            if self.successor_fault == "same_digest_changed_step":
                return _step(operation_ref, task_kind="server-managed-mutated-replay")
            assert self.window_binding is not None
            assert self.provider_group is not None
            next_operation_id = str(self.window_binding["operation_id"])
            next_revision = int(operation_ref["workflow_state_ref"]["revision"]) + 1
            if self.successor_fault == "switched_operation_id":
                next_operation_id = "operation-switched"
            elif self.successor_fault == "same_revision":
                next_revision = int(operation_ref["workflow_state_ref"]["revision"])
            elif self.successor_fault == "decreasing_revision":
                next_revision = int(operation_ref["workflow_state_ref"]["revision"]) - 1
            else:
                raise AssertionError(f"unknown successor fault: {self.successor_fault}")
            worker_ref = _sealed_parent("hybrid-worker-faulty-successor")
            faulty = _operation_ref(
                mode="hybrid_v1_1",
                operation_id=next_operation_id,
                request_ref=self.provider_group["request_ref"],
                window_binding=self.window_binding,
                worker_ref=worker_ref,
                status="pending",
                revision=next_revision,
                predecessor=operation_ref,
            )
            self.active_workers.discard(
                str(operation_ref["worker_ref"]["content_sha256"])
            )
            self.active_workers.add(str(worker_ref["content_sha256"]))
            self.active_ops["hybrid"] = deepcopy(faulty)
            return _step(faulty, task_kind="server-managed-faulty-successor")
        self.active_workers.discard(
            str(self.active_ops["hybrid"]["worker_ref"]["content_sha256"])
        )
        if self._hybrid_index == 4:
            assert self.window_binding is not None
            assert self.provider_group is not None
            consumed = deepcopy(self.active_ops["hybrid"])
            complete = _operation_ref(
                mode="hybrid_v1_1",
                operation_id=str(self.window_binding["operation_id"]),
                request_ref=self.provider_group["request_ref"],
                window_binding=self.window_binding,
                worker_ref=consumed["worker_ref"],
                status="complete",
                revision=int(consumed["workflow_state_ref"]["revision"]) + 1,
                predecessor=consumed,
            )
            projection = _projection(
                mode="hybrid_v1_1",
                operation_ref=complete,
                response=self._hybrid_response(),
                terminal=False,
            )
            terminal = _step(
                complete,
                task_kind="server-managed-hybrid-review",
                projection=projection,
            )
            self.active_ops["hybrid"] = deepcopy(complete)
            return terminal
        self._hybrid_index += 1
        self.hybrid_producer_count += 1
        return self._hybrid_step(status="pending")

    def start_incumbent_observe(self, *, provider_case_ref, window_binding):
        self.incumbent_start_calls += 1
        case_id = str(provider_case_ref["case_id"])
        worker_ref = _sealed_parent(f"incumbent-worker-{case_id}")
        operation_ref = _operation_ref(
            mode="incumbent_qwen_only",
            operation_id=f"incumbent-{case_id}",
            request_ref=_identity(case_id),
            window_binding=window_binding,
            worker_ref=worker_ref,
            status="pending",
            revision=30 + self.incumbent_start_calls,
            predecessor=None,
            run_id=f"incumbent-run-{case_id}",
        )
        self._incumbent[case_id] = {
            "case_ref": deepcopy(dict(provider_case_ref)),
            "current": deepcopy(operation_ref),
            "poll_replays": 0,
            "terminal": None,
        }
        self.active_ops[case_id] = deepcopy(operation_ref)
        self.active_workers.add(str(worker_ref["content_sha256"]))
        return _step(operation_ref, task_kind="vision_observe_screen")

    def poll_incumbent_observe(self, *, operation_ref):
        self.incumbent_poll_calls += 1
        case_id = str(operation_ref["operation_id"]).removeprefix("incumbent-")
        state = self._incumbent[case_id]
        if dict(operation_ref) != state["current"]:
            raise ValueError("stale incumbent operation ref")
        if state["poll_replays"] < self.pending_replays:
            state["poll_replays"] += 1
            return _step(operation_ref, task_kind="vision_observe_screen")
        advanced = _operation_ref(
            mode="incumbent_qwen_only",
            operation_id=str(operation_ref["operation_id"]),
            request_ref=operation_ref["request_ref"],
            window_binding=self.window_binding,
            worker_ref=operation_ref["worker_ref"],
            status="advanced",
            revision=int(operation_ref["workflow_state_ref"]["revision"]),
            predecessor=None,
            run_id=str(operation_ref["run_id"]),
        )
        state["current"] = deepcopy(advanced)
        self.active_ops[case_id] = deepcopy(advanced)
        pending_step = _step(operation_ref, task_kind="vision_observe_screen")
        advanced_step = _step(advanced, task_kind="vision_observe_screen")
        self.incumbent_poll_transitions.append(
            (deepcopy(pending_step), deepcopy(advanced_step))
        )
        return advanced_step

    def adopt_and_terminalize_incumbent(self, *, operation_ref, worker_ref):
        self.incumbent_adopt_calls += 1
        case_id = str(operation_ref["operation_id"]).removeprefix("incumbent-")
        state = self._incumbent[case_id]
        if state["terminal"] is not None:
            return deepcopy(state["terminal"])
        if (
            dict(operation_ref) != state["current"]
            or dict(worker_ref) != operation_ref["worker_ref"]
        ):
            raise ValueError("stale incumbent adoption")
        complete = _operation_ref(
            mode="incumbent_qwen_only",
            operation_id=str(operation_ref["operation_id"]),
            request_ref=operation_ref["request_ref"],
            window_binding=self.window_binding,
            worker_ref=worker_ref,
            status="complete",
            revision=int(operation_ref["workflow_state_ref"]["revision"]) + 1,
            predecessor=operation_ref,
            run_id=str(operation_ref["run_id"]),
        )
        projection = _projection(
            mode="incumbent_qwen_only",
            operation_ref=complete,
            response={
                "case_id": case_id,
                "elements": [{"candidate_id": f"qwen-{case_id}"}],
                "_benchmark_v2_provider_dispatch_receipt_refs": [
                    {
                        "provider": "qwen",
                        "content_sha256": __import__("hashlib")
                        .sha256(case_id.encode("utf-8"))
                        .hexdigest(),
                    }
                ],
            },
            terminal=True,
        )
        terminal = _step(
            complete,
            task_kind="vision_observe_screen",
            projection=projection,
        )
        state["current"] = deepcopy(complete)
        state["terminal"] = deepcopy(terminal)
        self.active_ops[case_id] = deepcopy(complete)
        self.active_workers.discard(str(worker_ref["content_sha256"]))
        return terminal

    def cancel_operation(self, *, operation_ref):
        self.cancel_calls += 1
        key = "hybrid" if operation_ref["mode"] == "hybrid_v1_1" else str(
            operation_ref["operation_id"]
        ).removeprefix("incumbent-")
        current = self.active_ops.get(key)
        if current is not None and dict(operation_ref) != current:
            stable_current = {
                name: deepcopy(value)
                for name, value in current.items()
                if name not in {"status", "content_sha256"}
            }
            stable_supplied = {
                name: deepcopy(value)
                for name, value in operation_ref.items()
                if name not in {"status", "content_sha256"}
            }
            if (
                stable_current != stable_supplied
                and current.get("predecessor_content_sha256")
                != operation_ref.get("content_sha256")
            ):
                raise ValueError("stale cleanup operation ref")
        self.active_ops.pop(key, None)
        if current is not None and current.get("worker_ref") is not None:
            self.active_workers.discard(
                str(current["worker_ref"]["content_sha256"])
            )
        if operation_ref.get("worker_ref") is not None:
            self.active_workers.discard(str(operation_ref["worker_ref"]["content_sha256"]))
        return {"status": "reconciled", "operation_ref": deepcopy(dict(operation_ref))}


class _FakeWindowOwner:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.binding = _window_binding()
        self.active_windows: set[str] = set()
        self.service: _FakeWorkflowService | None = None

    def open_screen_group(self, *, provider_group):
        self.events.append("window-open")
        self.active_windows.add(str(self.binding["window_binding_ref"]["id"]))
        return deepcopy(self.binding)

    def close_screen_group(self, *, window_binding, reason):
        self.events.append("window-close")
        assert self.service is not None
        assert not self.service.active_ops
        assert not self.service.active_workers
        self.active_windows.discard(str(window_binding["window_binding_ref"]["id"]))
        return _sealed_parent("window-close")


class _FakeLifecycle:
    def __init__(
        self,
        events: list[str],
        service: _FakeWorkflowService,
        owner: _FakeWindowOwner,
    ) -> None:
        self.events = events
        self.service = service
        self.owner = owner
        self.active_listeners = {"listener"}
        self.active_leases = {"lease"}

    def stable_zero(self, *, provider_group, window_binding, execution_refs, window_close_ref):
        self.events.append("lifecycle-stable-zero")
        self.active_listeners.clear()
        self.active_leases.clear()
        assert not self.service.active_ops
        assert not self.service.active_workers
        assert not self.owner.active_windows
        return _sealed_parent("stable-zero")


class _FakePredictionSink:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.values: list[dict[str, object]] = []

    def write_screen_group(self, *, projection):
        self.events.append("prediction-write")
        self.values.append(deepcopy(dict(projection)))
        return _identity("prediction-1", str(projection["content_sha256"]))


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        assert seconds > 0
        self.sleeps.append(seconds)
        self.now += seconds


def _ports(
    *,
    duplicate_reads: bool = False,
    pending_replays: int = 0,
    never_complete_hybrid: bool = False,
    stale_hybrid: bool = False,
    early_safe_stop: bool = False,
    quality_safe_stop: bool = False,
    successor_fault: str | None = None,
):
    events: list[str] = []
    service = _FakeWorkflowService(
        duplicate_reads=duplicate_reads,
        pending_replays=pending_replays,
        never_complete_hybrid=never_complete_hybrid,
        stale_hybrid=stale_hybrid,
        early_safe_stop=early_safe_stop,
        quality_safe_stop=quality_safe_stop,
        successor_fault=successor_fault,
    )
    owner = _FakeWindowOwner(events)
    owner.service = service
    lifecycle = _FakeLifecycle(events, service, owner)
    sink = _FakePredictionSink(events)
    return events, service, owner, lifecycle, sink


def test_actual_adapter_exposes_only_the_canonical_workflow_service_port() -> None:
    expected = {
        "start_hybrid_operation": ("self", "screen_group", "window_binding"),
        "continue_hybrid_operation": ("self", "operation_ref"),
        "start_incumbent_observe": ("self", "provider_case_ref", "window_binding"),
        "poll_incumbent_observe": ("self", "operation_ref"),
        "adopt_and_terminalize_incumbent": (
            "self",
            "operation_ref",
            "worker_ref",
        ),
        "cancel_operation": ("self", "operation_ref"),
    }
    for name, parameters in expected.items():
        assert tuple(inspect.signature(getattr(WorkflowServicePort, name)).parameters) == parameters
    assert tuple(inspect.signature(run_screen_group).parameters) == (
        "provider_group",
        "service",
        "window_owner",
        "lifecycle",
        "prediction_sink",
    )


def test_actual_adapter_ast_has_no_private_or_action_boundary() -> None:
    source_path = Path(__file__).parents[1] / "app" / "learn" / "hybrid" / "benchmark_v2_actual.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    source = source_path.read_text(encoding="utf-8")
    assert not any(
        forbidden in imported or forbidden in source
        for forbidden in (
            "LearningStageWorkerRegistry",
            "learning_workflow_run_store",
            "workflow_store",
            "workflow_worker",
            "handler",
            ".composition",
            ".start(",
            ".resume(",
            ".cancel(",
        )
    )
    forbidden_calls = {"click", "fill", "publish", "execute_action"}
    assert not {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    } & forbidden_calls


def test_run_screen_group_uses_one_hybrid_cascade_and_five_incumbent_operations() -> None:
    events, service, owner, lifecycle, sink = _ports()

    result = run_screen_group(
        provider_group=_provider_group(),
        service=service,
        window_owner=owner,
        lifecycle=lifecycle,
        prediction_sink=sink,
    )

    assert service.hybrid_start_calls == 1
    assert service.hybrid_producer_count == 5
    assert service.incumbent_start_calls == 5
    assert service.incumbent_adopt_calls == 5
    assert service.downstream_incumbent_starts == 0
    assert service.cancel_calls == 6
    assert len(result["rows"]) == 20
    assert {
        (row["case_ref"]["case_id"], row["arm_id"])
        for row in result["rows"]
    } == {
        (f"case-{case_index}", arm_id)
        for case_index in range(5)
        for arm_id in (
            "qwen_only",
            "omni_only_discovery",
            "omni_to_qwen",
            "omni_to_qwen_vista",
        )
    }
    assert result["artifact_is_authorization"] is False
    assert result["execute_binding_enabled"] is False
    assert result["content_sha256"] == content_sha256(result)
    assert sink.values == [result]
    assert events[-3:] == [
        "window-close",
        "lifecycle-stable-zero",
        "prediction-write",
    ]
    assert not service.active_ops
    assert not service.active_workers
    assert not owner.active_windows
    assert not lifecycle.active_listeners
    assert not lifecycle.active_leases

    shared = result["shared_parent_refs"]
    for row in result["rows"]:
        assert row["shared_parent_refs"] == shared
        refs = row["observation"]["provider_dispatch_receipt_refs"]
        assert {ref["provider"] for ref in refs} == {
            "qwen_only": {"qwen"},
            "omni_only_discovery": {"omni"},
            "omni_to_qwen": {"omni", "qwen"},
            "omni_to_qwen_vista": {"omni", "qwen", "vista"},
        }[row["arm_id"]]
    assert shared == {
        "screen_group_ref": {
            "id": "screen-group-1",
            "content_sha256": _provider_group()["content_sha256"],
        },
        "hybrid_capture_bundle_ref": _provider_group()["hybrid_capture_bundle_ref"],
        "window_binding_ref": _window_binding()["window_binding_ref"],
        "capture_ref": _window_binding()["capture_ref"],
        "owner_journal_ref": _window_binding()["owner_journal_ref"],
        "expected_uia_root_ref": _window_binding()["expected_uia_root_ref"],
    }


def test_actual_projection_seals_exact_pre_vista_evidence_with_class_specific_refs() -> None:
    events, service, owner, lifecycle, sink = _ports()

    result = run_screen_group(
        provider_group=_provider_group(),
        service=service,
        window_owner=owner,
        lifecycle=lifecycle,
        prediction_sink=sink,
    )

    evidence = result["pre_vista_evidence"]
    assert set(evidence) == {
        "contract_version",
        "provider_group_ref",
        "omni_inventory_envelope",
        "qwen_bindings_envelope",
        "fusion_result_envelope",
        "submitted_vista_request_envelopes",
        "safety",
        "content_sha256",
    }
    assert evidence["contract_version"] == "benchmark_v2_actual_pre_vista_evidence_v1"
    assert evidence["provider_group_ref"] == {
        "id": "screen-group-1",
        "content_sha256": _provider_group()["content_sha256"],
    }
    assert evidence["safety"] == {
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    assert evidence["content_sha256"] == content_sha256(evidence)

    expected_prefixes = (
        ("omni_inventory_envelope", "omni-inventory", b"benchmark-v2-omni-inventory\0"),
        ("qwen_bindings_envelope", "qwen-bindings", b"benchmark-v2-qwen-bindings\0"),
        ("fusion_result_envelope", "fusion-result", b"benchmark-v2-fusion-result\0"),
    )
    for field, id_prefix, domain in expected_prefixes:
        envelope = evidence[field]
        assert set(envelope) == {"ref", "canonical_bytes_b64"}
        raw = base64.b64decode(envelope["canonical_bytes_b64"], validate=True)
        assert raw == json.dumps(
            json.loads(raw.decode("utf-8")),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        assert envelope["ref"] == {
            "id": f"{id_prefix}/" + hashlib.sha256(domain + raw).hexdigest(),
            "content_sha256": hashlib.sha256(raw).hexdigest(),
        }

    request_envelopes = evidence["submitted_vista_request_envelopes"]
    decoded_requests = [
        json.loads(base64.b64decode(item["canonical_bytes_b64"], validate=True))
        for item in request_envelopes
    ]
    assert [item["candidate_id"] for item in decoded_requests] == sorted(
        item["candidate_id"] for item in decoded_requests
    )
    for envelope in request_envelopes:
        assert set(envelope) == {"ref", "canonical_bytes_b64"}
        raw = base64.b64decode(envelope["canonical_bytes_b64"], validate=True)
        assert envelope["ref"] == {
            "id": "submitted-vista-request/"
            + hashlib.sha256(b"benchmark-v2-submitted-vista-request\0" + raw).hexdigest(),
            "content_sha256": hashlib.sha256(raw).hexdigest(),
        }

    fusion, capture_bundle, inventory, bindings, cleanup_receipt = (
        _authoritative_inputs()
    )
    assert decoded_requests == sorted(
        build_vista_requests(
            fusion,
            capture_bundle,
            omni_inventory=inventory,
            qwen_bindings=bindings,
            qwen_cleanup_receipt=cleanup_receipt,
            expected_workflow_revision=int(capture_bundle["workflow_revision"]),
        ),
        key=lambda item: item["candidate_id"],
    )


@pytest.mark.parametrize("confidence", (1.0, 0.0, -0.0, 1e-7))
def test_uei_jcs_sealed_legal_floats_pass_closed_validators_and_actual_projection(
    confidence: float,
) -> None:
    _, service, owner, lifecycle, sink = _ports()
    original_response = service._hybrid_response

    def legal_float_response() -> dict[str, object]:
        response = original_response()
        orchestration = response["orchestration"]
        qwen = deepcopy(orchestration["qwen_bindings"])
        qwen.pop("content_sha256")
        qwen["bindings"][0]["semantic_confidence"] = confidence
        qwen = seal_immutable(qwen)
        orchestration["qwen_bindings"] = qwen
        orchestration["hybrid_vista_requests"] = build_vista_requests(
            orchestration["fusion_result"],
            orchestration["capture_bundle"],
            omni_inventory=orchestration["omni_inventory"],
            qwen_bindings=qwen,
            qwen_cleanup_receipt=orchestration["qwen_cleanup_receipt"],
            expected_workflow_revision=int(orchestration["workflow_revision"]),
        )
        return response

    service._hybrid_response = legal_float_response
    projection = run_screen_group(
        provider_group=_provider_group(),
        service=service,
        window_owner=owner,
        lifecycle=lifecycle,
        prediction_sink=sink,
    )

    evidence = projection["pre_vista_evidence"]
    qwen_bytes = base64.b64decode(
        evidence["qwen_bindings_envelope"]["canonical_bytes_b64"],
        validate=True,
    )
    decoded = json.loads(qwen_bytes.decode("utf-8"))
    assert decoded["bindings"][0]["semantic_confidence"] == confidence
    assert evidence["content_sha256"] == content_sha256(evidence)
    assert projection["content_sha256"] == content_sha256(projection)


def test_final_review_proposal_mutation_cannot_change_pre_vista_evidence() -> None:
    _, service_a, owner_a, lifecycle_a, sink_a = _ports()
    baseline = run_screen_group(
        provider_group=_provider_group(),
        service=service_a,
        window_owner=owner_a,
        lifecycle=lifecycle_a,
        prediction_sink=sink_a,
    )["pre_vista_evidence"]

    _, service_b, owner_b, lifecycle_b, sink_b = _ports()
    original_response = service_b._hybrid_response

    def mutated_response() -> dict[str, object]:
        response = original_response()
        response["result"]["proposals"] = [
            {"candidate_id": "proposal-only-mutation", "status": "failed"}
        ]
        return response

    service_b._hybrid_response = mutated_response
    mutated = run_screen_group(
        provider_group=_provider_group(),
        service=service_b,
        window_owner=owner_b,
        lifecycle=lifecycle_b,
        prediction_sink=sink_b,
    )["pre_vista_evidence"]

    assert mutated == baseline


@pytest.mark.parametrize(
    "fault",
    ("missing", "non_list", "duplicate", "omitted", "foreign_candidate"),
)
def test_invalid_propagated_pre_vista_requests_fail_closed_and_still_clean_up(
    fault: str,
) -> None:
    events, service, owner, lifecycle, sink = _ports()
    original_response = service._hybrid_response

    def invalid_requests_response() -> dict[str, object]:
        response = original_response()
        requests = response["orchestration"]["hybrid_vista_requests"]
        if fault == "missing":
            response["orchestration"].pop("hybrid_vista_requests")
        elif fault == "non_list":
            response["orchestration"]["hybrid_vista_requests"] = {"invalid": True}
        elif fault == "duplicate":
            response["orchestration"]["hybrid_vista_requests"] = [
                deepcopy(requests[0]),
                deepcopy(requests[0]),
            ]
        elif fault == "omitted":
            response["orchestration"]["hybrid_vista_requests"] = []
        else:
            foreign = deepcopy(requests[0])
            foreign["candidate_id"] = "foreign-candidate"
            response["orchestration"]["hybrid_vista_requests"] = [foreign]
        return response

    service._hybrid_response = invalid_requests_response
    with pytest.raises(ValueError, match="VISTA request"):
        run_screen_group(
            provider_group=_provider_group(),
            service=service,
            window_owner=owner,
            lifecycle=lifecycle,
            prediction_sink=sink,
        )

    assert not sink.values
    assert events[-2:] == ["window-close", "lifecycle-stable-zero"]
    assert not service.active_ops
    assert not service.active_workers
    assert not owner.active_windows


@pytest.mark.parametrize(
    "parent_name",
    ("omni_inventory", "qwen_bindings", "fusion_result"),
)
def test_pre_vista_parent_closed_validators_reject_absolute_path_extra_field(
    parent_name: str,
) -> None:
    events, service, owner, lifecycle, sink = _ports()
    original_response = service._hybrid_response

    def tampered_response() -> dict[str, object]:
        response = original_response()
        parent = deepcopy(response["orchestration"][parent_name])
        parent.pop("content_sha256")
        parent["debug_path"] = r"C:\private\benchmark\raw.json"
        response["orchestration"][parent_name] = seal_immutable(parent)
        return response

    service._hybrid_response = tampered_response
    with pytest.raises(ValueError, match="inventory|Qwen|fusion"):
        run_screen_group(
            provider_group=_provider_group(),
            service=service,
            window_owner=owner,
            lifecycle=lifecycle,
            prediction_sink=sink,
        )

    assert not sink.values
    assert events[-2:] == ["window-close", "lifecycle-stable-zero"]
    assert not service.active_ops
    assert not service.active_workers
    assert not owner.active_windows


@pytest.mark.parametrize("fault", ("absolute_path_extra", "source_revision"))
def test_propagated_vista_request_must_byte_match_closed_rebuild(fault: str) -> None:
    events, service, owner, lifecycle, sink = _ports()
    original_response = service._hybrid_response

    def tampered_response() -> dict[str, object]:
        response = original_response()
        request = deepcopy(
            response["orchestration"]["hybrid_vista_requests"][0]
        )
        request.pop("content_sha256")
        if fault == "absolute_path_extra":
            request["raw_path"] = r"C:\private\benchmark\request.json"
        else:
            request["source_revision"] = "f" * 64
        response["orchestration"]["hybrid_vista_requests"] = [
            seal_immutable(request)
        ]
        return response

    service._hybrid_response = tampered_response
    with pytest.raises(
        ValueError,
        match="differ from exact calibration output",
    ):
        run_screen_group(
            provider_group=_provider_group(),
            service=service,
            window_owner=owner,
            lifecycle=lifecycle,
            prediction_sink=sink,
        )

    assert not sink.values
    assert events[-2:] == ["window-close", "lifecycle-stable-zero"]
    assert not service.active_ops
    assert not service.active_workers
    assert not owner.active_windows


def test_duplicate_public_reads_do_not_duplicate_hybrid_or_incumbent_producers() -> None:
    events, service, owner, lifecycle, sink = _ports(duplicate_reads=True)

    result = run_screen_group(
        provider_group=_provider_group(),
        service=service,
        window_owner=owner,
        lifecycle=lifecycle,
        prediction_sink=sink,
    )

    assert len(result["rows"]) == 20
    assert service.hybrid_start_calls == 1
    assert service.hybrid_producer_count == 5
    assert service.hybrid_continue_calls == 10
    assert service.incumbent_start_calls == 5
    assert service.incumbent_poll_calls == 10
    assert service.incumbent_adopt_calls == 5
    assert service.downstream_incumbent_starts == 0
    assert len(sink.values) == 1


def test_incumbent_pending_to_advanced_is_read_only_then_adopts_exactly_once() -> None:
    events, service, owner, lifecycle, sink = _ports()

    result = run_screen_group(
        provider_group=_provider_group(),
        service=service,
        window_owner=owner,
        lifecycle=lifecycle,
        prediction_sink=sink,
    )

    assert len(result["rows"]) == 20
    assert len(service.incumbent_poll_transitions) == 5
    assert service.incumbent_adopt_calls == 5
    for pending_step, advanced_step in service.incumbent_poll_transitions:
        assert pending_step["status"] == "pending"
        assert advanced_step["status"] == "advanced"
        pending_operation = pending_step["operation_ref"]
        advanced_operation = advanced_step["operation_ref"]
        for name in (
            "mode",
            "run_id",
            "stage",
            "operation_id",
            "workflow_state_ref",
            "stage_execution_ref",
            "request_ref",
            "window_binding_ref",
            "capture_ref",
            "worker_ref",
            "predecessor_content_sha256",
            "artifact_is_authorization",
            "execute_binding_enabled",
        ):
            assert advanced_operation[name] == pending_operation[name]
        for name in (
            "mode",
            "worker_ref",
            "observed_task_kind",
            "adopted_result_projection",
            "terminal_receipt",
            "cleanup_refs",
            "artifact_is_authorization",
            "execute_binding_enabled",
        ):
            assert advanced_step[name] == pending_step[name]
        assert advanced_step["adopted_result_projection"] is None
        assert advanced_step["terminal_receipt"] is None
        assert advanced_step["cleanup_refs"] == {
            "worker_cleanup_ref": None,
            "provider_cleanup_ref": None,
        }
    assert not service.active_ops
    assert not service.active_workers
    assert not owner.active_windows
    assert not lifecycle.active_listeners
    assert not lifecycle.active_leases


def test_stale_hybrid_projection_fails_closed_before_prediction_and_still_cleans_up() -> None:
    events, service, owner, lifecycle, sink = _ports(stale_hybrid=True)

    with pytest.raises(ValueError, match="capture|stale"):
        run_screen_group(
            provider_group=_provider_group(),
            service=service,
            window_owner=owner,
            lifecycle=lifecycle,
            prediction_sink=sink,
        )

    assert service.hybrid_start_calls == 1
    assert service.incumbent_start_calls == 0
    assert not sink.values
    assert events[-1] == "window-close"
    assert "lifecycle-stable-zero" not in events
    assert not service.active_ops
    assert not service.active_workers
    assert not owner.active_windows


def test_chained_early_safe_stop_preserves_primary_terminal_error_and_cleanup() -> None:
    events, service, owner, lifecycle, sink = _ports(early_safe_stop=True)

    with pytest.raises(
        ValueError, match="Hybrid operation stopped without a complete result: safe_stopped"
    ):
        run_screen_group(
            provider_group=_provider_group(),
            service=service,
            window_owner=owner,
            lifecycle=lifecycle,
            prediction_sink=sink,
        )

    assert service.hybrid_continue_calls == 1
    assert service.incumbent_start_calls == 0
    assert service.cancel_calls == 1
    assert not sink.values
    assert events[-1] == "window-close"
    assert "lifecycle-stable-zero" not in events
    assert not service.active_ops
    assert not service.active_workers
    assert not owner.active_windows


def test_quality_fusion_safe_stop_remains_in_denominator_with_twenty_rows() -> None:
    events, service, owner, lifecycle, sink = _ports(quality_safe_stop=True)

    result = run_screen_group(
        provider_group=_provider_group(),
        service=service,
        window_owner=owner,
        lifecycle=lifecycle,
        prediction_sink=sink,
    )

    assert len(result["rows"]) == 20
    assert service.incumbent_start_calls == 5
    assert result["pre_vista_evidence"]["submitted_vista_request_envelopes"] == []
    vista_rows = [
        row for row in result["rows"] if row["arm_id"] == "omni_to_qwen_vista"
    ]
    assert len(vista_rows) == 5
    assert all(
        row["observation"]["review_projection"]
        == {
            "contract_version": "benchmark_v2_quality_safe_stop_review_projection_v1",
            "outcome": "quality_safe_stop",
            "reason": "no_vista_eligible_bound_candidates",
            "proposals": [],
            "automatic_acceptance": False,
            "execute_binding_enabled": False,
            "no_live_click_authorization": True,
        }
        for row in vista_rows
    )
    assert all(
        {item["provider"] for item in row["observation"]["provider_dispatch_receipt_refs"]}
        == {"omni", "qwen"}
        for row in vista_rows
    )
    assert events[-3:] == [
        "window-close",
        "lifecycle-stable-zero",
        "prediction-write",
    ]


def test_zero_vista_prediction_materializer_requires_explicit_quality_safe_stop() -> None:
    review = {
        "contract_version": "benchmark_v2_quality_safe_stop_review_projection_v1",
        "outcome": "quality_safe_stop",
        "reason": "no_vista_eligible_bound_candidates",
        "proposals": [],
        "automatic_acceptance": False,
        "execute_binding_enabled": False,
        "no_live_click_authorization": True,
    }

    assert benchmark_predictions._actual_vista_proposals(
        observation={"review_projection": review},
        submitted_vista_requests=[],
    ) == []
    forged = deepcopy(review)
    forged["reason"] = "different_reason"
    with pytest.raises(ValueError, match="quality safe-stop"):
        benchmark_predictions._actual_vista_proposals(
            observation={"review_projection": forged},
            submitted_vista_requests=[],
        )


def test_lifecycle_quality_safe_stop_uses_only_dispatched_omni_and_qwen() -> None:
    review = {
        "contract_version": "benchmark_v2_quality_safe_stop_review_projection_v1",
        "outcome": "quality_safe_stop",
        "reason": "no_vista_eligible_bound_candidates",
        "proposals": [],
        "automatic_acceptance": False,
        "execute_binding_enabled": False,
        "no_live_click_authorization": True,
    }

    assert benchmark_lifecycle._s13_expected_dispatch_providers(
        arm_id="omni_to_qwen_vista",
        observation={"review_projection": review},
        zero_vista_requests=True,
    ) == {"omni", "qwen"}
    with pytest.raises(ValueError, match="quality safe-stop"):
        benchmark_lifecycle._s13_expected_dispatch_providers(
            arm_id="omni_to_qwen_vista",
            observation={"review_projection": {**review, "proposals": [{}]}},
            zero_vista_requests=True,
        )


def test_quality_safe_stop_rejects_result_that_differs_from_fusion_parent() -> None:
    events, service, owner, lifecycle, sink = _ports(quality_safe_stop=True)
    original = service._quality_safe_stop_response

    def mismatched_response() -> dict[str, object]:
        response = original()
        result = deepcopy(response["result"])
        result.pop("content_sha256")
        result["candidates"][0]["reason"] = "resealed_but_different"
        response["result"] = seal_immutable(result)
        return response

    service._quality_safe_stop_response = mismatched_response
    with pytest.raises(ValueError, match="fusion result"):
        run_screen_group(
            provider_group=_provider_group(),
            service=service,
            window_owner=owner,
            lifecycle=lifecycle,
            prediction_sink=sink,
        )
    assert service.incumbent_start_calls == 0
    assert not sink.values


def test_hybrid_start_failure_before_operation_ref_preserves_primary_error() -> None:
    events, service, owner, lifecycle, sink = _ports()
    primary = RuntimeError("hybrid start failed before operation ref")
    stable_zero_calls = 0

    def fail_start(*, screen_group, window_binding):
        raise primary

    def fail_stable_zero(**_kwargs):
        nonlocal stable_zero_calls
        stable_zero_calls += 1
        events.append("unexpected-stable-zero")
        raise RuntimeError("benchmark actual execution cleanup multiset is incomplete")

    service.start_hybrid_operation = fail_start
    lifecycle.stable_zero = fail_stable_zero

    with pytest.raises(RuntimeError) as caught:
        run_screen_group(
            provider_group=_provider_group(),
            service=service,
            window_owner=owner,
            lifecycle=lifecycle,
            prediction_sink=sink,
        )

    assert caught.value is primary
    assert stable_zero_calls == 0
    assert not any(
        "cleanup multiset" in note
        for note in getattr(primary, "__notes__", ())
    )
    assert service.cancel_calls == 0
    assert events == ["window-open", "window-close"]
    assert not sink.values
    assert not service.active_ops
    assert not service.active_workers
    assert not owner.active_windows


def test_wrong_target_multiset_is_rejected_before_any_window_or_service_start() -> None:
    events, service, owner, lifecycle, sink = _ports()
    provider_group = _provider_group()
    provider_group["case_refs"] = provider_group["case_refs"][:4]
    provider_group["content_sha256"] = content_sha256(provider_group)

    with pytest.raises(ValueError, match="five case refs"):
        run_screen_group(
            provider_group=provider_group,
            service=service,
            window_owner=owner,
            lifecycle=lifecycle,
            prediction_sink=sink,
        )

    assert not events
    assert service.hybrid_start_calls == 0
    assert not sink.values


def test_prediction_sink_failure_occurs_only_after_stable_zero() -> None:
    events, service, owner, lifecycle, sink = _ports()

    def fail_write(*, projection):
        events.append("prediction-write-failed")
        assert not service.active_ops
        assert not service.active_workers
        assert not owner.active_windows
        raise RuntimeError("prediction sink unavailable")

    sink.write_screen_group = fail_write
    with pytest.raises(RuntimeError, match="prediction sink unavailable"):
        run_screen_group(
            provider_group=_provider_group(),
            service=service,
            window_owner=owner,
            lifecycle=lifecycle,
            prediction_sink=sink,
        )

    assert events[-3:] == [
        "window-close",
        "lifecycle-stable-zero",
        "prediction-write-failed",
    ]


def test_pending_workers_wait_with_nonzero_backoff_and_complete_before_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _FakeClock()
    monkeypatch.setattr(actual, "_monotonic", clock.monotonic)
    monkeypatch.setattr(actual, "_sleep", clock.sleep)
    events, service, owner, lifecycle, sink = _ports(pending_replays=3)

    result = run_screen_group(
        provider_group=_provider_group(),
        service=service,
        window_owner=owner,
        lifecycle=lifecycle,
        prediction_sink=sink,
    )

    assert len(result["rows"]) == 20
    assert len(clock.sleeps) == 40
    assert all(delay > 0 for delay in clock.sleeps)
    assert clock.now < actual._POLL_TIMEOUT_SECONDS * 6
    assert service.hybrid_producer_count == 5
    assert service.incumbent_start_calls == 5
    assert service.cancel_calls == 6
    assert not service.active_ops
    assert not service.active_workers


def test_true_poll_deadline_times_out_then_reconciles_before_window_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _FakeClock()
    monkeypatch.setattr(actual, "_monotonic", clock.monotonic)
    monkeypatch.setattr(actual, "_sleep", clock.sleep)
    monkeypatch.setattr(actual, "_POLL_TIMEOUT_SECONDS", 0.12)
    events, service, owner, lifecycle, sink = _ports(never_complete_hybrid=True)

    with pytest.raises(TimeoutError, match="deadline"):
        run_screen_group(
            provider_group=_provider_group(),
            service=service,
            window_owner=owner,
            lifecycle=lifecycle,
            prediction_sink=sink,
        )

    assert clock.sleeps
    assert all(delay > 0 for delay in clock.sleeps)
    assert service.hybrid_start_calls == 1
    assert service.incumbent_start_calls == 0
    assert service.cancel_calls == 1
    assert events[-1] == "window-close"
    assert "lifecycle-stable-zero" not in events
    assert not sink.values
    assert not service.active_ops
    assert not service.active_workers
    assert not owner.active_windows


@pytest.mark.parametrize(
    "fault",
    (
        "switched_operation_id",
        "same_revision",
        "decreasing_revision",
        "same_digest_changed_step",
    ),
)
def test_successor_lineage_fault_fails_before_second_downstream_call_and_cleans_up(
    fault: str,
) -> None:
    events, service, owner, lifecycle, sink = _ports(successor_fault=fault)

    with pytest.raises(ValueError, match="operation|revision|replay|stale"):
        run_screen_group(
            provider_group=_provider_group(),
            service=service,
            window_owner=owner,
            lifecycle=lifecycle,
            prediction_sink=sink,
        )

    assert service.hybrid_continue_calls == 1
    assert service.incumbent_start_calls == 0
    assert service.cancel_calls == 1
    assert events[-1] == "window-close"
    assert "lifecycle-stable-zero" not in events
    assert not sink.values
    assert not service.active_ops
    assert not service.active_workers
    assert not owner.active_windows
