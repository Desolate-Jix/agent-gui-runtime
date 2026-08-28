from __future__ import annotations

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
        receipt = _sealed({"cleanup_status": "verified", "reason": reason})
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


def _runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **window_options: bool):
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module

    manifest_path, corpus = _write_fixture(tmp_path)
    windows = _Windows(**window_options)
    ocr = _OCR()
    _install_fakes(monkeypatch, runtime_module, corpus, windows, ocr)
    runtime = runtime_module._BenchmarkV2ProductionRuntime(
        project_root=tmp_path,
        authority_root=tmp_path / "runtime_state" / "binding-authority",
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
            cleanup_entries.append(
                {
                    "operation_ref_sha256": operation["content_sha256"],
                    "terminal_receipt_ref": _sealed(
                        {
                            "run_id": operation["run_id"],
                            "stage": operation["stage"],
                            "operation_id": operation["operation_id"],
                            "worker_id": operation["worker_ref"]["worker_id"],
                        }
                    ),
                    "worker_cleanup_ref": deepcopy(
                        step["cleanup_refs"]["worker_cleanup_ref"]
                    ),
                    "provider_cleanup_ref": deepcopy(
                        step["cleanup_refs"]["provider_cleanup_ref"]
                    ),
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
                        "run_id": terminal_operation["run_id"],
                        "stage": terminal_operation["stage"],
                        "operation_id": terminal_operation["operation_id"],
                        "worker_id": worker["worker_id"],
                        "reservation_ref": reservation_ref,
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
