from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path
from typing import Mapping

import pytest
from PIL import Image

from app.learn.hybrid.benchmark_v2_contracts import (
    ARM_ORDER,
    BENCHMARK_RELEASE_ID,
    PROVIDER_CODE_REFS,
    PROVIDER_CORPUS_CONTRACT,
    PROVIDER_MANIFEST_CONTRACT,
    PARENT_REF,
    SAFETY,
    canonical_json_bytes,
    content_sha256,
)
from app.learn.hybrid.benchmark_v2_provider_corpus import (
    validate_preloaded_provider_corpus,
)
from app.learn.hybrid import benchmark_v2_incumbent_operation as incumbent
from app.learn.recognition.uei.canonical import seal_immutable as runtime_seal_immutable
from modules.ocr.contracts import OCRBoundingBox, OCRResult, OCRTextMatch


ESTIMAND_FILE_SHA256 = "c123a09b48ae144b6869c2d1a0d6e87db81948f6212a8bb686ad863826ad4eeb"
GATE_FILE_SHA256 = "677a5bb7f8f97468b811332bf0811333c793790b4098e2b21fc7068aa7136861"


def _evaluation_projection() -> dict[str, object]:
    return {
        "provider_policy": {
            "provider_revisions": {
                "omni": "PINNED_OMNI_REVISION",
                "qwen": "PINNED_QWEN_REVISION",
                "vista": "PINNED_VISTA_REVISION",
            },
            "provider_revisions_sha256": "25ff2b06d0f5c3fa24809b9e3b046994f3a1d3a472fecffd252238aaa0a0e1c4",
            "shared_budget": {
                "max_provider_calls_per_case": 3,
                "max_output_tokens_per_case": 2048,
                "max_wall_time_ms_per_case": 120000,
            },
            "shared_budget_sha256": "ee15ff899063c6e6ce6de50d635886699b2bc4c3962ca441f3ea2cbf23028932",
            "shared_context_policy": {
                "policy_version": "portfolio-hybrid-shared-uia-ocr-v1",
                "uia": "same_capture_optional",
                "ocr": "same_capture_optional",
            },
            "shared_context_policy_sha256": "a02c7efbb9c639d1c45c8e621be5f24a474a85aa34205e46a5b654d84eb1d31e",
        },
        "estimand": {
            "file_sha256": ESTIMAND_FILE_SHA256,
            "contract_version": "portfolio_hybrid_v1_1_estimand_v2_1",
            "arms": {
                "arm_ids": list(ARM_ORDER),
                "release_arm": "omni_to_qwen_vista",
                "statistical_arm_count": 4,
            },
            "execution_units": {
                "hybrid_arms": [
                    "omni_only_discovery",
                    "omni_to_qwen",
                    "omni_to_qwen_vista",
                ],
                "hybrid_invocation_unit": "screen_group",
                "hybrid_invocations_per_screen_group": 1,
                "incumbent_arm": "qwen_only",
                "incumbent_invocation_unit": "target",
                "targets_per_screen_group": 5,
                "call_count_reports": [
                    "unique_invocation_count",
                    "amortized_per_target_count",
                ],
            },
            "point_metric": {
                "denominator": "submitted_count",
                "gain_numerator": "sum(refined_hit-baseline_hit)",
                "gain": "gain_numerator/submitted_count",
                "comparison_arithmetic": "exact_rational_no_rounding",
                "min_vista_submitted_count": 1,
                "required_gain_numerator": ">0",
            },
        },
        "gate": {
            "file_sha256": GATE_FILE_SHA256,
            "contract_version": "portfolio_hybrid_v1_1_automatic_gate_v2",
            "automatic_split": "pre_review",
            "holdout_role": "automatic_gate",
            "regression_role": "precondition_only",
            "thresholds": {
                "min_coverage": "1/5",
                "min_important_target_correct_coverage_delta": "1/20",
                "min_semantic_precision_delta": "0/1",
                "min_vista_submitted_count": 1,
                "required_vista_gain_numerator": ">0",
                "wrong_target_count": 0,
            },
        },
    }


def _sealed(value: dict[str, object]) -> dict[str, object]:
    result = deepcopy(value)
    result["content_sha256"] = content_sha256(result)
    return result


def _raw_evidence_envelope(
    value: dict[str, object], *, id_prefix: str, domain: bytes
) -> dict[str, object]:
    canonical = canonical_json_bytes(value)
    return {
        "ref": {
            "id": f"{id_prefix}/{hashlib.sha256(domain + canonical).hexdigest()}",
            "content_sha256": hashlib.sha256(canonical).hexdigest(),
        },
        "canonical_bytes_b64": base64.b64encode(canonical).decode("ascii"),
    }


def _pre_vista_evidence(provider_group: Mapping[str, object]) -> dict[str, object]:
    omni = {"items": [{"candidate_id": "candidate-a"}, {"candidate_id": "candidate-b"}]}
    qwen = {
        "bindings": [{"candidate_id": "candidate-a"}, {"candidate_id": "candidate-b"}]
    }
    fusion = {
        "candidates": [
            {"candidate_id": "candidate-a", "state": "BOUND"},
            {"candidate_id": "candidate-b", "state": "BOUND"},
        ]
    }
    requests = [
        {"candidate_id": "candidate-a", "submission_status": "SUBMITTED"},
        {"candidate_id": "candidate-b", "submission_status": "SUBMITTED"},
    ]
    return _sealed(
        {
            "contract_version": "benchmark_v2_actual_pre_vista_evidence_v1",
            "provider_group_ref": {
                "id": provider_group["screen_group"],
                "content_sha256": provider_group["content_sha256"],
            },
            "omni_inventory_envelope": _raw_evidence_envelope(
                omni,
                id_prefix="omni-inventory",
                domain=b"benchmark-v2-omni-inventory\0",
            ),
            "qwen_bindings_envelope": _raw_evidence_envelope(
                qwen,
                id_prefix="qwen-bindings",
                domain=b"benchmark-v2-qwen-bindings\0",
            ),
            "fusion_result_envelope": _raw_evidence_envelope(
                fusion,
                id_prefix="fusion-result",
                domain=b"benchmark-v2-fusion-result\0",
            ),
            "submitted_vista_request_envelopes": [
                _raw_evidence_envelope(
                    request,
                    id_prefix="submitted-vista-request",
                    domain=b"benchmark-v2-submitted-vista-request\0",
                )
                for request in requests
            ],
            "safety": {
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            },
        }
    )


def _write_fixture(root: Path) -> tuple[Path, dict[str, object]]:
    provider_root = root / "provider"
    provider_root.mkdir(parents=True)
    cases: list[dict[str, object]] = []
    for partition_index, partition in enumerate(("regression", "holdout")):
        for index in range(12):
            group_number = partition_index * 12 + index
            group = hashlib.sha256(f"group-{group_number}".encode()).hexdigest()
            relative = (
                f"tests/fixtures/portfolio_hybrid_v1_1/corpus/{partition}/"
                f"case-{group_number:03d}.png"
            )
            image_path = root / relative
            image_path.parent.mkdir(parents=True, exist_ok=True)
            Image.new(
                "RGB",
                (1280, 720),
                color=(group_number + 1, group_number + 2, group_number + 3),
            ).save(image_path, format="PNG", optimize=False)
            image_sha = hashlib.sha256(image_path.read_bytes()).hexdigest()
            layout = {
                "layout_id": f"layout-{group_number}",
                "title": f"Screen {group_number}",
                "surface": "desktop",
                "density": "medium",
                "precision_case": "standard",
                "source_kind": "privacy_safe_synthetic",
                "source_provenance": f"fixture-{group_number}",
            }
            for target in range(5):
                cases.append(
                    {
                        "case_id": hashlib.sha256(
                            f"case-{group_number}-{target}".encode()
                        ).hexdigest(),
                        "partition": partition,
                        "screen_group": group,
                        "goal": f"Find target {target}",
                        "image": {
                            "path": relative,
                            "sha256": image_sha,
                            "width": 1280,
                            "height": 720,
                        },
                        "layout": deepcopy(layout),
                    }
                )
    corpus = {
        "contract_version": PROVIDER_CORPUS_CONTRACT,
        "benchmark_release_id": BENCHMARK_RELEASE_ID,
        "source_parent_ref": deepcopy(PARENT_REF),
        "provider_boundary": {
            "opaque_case_ids": True,
            "opaque_screen_groups": True,
            "filter_complete": True,
            "path_scope": "provider_safe_only",
        },
        "cases": cases,
        "safety": deepcopy(SAFETY),
    }
    corpus["content_sha256"] = content_sha256(corpus)
    corpus_raw = canonical_json_bytes(corpus, pretty=True)
    corpus_path = provider_root / "provider-corpus.v2.json"
    corpus_path.write_bytes(corpus_raw)
    corpus_file_sha = hashlib.sha256(corpus_raw).hexdigest()
    manifest = {
        "contract_version": PROVIDER_MANIFEST_CONTRACT,
        "benchmark_release_id": BENCHMARK_RELEASE_ID,
        "provider_corpus_ref": {
            "contract_version": PROVIDER_CORPUS_CONTRACT,
            "relative_path": "provider-corpus.v2.json",
            "file_sha256": corpus_file_sha,
            "content_sha256": corpus["content_sha256"],
            "source_parent_ref": deepcopy(corpus["source_parent_ref"]),
        },
        "holdout_partition": "holdout",
        "evaluation_projection": _evaluation_projection(),
        "sealed_runtime": {
            "code_refs": [
                {
                    "role": role,
                    "relative_path": relative,
                    "file_sha256": hashlib.sha256(relative.encode()).hexdigest(),
                }
                for role, relative in PROVIDER_CODE_REFS
            ],
            "release_code_refs": [
                {
                    "role": "benchmark_runtime",
                    "relative_path": "app/learn/hybrid/benchmark_v2_runtime.py",
                    "file_sha256": "c" * 64,
                },
                {
                    "role": "benchmark_runner",
                    "relative_path": "scripts/run_portfolio_hybrid_v1_1_benchmark_v2.py",
                    "file_sha256": "d" * 64,
                },
            ],
            "profile_refs": [
                {
                    "role": "hybrid_config",
                    "relative_path": "configs/learn_hybrid_v1_1.json",
                    "file_sha256": "b" * 64,
                }
            ],
        },
        "workload": {
            "contract_version": "provider_sandbox_workload_request_v1",
            "command": "validate_provider_corpus",
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        },
        "arm_order": list(ARM_ORDER),
        "safety": deepcopy(SAFETY),
    }
    manifest_path = provider_root / "provider-manifest.v2.json"
    manifest_path.write_bytes(canonical_json_bytes(manifest, pretty=True))
    return manifest_path, corpus


class _OCR:
    def __init__(self, *, empty: bool = False, wrong_path: bool = False) -> None:
        self.empty = empty
        self.wrong_path = wrong_path
        self.paths: list[str] = []

    def scan_image(self, image_path: str) -> OCRResult:
        self.paths.append(image_path)
        matches = [] if self.empty else [
            OCRTextMatch(
                text="Target",
                score=0.99,
                bbox=OCRBoundingBox(x=4, y=5, width=40, height=20),
            )
        ]
        return OCRResult(
            image_path=(
                str(Path(image_path).with_name("fabricated.png").resolve())
                if self.wrong_path
                else str(Path(image_path).resolve())
            ),
            matches=matches,
            metadata={"engine": "deterministic-test", "match_count": len(matches)},
        )


class _Windows:
    def __init__(
        self,
        *,
        empty_uia: bool = False,
        stale_pid: bool = False,
        stale_hwnd: bool = False,
        stale_create_time: bool = False,
        fail_close_once: bool = False,
    ) -> None:
        self.empty_uia = empty_uia
        self.stale_pid = stale_pid
        self.stale_hwnd = stale_hwnd
        self.stale_create_time = stale_create_time
        self.fail_close_once = fail_close_once
        self.active = 0
        self.maximum_active = 0
        self.launched: list[dict[str, object]] = []
        self.closed: list[str] = []
        self.close_calls = 0
        self.cleanup_by_journal: dict[str, dict[str, object]] = {}

    def launch(self, **kwargs: object) -> dict[str, object]:
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        image_path = Path(str(kwargs["image_path"]))
        operation_id = str(kwargs["operation_id"])
        journal_path = Path(str(kwargs["journal_path"]))
        owner: dict[str, object] = {
            "owner_id": f"owner-{operation_id}",
            "operation_id": operation_id,
            "hwnd": 1000 + len(self.launched),
            "process_identity": {"pid": 2000 + len(self.launched), "create_time_ns": 3000},
            "screenshot_sha256": str(kwargs["expected_sha256"]),
            "screenshot_path": str(image_path.resolve()),
            "image_dimensions": {"width": 1280, "height": 720},
            "journal_path": str(journal_path.resolve()),
            "window_rect": {"left": 10, "top": 20, "right": 1290, "bottom": 740},
            "client_rect": {"left": 0, "top": 0, "right": 1280, "bottom": 720},
            "window_title": "Fixture",
            "window_class": "FixtureClass",
            "scope_name": f"scope-{operation_id}",
            "uia_root_identity": _sealed({"kind": "uia-root", "operation_id": operation_id}),
            "journal_root": _sealed({"kind": "owner-journal", "operation_id": operation_id}),
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "display_only": True,
        }
        owner["content_sha256"] = content_sha256(owner)
        self.launched.append(owner)
        return deepcopy(owner)

    def snapshot(self, *, owner: Mapping[str, object]) -> dict[str, object]:
        pid = int(owner["process_identity"]["pid"]) + (1 if self.stale_pid else 0)
        hwnd = int(owner["hwnd"]) + (1 if self.stale_hwnd else 0)
        process_identity = deepcopy(owner["process_identity"])
        if self.stale_create_time:
            process_identity["create_time_ns"] += 1
        controls = [] if self.empty_uia else [
            {
                "provider": "windows_uia",
                "control_id": "uia-root",
                "name": "Fixture",
                "control_type": "Window",
                "automation_id": None,
                "class_name": "FixtureClass",
                "bbox": {"x": 0, "y": 0, "w": 1280, "h": 720},
                "screen_bbox": {"x": 10, "y": 20, "w": 1280, "h": 720},
                "enabled": True,
                "visible": True,
                "patterns": ["Invoke"],
            }
        ]
        snapshot = {
            "provider": "windows_uia",
            "provider_version": "windows_uia_provider_v1",
            "status": "ok",
            "window": {
                "handle": hwnd,
                "title": "Fixture",
                "process_id": pid,
                "process_name": "python.exe",
                "bbox": {"x": 0, "y": 0, "w": 1280, "h": 720},
            },
            "control_count": len(controls),
            "controls": controls,
        }
        return _sealed(
            {
                "contract_version": "portfolio_hybrid_benchmark_v2_owned_window_snapshot_v1",
                "owner_binding_ref": {
                    "id": owner["owner_id"],
                    "content_sha256": owner["content_sha256"],
                },
                "operation_id": owner["operation_id"],
                "exact_hwnd": hwnd,
                "process_identity": process_identity,
                "job_member_pids": [owner["process_identity"]["pid"]],
                "screenshot_sha256": owner["screenshot_sha256"],
                "uia_root_identity": deepcopy(owner["uia_root_identity"]),
                "uia_snapshot": snapshot,
                "pre_raw_identity_sha256": "c" * 64,
                "post_raw_identity_sha256": "c" * 64,
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
                "display_only": True,
            }
        )

    def close(self, *, journal_path: Path, reason: str) -> dict[str, object]:
        journal_key = str(Path(journal_path).resolve())
        existing = self.cleanup_by_journal.get(journal_key)
        if existing is not None:
            return deepcopy(existing)
        self.close_calls += 1
        if self.fail_close_once and self.close_calls == 1:
            raise RuntimeError("transient cleanup failure")
        self.active -= 1
        self.closed.append(reason)
        matching_owners = [
            owner
            for owner in self.launched
            if str(Path(str(owner["journal_path"])).resolve()) == journal_key
        ]
        if len(matching_owners) != 1:
            raise AssertionError("window cleanup fixture owner is ambiguous")
        owner = matching_owners[0]
        receipt = _sealed(
            {
                "contract_version": "portfolio_hybrid_benchmark_v2_window_cleanup_v1",
                "owner_id": owner["owner_id"],
                "reason": reason,
                "exact_hwnd": owner["hwnd"],
                "process_identity": deepcopy(owner["process_identity"]),
                "cleanup_subject_kind": "ready_window",
                "finalization_intent_sha256": "1" * 64,
                "process_event_sha256": "2" * 64,
                "ready_event_sha256": "3" * 64,
                "publication_content_sha256": "4" * 64,
                "cleanup_status": "verified",
                "shutdown_event_name": f"shutdown-{Path(journal_path).stem}",
                "shutdown_event_signaled": True,
                "shutdown_event_error_code": None,
                "shutdown_event_handle_closed": True,
                "enum_windows_exact_hwnd_absent": True,
                "matching_owned_windows_after": [],
                "member_pids_after": [],
                "stable_zero_observations": 2,
                "scope_absent_after_owner_close": True,
                "process_handle_closed": True,
                "job_handle_closed": True,
                "active_listeners_after": [],
                "listener_or_lease_residue": [],
                "outer_owner_python_finally_observed": True,
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            }
        )
        self.cleanup_by_journal[journal_key] = deepcopy(receipt)
        return receipt


def _install_fakes(
    monkeypatch: pytest.MonkeyPatch,
    runtime_module: object,
    corpus: Mapping[str, object],
    windows: _Windows,
    ocr: _OCR,
) -> None:
    case_refs = [
        {
            "case_id": case["case_id"],
            "case_content_sha256": content_sha256(case),
        }
        for case in corpus["cases"]
    ]
    corpus_file_ref = _sealed(
        {
            "contract_version": "benchmark_v2_provider_corpus_file_ref_v1",
            "relative_path": "provider-corpus.v2.json",
            "file_sha256": hashlib.sha256(
                canonical_json_bytes(corpus, pretty=True)
            ).hexdigest(),
            "source_parent_ref": deepcopy(corpus["source_parent_ref"]),
        }
    )
    monkeypatch.setattr(
        runtime_module,
        "load_provider_corpus",
        lambda *, child_path, expected_sha256: validate_preloaded_provider_corpus(
            raw=Path(child_path).read_bytes(), expected_sha256=expected_sha256
        ),
    )
    monkeypatch.setattr(runtime_module, "get_production_provider_case_resolver", lambda: object())
    monkeypatch.setattr(runtime_module, "provider_case_resolver_case_refs", lambda resolver: deepcopy(case_refs))
    monkeypatch.setattr(runtime_module, "provider_case_resolver_corpus_file_ref", lambda resolver: deepcopy(corpus_file_ref))
    monkeypatch.setattr(runtime_module, "launch_owned_window", windows.launch)
    monkeypatch.setattr(runtime_module, "snapshot_owned_window", windows.snapshot)
    monkeypatch.setattr(runtime_module, "close_owned_window", windows.close)
    monkeypatch.setattr(runtime_module, "ocr_service", ocr)
    monkeypatch.setattr(
        runtime_module,
        "load_hybrid_config",
        lambda project_root: {"mode": "hybrid_v1_1"},
    )
    monkeypatch.setattr(
        runtime_module,
        "get_production_server_worker_window_binding_publisher",
        lambda: object(),
    )
    monkeypatch.setattr(
        runtime_module,
        "publish_server_worker_window_binding",
        lambda **kwargs: _sealed(
            {
                "window_binding_ref": {
                    "id": kwargs["owner"]["owner_id"],
                    "content_sha256": kwargs["owner"]["content_sha256"],
                },
                "capture_ref": deepcopy(kwargs["capture_ref"]),
                "owner_journal_ref": deepcopy(kwargs["owner"]["journal_root"]),
            }
        ),
    )


def _runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    runtime_options: Mapping[str, object] | None = None,
    **window_options: bool,
):
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module

    manifest_path, corpus = _write_fixture(tmp_path)
    windows = _Windows(**window_options)
    ocr = _OCR()
    _install_fakes(monkeypatch, runtime_module, corpus, windows, ocr)
    runtime = runtime_module._BenchmarkV2ProductionRuntime(
        project_root=tmp_path,
        authority_root=tmp_path / "runtime_state" / "binding-authority",
        **dict(runtime_options or {}),
    )
    manifest = runtime.load_provider_manifest(path=manifest_path)
    return runtime_module, runtime, manifest, corpus, windows, ocr


def _actual_operation(
    *,
    mode: str,
    operation_id: str,
    request_ref: Mapping[str, object],
    binding: Mapping[str, object],
    revision: int,
    status: str = "pending",
    predecessor: Mapping[str, object] | None = None,
    predecessor_content_sha256: str | None = None,
) -> dict[str, object]:
    return incumbent.compose_benchmark_v2_workflow_service_operation_ref(
        mode=mode,
        run_id=str(binding["run_id"]),
        stage=str(binding["stage"]),
        operation_id=operation_id,
        workflow_state_ref={
            "run_id": str(binding["run_id"]),
            "revision": revision,
            "content_sha256": f"{revision % 10}" * 64,
        },
        stage_execution_ref={
            "run_id": str(binding["run_id"]),
            "stage": str(binding["stage"]),
            "operation_id": operation_id,
            "revision": revision,
            "content_sha256": f"{(revision + 5) % 10}" * 64,
        },
        request_ref=request_ref,
        window_binding_ref=binding["window_binding_ref"],
        capture_ref=binding["capture_ref"],
        worker_ref=_sealed(
            {
                "worker_id": f"worker-{operation_id}",
                "model_request_id": f"request-{operation_id}",
                "payload_sha256": hashlib.sha256(operation_id.encode()).hexdigest(),
            }
        ),
        status=status,
        predecessor_operation_ref=predecessor,
        predecessor_content_sha256=predecessor_content_sha256,
    )


def _actual_service_step(
    group: Mapping[str, object], binding: Mapping[str, object]
) -> dict[str, object]:
    operation = _actual_operation(
        mode="hybrid_v1_1",
        operation_id=str(binding["operation_id"]),
        request_ref=group["request_ref"],
        binding=binding,
        revision=1,
    )
    return incumbent.compose_benchmark_v2_workflow_service_step(
        operation_ref=operation,
        observed_task_kind="panel_learning_hybrid_omni_discovery",
        adopted_result_projection=None,
        terminal_receipt=None,
        cleanup_refs={"worker_cleanup_ref": None, "provider_cleanup_ref": None},
    )


def _canonical_incumbent_worker_cleanup(
    operation: Mapping[str, object],
    *,
    exact_handle_observation_refs: Mapping[str, object],
    supervisor_absence_observation_ref: object,
) -> dict[str, object]:
    return runtime_seal_immutable(
        {
            "contract_version": "benchmark_worker_cleanup_receipt_v1",
            "outcome": "verified_exact_worker_exited",
            "operation_anchor_ref": operation["operation_anchor_ref"],
            "reservation_ref": {"content_sha256": "2" * 64},
            "supervision_ref": {"content_sha256": "3" * 64},
            "run_id": operation["run_id"],
            "stage": operation["stage"],
            "operation_id": operation["operation_id"],
            "worker_id": operation["worker_ref"]["worker_id"],
            "process_identity": {"pid": 1234, "create_time_ns": 5678},
            "assignment_proven_ref": {"content_sha256": "4" * 64},
            "finalization_intent_ref": {"content_sha256": "5" * 64},
            "exact_handle_observation_refs": dict(exact_handle_observation_refs),
            "job_absence_observation_ref": {"content_sha256": "6" * 64},
            "worker_absence_observation_ref": {"content_sha256": "7" * 64},
            "supervisor_absence_observation_ref": (
                supervisor_absence_observation_ref
            ),
            "reservation_abort_ref": None,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )


def _actual_incumbent_cancelled_terminal_receipt(
    *,
    operation: Mapping[str, object],
    worker_cleanup_ref: Mapping[str, object],
    provider_cleanup_ref: Mapping[str, object],
) -> dict[str, object]:
    worker = operation["worker_ref"]
    return _sealed(
        {
            "contract_version": "benchmark_v2_incumbent_terminal_receipt_v1",
            "outcome": "benchmark_v2_incumbent_cancelled",
            "run_id": operation["run_id"],
            "stage": operation["stage"],
            "operation_id": operation["operation_id"],
            "worker_id": worker["worker_id"],
            "model_request_id": worker["model_request_id"],
            "payload_sha256": worker["payload_sha256"],
            "result_sha256": None,
            "terminal_intent_ref": None,
            "cancel_intent_ref": {"content_sha256": "f" * 64},
            "generic_adoption_ref": None,
            "window_adoption_ref": None,
            "worker_cleanup_ref": deepcopy(dict(worker_cleanup_ref)),
            "provider_cleanup_ref": deepcopy(dict(provider_cleanup_ref)),
            "provider_cleanup_outcome": provider_cleanup_ref["outcome"],
            "terminal_at": "2026-09-01T05:00:00+00:00",
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "predecessor_content_sha256": operation[
                "predecessor_content_sha256"
            ],
        }
    )


def _canonical_explicit_close_handle_refs() -> dict[str, object]:
    return {
        "worker_process": {"content_sha256": "8" * 64},
        "startup_event": {"content_sha256": "9" * 64},
        "beacon_file": {"content_sha256": "a" * 64},
        "owner_job": {"content_sha256": "b" * 64},
        "incumbent_provider_job": {"content_sha256": "c" * 64},
    }


@pytest.mark.parametrize("cleanup_path", ("explicit_close", "dead_supervisor"))
def test_incumbent_cleanup_supervisor_contract_accepts_canonical_paths(
    cleanup_path: str,
) -> None:
    from app.learn import workflow_service
    from app.learn.hybrid.benchmark_v2_runtime import (
        validate_benchmark_v2_incumbent_worker_cleanup_contract,
    )

    binding = {
        "run_id": f"run-{cleanup_path}",
        "stage": "screen_understanding",
        "operation_id": f"operation-{cleanup_path}",
        "window_binding_ref": {"id": "window", "content_sha256": "d" * 64},
        "capture_ref": {"id": "capture", "content_sha256": "e" * 64},
    }
    operation = _actual_operation(
        mode="incumbent_qwen_only",
        operation_id=str(binding["operation_id"]),
        request_ref={"id": "case", "content_sha256": "f" * 64},
        binding=binding,
        revision=2,
        status="complete",
    )
    operation = {
        **operation,
        "operation_anchor_ref": {"content_sha256": "1" * 64},
    }
    receipt = _canonical_incumbent_worker_cleanup(
        operation,
        exact_handle_observation_refs=(
            _canonical_explicit_close_handle_refs()
            if cleanup_path == "explicit_close"
            else {}
        ),
        supervisor_absence_observation_ref=(
            None
            if cleanup_path == "explicit_close"
            else {"content_sha256": "0" * 64}
        ),
    )

    assert validate_benchmark_v2_incumbent_worker_cleanup_contract(receipt) == receipt
    assert workflow_service._validate_benchmark_v2_actual_incumbent_worker_cleanup(
        cleanup=receipt,
        operation=operation,
    ) == receipt


@pytest.mark.parametrize(
    "mutation",
    (
        "missing_dead_supervisor_ref",
        "malformed_dead_supervisor_ref",
        "missing_explicit_handle_ref",
        "cross_operation_anchor",
    ),
)
def test_incumbent_cleanup_supervisor_contract_rejects_invalid_or_cross_lineage(
    mutation: str,
) -> None:
    from app.learn import workflow_service

    binding = {
        "run_id": f"run-{mutation}",
        "stage": "screen_understanding",
        "operation_id": f"operation-{mutation}",
        "window_binding_ref": {"id": "window", "content_sha256": "d" * 64},
        "capture_ref": {"id": "capture", "content_sha256": "e" * 64},
    }
    operation = _actual_operation(
        mode="incumbent_qwen_only",
        operation_id=str(binding["operation_id"]),
        request_ref={"id": "case", "content_sha256": "f" * 64},
        binding=binding,
        revision=2,
        status="complete",
    )
    operation = {
        **operation,
        "operation_anchor_ref": {"content_sha256": "1" * 64},
    }
    handles = _canonical_explicit_close_handle_refs()
    supervisor_ref: object = None
    if mutation in {"missing_dead_supervisor_ref", "malformed_dead_supervisor_ref"}:
        handles = {}
    if mutation == "malformed_dead_supervisor_ref":
        supervisor_ref = {"content_sha256": "not-a-sha"}
    receipt = _canonical_incumbent_worker_cleanup(
        operation,
        exact_handle_observation_refs=handles,
        supervisor_absence_observation_ref=supervisor_ref,
    )
    if mutation == "missing_explicit_handle_ref":
        body = dict(receipt)
        body.pop("content_sha256")
        body["exact_handle_observation_refs"] = {
            key: value
            for key, value in handles.items()
            if key != "beacon_file"
        }
        receipt = runtime_seal_immutable(body)
    elif mutation == "cross_operation_anchor":
        body = dict(receipt)
        body.pop("content_sha256")
        body["operation_anchor_ref"] = {"content_sha256": "0" * 64}
        receipt = runtime_seal_immutable(body)

    with pytest.raises(workflow_service.LearningWorkflowStageOperationError):
        workflow_service._validate_benchmark_v2_actual_incumbent_worker_cleanup(
            cleanup=receipt,
            operation=operation,
        )


def test_partial_terminal_accepts_runtime_jcs_and_phase_specific_reservations(
) -> None:
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module

    group = {
        "request_ref": {
            "id": "request/runtime-jcs-cleanup",
            "content_sha256": "c" * 64,
        }
    }
    binding = incumbent.compose_benchmark_v2_workflow_window_binding(
        run_id="run-runtime-jcs-cleanup",
        operation_id="operation-runtime-jcs-cleanup",
        window_binding_ref={
            "id": "window/runtime-jcs-cleanup",
            "content_sha256": "d" * 64,
        },
        capture_ref={
            "id": "capture/runtime-jcs-cleanup",
            "content_sha256": "e" * 64,
        },
        owner_journal_ref={"content_sha256": "f" * 64},
        expected_uia_root_ref={"content_sha256": "0" * 64},
    )
    operation = _actual_operation(
        mode="incumbent_qwen_only",
        operation_id=str(binding["operation_id"]),
        request_ref=group["request_ref"],
        binding=binding,
        revision=2,
        status="safe_stopped",
    )
    worker = operation["worker_ref"]
    worker_cleanup = runtime_seal_immutable(
        {
            "contract_version": "benchmark_worker_cleanup_receipt_v1",
            "outcome": "verified_exact_worker_exited",
            "operation_anchor_ref": {"content_sha256": "1" * 64},
            "reservation_ref": {"content_sha256": "2" * 64},
            "supervision_ref": {"content_sha256": "3" * 64},
            "run_id": operation["run_id"],
            "stage": operation["stage"],
            "operation_id": operation["operation_id"],
            "worker_id": worker["worker_id"],
            "process_identity": {
                "pid": 94884,
                "create_time_ns": 1_788_198_854_639_404_288,
            },
            "assignment_proven_ref": {"content_sha256": "4" * 64},
            "finalization_intent_ref": {"content_sha256": "5" * 64},
            "exact_handle_observation_refs": _canonical_explicit_close_handle_refs(),
            "job_absence_observation_ref": {"content_sha256": "6" * 64},
            "worker_absence_observation_ref": {"content_sha256": "7" * 64},
            "supervisor_absence_observation_ref": None,
            "reservation_abort_ref": None,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    provider_cleanup = runtime_seal_immutable(
        {
            "contract_version": "benchmark_provider_cleanup_ref_v1",
            "status": "cleanup_verified",
            "outcome": "verified_not_acquired",
            "authority_kind": "production_workflow_service",
            "run_id": operation["run_id"],
            "stage": operation["stage"],
            "operation_id": operation["operation_id"],
            "worker_id": worker["worker_id"],
            "model_request_id": worker["model_request_id"],
            "payload_sha256": worker["payload_sha256"],
            "reservation_ref": {"content_sha256": "c" * 64},
            "acquisition_owner_ref": {"content_sha256": "8" * 64},
            "acquisition_intent_ref": {"content_sha256": "9" * 64},
            "runtime_owner_ref": {"content_sha256": "a" * 64},
            "cleanup_receipt_ref": {"content_sha256": "b" * 64},
        }
    )
    terminal = incumbent.compose_benchmark_v2_workflow_service_step(
        operation_ref=operation,
        observed_task_kind="vision_observe_screen",
        adopted_result_projection=None,
        terminal_receipt=None,
        cleanup_refs={
            "worker_cleanup_ref": worker_cleanup,
            "provider_cleanup_ref": provider_cleanup,
        },
    )

    assert runtime_module._validate_service_terminal(terminal) == terminal
    assert len(runtime_module._provider_cleanup_refs(terminal)) == 2
    assert runtime_module._validate_partial_actual_terminal_cleanup(terminal) == terminal

    forged = deepcopy(terminal)
    forged_cleanup = deepcopy(worker_cleanup)
    forged_cleanup["content_sha256"] = content_sha256(forged_cleanup)
    forged["cleanup_refs"]["worker_cleanup_ref"] = forged_cleanup
    forged["content_sha256"] = content_sha256(forged)
    with pytest.raises(ValueError, match="worker_cleanup_ref content SHA differs"):
        runtime_module._validate_service_terminal(forged)


def _actual_completed_review_step(
    group: Mapping[str, object], binding: Mapping[str, object]
) -> dict[str, object]:
    operation_id = str(binding["operation_id"])
    worker = _sealed(
        {
            "contract_version": "benchmark_v2_workflow_service_generic_worker_ref_v1",
            "run_id": str(binding["run_id"]),
            "stage": str(binding["stage"]),
            "operation_id": operation_id,
            "worker_id": f"worker-{operation_id}",
            "model_request_id": f"request-{operation_id}",
            "payload_sha256": hashlib.sha256(operation_id.encode()).hexdigest(),
            "task_kind": "panel_learning_hybrid_review_projection",
        }
    )
    operation = incumbent.compose_benchmark_v2_workflow_service_operation_ref(
        mode="hybrid_v1_1",
        run_id=str(binding["run_id"]),
        stage=str(binding["stage"]),
        operation_id=operation_id,
        workflow_state_ref={
            "run_id": str(binding["run_id"]),
            "revision": 2,
            "content_sha256": "2" * 64,
        },
        stage_execution_ref={
            "run_id": str(binding["run_id"]),
            "stage": str(binding["stage"]),
            "operation_id": operation_id,
            "revision": 2,
            "content_sha256": "7" * 64,
        },
        request_ref=group["request_ref"],
        window_binding_ref=binding["window_binding_ref"],
        capture_ref=binding["capture_ref"],
        worker_ref=worker,
        status="complete",
    )
    return incumbent.compose_benchmark_v2_workflow_service_step(
        operation_ref=operation,
        observed_task_kind="panel_learning_hybrid_review_projection",
        adopted_result_projection=None,
        terminal_receipt=None,
        cleanup_refs={"worker_cleanup_ref": None, "provider_cleanup_ref": None},
    )


def _actual_completed_review_cleanup(
    operation: Mapping[str, object],
) -> dict[str, object]:
    worker = operation["worker_ref"]
    worker_cleanup = _sealed(
        {
            "contract_version": "benchmark_v2_hybrid_worker_cleanup_ref_v1",
            **{
                name: operation[name]
                for name in ("run_id", "stage", "operation_id")
            },
            **{
                name: worker[name]
                for name in ("worker_id", "model_request_id", "payload_sha256")
            },
            "backend_compute_termination": "not_running",
            "model_service_compute_termination": "request_not_active",
            "cancellation_ref": {"content_sha256": "c" * 64},
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    observation = _sealed(
        {
            "contract_version": (
                "benchmark_v2_hybrid_no_provider_live_absence_observation_v1"
            ),
            **{
                name: operation[name]
                for name in ("run_id", "stage", "operation_id")
            },
            **{
                name: worker[name]
                for name in (
                    "worker_id",
                    "model_request_id",
                    "payload_sha256",
                    "task_kind",
                )
            },
            "provider_role": "review",
            "current_worker_ref": deepcopy(worker),
            "latest_operation_worker_ref": deepcopy(worker),
            "review_dispatch_context_absent": True,
            "review_dispatch_receipt_absent": True,
            "provider_scope_absent": True,
            "provider_journal_absent": True,
            "provider_cleanup_journal_absent": True,
            "deterministic_provider_lease_artifact_absent": True,
            "deterministic_provider_owner_artifact_absent": True,
            "deterministic_provider_runtime_artifact_absent": True,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    provider_cleanup = _sealed(
        {
            "contract_version": "benchmark_v2_hybrid_no_provider_cleanup_ref_v1",
            "status": "cleanup_verified",
            "outcome": "verified_review_provider_not_applicable",
            "authority_kind": (
                "benchmark_v2_workflow_service_review_no_provider_cleanup"
            ),
            **{
                name: operation[name]
                for name in ("run_id", "stage", "operation_id")
            },
            **{
                name: worker[name]
                for name in (
                    "worker_id",
                    "model_request_id",
                    "payload_sha256",
                    "task_kind",
                )
            },
            "provider_role": "review",
            "worker_status": "completed",
            "runtime_attached": False,
            "result_available": True,
            "result_adopted": True,
            "continuation_phase": "terminal_prepared",
            "cancellation_backend_termination": "not_running",
            "cancellation_model_request_termination": "request_not_active",
            "service_binding_ref": {"content_sha256": "a" * 64},
            "terminal_prepared_continuation_receipt_ref": {
                "content_sha256": "b" * 64
            },
            "returned_worker_ref": deepcopy(worker),
            "worker_cleanup_ref": {
                "content_sha256": worker_cleanup["content_sha256"]
            },
            "live_absence_observation": observation,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    return incumbent.compose_benchmark_v2_actual_completed_hybrid_cleanup(
        operation_ref=operation,
        worker_cleanup_ref=worker_cleanup,
        provider_cleanup_ref=provider_cleanup,
    )


def test_actual_stable_zero_accepts_completed_review_no_provider_cleanup() -> None:
    binding = {
        "stage": "screen_understanding",
        "window_binding_ref": {
            "id": "window-review-no-provider",
            "content_sha256": "a" * 64,
        },
        "capture_ref": {
            "id": "capture-review-no-provider",
            "content_sha256": "b" * 64,
        },
    }
    group = {
        "request_ref": {
            "id": "request-review-no-provider",
            "content_sha256": "c" * 64,
        }
    }
    review_step = _actual_completed_review_step(
        group,
        {
            **binding,
            "run_id": "run-review-no-provider",
            "operation_id": "operation-review-no-provider",
        },
    )
    review_operation = review_step["operation_ref"]
    review_cleanup = _actual_completed_review_cleanup(review_operation)

    service = _ActualService([])
    incumbent_terminals = []
    for index in range(5):
        operation = _actual_operation(
            mode="incumbent_qwen_only",
            operation_id=f"incumbent-review-no-provider-{index}",
            request_ref={
                "id": f"case-review-no-provider-{index}",
                "content_sha256": f"{index + 1:x}" * 64,
            },
            binding={
                **binding,
                "run_id": f"run-review-no-provider-{index}",
            },
            revision=index + 1,
        )
        incumbent_terminals.append(service.cancel_operation(operation_ref=operation))

    operations = [
        review_operation,
        *(item["operation_ref"] for item in incumbent_terminals),
    ]
    cleanup_entries = [
        {
            "operation_ref_sha256": review_operation["content_sha256"],
            "terminal_receipt_ref": _sealed(
                {
                    "run_id": review_operation["run_id"],
                    "stage": review_operation["stage"],
                    "operation_id": review_operation["operation_id"],
                    "worker_id": review_operation["worker_ref"]["worker_id"],
                }
            ),
            "worker_cleanup_ref": review_cleanup["worker_cleanup_ref"],
            "provider_cleanup_ref": review_cleanup["provider_cleanup_ref"],
        },
        *(
            {
                "operation_ref_sha256": item["operation_ref"]["content_sha256"],
                "terminal_receipt_ref": _actual_incumbent_cancelled_terminal_receipt(
                    operation=item["operation_ref"],
                    worker_cleanup_ref=item["cleanup_refs"]["worker_cleanup_ref"],
                    provider_cleanup_ref=item["cleanup_refs"]["provider_cleanup_ref"],
                ),
                "worker_cleanup_ref": item["cleanup_refs"]["worker_cleanup_ref"],
                "provider_cleanup_ref": item["cleanup_refs"]["provider_cleanup_ref"],
            }
            for item in incumbent_terminals
        ),
    ]
    receipt = runtime_seal_immutable(
        {
            "contract_version": "benchmark_v2_actual_operations_stable_zero_v1",
            "operation_refs": operations,
            "cleanup_entries": cleanup_entries,
            "window_binding_ref": binding["window_binding_ref"],
            "capture_ref": binding["capture_ref"],
            "cleanup_status": "stable_zero",
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )

    assert incumbent.validate_benchmark_v2_actual_operations_stable_zero(receipt) == receipt

    for field, value in (
        ("task_kind", "panel_learning_calibration_sequence"),
        ("provider_role", "qwen"),
    ):
        foreign = deepcopy(receipt)
        provider_cleanup = foreign["cleanup_entries"][0]["provider_cleanup_ref"]
        provider_cleanup[field] = value
        provider_cleanup["content_sha256"] = content_sha256(provider_cleanup)
        foreign["content_sha256"] = content_sha256(foreign)
        with pytest.raises(ValueError):
            incumbent.validate_benchmark_v2_actual_operations_stable_zero(foreign)


def test_actual_stable_zero_uses_incumbent_terminal_receipt_contract_hash() -> None:
    binding = {
        "stage": "screen_understanding",
        "window_binding_ref": {
            "id": "window-incumbent-terminal",
            "content_sha256": "a" * 64,
        },
        "capture_ref": {
            "id": "capture-incumbent-terminal",
            "content_sha256": "b" * 64,
        },
    }
    group = {
        "request_ref": {
            "id": "request-incumbent-terminal",
            "content_sha256": "c" * 64,
        }
    }
    review_step = _actual_completed_review_step(
        group,
        {
            **binding,
            "run_id": "run-incumbent-terminal-review",
            "operation_id": "operation-incumbent-terminal-review",
        },
    )
    review_operation = review_step["operation_ref"]
    review_cleanup = _actual_completed_review_cleanup(review_operation)

    service = _ActualService([])
    incumbent_terminals = []
    for index in range(5):
        operation = _actual_operation(
            mode="incumbent_qwen_only",
            operation_id=f"incumbent-terminal-{index}",
            request_ref={
                "id": f"case-incumbent-terminal-{index}",
                "content_sha256": f"{index + 1:x}" * 64,
            },
            binding={
                **binding,
                "run_id": f"run-incumbent-terminal-{index}",
            },
            revision=index + 1,
        )
        incumbent_terminals.append(service.cancel_operation(operation_ref=operation))

    operations = [
        review_operation,
        *(item["operation_ref"] for item in incumbent_terminals),
    ]
    entries = [
        {
            "operation_ref_sha256": review_operation["content_sha256"],
            "terminal_receipt_ref": _sealed(
                {
                    "run_id": review_operation["run_id"],
                    "stage": review_operation["stage"],
                    "operation_id": review_operation["operation_id"],
                    "worker_id": review_operation["worker_ref"]["worker_id"],
                }
            ),
            "worker_cleanup_ref": review_cleanup["worker_cleanup_ref"],
            "provider_cleanup_ref": review_cleanup["provider_cleanup_ref"],
        }
    ]
    for index, item in enumerate(incumbent_terminals):
        operation = item["operation_ref"]
        worker = operation["worker_ref"]
        worker_cleanup = deepcopy(item["cleanup_refs"]["worker_cleanup_ref"])
        if index == 0:
            worker_cleanup = runtime_seal_immutable(
                {
                    "contract_version": "benchmark_worker_cleanup_receipt_v1",
                    "outcome": "verified_exact_worker_exited",
                    "operation_anchor_ref": {"content_sha256": "6" * 64},
                    "reservation_ref": deepcopy(worker_cleanup["reservation_ref"]),
                    "supervision_ref": {"content_sha256": "7" * 64},
                    "run_id": operation["run_id"],
                    "stage": operation["stage"],
                    "operation_id": operation["operation_id"],
                    "worker_id": worker["worker_id"],
                    "process_identity": {
                        "pid": 107888,
                        "create_time_ns": 1788238246637361408,
                    },
                    "assignment_proven_ref": {"content_sha256": "8" * 64},
                    "finalization_intent_ref": {"content_sha256": "9" * 64},
                    "exact_handle_observation_refs": {
                        "worker_process": {"content_sha256": "a" * 64},
                        "startup_event": {"content_sha256": "b" * 64},
                        "beacon_file": {"content_sha256": "c" * 64},
                    },
                    "job_absence_observation_ref": {"content_sha256": "d" * 64},
                    "worker_absence_observation_ref": {"content_sha256": "e" * 64},
                    "supervisor_absence_observation_ref": None,
                    "reservation_abort_ref": None,
                    "artifact_is_authorization": False,
                    "execute_binding_enabled": False,
                }
            )
        provider_cleanup = item["cleanup_refs"]["provider_cleanup_ref"]
        terminal_receipt = _sealed(
            {
                "contract_version": "benchmark_v2_incumbent_terminal_receipt_v1",
                "outcome": "benchmark_v2_incumbent_cancelled",
                "run_id": operation["run_id"],
                "stage": operation["stage"],
                "operation_id": operation["operation_id"],
                "worker_id": worker["worker_id"],
                "model_request_id": worker["model_request_id"],
                "payload_sha256": worker["payload_sha256"],
                "result_sha256": None,
                "terminal_intent_ref": None,
                "cancel_intent_ref": {"content_sha256": "f" * 64},
                "generic_adoption_ref": None,
                "window_adoption_ref": None,
                "worker_cleanup_ref": worker_cleanup,
                "provider_cleanup_ref": provider_cleanup,
                "provider_cleanup_outcome": provider_cleanup["outcome"],
                "terminal_at": "2026-09-01T05:00:00+00:00",
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
                "predecessor_content_sha256": operation[
                    "predecessor_content_sha256"
                ],
            }
        )
        assert (
            incumbent.validate_benchmark_v2_incumbent_terminal_receipt(
                terminal_receipt
            )
            == terminal_receipt
        )
        entries.append(
            {
                "operation_ref_sha256": operation["content_sha256"],
                "terminal_receipt_ref": terminal_receipt,
                "worker_cleanup_ref": worker_cleanup,
                "provider_cleanup_ref": provider_cleanup,
            }
        )

    receipt = runtime_seal_immutable(
        {
            "contract_version": "benchmark_v2_actual_operations_stable_zero_v1",
            "operation_refs": operations,
            "cleanup_entries": entries,
            "window_binding_ref": binding["window_binding_ref"],
            "capture_ref": binding["capture_ref"],
            "cleanup_status": "stable_zero",
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )

    assert incumbent.validate_benchmark_v2_actual_operations_stable_zero(receipt) == receipt

    forged = deepcopy(receipt)
    forged["cleanup_entries"][1]["terminal_receipt_ref"]["content_sha256"] = "0" * 64
    forged = runtime_seal_immutable(
        {key: value for key, value in forged.items() if key != "content_sha256"}
    )
    with pytest.raises(ValueError, match="terminal receipt content SHA mismatch"):
        incumbent.validate_benchmark_v2_actual_operations_stable_zero(forged)

    malformed = deepcopy(receipt)
    del malformed["cleanup_entries"][1]["terminal_receipt_ref"]["terminal_at"]
    malformed = runtime_seal_immutable(
        {key: value for key, value in malformed.items() if key != "content_sha256"}
    )
    with pytest.raises(ValueError, match="terminal receipt schema is not closed"):
        incumbent.validate_benchmark_v2_actual_operations_stable_zero(malformed)

    hybrid_discriminator = deepcopy(receipt)
    hybrid_terminal = deepcopy(
        hybrid_discriminator["cleanup_entries"][1]["terminal_receipt_ref"]
    )
    hybrid_terminal.update(
        {
            "run_id": review_operation["run_id"],
            "stage": review_operation["stage"],
            "operation_id": review_operation["operation_id"],
            "worker_id": review_operation["worker_ref"]["worker_id"],
            "model_request_id": review_operation["worker_ref"]["model_request_id"],
            "payload_sha256": review_operation["worker_ref"]["payload_sha256"],
            "predecessor_content_sha256": review_operation[
                "predecessor_content_sha256"
            ],
        }
    )
    hybrid_discriminator["cleanup_entries"][0]["terminal_receipt_ref"] = _sealed(
        {
            key: value
            for key, value in hybrid_terminal.items()
            if key != "content_sha256"
        }
    )
    hybrid_discriminator = runtime_seal_immutable(
        {
            key: value
            for key, value in hybrid_discriminator.items()
            if key != "content_sha256"
        }
    )
    with pytest.raises(ValueError, match="terminal receipt ref content SHA mismatch"):
        incumbent.validate_benchmark_v2_actual_operations_stable_zero(
            hybrid_discriminator
        )

    cross_lineage = deepcopy(receipt)
    terminal = cross_lineage["cleanup_entries"][1]["terminal_receipt_ref"]
    terminal["operation_id"] = "operation-cross-lineage"
    cross_lineage["cleanup_entries"][1]["terminal_receipt_ref"] = _sealed(
        {key: value for key, value in terminal.items() if key != "content_sha256"}
    )
    cross_lineage = runtime_seal_immutable(
        {key: value for key, value in cross_lineage.items() if key != "content_sha256"}
    )
    with pytest.raises(ValueError, match="terminal lineage is stale"):
        incumbent.validate_benchmark_v2_actual_operations_stable_zero(cross_lineage)

    terminal_lineage_mutations = (
        ("model_request_id", "request-cross-lineage"),
        ("payload_sha256", "0" * 64),
        ("predecessor_content_sha256", "1" * 64),
        ("worker_cleanup_ref", receipt["cleanup_entries"][2]["worker_cleanup_ref"]),
        (
            "provider_cleanup_ref",
            receipt["cleanup_entries"][2]["provider_cleanup_ref"],
        ),
        ("provider_cleanup_outcome", "verified_exact_process_exited"),
    )
    for field, value in terminal_lineage_mutations:
        mutated = deepcopy(receipt)
        terminal = mutated["cleanup_entries"][1]["terminal_receipt_ref"]
        terminal[field] = deepcopy(value)
        mutated["cleanup_entries"][1]["terminal_receipt_ref"] = _sealed(
            {key: child for key, child in terminal.items() if key != "content_sha256"}
        )
        mutated = runtime_seal_immutable(
            {key: child for key, child in mutated.items() if key != "content_sha256"}
        )
        with pytest.raises(ValueError, match="terminal .*lineage is stale"):
            incumbent.validate_benchmark_v2_actual_operations_stable_zero(mutated)


@pytest.mark.parametrize(
    ("mode", "status"),
    (
        ("hybrid_v1_1", "complete"),
        ("hybrid_v1_1", "safe_stopped"),
        ("incumbent_qwen_only", "cancelled"),
    ),
)
def test_actual_cleanup_terminal_operation_requires_exact_replay(
    mode: str,
    status: str,
) -> None:
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module

    request_ref = {"id": "terminal-replay-request", "content_sha256": "a" * 64}
    binding = {
        "run_id": "terminal-replay-run",
        "stage": "provider_execution",
        "operation_id": "terminal-replay-operation",
        "window_binding_ref": {
            "id": "terminal-replay-binding",
            "content_sha256": "b" * 64,
        },
        "capture_ref": {
            "id": "terminal-replay-capture",
            "content_sha256": "c" * 64,
        },
    }
    terminal = _actual_operation(
        mode=mode,
        operation_id=str(binding["operation_id"]),
        request_ref=request_ref,
        binding=binding,
        revision=3,
        status=status,
    )
    runtime_module._validate_actual_terminal_successor(
        terminal=deepcopy(terminal),
        supplied=deepcopy(terminal),
    )
    successor = _actual_operation(
        mode=mode,
        operation_id=str(binding["operation_id"]),
        request_ref=request_ref,
        binding=binding,
        revision=4,
        status=status,
        predecessor=terminal,
    )

    with pytest.raises(ValueError, match="terminal replay differs"):
        runtime_module._validate_actual_terminal_successor(
            terminal=successor,
            supplied=terminal,
        )


def _actual_cleanup_projection_case(
    *, mode: str
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    request_ref = {"id": f"{mode}-cleanup-request", "content_sha256": "a" * 64}
    binding = {
        "run_id": f"{mode}-cleanup-run",
        "stage": (
            "screen_understanding"
            if mode == "incumbent_qwen_only"
            else "provider_execution"
        ),
        "operation_id": f"{mode}-cleanup-operation",
        "window_binding_ref": {
            "id": f"{mode}-cleanup-binding",
            "content_sha256": "b" * 64,
        },
        "capture_ref": {
            "id": f"{mode}-cleanup-capture",
            "content_sha256": "c" * 64,
        },
    }
    current = _actual_operation(
        mode=mode,
        operation_id=str(binding["operation_id"]),
        request_ref=request_ref,
        binding=binding,
        revision=8,
        status="advanced",
    )
    return request_ref, binding, current


@pytest.mark.parametrize("current_status", ("advanced", "cleanup_pending"))
def test_actual_incumbent_cleanup_accepts_monotonic_durable_projection(
    current_status: str,
) -> None:
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module

    request_ref, binding, current = _actual_cleanup_projection_case(
        mode="incumbent_qwen_only"
    )
    if current_status == "cleanup_pending":
        current = _actual_operation(
            mode="incumbent_qwen_only",
            operation_id=str(binding["operation_id"]),
            request_ref=request_ref,
            binding=binding,
            revision=8,
            status=current_status,
        )
    returned = _actual_operation(
        mode="incumbent_qwen_only",
        operation_id=str(current["operation_id"]),
        request_ref=request_ref,
        binding=binding,
        status="cancelled",
        revision=11,
        predecessor_content_sha256="d" * 64,
    )

    runtime_module._validate_actual_terminal_successor(
        terminal=returned,
        supplied=current,
    )


def test_actual_incumbent_cleanup_rejects_nonadvancing_durable_projection() -> None:
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module

    request_ref, binding, current = _actual_cleanup_projection_case(
        mode="incumbent_qwen_only"
    )
    returned = _actual_operation(
        mode="incumbent_qwen_only",
        operation_id=str(current["operation_id"]),
        request_ref=request_ref,
        binding=binding,
        status="cancelled",
        revision=8,
        predecessor_content_sha256="d" * 64,
    )

    with pytest.raises(ValueError, match="cleanup successor lineage is stale"):
        runtime_module._validate_actual_terminal_successor(
            terminal=returned,
            supplied=current,
        )


def test_actual_hybrid_cleanup_keeps_strict_public_predecessor_chain() -> None:
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module

    request_ref, binding, current = _actual_cleanup_projection_case(
        mode="hybrid_v1_1"
    )
    returned = _actual_operation(
        mode="hybrid_v1_1",
        operation_id=str(current["operation_id"]),
        request_ref=request_ref,
        binding=binding,
        status="cancelled",
        revision=11,
        predecessor_content_sha256="d" * 64,
    )

    with pytest.raises(ValueError, match="cleanup successor lineage is stale"):
        runtime_module._validate_actual_terminal_successor(
            terminal=returned,
            supplied=current,
        )


def test_legacy_three_field_actual_cleanup_aggregate_remains_valid() -> None:
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module

    service = _ActualService([])
    terminals = []
    for index in range(2):
        binding = incumbent.compose_benchmark_v2_workflow_window_binding(
            run_id=f"legacy-run-{index}",
            operation_id=f"legacy-operation-{index}",
            window_binding_ref={
                "id": f"legacy-window-{index}",
                "content_sha256": f"{index + 1}" * 64,
            },
            capture_ref={
                "id": f"legacy-capture-{index}",
                "content_sha256": f"{index + 3}" * 64,
            },
            owner_journal_ref={"content_sha256": f"{index + 5}" * 64},
            expected_uia_root_ref={"content_sha256": f"{index + 7}" * 64},
        )
        group = {
            "request_ref": {
                "id": f"legacy-request-{index}",
                "content_sha256": "a" * 64,
            }
        }
        step = _actual_service_step(group, binding)
        terminals.append(
            service.cancel_operation(operation_ref=step["operation_ref"])
        )

    runtime_module._validate_actual_operations_cleanup_aggregate(
        {
            "full_group_attestation_refs": [],
            "pre_reservation_recovery_refs": [],
            "partial_workflow_terminal_refs": terminals,
        }
    )


class _ActualService:
    def __init__(
        self,
        events: list[str],
        *,
        authoritative_cleanup: bool = True,
        persist_terminal_lookup: bool = True,
        fabricate_attestation: bool = False,
    ) -> None:
        self.events = events
        self.authoritative_cleanup = authoritative_cleanup
        self.persist_terminal_lookup = persist_terminal_lookup
        self.fabricate_attestation = fabricate_attestation
        self.lookup_calls = 0
        self.start_calls = 0
        self.cancel_calls = 0
        self.stable_zero_calls = 0
        self.stable_zero_operation_counts: list[int] = []
        self.current: dict[str, object] | None = None
        self.started_operation_ref: dict[str, object] | None = None
        self.cancelled_operation_refs: list[dict[str, object]] = []
        self.incumbent_terminals: dict[str, dict[str, object]] = {}
        self.terminal_steps_by_sha: dict[str, dict[str, object]] = {}

    def lookup_hybrid_operation(self, *, screen_group, window_binding):
        self.lookup_calls += 1
        self.events.append("service-lookup")
        return deepcopy(self.current)

    def start_hybrid_operation(self, *, screen_group, window_binding):
        self.start_calls += 1
        self.events.append("service-start")
        self.current = _actual_service_step(screen_group, window_binding)
        self.started_operation_ref = deepcopy(self.current["operation_ref"])
        return deepcopy(self.current)

    def lookup_incumbent_observe(self, *, provider_case_ref, window_binding):
        del window_binding
        return deepcopy(self.incumbent_terminals.get(str(provider_case_ref["case_id"])))

    def attest_actual_operations_stable_zero(self, *, operation_refs):
        self.stable_zero_calls += 1
        self.stable_zero_operation_counts.append(len(operation_refs))
        self.events.append("service-stable-zero")
        if self.fabricate_attestation:
            return _sealed({"kind": "fabricated-stable-zero"})
        if not self.authoritative_cleanup or not self.persist_terminal_lookup:
            raise ValueError("actual operation cleanup is not authoritatively stable-zero")
        if any(
            str(operation["content_sha256"]) not in self.terminal_steps_by_sha
            for operation in operation_refs
        ):
            raise ValueError("actual operation stable-zero lineage is stale")
        steps = [
            deepcopy(self.terminal_steps_by_sha[str(operation["content_sha256"])])
            for operation in operation_refs
        ]
        cleanup_entries = []
        for step in steps:
            operation = step["operation_ref"]
            worker_cleanup = deepcopy(step["cleanup_refs"]["worker_cleanup_ref"])
            provider_cleanup = deepcopy(
                step["cleanup_refs"]["provider_cleanup_ref"]
            )
            terminal_receipt = (
                _actual_incumbent_cancelled_terminal_receipt(
                    operation=operation,
                    worker_cleanup_ref=worker_cleanup,
                    provider_cleanup_ref=provider_cleanup,
                )
                if operation["mode"] == "incumbent_qwen_only"
                else _sealed(
                    {
                        "run_id": operation["run_id"],
                        "stage": operation["stage"],
                        "operation_id": operation["operation_id"],
                        "worker_id": operation["worker_ref"]["worker_id"],
                    }
                )
            )
            cleanup_entries.append(
                {
                    "operation_ref_sha256": operation["content_sha256"],
                    "terminal_receipt_ref": terminal_receipt,
                    "worker_cleanup_ref": worker_cleanup,
                    "provider_cleanup_ref": provider_cleanup,
                }
            )
        return _sealed(
            {
                "contract_version": "benchmark_v2_actual_operations_stable_zero_v1",
                "operation_refs": deepcopy(operation_refs),
                "cleanup_entries": cleanup_entries,
                "window_binding_ref": deepcopy(operation_refs[0]["window_binding_ref"]),
                "capture_ref": deepcopy(operation_refs[0]["capture_ref"]),
                "cleanup_status": "stable_zero",
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            }
        )

    def cancel_operation(self, *, operation_ref):
        self.cancel_calls += 1
        self.cancelled_operation_refs.append(deepcopy(dict(operation_ref)))
        if operation_ref["status"] in {"complete", "cancelled", "safe_stopped"}:
            terminal_operation = deepcopy(dict(operation_ref))
        else:
            terminal_operation = _actual_operation(
                mode=str(operation_ref["mode"]),
                operation_id=str(operation_ref["operation_id"]),
                request_ref=operation_ref["request_ref"],
                binding={
                    "run_id": operation_ref["run_id"],
                    "stage": operation_ref["stage"],
                    "operation_id": operation_ref["operation_id"],
                    "window_binding_ref": operation_ref["window_binding_ref"],
                    "capture_ref": operation_ref["capture_ref"],
                },
                revision=int(operation_ref["workflow_state_ref"]["revision"]) + 1,
                status=(
                    "safe_stopped"
                    if str(operation_ref["mode"]) == "hybrid_v1_1"
                    else "cancelled"
                ),
                predecessor=operation_ref,
            )
        if self.authoritative_cleanup:
            worker = terminal_operation["worker_ref"]
            reservation_ref = {
                "content_sha256": hashlib.sha256(
                    f"reservation:{terminal_operation['operation_id']}".encode("utf-8")
                ).hexdigest()
            }
            if terminal_operation["mode"] == "hybrid_v1_1":
                worker_cleanup = _sealed(
                    {
                        "contract_version": "benchmark_v2_hybrid_worker_cleanup_ref_v1",
                        "run_id": terminal_operation["run_id"],
                        "stage": terminal_operation["stage"],
                        "operation_id": terminal_operation["operation_id"],
                        "worker_id": worker["worker_id"],
                        "model_request_id": worker["model_request_id"],
                        "payload_sha256": worker["payload_sha256"],
                        "backend_compute_termination": "terminated",
                        "model_service_compute_termination": "terminated",
                        "cancellation_ref": {"content_sha256": "c" * 64},
                        "artifact_is_authorization": False,
                        "execute_binding_enabled": False,
                    }
                )
            else:
                worker_cleanup = _sealed(
                    {
                        "contract_version": "benchmark_worker_cleanup_receipt_v1",
                        "outcome": "verified_not_launched",
                        "operation_anchor_ref": {"content_sha256": "6" * 64},
                        "run_id": terminal_operation["run_id"],
                        "stage": terminal_operation["stage"],
                        "operation_id": terminal_operation["operation_id"],
                        "worker_id": worker["worker_id"],
                        "reservation_ref": reservation_ref,
                        "supervision_ref": None,
                        "process_identity": None,
                        "assignment_proven_ref": None,
                        "finalization_intent_ref": None,
                        "exact_handle_observation_refs": None,
                        "job_absence_observation_ref": None,
                        "worker_absence_observation_ref": None,
                        "supervisor_absence_observation_ref": None,
                        "reservation_abort_ref": {"content_sha256": "d" * 64},
                        "artifact_is_authorization": False,
                        "execute_binding_enabled": False,
                    }
                )
            provider_cleanup = _sealed(
                {
                    "contract_version": "benchmark_provider_cleanup_ref_v1",
                    "status": "cleanup_verified",
                    "outcome": "verified_not_acquired",
                    "authority_kind": "benchmark_v2_workflow_service_dispatch_cleanup",
                    "run_id": terminal_operation["run_id"],
                    "stage": terminal_operation["stage"],
                    "operation_id": terminal_operation["operation_id"],
                    "worker_id": worker["worker_id"],
                    "model_request_id": worker["model_request_id"],
                    "payload_sha256": worker["payload_sha256"],
                    "reservation_ref": reservation_ref,
                    "acquisition_owner_ref": {"content_sha256": "2" * 64},
                    "acquisition_intent_ref": {"content_sha256": "3" * 64},
                    "runtime_owner_ref": {"content_sha256": "4" * 64},
                    "cleanup_receipt_ref": {"content_sha256": "5" * 64},
                }
            )
        else:
            worker_cleanup = _sealed(
                {"kind": "worker-cleanup", "operation_id": operation_ref["operation_id"]}
            )
            provider_cleanup = _sealed(
                {"kind": "provider-cleanup", "operation_id": operation_ref["operation_id"]}
            )
        cleanup = {
            "worker_cleanup_ref": worker_cleanup,
            "provider_cleanup_ref": provider_cleanup,
        }
        result = _sealed(
            {
                "status": terminal_operation["status"],
                "operation_ref": terminal_operation,
                "provider_dispatch_context_projection": None,
                "cleanup_refs": cleanup,
            }
        )
        if self.persist_terminal_lookup:
            step = incumbent.compose_benchmark_v2_workflow_service_step(
                operation_ref=terminal_operation,
                observed_task_kind=(
                    "server-managed-hybrid-cleanup"
                    if terminal_operation["mode"] == "hybrid_v1_1"
                    else "vision_observe_screen"
                ),
                adopted_result_projection=None,
                terminal_receipt=None,
                cleanup_refs=cleanup,
            )
            if terminal_operation["mode"] == "hybrid_v1_1":
                self.current = step
            else:
                case_id = str(terminal_operation["operation_id"]).removeprefix(
                    "incumbent-"
                )
                self.incumbent_terminals[case_id] = step
            self.terminal_steps_by_sha[
                str(terminal_operation["content_sha256"])
            ] = deepcopy(step)
        return result


class _DurableIncumbentService(_ActualService):
    def __init__(
        self, events: list[str], *, lost_response_kind: str | None = None
    ) -> None:
        super().__init__(events)
        self.lost_response_kind = lost_response_kind
        self.incumbent_lookup_calls = 0
        self.incumbent_start_calls = 0
        self.incumbent_poll_calls = 0
        self.incumbent_adopt_calls = 0
        self.incumbent_current: dict[str, dict[str, object]] = {}
        self.hybrid_steps: dict[str, dict[str, object]] = {}

    def start_hybrid_operation(self, *, screen_group, window_binding):
        step = super().start_hybrid_operation(
            screen_group=screen_group,
            window_binding=window_binding,
        )
        self.hybrid_steps[str(screen_group["request_ref"]["content_sha256"])] = deepcopy(
            step
        )
        return step

    def lookup_hybrid_operation(self, *, screen_group, window_binding):
        del window_binding
        self.lookup_calls += 1
        return deepcopy(
            self.hybrid_steps.get(str(screen_group["request_ref"]["content_sha256"]))
        )

    def cancel_operation(self, *, operation_ref):
        result = super().cancel_operation(operation_ref=operation_ref)
        if operation_ref["mode"] == "hybrid_v1_1":
            self.hybrid_steps[
                str(operation_ref["request_ref"]["content_sha256"])
            ] = deepcopy(self.current)
        return result

    def _step(
        self,
        *,
        provider_case_ref: Mapping[str, object],
        status: str,
        predecessor: Mapping[str, object] | None,
    ) -> dict[str, object]:
        case_id = str(provider_case_ref["case_id"])
        assert self.current_binding is not None
        child_binding = {
            **self.current_binding,
            "run_id": f"incumbent-run-{case_id}",
            "operation_id": f"incumbent-{case_id}",
        }
        revision = 1 if predecessor is None else int(
            predecessor["workflow_state_ref"]["revision"]
        ) + 1
        operation = _actual_operation(
            mode="incumbent_qwen_only",
            operation_id=f"incumbent-{case_id}",
            request_ref={
                "id": case_id,
                "content_sha256": str(provider_case_ref["case_content_sha256"]),
            },
            binding=child_binding,
            revision=revision,
            status=status,
            predecessor=predecessor,
        )
        return incumbent.compose_benchmark_v2_workflow_service_step(
            operation_ref=operation,
            observed_task_kind="vision_observe_screen",
            adopted_result_projection=None,
            terminal_receipt=None,
            cleanup_refs={"worker_cleanup_ref": None, "provider_cleanup_ref": None},
        )

    current_binding: dict[str, object] | None = None

    def lookup_incumbent_observe(self, *, provider_case_ref, window_binding):
        self.incumbent_lookup_calls += 1
        self.current_binding = deepcopy(dict(window_binding))
        case_id = str(provider_case_ref["case_id"])
        if case_id in self.incumbent_terminals:
            return deepcopy(self.incumbent_terminals[case_id])
        return deepcopy(self.incumbent_current.get(case_id))

    def start_incumbent_observe(self, *, provider_case_ref, window_binding):
        self.incumbent_start_calls += 1
        self.current_binding = deepcopy(dict(window_binding))
        case_id = str(provider_case_ref["case_id"])
        step = self._step(
            provider_case_ref=provider_case_ref,
            status="pending",
            predecessor=None,
        )
        self.incumbent_current[case_id] = deepcopy(step)
        if self.lost_response_kind == "start":
            raise ConnectionError("incumbent start response lost")
        return step

    def poll_incumbent_observe(self, *, operation_ref):
        self.incumbent_poll_calls += 1
        case_id = str(operation_ref["request_ref"]["id"])
        case_ref = {
            "case_id": case_id,
            "case_content_sha256": operation_ref["request_ref"]["content_sha256"],
        }
        step = self._step(
            provider_case_ref=case_ref,
            status="advanced",
            predecessor=operation_ref,
        )
        self.incumbent_current[case_id] = deepcopy(step)
        if self.lost_response_kind == "poll":
            raise ConnectionError("incumbent poll response lost")
        return step

    def adopt_and_terminalize_incumbent(self, *, operation_ref, worker_ref):
        assert dict(worker_ref) == operation_ref["worker_ref"]
        self.incumbent_adopt_calls += 1
        case_id = str(operation_ref["request_ref"]["id"])
        case_ref = {
            "case_id": case_id,
            "case_content_sha256": operation_ref["request_ref"]["content_sha256"],
        }
        step = self._step(
            provider_case_ref=case_ref,
            status="complete",
            predecessor=operation_ref,
        )
        self.incumbent_current[case_id] = deepcopy(step)
        if self.lost_response_kind == "adopt":
            raise ConnectionError("incumbent adopt response lost")
        return step


def _actual_adapter(
    events: list[str],
    calls: list[dict[str, object]],
    *,
    fabricate_window_close: bool = False,
):
    def run_screen_group(*, provider_group, service, window_owner, lifecycle, prediction_sink):
        calls.append(
            {
                "provider_group": deepcopy(dict(provider_group)),
                "service": service,
                "window_owner": window_owner,
                "lifecycle": lifecycle,
                "prediction_sink": prediction_sink,
            }
        )
        events.append("adapter")
        binding = window_owner.open_screen_group(provider_group=provider_group)
        hybrid = service.start_hybrid_operation(
            screen_group=provider_group,
            window_binding=binding,
        )["operation_ref"]
        operations = [hybrid]
        for index, case_ref in enumerate(provider_group["case_refs"], 2):
            incumbent_binding = {
                **binding,
                "run_id": f"incumbent-run-{case_ref['case_id']}",
                "operation_id": f"incumbent-{case_ref['case_id']}",
            }
            operations.append(
                _actual_operation(
                    mode="incumbent_qwen_only",
                    operation_id=f"incumbent-{case_ref['case_id']}",
                    request_ref={
                        "id": str(case_ref["case_id"]),
                        "content_sha256": str(case_ref["case_content_sha256"]),
                    },
                    binding=incumbent_binding,
                    revision=index,
                )
            )
        for operation in operations:
            service.cancel_operation(operation_ref=operation)
        close_ref = (
            _sealed({"kind": "fabricated-window-close"})
            if fabricate_window_close
            else window_owner.close_screen_group(
                window_binding=binding,
                reason="benchmark_v2_screen_group_finished",
            )
        )
        execution_refs = [
            {
                "id": f"{operation['mode']}/{operation['operation_id']}",
                "content_sha256": str(operation["content_sha256"]),
            }
            for operation in operations
        ]
        lifecycle_ref = lifecycle.stable_zero(
            provider_group=provider_group,
            window_binding=binding,
            execution_refs=execution_refs,
            window_close_ref=close_ref,
        )
        provider_sets = {
            "qwen_only": ("qwen",),
            "omni_only_discovery": ("omni",),
            "omni_to_qwen": ("omni", "qwen"),
            "omni_to_qwen_vista": ("omni", "qwen", "vista"),
        }
        rows = []
        for case_ref in provider_group["case_refs"]:
            for arm_id, providers in provider_sets.items():
                rows.append(
                    {
                        "case_ref": deepcopy(case_ref),
                        "arm_id": arm_id,
                        "observation": {
                            "provider_dispatch_receipt_refs": [
                                {
                                    "provider": provider,
                                    "content_sha256": hashlib.sha256(
                                        f"{case_ref['case_id']}:{arm_id}:{provider}".encode()
                                    ).hexdigest(),
                                }
                                for provider in providers
                            ]
                        },
                    }
                )
        projection = _sealed(
            {
                "contract_version": "benchmark_v2_actual_screen_group_projection_v1",
                "partition": provider_group["partition"],
                "screen_group": provider_group["screen_group"],
                "request_ref": deepcopy(provider_group["request_ref"]),
                "pre_vista_evidence": _pre_vista_evidence(provider_group),
                "rows": rows,
                "execution_refs": execution_refs,
                "window_close_ref": deepcopy(close_ref),
                "lifecycle_ref": deepcopy(lifecycle_ref),
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            }
        )
        events.append("sink")
        prediction_sink.write_screen_group(projection=projection)
        events.append("adapter-return")
        return projection

    return run_screen_group


def test_production_runtime_public_surface_is_closed_and_singleton_stable() -> None:
    from app.learn.hybrid.benchmark_v2_runtime import (
        BenchmarkV2ProductionRuntimePort,
        get_production_benchmark_v2_runtime,
    )

    assert get_production_benchmark_v2_runtime() is get_production_benchmark_v2_runtime()
    assert list(inspect.signature(BenchmarkV2ProductionRuntimePort.load_provider_manifest).parameters) == [
        "self",
        "path",
    ]
    assert list(inspect.signature(BenchmarkV2ProductionRuntimePort.prepare_screen_groups).parameters) == [
        "self",
        "provider_manifest",
        "partition",
        "attempt_ref",
        "attempt_dir",
    ]
    assert list(inspect.signature(BenchmarkV2ProductionRuntimePort.run_actual_screen_group).parameters) == [
        "self",
        "provider_group",
        "attempt_ref",
        "attempt_dir",
    ]
    runtime = get_production_benchmark_v2_runtime()
    assert not hasattr(runtime, "composition")
    assert not hasattr(runtime, "store")
    assert not hasattr(runtime, "worker_registry")
    for internal in (
        "service",
        "window_owner",
        "lifecycle",
        "prediction_sink",
        "registry",
        "components",
    ):
        assert not hasattr(runtime, internal)


def test_actual_facade_runs_task8_once_with_lookup_journals_cleanup_and_durable_sink(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_module, runtime, manifest, _, windows, _ = _runtime(monkeypatch, tmp_path)
    attempt_ref = _sealed({"attempt_id": "attempt-actual"})
    attempt_dir = (tmp_path / "attempt-actual").resolve()
    iterator = runtime.prepare_screen_groups(
        provider_manifest=manifest,
        partition="regression",
        attempt_ref=attempt_ref,
        attempt_dir=attempt_dir,
    )
    group = next(iterator)
    events: list[str] = []
    calls: list[dict[str, object]] = []
    service = _ActualService(events)
    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        lambda: service,
    )
    monkeypatch.setattr(
        runtime_module.benchmark_v2_actual,
        "run_screen_group",
        _actual_adapter(events, calls),
    )

    result = runtime.run_actual_screen_group(
        provider_group=group,
        attempt_ref=attempt_ref,
        attempt_dir=attempt_dir,
    )

    assert len(calls) == 1
    assert calls[0]["provider_group"] == group
    assert calls[0]["window_owner"] is not runtime
    assert service.lookup_calls == 2
    assert service.start_calls == 1
    assert service.cancel_calls == 6
    assert service.stable_zero_calls == 1
    assert events.index("service-lookup") < events.index("service-start")
    assert events.index("service-stable-zero") < events.index("sink")
    assert events[-1] == "adapter-return"
    assert windows.active == 0
    assert runtime.resource_counts() == {
        "service_operations": 0,
        "windows": 0,
        "providers": 0,
        "listeners": 0,
        "leases": 0,
    }
    assert result["content_sha256"] == content_sha256(result)
    records = list((attempt_dir / "actual-screen-groups").glob("*.projection.json"))
    assert len(records) == 1
    record = json.loads(records[0].read_text(encoding="utf-8"))
    assert record["projection"] == result
    assert record["provider_group_ref"] == {
        "id": group["screen_group"],
        "content_sha256": group["content_sha256"],
    }
    assert list((attempt_dir / "actual-screen-groups").glob("*.service-intent.json"))
    assert list((attempt_dir / "actual-screen-groups").glob("*.service-result.json"))
    iterator.close()


def test_actual_facade_identical_replay_is_idempotent_and_changed_group_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_module, runtime, manifest, _, _, _ = _runtime(monkeypatch, tmp_path)
    attempt_ref = _sealed({"attempt_id": "attempt-actual-replay"})
    attempt_dir = (tmp_path / "attempt-actual-replay").resolve()
    iterator = runtime.prepare_screen_groups(
        provider_manifest=manifest,
        partition="regression",
        attempt_ref=attempt_ref,
        attempt_dir=attempt_dir,
    )
    group = next(iterator)
    events: list[str] = []
    calls: list[dict[str, object]] = []
    service = _ActualService(events)
    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        lambda: service,
    )
    monkeypatch.setattr(
        runtime_module.benchmark_v2_actual,
        "run_screen_group",
        _actual_adapter(events, calls),
    )
    first = runtime.run_actual_screen_group(
        provider_group=group,
        attempt_ref=attempt_ref,
        attempt_dir=attempt_dir,
    )

    replay = runtime.run_actual_screen_group(
        provider_group=group,
        attempt_ref=attempt_ref,
        attempt_dir=attempt_dir,
    )
    changed = deepcopy(group)
    changed["capture_image_path"] = "artifacts/screenshots/different.png"
    changed["content_sha256"] = content_sha256(changed)
    with pytest.raises(ValueError, match="different-content|replay"):
        runtime.run_actual_screen_group(
            provider_group=changed,
            attempt_ref=attempt_ref,
            attempt_dir=attempt_dir,
        )

    assert replay == first
    assert len(calls) == 1
    assert service.start_calls == 1
    iterator.close()


def test_actual_facade_rejects_legacy_replay_without_pre_vista_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_module, runtime, manifest, _, _, _ = _runtime(monkeypatch, tmp_path)
    attempt_ref = _sealed({"attempt_id": "attempt-legacy-projection"})
    attempt_dir = (tmp_path / "attempt-legacy-projection").resolve()
    iterator = runtime.prepare_screen_groups(
        provider_manifest=manifest,
        partition="regression",
        attempt_ref=attempt_ref,
        attempt_dir=attempt_dir,
    )
    group = next(iterator)
    calls: list[dict[str, object]] = []
    service = _ActualService([])
    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        lambda: service,
    )
    monkeypatch.setattr(
        runtime_module.benchmark_v2_actual,
        "run_screen_group",
        _actual_adapter([], calls),
    )
    runtime.run_actual_screen_group(
        provider_group=group,
        attempt_ref=attempt_ref,
        attempt_dir=attempt_dir,
    )
    path = next((attempt_dir / "actual-screen-groups").glob("*.projection.json"))
    record = json.loads(path.read_text(encoding="utf-8"))
    record["projection"].pop("pre_vista_evidence")
    record["projection"]["content_sha256"] = content_sha256(record["projection"])
    record["content_sha256"] = content_sha256(record)
    path.write_bytes(canonical_json_bytes(record, pretty=True))

    with pytest.raises(ValueError, match="pre-VISTA evidence"):
        runtime.run_actual_screen_group(
            provider_group=group,
            attempt_ref=attempt_ref,
            attempt_dir=attempt_dir,
        )

    assert len(calls) == 1
    iterator.close()


def test_actual_facade_rejects_stale_attempt_before_task8_or_service(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_module, runtime, manifest, _, _, _ = _runtime(monkeypatch, tmp_path)
    attempt_ref = _sealed({"attempt_id": "attempt-actual-stale"})
    attempt_dir = (tmp_path / "attempt-actual-stale").resolve()
    iterator = runtime.prepare_screen_groups(
        provider_manifest=manifest,
        partition="regression",
        attempt_ref=attempt_ref,
        attempt_dir=attempt_dir,
    )
    group = next(iterator)
    calls: list[dict[str, object]] = []
    service = _ActualService([])
    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        lambda: service,
    )
    monkeypatch.setattr(
        runtime_module.benchmark_v2_actual,
        "run_screen_group",
        _actual_adapter([], calls),
    )

    with pytest.raises(ValueError, match="attempt"):
        runtime.run_actual_screen_group(
            provider_group=group,
            attempt_ref=_sealed({"attempt_id": "other-attempt"}),
            attempt_dir=attempt_dir,
        )

    assert calls == []
    assert service.lookup_calls == 0
    assert service.start_calls == 0
    iterator.close()


def test_actual_facade_intent_fsync_failure_prevents_task8_and_service_start(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_module, runtime, manifest, _, windows, _ = _runtime(monkeypatch, tmp_path)
    attempt_ref = _sealed({"attempt_id": "attempt-actual-fsync"})
    attempt_dir = (tmp_path / "attempt-actual-fsync").resolve()
    iterator = runtime.prepare_screen_groups(
        provider_manifest=manifest,
        partition="regression",
        attempt_ref=attempt_ref,
        attempt_dir=attempt_dir,
    )
    group = next(iterator)
    calls: list[dict[str, object]] = []
    service = _ActualService([])
    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        lambda: service,
    )
    monkeypatch.setattr(
        runtime_module.benchmark_v2_actual,
        "run_screen_group",
        _actual_adapter([], calls),
    )

    with monkeypatch.context() as failure:
        failure.setattr(runtime_module.os, "fsync", lambda _descriptor: (_ for _ in ()).throw(OSError("fsync failed")))
        with pytest.raises(OSError, match="fsync failed"):
            runtime.run_actual_screen_group(
                provider_group=group,
                attempt_ref=attempt_ref,
                attempt_dir=attempt_dir,
            )

    assert calls == []
    assert service.lookup_calls == 0
    assert service.start_calls == 0
    assert windows.active == 1
    iterator.close()
    assert windows.active == 0


def test_actual_facade_rejects_missing_dispatch_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_module, runtime, manifest, _, windows, _ = _runtime(monkeypatch, tmp_path)
    attempt_ref = _sealed({"attempt_id": "attempt-actual-evidence"})
    attempt_dir = (tmp_path / "attempt-actual-evidence").resolve()
    iterator = runtime.prepare_screen_groups(
        provider_manifest=manifest,
        partition="regression",
        attempt_ref=attempt_ref,
        attempt_dir=attempt_dir,
    )
    group = next(iterator)
    service = _ActualService([])
    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        lambda: service,
    )
    valid = _actual_adapter([], [])

    def missing_dispatch(**kwargs):
        sink = kwargs["prediction_sink"]

        class CorruptingSink:
            def write_screen_group(self, *, projection):
                changed = deepcopy(dict(projection))
                for row in changed["rows"]:
                    row["observation"]["provider_dispatch_receipt_refs"] = []
                changed["content_sha256"] = content_sha256(changed)
                return sink.write_screen_group(projection=changed)

        return valid(**{**kwargs, "prediction_sink": CorruptingSink()})

    monkeypatch.setattr(
        runtime_module.benchmark_v2_actual,
        "run_screen_group",
        missing_dispatch,
    )
    with pytest.raises(ValueError, match="dispatch evidence"):
        runtime.run_actual_screen_group(
            provider_group=group,
            attempt_ref=attempt_ref,
            attempt_dir=attempt_dir,
        )

    assert not list((attempt_dir / "actual-screen-groups").glob("*.projection.json"))
    iterator.close()
    assert windows.active == 0


@pytest.mark.parametrize(
    "corruption",
    (
        "missing",
        "extra",
        "stale_group",
        "self_hash",
        "envelope_extra",
        "wrong_class_ref",
        "noncanonical_bytes",
        "invalid_base64",
        "absolute_path",
        "unsorted_requests",
        "incomplete_requests",
        "unsafe",
    ),
)
def test_actual_facade_rejects_invalid_pre_vista_evidence_before_persistence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    corruption: str,
) -> None:
    runtime_module, runtime, manifest, _, windows, _ = _runtime(monkeypatch, tmp_path)
    attempt_ref = _sealed({"attempt_id": f"attempt-pre-vista-{corruption}"})
    attempt_dir = (tmp_path / str(attempt_ref["attempt_id"])).resolve()
    iterator = runtime.prepare_screen_groups(
        provider_manifest=manifest,
        partition="regression",
        attempt_ref=attempt_ref,
        attempt_dir=attempt_dir,
    )
    group = next(iterator)
    service = _ActualService([])
    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        lambda: service,
    )
    valid = _actual_adapter([], [])

    def corrupting_adapter(**kwargs):
        sink = kwargs["prediction_sink"]
        written: list[dict[str, object]] = []

        class CorruptingSink:
            def write_screen_group(self, *, projection):
                changed = deepcopy(dict(projection))
                if corruption == "missing":
                    changed.pop("pre_vista_evidence")
                else:
                    evidence = deepcopy(changed["pre_vista_evidence"])
                    if corruption == "extra":
                        evidence["unexpected"] = True
                    elif corruption == "stale_group":
                        evidence["provider_group_ref"]["id"] = "stale-group"
                    elif corruption == "self_hash":
                        evidence["content_sha256"] = "0" * 64
                    elif corruption == "envelope_extra":
                        evidence["omni_inventory_envelope"]["unexpected"] = True
                    elif corruption == "wrong_class_ref":
                        evidence["omni_inventory_envelope"]["ref"]["id"] = (
                            "qwen-bindings/" + "0" * 64
                        )
                    elif corruption == "noncanonical_bytes":
                        raw = base64.b64decode(
                            evidence["omni_inventory_envelope"]["canonical_bytes_b64"]
                        )
                        noncanonical = b" " + raw
                        evidence["omni_inventory_envelope"] = {
                            "ref": {
                                "id": "omni-inventory/"
                                + hashlib.sha256(
                                    b"benchmark-v2-omni-inventory\0" + noncanonical
                                ).hexdigest(),
                                "content_sha256": hashlib.sha256(noncanonical).hexdigest(),
                            },
                            "canonical_bytes_b64": base64.b64encode(noncanonical).decode(
                                "ascii"
                            ),
                        }
                    elif corruption == "invalid_base64":
                        evidence["omni_inventory_envelope"]["canonical_bytes_b64"] = "%%%"
                    elif corruption == "absolute_path":
                        evidence["omni_inventory_envelope"] = _raw_evidence_envelope(
                            {"capture_path": "C:\\private\\capture.png"},
                            id_prefix="omni-inventory",
                            domain=b"benchmark-v2-omni-inventory\0",
                        )
                    elif corruption == "unsorted_requests":
                        evidence["submitted_vista_request_envelopes"].reverse()
                    elif corruption == "incomplete_requests":
                        evidence["submitted_vista_request_envelopes"].pop()
                    elif corruption == "unsafe":
                        evidence["safety"]["execute_binding_enabled"] = True
                    if corruption != "self_hash":
                        evidence["content_sha256"] = content_sha256(evidence)
                    changed["pre_vista_evidence"] = evidence
                changed["content_sha256"] = content_sha256(changed)
                written.append(deepcopy(changed))
                return sink.write_screen_group(projection=changed)

        valid(**{**kwargs, "prediction_sink": CorruptingSink()})
        return written[0]

    monkeypatch.setattr(
        runtime_module.benchmark_v2_actual,
        "run_screen_group",
        corrupting_adapter,
    )

    with pytest.raises(ValueError, match="pre-VISTA|evidence|canonical|path|lineage"):
        runtime.run_actual_screen_group(
            provider_group=group,
            attempt_ref=attempt_ref,
            attempt_dir=attempt_dir,
        )

    assert not list((attempt_dir / "actual-screen-groups").glob("*.projection.json"))
    iterator.close()
    assert windows.active == 0


def test_actual_facade_recovers_service_start_by_lookup_without_blind_restart(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_module, runtime, manifest, _, windows, _ = _runtime(monkeypatch, tmp_path)
    attempt_ref = _sealed({"attempt_id": "attempt-actual-recovery"})
    attempt_dir = (tmp_path / "attempt-actual-recovery").resolve()
    iterator = runtime.prepare_screen_groups(
        provider_manifest=manifest,
        partition="regression",
        attempt_ref=attempt_ref,
        attempt_dir=attempt_dir,
    )
    group = next(iterator)
    events: list[str] = []
    service = _ActualService(events)
    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        lambda: service,
    )

    def interrupted(*, provider_group, service, window_owner, lifecycle, prediction_sink):
        del lifecycle, prediction_sink
        binding = window_owner.open_screen_group(provider_group=provider_group)
        service.start_hybrid_operation(
            screen_group=provider_group,
            window_binding=binding,
        )
        raise RuntimeError("simulated host interruption after durable service result")

    monkeypatch.setattr(
        runtime_module.benchmark_v2_actual,
        "run_screen_group",
        interrupted,
    )
    with pytest.raises(RuntimeError, match="simulated host interruption"):
        runtime.run_actual_screen_group(
            provider_group=group,
            attempt_ref=attempt_ref,
            attempt_dir=attempt_dir,
        )
    assert windows.active == 1
    assert service.lookup_calls == 1
    assert service.start_calls == 1

    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        runtime_module.benchmark_v2_actual,
        "run_screen_group",
        _actual_adapter(events, calls),
    )
    result = runtime.run_actual_screen_group(
        provider_group=group,
        attempt_ref=attempt_ref,
        attempt_dir=attempt_dir,
    )

    assert result["content_sha256"] == content_sha256(result)
    assert service.lookup_calls == 3
    assert service.start_calls == 1
    assert len(calls) == 1
    assert windows.active == 0
    iterator.close()


def test_actual_facade_rejects_sink_before_stable_zero(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_module, runtime, manifest, _, windows, _ = _runtime(monkeypatch, tmp_path)
    attempt_ref = _sealed({"attempt_id": "attempt-actual-no-zero"})
    attempt_dir = (tmp_path / "attempt-actual-no-zero").resolve()
    iterator = runtime.prepare_screen_groups(
        provider_manifest=manifest,
        partition="regression",
        attempt_ref=attempt_ref,
        attempt_dir=attempt_dir,
    )
    group = next(iterator)
    service = _ActualService([])
    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        lambda: service,
    )

    def skips_zero(*, provider_group, service, window_owner, lifecycle, prediction_sink):
        del service, lifecycle
        binding = window_owner.open_screen_group(provider_group=provider_group)
        close_ref = window_owner.close_screen_group(
            window_binding=binding,
            reason="benchmark_v2_screen_group_finished",
        )
        prediction_sink.write_screen_group(
            projection=_sealed(
                {
                    "contract_version": "benchmark_v2_actual_screen_group_projection_v1",
                    "partition": provider_group["partition"],
                    "screen_group": provider_group["screen_group"],
                    "request_ref": provider_group["request_ref"],
                    "rows": [],
                    "execution_refs": [],
                    "window_close_ref": close_ref,
                    "lifecycle_ref": _sealed({"kind": "fabricated-zero"}),
                    "artifact_is_authorization": False,
                    "execute_binding_enabled": False,
                }
            )
        )

    monkeypatch.setattr(
        runtime_module.benchmark_v2_actual,
        "run_screen_group",
        skips_zero,
    )
    with pytest.raises(ValueError, match="stable-zero evidence is missing"):
        runtime.run_actual_screen_group(
            provider_group=group,
            attempt_ref=attempt_ref,
            attempt_dir=attempt_dir,
        )

    assert windows.active == 0
    assert not list((attempt_dir / "actual-screen-groups").glob("*.projection.json"))
    iterator.close()


def test_actual_facade_rejects_window_close_not_issued_by_exact_runtime_owner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_module, runtime, manifest, _, windows, _ = _runtime(monkeypatch, tmp_path)
    attempt_ref = _sealed({"attempt_id": "attempt-actual-fake-window-close"})
    attempt_dir = (tmp_path / "attempt-actual-fake-window-close").resolve()
    iterator = runtime.prepare_screen_groups(
        provider_manifest=manifest,
        partition="regression",
        attempt_ref=attempt_ref,
        attempt_dir=attempt_dir,
    )
    group = next(iterator)
    service = _ActualService([])
    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        lambda: service,
    )
    monkeypatch.setattr(
        runtime_module.benchmark_v2_actual,
        "run_screen_group",
        _actual_adapter([], [], fabricate_window_close=True),
    )

    with pytest.raises(ValueError, match="exact runtime owner"):
        runtime.run_actual_screen_group(
            provider_group=group,
            attempt_ref=attempt_ref,
            attempt_dir=attempt_dir,
        )

    assert windows.active == 1
    assert not list((attempt_dir / "actual-screen-groups").glob("*.projection.json"))
    iterator.close()
    assert windows.active == 0


def test_actual_facade_rejects_sealed_but_non_authoritative_cleanup_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_module, runtime, manifest, _, windows, _ = _runtime(monkeypatch, tmp_path)
    attempt_ref = _sealed({"attempt_id": "attempt-actual-fake-cleanup"})
    attempt_dir = (tmp_path / "attempt-actual-fake-cleanup").resolve()
    iterator = runtime.prepare_screen_groups(
        provider_manifest=manifest,
        partition="regression",
        attempt_ref=attempt_ref,
        attempt_dir=attempt_dir,
    )
    group = next(iterator)
    service = _ActualService([], authoritative_cleanup=False)
    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        lambda: service,
    )
    monkeypatch.setattr(
        runtime_module.benchmark_v2_actual,
        "run_screen_group",
        _actual_adapter([], []),
    )

    with pytest.raises(ValueError, match="authoritative|cleanup"):
        runtime.run_actual_screen_group(
            provider_group=group,
            attempt_ref=attempt_ref,
            attempt_dir=attempt_dir,
        )

    assert not list((attempt_dir / "actual-screen-groups").glob("*.projection.json"))
    iterator.close()
    assert windows.active == 0


def test_actual_facade_rejects_fabricated_service_stable_zero_attestation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_module, runtime, manifest, _, windows, _ = _runtime(monkeypatch, tmp_path)
    attempt_ref = _sealed({"attempt_id": "attempt-actual-fake-attestation"})
    attempt_dir = (tmp_path / "attempt-actual-fake-attestation").resolve()
    iterator = runtime.prepare_screen_groups(
        provider_manifest=manifest,
        partition="regression",
        attempt_ref=attempt_ref,
        attempt_dir=attempt_dir,
    )
    group = next(iterator)
    service = _ActualService([], fabricate_attestation=True)
    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        lambda: service,
    )
    monkeypatch.setattr(
        runtime_module.benchmark_v2_actual,
        "run_screen_group",
        _actual_adapter([], []),
    )

    with pytest.raises(ValueError, match="stable-zero|attestation"):
        runtime.run_actual_screen_group(
            provider_group=group,
            attempt_ref=attempt_ref,
            attempt_dir=attempt_dir,
        )

    assert not list((attempt_dir / "actual-screen-groups").glob("*.projection.json"))
    iterator.close()
    assert windows.active == 0


def test_actual_facade_rejects_cleanup_not_confirmed_by_exact_service_lookup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_module, runtime, manifest, _, _, _ = _runtime(monkeypatch, tmp_path)
    attempt_ref = _sealed({"attempt_id": "attempt-actual-active-service"})
    attempt_dir = (tmp_path / "attempt-actual-active-service").resolve()
    iterator = runtime.prepare_screen_groups(
        provider_manifest=manifest,
        partition="regression",
        attempt_ref=attempt_ref,
        attempt_dir=attempt_dir,
    )
    group = next(iterator)
    service = _ActualService([], persist_terminal_lookup=False)
    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        lambda: service,
    )
    monkeypatch.setattr(
        runtime_module.benchmark_v2_actual,
        "run_screen_group",
        _actual_adapter([], []),
    )

    with pytest.raises(ValueError, match="lookup|terminal|active"):
        runtime.run_actual_screen_group(
            provider_group=group,
            attempt_ref=attempt_ref,
            attempt_dir=attempt_dir,
        )

    assert not list((attempt_dir / "actual-screen-groups").glob("*.projection.json"))
    iterator.close()


def test_actual_task8_result_fsync_failure_cancels_exact_started_operation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_module, runtime, manifest, _, windows, _ = _runtime(monkeypatch, tmp_path)
    attempt_ref = _sealed({"attempt_id": "attempt-actual-result-fsync"})
    attempt_dir = (tmp_path / "attempt-actual-result-fsync").resolve()
    iterator = runtime.prepare_screen_groups(
        provider_manifest=manifest,
        partition="regression",
        attempt_ref=attempt_ref,
        attempt_dir=attempt_dir,
    )
    group = next(iterator)
    service = _ActualService([], authoritative_cleanup=True)
    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        lambda: service,
    )
    original_fsync = runtime_module.os.fsync
    fsync_calls = 0

    def fail_result_fsync(descriptor):
        nonlocal fsync_calls
        fsync_calls += 1
        if fsync_calls == 2:
            raise OSError("service result fsync failed")
        return original_fsync(descriptor)

    with monkeypatch.context() as failure:
        failure.setattr(runtime_module.os, "fsync", fail_result_fsync)
        with pytest.raises(OSError, match="service result fsync failed"):
            runtime.run_actual_screen_group(
                provider_group=group,
                attempt_ref=attempt_ref,
                attempt_dir=attempt_dir,
            )

    assert service.start_calls == 1
    assert service.cancel_calls == 1
    assert service.current is not None
    assert service.cancelled_operation_refs == [service.started_operation_ref]
    assert windows.active == 0
    assert not list((attempt_dir / "actual-screen-groups").glob("*.projection.json"))
    iterator.close()


def test_prepare_screen_groups_is_lazy_exact_and_shares_capture_lineage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, runtime, manifest, _, windows, ocr = _runtime(monkeypatch, tmp_path)
    attempt_ref = _sealed({"attempt_id": "attempt-1"})
    assert windows.active == 0

    groups = []
    for partition in ("regression", "holdout"):
        iterator = iter(
            runtime.prepare_screen_groups(
                provider_manifest=manifest,
                partition=partition,
                attempt_ref=attempt_ref,
                attempt_dir=tmp_path / "attempt",
            )
        )
        for _ in range(12):
            group = next(iterator)
            groups.append(group)
            assert windows.active == 1
            assert len(group["case_refs"]) == 5
            assert group["capture_image_path"].startswith("artifacts/screenshots/")
            sources = group["capture_bundle"]["context"]["sources"]
            assert {source["source_kind"] for source in sources} == {"ocr", "uia"}
            assert {
                source["capture_lineage_ref"]["content_sha256"] for source in sources
            } == {group["capture_bundle"]["capture_lineage_ref"]["content_sha256"]}
            assert Path(ocr.paths[-1]).read_bytes() == Path(
                windows.launched[-1]["screenshot_path"]
            ).read_bytes()
        with pytest.raises(StopIteration):
            next(iterator)

    assert len({group["screen_group"] for group in groups}) == 24
    assert sum(len(group["case_refs"]) for group in groups) == 120
    assert windows.maximum_active == 1
    assert windows.active == 0
    assert len(windows.closed) == 24


def test_screen_group_capture_ref_binds_raw_screenshot_sha_not_lineage_object(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, runtime, manifest, _, windows, _ = _runtime(monkeypatch, tmp_path)
    iterator = runtime.prepare_screen_groups(
        provider_manifest=manifest,
        partition="regression",
        attempt_ref=_sealed({"attempt_id": "attempt-capture-ref-sha"}),
        attempt_dir=tmp_path / "attempt-capture-ref-sha",
    )

    with iterator:
        group = next(iterator)
        binding = runtime.open_screen_group(provider_group=group)
        screenshot_sha256 = hashlib.sha256(
            Path(windows.launched[-1]["screenshot_path"]).read_bytes()
        ).hexdigest()
        lineage_sha256 = group["capture_bundle"]["capture_lineage_ref"][
            "content_sha256"
        ]

        assert binding["capture_ref"]["content_sha256"] == screenshot_sha256
        assert lineage_sha256 != screenshot_sha256


def test_owned_window_journal_preserves_production_process_create_time_exactly(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_module, runtime, manifest, _, windows, _ = _runtime(monkeypatch, tmp_path)
    create_time_ns = 1_788_068_912_282_699_008
    launch = runtime_module.launch_owned_window

    def launch_with_production_identity(**kwargs: object) -> dict[str, object]:
        owner = launch(**kwargs)
        owner["process_identity"]["create_time_ns"] = create_time_ns
        owner["content_sha256"] = content_sha256(owner)
        windows.launched[-1] = deepcopy(owner)
        return owner

    monkeypatch.setattr(
        runtime_module,
        "launch_owned_window",
        launch_with_production_identity,
    )
    attempt_ref = _sealed({"attempt_id": "attempt-owned-window-process-identity"})
    iterator = runtime.prepare_screen_groups(
        provider_manifest=manifest,
        partition="regression",
        attempt_ref=attempt_ref,
        attempt_dir=(tmp_path / "attempt-owned-window-process-identity").resolve(),
    )

    with iterator:
        next(iterator)
        events = runtime_module.read_benchmark_v2_attempt_journal(
            journal_path=runtime_module._benchmark_v2_attempt_journal_path(
                project_root=tmp_path,
                attempt_ref=attempt_ref,
            ),
            attempt_ref=attempt_ref,
        )
        owned = [
            event
            for event in events
            if event["event_kind"] == "window_owned"
            and event["resource_ref"]["value"].get("ownership_state") == "owned"
        ]

        assert len(owned) == 1
        value = owned[0]["resource_ref"]["value"]
        assert value["process_identity_projection"] == {
            "pid": windows.launched[-1]["process_identity"]["pid"],
            "create_time_ns_decimal": str(create_time_ns),
        }
        assert "process_identity" not in value


def test_screen_group_iterator_context_closes_retained_early_break(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, runtime, manifest, _, windows, _ = _runtime(monkeypatch, tmp_path)
    iterator = runtime.prepare_screen_groups(
        provider_manifest=manifest,
        partition="regression",
        attempt_ref=_sealed({"attempt_id": "attempt-early-break"}),
        attempt_dir=tmp_path / "attempt",
    )

    with iterator:
        for _group in iterator:
            assert windows.active == 1
            break

    assert windows.active == 0
    assert len(windows.closed) == 1
    iterator.close()
    assert len(windows.closed) == 1


def test_screen_group_iterator_retries_exact_owner_after_transient_cleanup_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, runtime, manifest, _, windows, _ = _runtime(
        monkeypatch,
        tmp_path,
        fail_close_once=True,
    )
    iterator = runtime.prepare_screen_groups(
        provider_manifest=manifest,
        partition="regression",
        attempt_ref=_sealed({"attempt_id": "attempt-cleanup-retry"}),
        attempt_dir=tmp_path / "attempt",
    )
    next(iterator)

    with pytest.raises(RuntimeError, match="transient cleanup failure"):
        iterator.close()
    assert windows.active == 1
    assert windows.close_calls == 1
    assert windows.closed == []

    iterator.close()
    assert windows.active == 0
    assert windows.close_calls == 2
    assert len(windows.closed) == 1
    with pytest.raises(StopIteration):
        next(iterator)


def test_prepare_failure_retains_exact_cleanup_owner_until_retry_succeeds(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_module, runtime, manifest, _, windows, _ = _runtime(
        monkeypatch,
        tmp_path,
        fail_close_once=True,
    )
    monkeypatch.setattr(runtime_module, "ocr_service", _OCR(empty=True))
    attempt_ref = _sealed({"attempt_id": "attempt-prepare-cleanup-retry"})
    iterator = runtime.prepare_screen_groups(
        provider_manifest=manifest,
        partition="regression",
        attempt_ref=attempt_ref,
        attempt_dir=tmp_path / "attempt",
    )

    with pytest.raises(BaseExceptionGroup, match="prepare and cleanup"):
        next(iterator)
    assert windows.active == 1
    assert windows.close_calls == 1
    assert windows.closed == []
    assert runtime._active is None
    assert runtime._pending_cleanup is not None

    blocked = runtime.prepare_screen_groups(
        provider_manifest=manifest,
        partition="regression",
        attempt_ref=attempt_ref,
        attempt_dir=tmp_path / "attempt",
    )
    with pytest.raises(RuntimeError, match="already owns"):
        next(blocked)
    assert len(windows.launched) == 1

    iterator.close()
    assert windows.active == 0
    assert windows.close_calls == 2
    assert len(windows.closed) == 1
    assert runtime._pending_cleanup is None


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        ("ocr", "OCR"),
        ("fabricated_ocr", "OCR"),
        ("uia", "UIA"),
        ("stale", "window|HWND|process"),
        ("stale_hwnd", "window|HWND|process"),
        ("stale_create_time", "window|HWND|process"),
    ],
)
def test_prepare_rejects_empty_or_stale_evidence_and_closes_window(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure: str,
    message: str,
) -> None:
    runtime_module, runtime, manifest, corpus, windows, _ = _runtime(
        monkeypatch,
        tmp_path,
        empty_uia=failure == "uia",
        stale_pid=failure == "stale",
        stale_hwnd=failure == "stale_hwnd",
        stale_create_time=failure == "stale_create_time",
    )
    if failure == "ocr":
        empty = _OCR(empty=True)
        monkeypatch.setattr(runtime_module, "ocr_service", empty)
    elif failure == "fabricated_ocr":
        fabricated = _OCR(wrong_path=True)
        monkeypatch.setattr(runtime_module, "ocr_service", fabricated)
    with pytest.raises(ValueError, match=message):
        next(
            iter(
                runtime.prepare_screen_groups(
                    provider_manifest=manifest,
                    partition="regression",
                    attempt_ref=_sealed({"attempt_id": "attempt-fail"}),
                    attempt_dir=tmp_path / "attempt",
                )
            )
        )
    assert windows.active == 0
    assert len(windows.closed) == 1


def test_missing_source_and_wrong_corpus_sha_fail_before_window_launch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, runtime, manifest, corpus, windows, _ = _runtime(monkeypatch, tmp_path)
    for case in corpus["cases"]:
        if case["partition"] == "regression":
            (tmp_path / case["image"]["path"]).unlink(missing_ok=True)
    with pytest.raises(ValueError, match="source|image|screenshot"):
        next(
            iter(
                runtime.prepare_screen_groups(
                    provider_manifest=manifest,
                    partition="regression",
                    attempt_ref=_sealed({"attempt_id": "attempt-missing"}),
                    attempt_dir=tmp_path / "attempt",
                )
            )
        )
    assert windows.launched == []

    manifest_path, _ = _write_fixture(tmp_path / "other")
    decoded = json.loads(manifest_path.read_text(encoding="utf-8"))
    decoded["provider_corpus_ref"]["file_sha256"] = "0" * 64
    manifest_path.write_bytes(canonical_json_bytes(decoded, pretty=True))
    with pytest.raises(ValueError, match="SHA"):
        runtime.load_provider_manifest(path=manifest_path)


def test_actual_incumbent_calls_are_durable_case_scoped_and_lookup_recovered(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_module, runtime, manifest, _, _, _ = _runtime(monkeypatch, tmp_path)
    attempt_ref = _sealed({"attempt_id": "attempt-incumbent-durable"})
    attempt_dir = (tmp_path / "attempt-incumbent-durable").resolve()
    iterator = runtime.prepare_screen_groups(
        provider_manifest=manifest,
        partition="regression",
        attempt_ref=attempt_ref,
        attempt_dir=attempt_dir,
    )
    group = next(iterator)
    binding = runtime.open_screen_group(provider_group=group)
    delegate = _DurableIncumbentService([])
    result_path = attempt_dir / "actual-screen-groups" / "group.service-result.json"
    service = runtime_module._ActualScreenGroupService(
        delegate=delegate,
        group=group,
        binding=binding,
        intent_ref=_sealed({"kind": "screen-group-service-intent"}),
        result_path=result_path,
    )

    starts = [
        service.start_incumbent_observe(
            provider_case_ref=case_ref,
            window_binding=binding,
        )
        for case_ref in group["case_refs"]
    ]
    assert delegate.incumbent_start_calls == 5
    assert len({step["operation_ref"]["run_id"] for step in starts}) == 5
    assert len({step["operation_ref"]["operation_id"] for step in starts}) == 5

    first = starts[0]
    advanced = service.poll_incumbent_observe(
        operation_ref=first["operation_ref"]
    )
    complete = service.adopt_and_terminalize_incumbent(
        operation_ref=advanced["operation_ref"],
        worker_ref=advanced["worker_ref"],
    )
    restarted = runtime_module._ActualScreenGroupService(
        delegate=delegate,
        group=group,
        binding=binding,
        intent_ref=_sealed({"kind": "screen-group-service-intent"}),
        result_path=result_path,
    )
    replay = restarted.start_incumbent_observe(
        provider_case_ref=group["case_refs"][0],
        window_binding=binding,
    )

    assert replay == complete
    assert delegate.incumbent_start_calls == 5
    assert delegate.incumbent_poll_calls == 1
    assert delegate.incumbent_adopt_calls == 1
    call_root = result_path.parent / "incumbent-calls"
    assert len(list(call_root.glob("*.intent.json"))) == 7
    assert len(list(call_root.glob("*.result.json"))) == 7
    iterator.close()


def test_actual_incumbent_pending_poll_is_resampled_after_worker_progress(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_module, runtime, manifest, _, _, _ = _runtime(monkeypatch, tmp_path)
    attempt_ref = _sealed({"attempt_id": "attempt-incumbent-poll-progress"})
    attempt_dir = (tmp_path / "attempt-incumbent-poll-progress").resolve()
    iterator = runtime.prepare_screen_groups(
        provider_manifest=manifest,
        partition="regression",
        attempt_ref=attempt_ref,
        attempt_dir=attempt_dir,
    )
    group = next(iterator)
    binding = runtime.open_screen_group(provider_group=group)

    class _ProgressingIncumbentService(_DurableIncumbentService):
        worker_completed = False

        def poll_incumbent_observe(self, *, operation_ref):
            if not self.worker_completed:
                self.incumbent_poll_calls += 1
                case_id = str(operation_ref["request_ref"]["id"])
                return deepcopy(self.incumbent_current[case_id])
            return super().poll_incumbent_observe(operation_ref=operation_ref)

    delegate = _ProgressingIncumbentService([])
    result_path = attempt_dir / "actual-screen-groups" / "group.service-result.json"
    service = runtime_module._ActualScreenGroupService(
        delegate=delegate,
        group=group,
        binding=binding,
        intent_ref=_sealed({"kind": "screen-group-service-intent"}),
        result_path=result_path,
    )
    case_ref = group["case_refs"][0]
    started = service.start_incumbent_observe(
        provider_case_ref=case_ref,
        window_binding=binding,
    )
    pending = service.poll_incumbent_observe(
        operation_ref=started["operation_ref"]
    )
    assert pending["operation_ref"]["status"] == "pending"

    delegate.worker_completed = True
    restarted = runtime_module._ActualScreenGroupService(
        delegate=delegate,
        group=group,
        binding=binding,
        intent_ref=_sealed({"kind": "screen-group-service-intent"}),
        result_path=result_path,
    )
    advanced = restarted.poll_incumbent_observe(
        operation_ref=started["operation_ref"]
    )

    assert advanced["operation_ref"]["status"] == "advanced"
    assert delegate.incumbent_poll_calls == 2
    iterator.close()


def test_actual_incumbent_recorded_advanced_poll_replays_over_pending_lookup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_module, runtime, manifest, _, _, _ = _runtime(monkeypatch, tmp_path)
    attempt_ref = _sealed({"attempt_id": "attempt-incumbent-poll-replay"})
    attempt_dir = (tmp_path / "attempt-incumbent-poll-replay").resolve()
    iterator = runtime.prepare_screen_groups(
        provider_manifest=manifest,
        partition="regression",
        attempt_ref=attempt_ref,
        attempt_dir=attempt_dir,
    )
    group = next(iterator)
    binding = runtime.open_screen_group(provider_group=group)
    delegate = _DurableIncumbentService([])
    result_path = attempt_dir / "actual-screen-groups" / "group.service-result.json"
    service = runtime_module._ActualScreenGroupService(
        delegate=delegate,
        group=group,
        binding=binding,
        intent_ref=_sealed({"kind": "screen-group-service-intent"}),
        result_path=result_path,
    )
    case_ref = group["case_refs"][0]
    started = service.start_incumbent_observe(
        provider_case_ref=case_ref,
        window_binding=binding,
    )
    advanced = service.poll_incumbent_observe(
        operation_ref=started["operation_ref"]
    )
    case_id = str(case_ref["case_id"])
    delegate.incumbent_current[case_id] = deepcopy(started)

    restarted = runtime_module._ActualScreenGroupService(
        delegate=delegate,
        group=group,
        binding=binding,
        intent_ref=_sealed({"kind": "screen-group-service-intent"}),
        result_path=result_path,
    )
    replay = restarted.poll_incumbent_observe(
        operation_ref=started["operation_ref"]
    )

    assert replay == advanced
    assert delegate.incumbent_poll_calls == 1
    iterator.close()


def test_actual_incumbent_adopt_consumes_read_only_advanced_poll_over_pending_lookup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_module, runtime, manifest, _, _, _ = _runtime(monkeypatch, tmp_path)
    attempt_ref = _sealed({"attempt_id": "attempt-incumbent-read-only-adopt"})
    attempt_dir = (tmp_path / "attempt-incumbent-read-only-adopt").resolve()
    iterator = runtime.prepare_screen_groups(
        provider_manifest=manifest,
        partition="regression",
        attempt_ref=attempt_ref,
        attempt_dir=attempt_dir,
    )
    group = next(iterator)
    binding = runtime.open_screen_group(provider_group=group)

    class _ReadOnlyAdvancedPollService(_DurableIncumbentService):
        def poll_incumbent_observe(self, *, operation_ref):
            self.incumbent_poll_calls += 1
            case_id = str(operation_ref["request_ref"]["id"])
            pending = deepcopy(self.incumbent_current[case_id])
            advanced_operation = deepcopy(pending["operation_ref"])
            advanced_operation["status"] = "advanced"
            advanced_operation.pop("content_sha256")
            advanced_operation["content_sha256"] = content_sha256(
                advanced_operation
            )
            return incumbent.compose_benchmark_v2_workflow_service_step(
                operation_ref=advanced_operation,
                observed_task_kind="vision_observe_screen",
                adopted_result_projection=None,
                terminal_receipt=None,
                cleanup_refs={
                    "worker_cleanup_ref": None,
                    "provider_cleanup_ref": None,
                },
            )

    delegate = _ReadOnlyAdvancedPollService([])
    service = runtime_module._ActualScreenGroupService(
        delegate=delegate,
        group=group,
        binding=binding,
        intent_ref=_sealed({"kind": "screen-group-service-intent"}),
        result_path=(
            attempt_dir / "actual-screen-groups" / "group.service-result.json"
        ),
    )
    case_ref = group["case_refs"][0]
    started = service.start_incumbent_observe(
        provider_case_ref=case_ref,
        window_binding=binding,
    )
    advanced = service.poll_incumbent_observe(
        operation_ref=started["operation_ref"]
    )

    assert advanced["status"] == "advanced"
    assert delegate.incumbent_current[str(case_ref["case_id"])]["status"] == "pending"

    complete = service.adopt_and_terminalize_incumbent(
        operation_ref=advanced["operation_ref"],
        worker_ref=advanced["worker_ref"],
    )

    assert complete["status"] == "complete"
    assert delegate.incumbent_adopt_calls == 1
    iterator.close()


@pytest.mark.parametrize("call_kind", ("start", "poll", "adopt"))
def test_actual_incumbent_lost_response_uses_lookup_without_duplicate_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    call_kind: str,
) -> None:
    runtime_module, runtime, manifest, _, _, _ = _runtime(monkeypatch, tmp_path)
    attempt_ref = _sealed({"attempt_id": f"attempt-incumbent-lost-{call_kind}"})
    attempt_dir = (tmp_path / f"attempt-incumbent-lost-{call_kind}").resolve()
    iterator = runtime.prepare_screen_groups(
        provider_manifest=manifest,
        partition="regression",
        attempt_ref=attempt_ref,
        attempt_dir=attempt_dir,
    )
    group = next(iterator)
    binding = runtime.open_screen_group(provider_group=group)
    delegate = _DurableIncumbentService([], lost_response_kind=call_kind)
    service = runtime_module._ActualScreenGroupService(
        delegate=delegate,
        group=group,
        binding=binding,
        intent_ref=_sealed({"kind": "screen-group-service-intent"}),
        result_path=(
            attempt_dir / "actual-screen-groups" / "group.service-result.json"
        ),
    )
    case_ref = group["case_refs"][0]
    if call_kind == "start":
        consumed = None
        first = service.start_incumbent_observe(
            provider_case_ref=case_ref,
            window_binding=binding,
        )
        replay = service.start_incumbent_observe(
            provider_case_ref=case_ref,
            window_binding=binding,
        )
    else:
        consumed = service.start_incumbent_observe(
            provider_case_ref=case_ref,
            window_binding=binding,
        )
        if call_kind == "adopt":
            consumed = service.poll_incumbent_observe(
                operation_ref=consumed["operation_ref"]
            )
        if call_kind == "poll":
            first = service.poll_incumbent_observe(
                operation_ref=consumed["operation_ref"]
            )
            replay = service.poll_incumbent_observe(
                operation_ref=consumed["operation_ref"]
            )
        else:
            first = service.adopt_and_terminalize_incumbent(
                operation_ref=consumed["operation_ref"],
                worker_ref=consumed["worker_ref"],
            )
            replay = service.adopt_and_terminalize_incumbent(
                operation_ref=consumed["operation_ref"],
                worker_ref=consumed["worker_ref"],
            )

    assert replay == first
    assert getattr(delegate, f"incumbent_{call_kind}_calls") == 1
    assert delegate.incumbent_lookup_calls >= 3
    iterator.close()


@pytest.mark.parametrize("call_kind", ("start", "poll", "adopt"))
def test_actual_incumbent_result_fsync_failure_recovers_by_lookup_and_cancels_exact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    call_kind: str,
) -> None:
    runtime_module, runtime, manifest, _, windows, _ = _runtime(monkeypatch, tmp_path)
    attempt_ref = _sealed({"attempt_id": f"attempt-incumbent-fsync-{call_kind}"})
    attempt_dir = (tmp_path / f"attempt-incumbent-fsync-{call_kind}").resolve()
    iterator = runtime.prepare_screen_groups(
        provider_manifest=manifest,
        partition="regression",
        attempt_ref=attempt_ref,
        attempt_dir=attempt_dir,
    )
    group = next(iterator)
    binding = runtime.open_screen_group(provider_group=group)
    delegate = _DurableIncumbentService([])
    service = runtime_module._ActualScreenGroupService(
        delegate=delegate,
        group=group,
        binding=binding,
        intent_ref=_sealed({"kind": "screen-group-service-intent"}),
        result_path=(
            attempt_dir / "actual-screen-groups" / "group.service-result.json"
        ),
    )
    case_ref = group["case_refs"][0]
    step = None
    if call_kind != "start":
        step = service.start_incumbent_observe(
            provider_case_ref=case_ref,
            window_binding=binding,
        )
    if call_kind == "adopt":
        step = service.poll_incumbent_observe(operation_ref=step["operation_ref"])

    real_fsync = runtime_module.os.fsync
    fsync_calls = 0

    def fail_result_fsync(descriptor: int) -> None:
        nonlocal fsync_calls
        fsync_calls += 1
        if fsync_calls == 2:
            raise OSError(f"{call_kind} result fsync failed")
        real_fsync(descriptor)

    with monkeypatch.context() as failure:
        failure.setattr(runtime_module.os, "fsync", fail_result_fsync)
        with pytest.raises(OSError, match="result fsync failed"):
            if call_kind == "start":
                service.start_incumbent_observe(
                    provider_case_ref=case_ref,
                    window_binding=binding,
                )
            elif call_kind == "poll":
                service.poll_incumbent_observe(operation_ref=step["operation_ref"])
            else:
                service.adopt_and_terminalize_incumbent(
                    operation_ref=step["operation_ref"],
                    worker_ref=step["worker_ref"],
                )

    assert delegate.cancel_calls == 1
    assert delegate.cancelled_operation_refs
    assert getattr(delegate, f"incumbent_{call_kind}_calls") == 1
    assert windows.active == 1
    iterator.close()
    assert windows.active == 0


def test_actual_cleanup_reconciles_hybrid_started_before_any_incumbent_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_module, runtime, manifest, _, _, _ = _runtime(monkeypatch, tmp_path)
    attempt_ref = _sealed({"attempt_id": "attempt-partial-hybrid-cleanup"})
    attempt_dir = (tmp_path / "attempt-partial-hybrid-cleanup").resolve()
    iterator = runtime.prepare_screen_groups(
        provider_manifest=manifest,
        partition="regression",
        attempt_ref=attempt_ref,
        attempt_dir=attempt_dir,
    )
    group = next(iterator)
    service = _ActualService([])
    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        lambda: service,
    )

    def fail_after_hybrid_start(
        *, provider_group, service, window_owner, lifecycle, prediction_sink
    ):
        del lifecycle, prediction_sink
        binding = window_owner.open_screen_group(provider_group=provider_group)
        service.start_hybrid_operation(
            screen_group=provider_group,
            window_binding=binding,
        )
        raise RuntimeError("failed before first incumbent call")

    monkeypatch.setattr(
        runtime_module.benchmark_v2_actual,
        "run_screen_group",
        fail_after_hybrid_start,
    )

    with pytest.raises(RuntimeError, match="before first incumbent"):
        runtime.run_actual_screen_group(
            provider_group=group,
            attempt_ref=attempt_ref,
            attempt_dir=attempt_dir,
        )

    actual_root = attempt_dir / "actual-screen-groups"
    assert list(actual_root.glob("*.service-intent.json"))
    assert list(actual_root.glob("*.service-result.json"))
    assert not (actual_root / "incumbent-calls").exists()

    receipt = runtime.cleanup_attempt(
        attempt=attempt_ref,
        reason="partial_actual_group_failed",
    )
    replay = runtime.cleanup_attempt(
        attempt=attempt_ref,
        reason="partial_actual_group_failed",
    )

    assert replay == receipt
    assert service.cancel_calls == 1
    assert [item["mode"] for item in service.cancelled_operation_refs] == [
        "hybrid_v1_1"
    ]
    assert service.stable_zero_calls == 0
    assert service.stable_zero_operation_counts == []
    assert receipt["service_terminal_ref"]["parent_kind"] == (
        "workflow_service_terminal"
    )
    assert len(receipt["provider_cleanup_refs"]) == 2
    assert receipt["resource_counts"] == {
        "service_operations": 0,
        "windows": 0,
        "providers": 0,
        "listeners": 0,
        "leases": 0,
    }


def test_actual_cleanup_resumes_advanced_incumbent_instead_of_cancelling(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_module, runtime, manifest, _, _, _ = _runtime(monkeypatch, tmp_path)
    attempt_ref = _sealed({"attempt_id": "attempt-advanced-incumbent-cleanup"})
    attempt_dir = (tmp_path / "attempt-advanced-incumbent-cleanup").resolve()
    iterator = runtime.prepare_screen_groups(
        provider_manifest=manifest,
        partition="regression",
        attempt_ref=attempt_ref,
        attempt_dir=attempt_dir,
    )
    group = next(iterator)
    binding = runtime.open_screen_group(provider_group=group)
    case_ref = deepcopy(group["case_refs"][0])
    parent_intent_sha = "e" * 64

    class CompletionWonService(_DurableIncumbentService):
        def cancel_operation(self, *, operation_ref):
            if operation_ref["mode"] == "incumbent_qwen_only":
                raise AssertionError("completion-won incumbent must not be cancelled")
            return super().cancel_operation(operation_ref=operation_ref)

        def adopt_and_terminalize_incumbent(self, *, operation_ref, worker_ref):
            assert dict(worker_ref) == operation_ref["worker_ref"]
            self.incumbent_adopt_calls += 1
            operation_binding = {
                name: deepcopy(operation_ref[name])
                for name in (
                    "run_id",
                    "stage",
                    "operation_id",
                    "window_binding_ref",
                    "capture_ref",
                )
            }
            terminal_operation = _actual_operation(
                mode="incumbent_qwen_only",
                operation_id=str(operation_ref["operation_id"]),
                request_ref=operation_ref["request_ref"],
                binding=operation_binding,
                revision=int(operation_ref["workflow_state_ref"]["revision"]) + 1,
                status="complete",
                predecessor=operation_ref,
            )
            cleanup = _ActualService([]).cancel_operation(
                operation_ref=operation_ref
            )["cleanup_refs"]
            terminal = incumbent.compose_benchmark_v2_workflow_service_step(
                operation_ref=terminal_operation,
                observed_task_kind="vision_observe_screen",
                adopted_result_projection=None,
                terminal_receipt=None,
                cleanup_refs=cleanup,
            )
            case_id = str(operation_ref["request_ref"]["id"])
            self.incumbent_current[case_id] = deepcopy(terminal)
            return terminal

    service = CompletionWonService([])
    service.start_hybrid_operation(screen_group=group, window_binding=binding)
    pending = service.start_incumbent_observe(
        provider_case_ref=case_ref,
        window_binding=binding,
    )
    advanced = service.poll_incumbent_observe(
        operation_ref=pending["operation_ref"]
    )
    assert advanced["status"] == "advanced"
    monkeypatch.setattr(
        runtime_module,
        "_read_actual_screen_group_service_intents",
        lambda **_kwargs: [
            {
                "provider_group": deepcopy(group),
                "window_binding": deepcopy(binding),
                "content_sha256": parent_intent_sha,
            }
        ],
    )
    monkeypatch.setattr(
        runtime_module,
        "_read_actual_incumbent_call_intents",
        lambda **_kwargs: [
            {
                "provider_case_ref": deepcopy(case_ref),
                "window_binding": deepcopy(binding),
                "service_intent_ref": {"content_sha256": parent_intent_sha},
            }
        ],
    )

    first = runtime_module._reconcile_actual_operations(
        attempt_dir=attempt_dir,
        service=service,
    )
    second = runtime_module._reconcile_actual_operations(
        attempt_dir=attempt_dir,
        service=service,
    )

    assert first[0][1] == second[0][1]
    assert first[0][1]["status"] == "complete"
    assert service.incumbent_adopt_calls == 1
    assert all(
        operation["mode"] == "hybrid_v1_1"
        for operation in service.cancelled_operation_refs
    )
    iterator.close()


def test_actual_cleanup_consumes_pre_reservation_recovery_without_fake_operation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.learn.hybrid.benchmark_v2_incumbent_operation import (
        compose_benchmark_v2_incumbent_pre_reservation_recovery,
    )
    from app.learn.workflow_service import _benchmark_v2_incumbent_child_slot

    runtime_module, runtime, manifest, _, _, _ = _runtime(monkeypatch, tmp_path)
    attempt_ref = _sealed({"attempt_id": "attempt-pre-reservation-recovery"})
    attempt_dir = (tmp_path / "attempt-pre-reservation-recovery").resolve()
    iterator = runtime.prepare_screen_groups(
        provider_manifest=manifest,
        partition="regression",
        attempt_ref=attempt_ref,
        attempt_dir=attempt_dir,
    )
    group = next(iterator)
    binding = incumbent.compose_benchmark_v2_workflow_window_binding(
        run_id="parent-run-pre-reservation",
        operation_id="parent-operation-pre-reservation",
        window_binding_ref={"id": "window-pre", "content_sha256": "a" * 64},
        capture_ref={"id": "capture-pre", "content_sha256": "b" * 64},
        owner_journal_ref={"content_sha256": "c" * 64},
        expected_uia_root_ref={"content_sha256": "d" * 64},
    )
    provider_case_ref = deepcopy(group["case_refs"][0])
    parent_intent_sha = "e" * 64
    child_slot = _benchmark_v2_incumbent_child_slot(
        provider_case_ref=provider_case_ref,
        window_binding=binding,
    )

    class RecoveringService(_ActualService):
        def __init__(self, operations, *, tamper_child_identity: bool = False):
            super().__init__(operations)
            self.tamper_child_identity = tamper_child_identity
            self.completed_hybrid_cleanup_calls = 0

        def start_hybrid_operation(self, *, screen_group, window_binding):
            self.start_calls += 1
            self.current = _actual_completed_review_step(
                screen_group,
                window_binding,
            )
            self.started_operation_ref = deepcopy(self.current["operation_ref"])
            return deepcopy(self.current)

        def cancel_operation(self, *, operation_ref):
            self.cancel_calls += 1
            self.cancelled_operation_refs.append(deepcopy(dict(operation_ref)))
            assert self.current is not None
            assert operation_ref == self.current["operation_ref"]
            return deepcopy(self.current)

        def attest_completed_hybrid_cleanup(self, *, operation_ref):
            self.completed_hybrid_cleanup_calls += 1
            assert self.current is not None
            assert operation_ref == self.current["operation_ref"]
            return _actual_completed_review_cleanup(operation_ref)

        def recover_incumbent_pre_reservation(
            self, *, provider_case_ref, window_binding
        ):
            return compose_benchmark_v2_incumbent_pre_reservation_recovery(
                run_id=(
                    "tampered-child-run"
                    if self.tamper_child_identity
                    else str(child_slot["run_id"])
                ),
                stage=str(window_binding["stage"]),
                operation_id=(
                    "tampered-child-operation"
                    if self.tamper_child_identity
                    else str(child_slot["operation_id"])
                ),
                provider_case_ref=provider_case_ref,
                window_binding_ref=window_binding["window_binding_ref"],
                capture_ref=window_binding["capture_ref"],
                child_start_intent_ref={"content_sha256": "1" * 64},
                stage_execution_ref={"content_sha256": "2" * 64},
                reservation_absence_ref={"content_sha256": "3" * 64},
                workflow_state_ref={
                    "run_id": (
                        "tampered-child-run"
                        if self.tamper_child_identity
                        else str(child_slot["run_id"])
                    ),
                    "revision": 4,
                    "content_sha256": "4" * 64,
                },
            )

        def lookup_incumbent_observe(self, **_kwargs):
            raise AssertionError("recovered pre-reservation start must not be looked up")

    monkeypatch.setattr(
        runtime_module,
        "_read_actual_screen_group_service_intents",
        lambda **_kwargs: [
            {
                "provider_group": deepcopy(group),
                "window_binding": deepcopy(binding),
                "content_sha256": parent_intent_sha,
            }
        ],
    )
    monkeypatch.setattr(
        runtime_module,
        "_read_actual_incumbent_call_intents",
        lambda **_kwargs: [
            {
                "provider_case_ref": deepcopy(provider_case_ref),
                "window_binding": deepcopy(binding),
                "service_intent_ref": {"content_sha256": parent_intent_sha},
            }
        ],
    )

    wrong_service = RecoveringService([], tamper_child_identity=True)
    wrong_service.start_hybrid_operation(screen_group=group, window_binding=binding)
    with pytest.raises(
        ValueError,
        match="pre-reservation recovery lineage differs",
    ):
        runtime_module._reconcile_actual_operations(
            attempt_dir=attempt_dir,
            service=wrong_service,
        )

    service = RecoveringService([])
    service.start_hybrid_operation(screen_group=group, window_binding=binding)
    reconciled = runtime_module._reconcile_actual_operations(
        attempt_dir=attempt_dir,
        service=service,
    )
    assert [len(reconciled[index]) for index in range(5)] == [1, 0, 1, 1, 0]
    assert reconciled[5] == 0
    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        lambda: service,
    )

    receipt = runtime.cleanup_attempt(
        attempt=attempt_ref,
        reason="pre_reservation_start_failed",
    )
    replay = runtime.cleanup_attempt(
        attempt=attempt_ref,
        reason="pre_reservation_start_failed",
    )

    assert replay == receipt
    assert receipt["service_terminal_ref"]["parent_kind"] == (
        "actual_operations_cleanup_aggregate"
    )
    assert receipt["resource_counts"] == {
        "service_operations": 0,
        "windows": 0,
        "providers": 0,
        "listeners": 0,
        "leases": 0,
    }
    assert service.cancel_calls == 2
    assert service.completed_hybrid_cleanup_calls == 2
    assert service.stable_zero_calls == 0
    assert len(service.cancelled_operation_refs) == 2
    iterator.close()


def test_actual_cleanup_fails_closed_when_durable_hybrid_intent_is_not_terminal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_module, runtime, manifest, _, _, _ = _runtime(monkeypatch, tmp_path)
    attempt_ref = _sealed({"attempt_id": "attempt-partial-hybrid-unresolved"})
    attempt_dir = (tmp_path / "attempt-partial-hybrid-unresolved").resolve()
    iterator = runtime.prepare_screen_groups(
        provider_manifest=manifest,
        partition="regression",
        attempt_ref=attempt_ref,
        attempt_dir=attempt_dir,
    )
    group = next(iterator)
    service = _ActualService([])
    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        lambda: service,
    )

    def fail_after_hybrid_start(
        *, provider_group, service, window_owner, lifecycle, prediction_sink
    ):
        del lifecycle, prediction_sink
        binding = window_owner.open_screen_group(provider_group=provider_group)
        service.start_hybrid_operation(
            screen_group=provider_group,
            window_binding=binding,
        )
        raise RuntimeError("lost durable Hybrid lookup")

    monkeypatch.setattr(
        runtime_module.benchmark_v2_actual,
        "run_screen_group",
        fail_after_hybrid_start,
    )

    with pytest.raises(RuntimeError, match="lost durable Hybrid lookup"):
        runtime.run_actual_screen_group(
            provider_group=group,
            attempt_ref=attempt_ref,
            attempt_dir=attempt_dir,
        )
    service.current = None

    with pytest.raises(ValueError, match="resource counts are not stable-zero"):
        runtime.cleanup_attempt(
            attempt=attempt_ref,
            reason="unresolved_actual_group_failed",
        )

    events = runtime_module.read_benchmark_v2_attempt_journal(
        journal_path=runtime_module._benchmark_v2_attempt_journal_path(
            project_root=tmp_path,
            attempt_ref=attempt_ref,
        ),
        attempt_ref=attempt_ref,
    )
    assert service.cancel_calls == 0
    assert service.stable_zero_calls == 0
    assert not any(event["event_kind"] == "attempt_terminal" for event in events)


def test_prepared_attempt_without_actual_intent_does_not_construct_workflow_service(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_module, runtime, manifest, _, _, _ = _runtime(monkeypatch, tmp_path)
    attempt_ref = _sealed({"attempt_id": "attempt-prepared-without-actual-intent"})
    iterator = runtime.prepare_screen_groups(
        provider_manifest=manifest,
        partition="regression",
        attempt_ref=attempt_ref,
        attempt_dir=(tmp_path / "attempt-prepared-without-actual-intent").resolve(),
    )

    def unexpected_service_construction():
        raise AssertionError("prepared attempt must not construct WorkflowService")

    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        unexpected_service_construction,
    )
    monkeypatch.setattr(
        runtime_module,
        "get_production_provider_case_resolver",
        lambda: (_ for _ in ()).throw(
            AssertionError("prepared attempt must not resolve provider corpus")
        ),
    )

    receipt = runtime.cleanup_attempt(
        attempt=attempt_ref,
        reason="prepared_without_actual_intent",
    )

    assert receipt["cleanup_status"] == "stable_zero"
    assert receipt["service_terminal_ref"] is None
    assert receipt["provider_cleanup_refs"] == []
    iterator.close()


def test_partial_actual_review_no_provider_cleanup_is_exact_and_non_authorizing() -> None:
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module

    binding = {
        "run_id": "run-partial-review",
        "stage": "screen_understanding",
        "operation_id": "operation-partial-review",
        "window_binding_ref": {
            "id": "window-partial-review",
            "content_sha256": "a" * 64,
        },
        "capture_ref": {
            "id": "capture-partial-review",
            "content_sha256": "b" * 64,
        },
    }
    operation = _actual_operation(
        mode="hybrid_v1_1",
        operation_id=str(binding["operation_id"]),
        request_ref={"id": "request-partial-review", "content_sha256": "c" * 64},
        binding=binding,
        revision=3,
        status="safe_stopped",
    )
    worker = operation["worker_ref"]
    returned_worker_ref = _sealed(
        {
            "contract_version": "benchmark_v2_workflow_service_generic_worker_ref_v1",
            "run_id": operation["run_id"],
            "stage": operation["stage"],
            "operation_id": operation["operation_id"],
            "worker_id": worker["worker_id"],
            "model_request_id": worker["model_request_id"],
            "payload_sha256": worker["payload_sha256"],
            "task_kind": "panel_learning_hybrid_review_projection",
        }
    )
    worker_cleanup = _sealed(
        {
            "contract_version": "benchmark_v2_hybrid_worker_cleanup_ref_v1",
            "run_id": operation["run_id"],
            "stage": operation["stage"],
            "operation_id": operation["operation_id"],
            "worker_id": worker["worker_id"],
            "model_request_id": worker["model_request_id"],
            "payload_sha256": worker["payload_sha256"],
            "backend_compute_termination": "not_running",
            "model_service_compute_termination": "request_not_active",
            "cancellation_ref": {"content_sha256": "d" * 64},
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    absence = _sealed(
        {
            "contract_version": (
                "benchmark_v2_hybrid_no_provider_live_absence_observation_v1"
            ),
            "run_id": operation["run_id"],
            "stage": operation["stage"],
            "operation_id": operation["operation_id"],
            "worker_id": worker["worker_id"],
            "model_request_id": worker["model_request_id"],
            "payload_sha256": worker["payload_sha256"],
            "task_kind": "panel_learning_hybrid_review_projection",
            "provider_role": "review",
            "current_worker_ref": returned_worker_ref,
            "latest_operation_worker_ref": returned_worker_ref,
            "review_dispatch_context_absent": True,
            "review_dispatch_receipt_absent": True,
            "provider_scope_absent": True,
            "provider_journal_absent": True,
            "provider_cleanup_journal_absent": True,
            "deterministic_provider_lease_artifact_absent": True,
            "deterministic_provider_owner_artifact_absent": True,
            "deterministic_provider_runtime_artifact_absent": True,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    provider_cleanup = _sealed(
        {
            "contract_version": "benchmark_v2_hybrid_no_provider_cleanup_ref_v1",
            "status": "cleanup_verified",
            "outcome": "verified_review_provider_not_applicable",
            "authority_kind": (
                "benchmark_v2_workflow_service_review_no_provider_cleanup"
            ),
            "run_id": operation["run_id"],
            "stage": operation["stage"],
            "operation_id": operation["operation_id"],
            "worker_id": worker["worker_id"],
            "model_request_id": worker["model_request_id"],
            "payload_sha256": worker["payload_sha256"],
            "task_kind": "panel_learning_hybrid_review_projection",
            "provider_role": "review",
            "worker_status": "completed",
            "runtime_attached": False,
            "result_available": True,
            "result_adopted": True,
            "continuation_phase": "terminal_prepared",
            "cancellation_backend_termination": "not_running",
            "cancellation_model_request_termination": "request_not_active",
            "service_binding_ref": {"content_sha256": "e" * 64},
            "terminal_prepared_continuation_receipt_ref": {
                "content_sha256": "f" * 64
            },
            "returned_worker_ref": returned_worker_ref,
            "worker_cleanup_ref": {
                "content_sha256": worker_cleanup["content_sha256"]
            },
            "live_absence_observation": absence,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    terminal = incumbent.compose_benchmark_v2_workflow_service_step(
        operation_ref=operation,
        observed_task_kind="panel_learning_hybrid_review_projection",
        adopted_result_projection=None,
        terminal_receipt=None,
        cleanup_refs={
            "worker_cleanup_ref": worker_cleanup,
            "provider_cleanup_ref": provider_cleanup,
        },
    )

    assert runtime_module._validate_partial_actual_terminal_cleanup(terminal) == terminal

    foreign = deepcopy(terminal)
    foreign_cleanup = deepcopy(provider_cleanup)
    foreign_cleanup["run_id"] = "foreign-run"
    foreign_cleanup["content_sha256"] = content_sha256(foreign_cleanup)
    foreign["cleanup_refs"]["provider_cleanup_ref"] = foreign_cleanup
    foreign["content_sha256"] = content_sha256(foreign)
    with pytest.raises(ValueError, match="cleanup.*stale"):
        runtime_module._validate_partial_actual_terminal_cleanup(foreign)


@pytest.mark.parametrize(
    "mutation",
    (
        "missing_worker_cleanup",
        "missing_provider_cleanup",
        "foreign_worker_cleanup",
        "foreign_provider_cleanup",
    ),
)
def test_partial_actual_cleanup_rejects_missing_or_foreign_cleanup_lineage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutation: str,
) -> None:
    runtime_module, runtime, manifest, _, _, _ = _runtime(monkeypatch, tmp_path)
    attempt_ref = _sealed({"attempt_id": f"attempt-partial-{mutation}"})
    attempt_dir = (tmp_path / f"attempt-partial-{mutation}").resolve()
    iterator = runtime.prepare_screen_groups(
        provider_manifest=manifest,
        partition="regression",
        attempt_ref=attempt_ref,
        attempt_dir=attempt_dir,
    )
    group = next(iterator)
    service = _DurableIncumbentService([])
    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        lambda: service,
    )

    def fail_after_hybrid_start(
        *, provider_group, service, window_owner, lifecycle, prediction_sink
    ):
        del lifecycle, prediction_sink
        binding = window_owner.open_screen_group(provider_group=provider_group)
        service.start_hybrid_operation(
            screen_group=provider_group,
            window_binding=binding,
        )
        raise RuntimeError("partial actual operation")

    monkeypatch.setattr(
        runtime_module.benchmark_v2_actual,
        "run_screen_group",
        fail_after_hybrid_start,
    )
    with pytest.raises(RuntimeError, match="partial actual operation"):
        runtime.run_actual_screen_group(
            provider_group=group,
            attempt_ref=attempt_ref,
            attempt_dir=attempt_dir,
        )

    valid_cancel = service.cancel_operation

    def invalid_cancel(*, operation_ref):
        terminal = valid_cancel(operation_ref=operation_ref)
        cleanup_name = (
            "worker_cleanup_ref"
            if "worker" in mutation
            else "provider_cleanup_ref"
        )
        if mutation.startswith("missing"):
            terminal["cleanup_refs"][cleanup_name] = None
        else:
            cleanup = terminal["cleanup_refs"][cleanup_name]
            cleanup["run_id"] = "foreign-run"
            cleanup["content_sha256"] = content_sha256(cleanup)
        terminal["content_sha256"] = content_sha256(terminal)
        return terminal

    service.cancel_operation = invalid_cancel

    with pytest.raises(BaseExceptionGroup, match="cleanup.*indeterminate"):
        runtime.cleanup_attempt(
            attempt=attempt_ref,
            reason="reject_partial_cleanup_lineage",
        )

    events = runtime_module.read_benchmark_v2_attempt_journal(
        journal_path=runtime_module._benchmark_v2_attempt_journal_path(
            project_root=tmp_path,
            attempt_ref=attempt_ref,
        ),
        attempt_ref=attempt_ref,
    )
    assert not any(event["event_kind"] == "attempt_terminal" for event in events)


def test_partial_actual_vista_not_acquired_cleanup_uses_recovered_lease() -> None:
    from app.learn.hybrid import benchmark_v2_runtime as runtime

    binding = {
        "run_id": "run-vista-not-acquired",
        "stage": "screen_understanding",
        "operation_id": "operation-vista-not-acquired",
        "window_binding_ref": {
            "id": "window-vista-not-acquired",
            "content_sha256": "a" * 64,
        },
        "capture_ref": {
            "id": "capture-vista-not-acquired",
            "content_sha256": "b" * 64,
        },
    }
    operation = _actual_operation(
        mode="hybrid_v1_1",
        operation_id=str(binding["operation_id"]),
        request_ref={"id": "request-vista-not-acquired", "content_sha256": "c" * 64},
        binding=binding,
        revision=3,
        status="safe_stopped",
    )
    worker = operation["worker_ref"]
    provider_cleanup = _sealed(
        {
            "contract_version": "benchmark_provider_cleanup_ref_v1",
            "status": "cleanup_verified",
            "outcome": "verified_not_acquired",
            "provider": "vista",
            "task_kind": "panel_learning_calibration_sequence",
            "authority_kind": "benchmark_v2_workflow_service_dispatch_cleanup",
            "run_id": operation["run_id"],
            "stage": operation["stage"],
            "operation_id": operation["operation_id"],
            "worker_id": worker["worker_id"],
            "model_request_id": worker["model_request_id"],
            "payload_sha256": worker["payload_sha256"],
            "reservation_ref": {"content_sha256": "2" * 64},
            "acquisition_owner_ref": {"content_sha256": "3" * 64},
            "acquisition_intent_ref": {"content_sha256": "2" * 64},
            "runtime_owner_ref": {"content_sha256": "4" * 64},
            "recovered_lease_ref": {"content_sha256": "5" * 64},
        }
    )
    worker_cleanup = _sealed(
        {
            "contract_version": "benchmark_v2_hybrid_completed_worker_cleanup_ref_v1",
            "run_id": operation["run_id"],
            "stage": operation["stage"],
            "operation_id": operation["operation_id"],
            "worker_id": worker["worker_id"],
            "model_request_id": worker["model_request_id"],
            "payload_sha256": worker["payload_sha256"],
            "worker_status": "completed",
            "runtime_attached": False,
            "result_available": True,
            "authoritative_worker_record_sha256": "6" * 64,
            "provider_cleanup_ref": {
                "content_sha256": provider_cleanup["content_sha256"]
            },
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    terminal = incumbent.compose_benchmark_v2_workflow_service_step(
        operation_ref=operation,
        observed_task_kind="panel_learning_calibration_sequence",
        adopted_result_projection=None,
        terminal_receipt=None,
        cleanup_refs={
            "worker_cleanup_ref": worker_cleanup,
            "provider_cleanup_ref": provider_cleanup,
        },
    )

    assert runtime._validate_partial_actual_terminal_cleanup(terminal) == terminal

    confused = dict(provider_cleanup)
    confused.pop("content_sha256")
    confused["cleanup_receipt_ref"] = confused.pop("recovered_lease_ref")
    confused = _sealed(confused)
    confused_terminal = deepcopy(terminal)
    confused_terminal["cleanup_refs"]["provider_cleanup_ref"] = confused
    confused_terminal["cleanup_refs"]["worker_cleanup_ref"][
        "provider_cleanup_ref"
    ] = {"content_sha256": confused["content_sha256"]}
    confused_terminal["cleanup_refs"]["worker_cleanup_ref"].pop("content_sha256")
    confused_terminal["cleanup_refs"]["worker_cleanup_ref"] = _sealed(
        confused_terminal["cleanup_refs"]["worker_cleanup_ref"]
    )
    confused_terminal.pop("content_sha256")
    confused_terminal = _sealed(confused_terminal)
    with pytest.raises(ValueError, match="provider cleanup"):
        runtime._validate_partial_actual_terminal_cleanup(confused_terminal)
