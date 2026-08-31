from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import gc
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import socket
import sys
import time

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class _UnitCleanupReceiptAuthority:
    def verify_benchmark_worker_cleanup_receipt(self, **kwargs):
        return deepcopy(kwargs["receipt"])
PARENT_MANIFEST = (
    PROJECT_ROOT
    / "tests"
    / "fixtures"
    / "portfolio_hybrid_v1_1"
    / "corpus-manifest.v1.json"
)
SHA = "a" * 64


def _recorded_qwen_benchmark_worker_entry(
    target,
    args,
    release_event,
    lease_dir: str,
    model_request_id: str,
    recorded_response: dict[str, object],
) -> None:
    from app.core import model_server
    from app.learn import workflow_worker

    model_server.MODEL_SERVER_LEASE_DIR = Path(lease_dir)
    original_write = workflow_worker._write_worker_result

    def _recorded_task(*_args, **_kwargs):
        if not release_event.wait(45):
            raise RuntimeError("recorded Qwen response release timed out")
        from app.learn.hybrid import benchmark_v2_dispatch_attestation as dispatch

        dispatch_context = dispatch.current_benchmark_dispatch_context()
        if not isinstance(dispatch_context, dict) or dispatch_context.get(
            "provider"
        ) != "qwen":
            raise RuntimeError("recorded Qwen dispatch context is unavailable")
        dispatch._attest_exact_window = lambda value: {
            "content_sha256": "d" * 64
        }
        dispatch._attest_exact_provider_runtime = lambda provider, value: {
            "content_sha256": "e" * 64
        }
        dispatch.attest_benchmark_provider_dispatch(
            provider="qwen",
            operation_ref=dispatch_context["operation_ref"],
            window_binding=dispatch_context["window_binding"],
            provider_runtime={"recorded_fixture": True},
        )
        return deepcopy(recorded_response)

    def _write_with_provider_parent(path, payload):
        receipt = model_server.observe_qwen_model_request_cleanup(model_request_id)
        if not isinstance(receipt, dict) or receipt.get("outcome") != (
            "verified_exact_process_exited"
        ):
            raise RuntimeError("recorded Qwen cleanup parent is unavailable")
        exact = deepcopy(payload)
        exact["provider_cleanup_evidence_ref"] = {
            "content_sha256": receipt["content_sha256"]
        }
        original_write(path, exact)

    workflow_worker.execute_learning_stage_worker_task = _recorded_task
    workflow_worker._write_worker_result = _write_with_provider_parent
    target(*args)


def _recorded_qwen_incumbent_resume_cut(
    project_root: str,
    state_path: str,
    worker_root: str,
    lease_dir: str,
    corpus_raw: bytes,
    corpus_file_sha: str,
    corpus_file_ref: dict[str, object],
    run_id: str,
    stage: str,
    operation_id: str,
    worker_id: str,
    result_queue,
    cleanup: bool = False,
) -> None:
    import traceback

    from app.core import model_server
    from app.learn.hybrid.benchmark_v2_provider_corpus import (
        compose_test_provider_case_resolver,
        validate_preloaded_provider_corpus,
    )
    from app.learn.workflow_service import (
        cancel_guarded_learning_workflow_stage_operation,
        compose_test_learning_workflow_service,
        continue_guarded_learning_stage_worker_result,
    )
    from app.learn.workflow_store import LearningWorkflowRunStore
    from app.learn.workflow_worker import (
        LearningStageWorkerRegistry,
        compose_test_benchmark_worker_supervision_root,
    )

    store = None
    try:
        model_server.MODEL_SERVER_LEASE_DIR = Path(lease_dir)
        corpus = validate_preloaded_provider_corpus(
            raw=corpus_raw, expected_sha256=corpus_file_sha
        )
        store = LearningWorkflowRunStore(state_path=Path(state_path))
        root = compose_test_benchmark_worker_supervision_root(
            journal_root=Path(worker_root),
            test_capability=object(),
            workflow_store=store,
            test_store_capability=object(),
        )
        registry = LearningStageWorkerRegistry(
            result_root=Path(worker_root), benchmark_supervision_root=root
        )
        resolver = compose_test_provider_case_resolver(
            validated_corpus=corpus,
            provider_corpus_file_ref=corpus_file_ref,
            workflow_store=store,
            benchmark_supervision_root=root,
        )
        composition = compose_test_learning_workflow_service(
            store=store,
            worker_registry=registry,
            project_root=Path(project_root),
            benchmark_supervision_root=root,
            provider_case_resolver=resolver,
        )
        state = store.get(run_id)
        operation = state["stages"][stage]["evidence_refs"]["stage_execution"].get(
            "benchmark_v2_incumbent"
        )
        completion_won = isinstance(operation, dict) and (
            operation.get("terminal_intent") is not None
            or operation.get("phase") in {"adopted", "complete"}
        )
        if cleanup and not completion_won:
            result = cancel_guarded_learning_workflow_stage_operation(
                composition=composition,
                run_id=run_id,
                expected_revision=state["revision"],
                stage=stage,
                operation_id=operation_id,
                reason="recorded Qwen outer-finally cleanup",
            )
        else:
            result = continue_guarded_learning_stage_worker_result(
                composition=composition,
                run_id=run_id,
                expected_revision=state["revision"],
                stage=stage,
                operation_id=operation_id,
                worker_id=worker_id,
            )
        result_queue.put({"status": "ok", "result": result})
    except BaseException as error:
        result_queue.put(
            {
                "status": "error",
                "error_type": type(error).__name__,
                "details": str(error),
                "traceback": traceback.format_exc(),
            }
        )
        raise
    finally:
        if store is not None:
            store.close()


def _recorded_qwen_incumbent_cancel_intent_cut(
    project_root: str,
    state_path: str,
    worker_root: str,
    lease_dir: str,
    corpus_raw: bytes,
    corpus_file_sha: str,
    corpus_file_ref: dict[str, object],
    run_id: str,
    stage: str,
    operation_id: str,
    case_ref: dict[str, object],
    window_binding_ref: dict[str, object],
    capture_ref: dict[str, object],
    release_event,
    cancel_event,
    recorded_response: dict[str, object],
    result_queue,
) -> None:
    import traceback

    from app.core import model_server
    from app.learn import workflow_service
    from app.learn.hybrid.benchmark_v2_provider_corpus import (
        compose_test_provider_case_resolver,
        validate_preloaded_provider_corpus,
    )
    from app.learn.workflow_service import (
        cancel_guarded_learning_workflow_stage_operation,
        compose_test_learning_workflow_service,
        start_guarded_learning_stage_worker,
    )
    from app.learn.workflow_store import LearningWorkflowRunStore
    from app.learn.workflow_worker import (
        LearningStageWorkerRegistry,
        compose_test_benchmark_worker_supervision_root,
    )

    store = None
    try:
        model_server.MODEL_SERVER_LEASE_DIR = Path(lease_dir)
        corpus = validate_preloaded_provider_corpus(
            raw=corpus_raw, expected_sha256=corpus_file_sha
        )
        store = LearningWorkflowRunStore(state_path=Path(state_path))
        root = compose_test_benchmark_worker_supervision_root(
            journal_root=Path(worker_root),
            test_capability=object(),
            workflow_store=store,
            test_store_capability=object(),
        )

        def _recorded_process_factory(*, target, args, name):
            return multiprocessing.get_context("spawn").Process(
                target=_recorded_qwen_benchmark_worker_entry,
                args=(
                    target,
                    args,
                    release_event,
                    lease_dir,
                    str(args[3]),
                    recorded_response,
                ),
                name=name,
            )

        registry = LearningStageWorkerRegistry(
            result_root=Path(worker_root),
            process_factory=_recorded_process_factory,
            benchmark_supervision_root=root,
        )
        resolver = compose_test_provider_case_resolver(
            validated_corpus=corpus,
            provider_corpus_file_ref=corpus_file_ref,
            workflow_store=store,
            benchmark_supervision_root=root,
        )
        composition = compose_test_learning_workflow_service(
            store=store,
            worker_registry=registry,
            project_root=Path(project_root),
            benchmark_supervision_root=root,
            provider_case_resolver=resolver,
        )
        started = start_guarded_learning_stage_worker(
            composition=composition,
            run_id=run_id,
            expected_revision=store.get(run_id)["revision"],
            stage=stage,
            operation_id=operation_id,
            task_kind="vision_observe_screen",
            payload={
                "benchmark_v2_incumbent": {
                    "provider_case_ref": case_ref,
                    "window_binding_ref": window_binding_ref,
                    "capture_ref": capture_ref,
                }
            },
        )
        state = store.get(run_id)
        operation = state["stages"][stage]["evidence_refs"]["stage_execution"][
            "benchmark_v2_incumbent"
        ]
        launch_owner = registry.inspect_benchmark_worker_launch_owner(
            worker_id=started["worker_id"],
            run_id=run_id,
            stage=stage,
            operation_id=operation_id,
            reservation_ref=operation["reservation_ref"],
            expected_operation_anchor=state["stages"][stage]["evidence_refs"][
                "stage_execution"
            ]["benchmark_v2_operation_anchor"],
            supervision_root=root,
        )
        result_queue.put(
            {
                "status": "started",
                "authority_kind": root.authority_kind,
                "worker_id": started["worker_id"],
                "model_request_id": operation["worker_ref"]["model_request_id"],
                "execution_nonce": operation["execution_nonce"],
                "workflow_revision": state["revision"],
                "process_identity": launch_owner["process_identity"],
                "scope_name": launch_owner["scope_name"],
                "assignment_proven_ref": launch_owner["assignment_proven_ref"],
            }
        )
        if not cancel_event.wait(45):
            raise RuntimeError("cancel cut release timed out")

        original_persist = workflow_service._persist_benchmark_v2_incumbent_operation
        crashed = False

        def _persist_then_crash(**kwargs):
            nonlocal crashed
            persisted = original_persist(**kwargs)
            if kwargs["operation"].get("phase") == "cancel_intent" and not crashed:
                crashed = True
                durable = store.get(run_id)
                durable_operation = durable["stages"][stage]["evidence_refs"][
                    "stage_execution"
                ]["benchmark_v2_incumbent"]
                result_queue.put(
                    {
                        "status": "intent_durable",
                        "revision": durable["revision"],
                        "operation": durable_operation,
                    }
                )
                raise RuntimeError("crash after durable cancel intent")
            return persisted

        workflow_service._persist_benchmark_v2_incumbent_operation = _persist_then_crash
        try:
            cancel_guarded_learning_workflow_stage_operation(
                composition=composition,
                run_id=run_id,
                expected_revision=store.get(run_id)["revision"],
                stage=stage,
                operation_id=operation_id,
                reason="recorded Qwen durable cancel cut",
            )
        except RuntimeError as error:
            if str(error) != "crash after durable cancel intent":
                raise
        if not crashed:
            raise RuntimeError("durable cancel cut was not reached")
    except BaseException as error:
        result_queue.put(
            {
                "status": "error",
                "error_type": type(error).__name__,
                "details": str(error),
                "traceback": traceback.format_exc(),
            }
        )
        raise
    finally:
        if store is not None:
            store.close()


def _recorded_qwen_incumbent_cancel_resume_cut(
    project_root: str,
    state_path: str,
    worker_root: str,
    lease_dir: str,
    corpus_raw: bytes,
    corpus_file_sha: str,
    corpus_file_ref: dict[str, object],
    run_id: str,
    stage: str,
    operation_id: str,
    result_queue,
) -> None:
    import traceback

    from app.core import model_server
    from app.learn.hybrid.benchmark_v2_provider_corpus import (
        compose_test_provider_case_resolver,
        validate_preloaded_provider_corpus,
    )
    from app.learn.workflow_service import (
        cancel_guarded_learning_workflow_stage_operation,
        compose_test_learning_workflow_service,
    )
    from app.learn.workflow_store import LearningWorkflowRunStore
    from app.learn.workflow_worker import (
        LearningStageWorkerRegistry,
        compose_test_benchmark_worker_supervision_root,
    )

    store = None
    try:
        model_server.MODEL_SERVER_LEASE_DIR = Path(lease_dir)
        corpus = validate_preloaded_provider_corpus(
            raw=corpus_raw, expected_sha256=corpus_file_sha
        )
        store = LearningWorkflowRunStore(state_path=Path(state_path))
        root = compose_test_benchmark_worker_supervision_root(
            journal_root=Path(worker_root),
            test_capability=object(),
            workflow_store=store,
            test_store_capability=object(),
        )
        registry = LearningStageWorkerRegistry(
            result_root=Path(worker_root), benchmark_supervision_root=root
        )
        resolver = compose_test_provider_case_resolver(
            validated_corpus=corpus,
            provider_corpus_file_ref=corpus_file_ref,
            workflow_store=store,
            benchmark_supervision_root=root,
        )
        composition = compose_test_learning_workflow_service(
            store=store,
            worker_registry=registry,
            project_root=Path(project_root),
            benchmark_supervision_root=root,
            provider_case_resolver=resolver,
        )
        result = cancel_guarded_learning_workflow_stage_operation(
            composition=composition,
            run_id=run_id,
            expected_revision=store.get(run_id)["revision"],
            stage=stage,
            operation_id=operation_id,
            reason="resume recorded Qwen durable cancel",
        )
        result_queue.put({"status": "ok", "result": result})
    except BaseException as error:
        result_queue.put(
            {
                "status": "error",
                "error_type": type(error).__name__,
                "details": str(error),
                "traceback": traceback.format_exc(),
            }
        )
        raise
    finally:
        if store is not None:
            store.close()


@pytest.fixture(scope="module")
def validated_provider_snapshot(tmp_path_factory: pytest.TempPathFactory):
    from app.learn.hybrid.benchmark_v2_privileged_projector import (
        project_provider_corpus,
    )
    from app.learn.hybrid.benchmark_v2_provider_corpus import (
        validate_preloaded_provider_corpus,
    )
    from app.learn.recognition.uei.canonical import seal_immutable

    root = tmp_path_factory.mktemp("incumbent-provider-corpus")
    path = root / "provider-corpus.v2.json"
    receipt = project_provider_corpus(
        parent_manifest_path=PARENT_MANIFEST,
        output_path=path,
    )
    raw = path.read_bytes()
    corpus = validate_preloaded_provider_corpus(
        raw=raw,
        expected_sha256=receipt["file_sha256"],
    )
    corpus_file_ref = seal_immutable(
        {
            "contract_version": "benchmark_v2_provider_corpus_file_ref_v1",
            "relative_path": "provider-corpus.v2.json",
            "file_sha256": receipt["file_sha256"],
            "source_parent_ref": {
                "content_sha256": corpus["source_parent_ref"]["content_sha256"]
            },
        }
    )
    return corpus, corpus_file_ref


def _test_pair(tmp_path: Path, validated_provider_snapshot):
    from app.learn.hybrid.benchmark_v2_provider_corpus import (
        compose_test_provider_case_resolver,
    )
    from app.learn.workflow_store import LearningWorkflowRunStore
    from app.learn.workflow_worker import (
        LearningStageWorkerRegistry,
        compose_test_benchmark_worker_supervision_root,
    )

    store = LearningWorkflowRunStore(state_path=tmp_path / "state.json")
    worker_root = tmp_path / "workers"
    root = compose_test_benchmark_worker_supervision_root(
        journal_root=worker_root,
        test_capability=object(),
        workflow_store=store,
        test_store_capability=object(),
    )
    registry = LearningStageWorkerRegistry(
        result_root=worker_root,
        benchmark_supervision_root=root,
    )
    corpus, corpus_file_ref = validated_provider_snapshot
    resolver = compose_test_provider_case_resolver(
        validated_corpus=corpus,
        provider_corpus_file_ref=corpus_file_ref,
        workflow_store=store,
        benchmark_supervision_root=root,
    )
    return store, registry, root, resolver


def _case_ref(resolver) -> dict[str, str]:
    from app.learn.hybrid.benchmark_v2_provider_corpus import (
        provider_case_resolver_case_refs,
    )

    return provider_case_resolver_case_refs(resolver)[0]


def _binding_for_case(tmp_path: Path, case: dict[str, object], operation_id: str):
    from app.learn.hybrid.benchmark_v2_contracts import canonical_json_bytes, content_sha256

    image_path = (PROJECT_ROOT / str(case["image"]["path"])).resolve()
    image_sha = hashlib.sha256(image_path.read_bytes()).hexdigest()
    process_identity = {"pid": 101, "create_time_ns": 202}
    job_ref = {
        "contract_version": "portfolio_hybrid_benchmark_v2_worker_job_membership_ref_v1",
        "job_name": "Local\\AgentGuiBenchmarkWorkerTest-" + "b" * 64,
        "process_identity": process_identity,
        "member_pids": [101],
    }
    job_ref["content_sha256"] = content_sha256(job_ref)
    binding = {
        "contract_version": "portfolio_hybrid_benchmark_v2_worker_window_binding_v1",
        "operation_id": operation_id,
        "exact_hwnd": 303,
        "process_identity": process_identity,
        "job_name": job_ref["job_name"],
        "job_membership_ref": job_ref,
        "screenshot_sha256": image_sha,
        "capture_sha256": image_sha,
        "capture_image_path": str(image_path),
        "image_dimensions": {"width": 1280, "height": 720},
        "owner_journal_path": str((tmp_path / "owner.json").resolve()),
        "owner_journal_content_sha256": "1" * 64,
        "owner_ready_event_sha256": "2" * 64,
        "owner_binding_content_sha256": "3" * 64,
        "owner_id": "owner-1",
        "expected_uia_root_hwnd": 303,
        "expected_uia_owner_pid": 101,
        "expected_uia_root_content_sha256": "4" * 64,
        "window_class": "BenchmarkFixtureWindow",
        "window_title": "Benchmark fixture",
        "window_rect": {"left": 0, "top": 0, "right": 1280, "bottom": 720},
        "client_rect": {
            "left": 0,
            "top": 0,
            "right": 1280,
            "bottom": 720,
            "width": 1280,
            "height": 720,
        },
        "dpi": 96,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "display_only": True,
    }
    binding["payload_sha256"] = hashlib.sha256(
        canonical_json_bytes(binding)
    ).hexdigest()
    return binding, image_sha


def _prepared_document(
    source_bundle: dict[str, object], *, prepared_revision: int = 7
) -> dict[str, object]:
    from app.learn.hybrid.benchmark_v2_incumbent_operation import (
        compose_benchmark_v2_incumbent_operation,
    )

    source = source_bundle["handler_payload_source"]
    return compose_benchmark_v2_incumbent_operation(
        run_id="run-c1",
        stage="screen_understanding",
        operation_id="operation-c1",
        operation_anchor_ref={"content_sha256": "1" * 64},
        reservation_ref={"content_sha256": "2" * 64},
        supervision_inputs_ref={"content_sha256": "3" * 64},
        expected_supervision_ref={"content_sha256": "4" * 64},
        prepared_revision=prepared_revision,
        handler_payload_source=source,
        handler_payload_source_ref=source_bundle["handler_payload_source_ref"],
        window_binding_ref=source["window_binding_ref"],
        capture_ref=source["capture_ref"],
        execution_nonce="5" * 32,
        worker_ref={
            "worker_id": "worker-c1",
            "model_request_id": "request-c1",
            "payload_sha256": source["handler_payload_sha256"],
            "execution_nonce": "5" * 32,
            "reservation_ref": {"content_sha256": "2" * 64},
            "supervision_ref": None,
        },
    )


def _provider_owner_changes() -> dict[str, object]:
    return {
        "provider_reservation_ref": {"content_sha256": "6" * 64},
        "acquisition_owner_ref": {"content_sha256": "f" * 64},
        "acquisition_intent_ref": {"content_sha256": "7" * 64},
        "runtime_owner_ref": {"content_sha256": "8" * 64},
    }


def _result_ready_document(
    source_bundle: dict[str, object], *, result_identity: dict[str, object]
) -> dict[str, object]:
    from app.learn.hybrid.benchmark_v2_incumbent_operation import (
        transition_benchmark_v2_incumbent_operation,
    )

    operation = _prepared_document(source_bundle)
    operation = transition_benchmark_v2_incumbent_operation(
        operation,
        to_phase="provider_owner_prepared",
        changes=_provider_owner_changes(),
    )
    operation = transition_benchmark_v2_incumbent_operation(
        operation, to_phase="worker_starting", changes={}
    )
    operation = transition_benchmark_v2_incumbent_operation(
        operation,
        to_phase="worker_bound",
        changes={
            "worker_ref": {
                **operation["worker_ref"],
                "supervision_ref": {"content_sha256": "9" * 64},
            }
        },
    )
    return transition_benchmark_v2_incumbent_operation(
        operation,
        to_phase="result_ready",
        changes={"result_identity_ref": result_identity},
    )


def test_parent_seal_dispatch_rejects_the_wrong_canonical_form() -> None:
    from app.learn.hybrid import benchmark_v2_incumbent_operation as incumbent
    from app.learn.hybrid.benchmark_v2_contracts import content_sha256
    from app.learn.recognition.uei.canonical import seal_immutable

    parent_body = {
        "contract_version": "benchmark_worker_cleanup_receipt_v1",
        "process_identity": {
            "pid": 321,
            "create_time_ns": 1_787_780_587_306_627_584,
        },
    }
    runtime_parent = seal_immutable(parent_body)
    assert (
        incumbent._runtime_sealed_parent(runtime_parent, "runtime parent")
        == runtime_parent
    )

    wrong_parent = deepcopy(parent_body)
    wrong_parent["content_sha256"] = content_sha256(wrong_parent)
    assert wrong_parent["content_sha256"] != runtime_parent["content_sha256"]
    with pytest.raises(ValueError, match="content SHA mismatch"):
        incumbent._runtime_sealed_parent(wrong_parent, "runtime parent")


def test_incumbent_intent_rejects_runtime_jcs_seal() -> None:
    from app.learn.hybrid.benchmark_v2_incumbent_operation import (
        validate_benchmark_v2_incumbent_terminal_intent,
    )
    from app.learn.recognition.uei.canonical import seal_immutable

    wrong_intent = seal_immutable(
        {
            "contract_version": "benchmark_v2_incumbent_terminal_intent_v1",
            "run_id": "run-seal",
            "stage": "screen_understanding",
            "operation_id": "operation-seal",
            "worker_id": "worker-seal",
            "model_request_id": "request-seal",
            "payload_sha256": "1" * 64,
            "result_sha256": "2" * 64,
            "normal_binding_evidence_ref": {"content_sha256": "5" * 64},
            "provider_cleanup_evidence_ref": {"content_sha256": "6" * 64},
            "worker_cleanup_evidence_ref": {"content_sha256": "c" * 64},
            "intent_revision": 1_787_780_587_306_627_584,
            "intent_at": "2026-08-27T00:00:00+00:00",
            "predecessor_content_sha256": "d" * 64,
        }
    )
    with pytest.raises(ValueError, match="terminal intent content SHA mismatch"):
        validate_benchmark_v2_incumbent_terminal_intent(wrong_intent)

@pytest.fixture
def source_bundle(tmp_path: Path, validated_provider_snapshot):
    from app.learn.hybrid.benchmark_v2_incumbent_operation import (
        compose_benchmark_v2_incumbent_payload_projection,
    )

    store, registry, root, resolver = _test_pair(
        tmp_path, validated_provider_snapshot
    )
    case_ref = _case_ref(resolver)
    case = resolver.resolve(case_ref)
    binding, image_sha = _binding_for_case(tmp_path, case, "operation-c1")
    result = compose_benchmark_v2_incumbent_payload_projection(
        provider_case_resolver=resolver,
        provider_case_ref=case_ref,
        window_binding_ref={
            "id": "binding-c1",
            "content_sha256": binding["payload_sha256"],
        },
        capture_ref={"id": "capture-c1", "content_sha256": image_sha},
        serialized_window_binding=binding,
    )
    result["provider_case_resolver"] = resolver
    yield result
    store.close()


def test_incumbent_child_identity_resolves_only_its_deterministic_parent(
    source_bundle: dict[str, object],
) -> None:
    from app.learn.hybrid.benchmark_v2_contracts import content_sha256
    from app.learn.hybrid.benchmark_v2_incumbent_operation import (
        resolve_benchmark_v2_incumbent_parent_identity,
    )

    payload = deepcopy(source_bundle["authoritative_payload"])
    serialized = payload["_benchmark_v2_window_binding"]
    parent_run_id = "benchmark-v2-run-parent"
    parent_operation_id = str(serialized["operation_id"])
    stage = "screen_understanding"
    case_id = payload["metadata"]["case_id"]
    token = content_sha256(
        {
            "contract_version": "benchmark_v2_incumbent_child_slot_identity_v1",
            "parent_run_id": parent_run_id,
            "parent_stage": stage,
            "parent_operation_id": parent_operation_id,
            "case_id": case_id,
        }
    )
    separator = "::benchmark-v2-incumbent::"
    worker_identity = {
        "run_id": f"{parent_run_id}{separator}{token}",
        "stage": stage,
        "operation_id": f"{parent_operation_id}{separator}{token}",
    }

    assert resolve_benchmark_v2_incumbent_parent_identity(
        run_id=worker_identity["run_id"],
        stage=worker_identity["stage"],
        operation_id=worker_identity["operation_id"],
        case_id=case_id,
    ) == (parent_run_id, parent_operation_id)

    stale_identity = deepcopy(worker_identity)
    stale_identity["operation_id"] = (
        f"{parent_operation_id}{separator}{'f' * 64}"
    )
    with pytest.raises(ValueError, match="child binding identity"):
        resolve_benchmark_v2_incumbent_parent_identity(
            run_id=stale_identity["run_id"],
            stage=stale_identity["stage"],
            operation_id=stale_identity["operation_id"],
            case_id=case_id,
        )


def test_resolver_is_opaque_exact_and_returns_a_deepcopy(
    tmp_path: Path, validated_provider_snapshot
) -> None:
    from app.learn.hybrid.benchmark_v2_provider_corpus import (
        compose_test_provider_case_resolver,
    )
    from app.learn.recognition.uei.canonical import seal_immutable

    store, registry, root, resolver = _test_pair(tmp_path, validated_provider_snapshot)
    ref = _case_ref(resolver)
    first = resolver.resolve(ref)
    first["goal"] = "mutated"
    assert resolver.resolve(ref)["goal"] != "mutated"
    with pytest.raises(ValueError, match="closed case ref"):
        resolver.resolve({**ref, "path": "forbidden.json"})
    with pytest.raises(ValueError, match="case identity"):
        resolver.resolve({**ref, "case_content_sha256": "f" * 64})
    with pytest.raises(TypeError):
        json.dumps(resolver)
    corpus, corpus_file_ref = validated_provider_snapshot
    wrong_file_ref = deepcopy(corpus_file_ref)
    wrong_file_ref.pop("content_sha256")
    wrong_file_ref["file_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="file SHA.*validated snapshot"):
        compose_test_provider_case_resolver(
            validated_corpus=corpus,
            provider_corpus_file_ref=seal_immutable(wrong_file_ref),
            workflow_store=store,
            benchmark_supervision_root=root,
        )
    store.close()


def test_composition_rejects_cross_pair_before_store_or_registry_mutation(
    tmp_path: Path, validated_provider_snapshot
) -> None:
    from app.learn.workflow_service import compose_test_learning_workflow_service
    from app.learn.workflow_store import LearningWorkflowRunStore

    store, registry, root, resolver = _test_pair(
        tmp_path / "one", validated_provider_snapshot
    )
    other_store = LearningWorkflowRunStore(state_path=tmp_path / "other.json")
    with pytest.raises(ValueError, match="same test store"):
        compose_test_learning_workflow_service(
            store=other_store,
            worker_registry=registry,
            project_root=tmp_path,
            benchmark_supervision_root=root,
            provider_case_resolver=resolver,
        )
    composition = compose_test_learning_workflow_service(
        store=store,
        worker_registry=registry,
        project_root=tmp_path,
        benchmark_supervision_root=root,
        provider_case_resolver=resolver,
    )
    assert composition.store is store
    assert composition.worker_registry is registry
    assert composition.composition_kind == "test"
    store.close()
    other_store.close()


def test_guarded_entry_rejects_direct_unminted_composition_before_registry_use(
    tmp_path: Path,
) -> None:
    from app.learn import workflow_service

    calls: list[str] = []

    class _Registry(_UnitCleanupReceiptAuthority):
        def status(self, **_kwargs):
            calls.append("status")
            raise AssertionError("unminted composition reached Registry")

    composition = workflow_service.LearningWorkflowServiceComposition(
        store=object(),
        worker_registry=_Registry(),
        project_root=tmp_path,
        composition_kind="test",
        benchmark_supervision_root=None,
        provider_case_resolver=None,
    )
    with pytest.raises(
        workflow_service.LearningWorkflowStageOperationError,
        match="factory-minted",
    ):
        workflow_service.status_guarded_learning_stage_worker(
            composition=composition,
            worker_id="worker-unminted",
            run_id="run-unminted",
            operation_id="operation-unminted",
        )
    assert calls == []


def test_guarded_entry_rejects_component_substitution_on_a_factory_mint(
    tmp_path: Path,
) -> None:
    from dataclasses import replace
    from app.learn import workflow_service

    class _Registry(_UnitCleanupReceiptAuthority):
        def status(self, **_kwargs):
            return {"status": "running"}

    minted = workflow_service.compose_test_learning_workflow_service_unit(
        store=object(),
        worker_registry=_Registry(),
        project_root=tmp_path,
    )
    substituted = replace(minted, worker_registry=_Registry())
    with pytest.raises(
        workflow_service.LearningWorkflowStageOperationError,
        match="factory-minted",
    ):
        workflow_service.status_guarded_learning_stage_worker(
            composition=substituted,
            worker_id="worker-substituted",
            run_id="run-substituted",
            operation_id="operation-substituted",
        )


def test_operation_lock_key_is_exact_and_shared(tmp_path: Path) -> None:
    from app.learn.workflow_service import get_learning_workflow_operation_lock
    from app.learn.workflow_store import LearningWorkflowRunStore

    store = LearningWorkflowRunStore()
    first = get_learning_workflow_operation_lock(
        store=store, run_id="run", operation_id="operation"
    )
    assert first is get_learning_workflow_operation_lock(
        store=store, run_id="run", operation_id="operation"
    )
    assert first is not get_learning_workflow_operation_lock(
        store=store, run_id="run-2", operation_id="operation"
    )


def test_benchmark_v2_c3_specialized_spine_surface_and_no_cascade() -> None:
    import app.learn.workflow_service as workflow_service

    expected = {
        "_start_benchmark_v2_incumbent_operation",
        "_resume_benchmark_v2_incumbent_operation",
        "_cancel_benchmark_v2_incumbent_operation",
    }
    for name in expected:
        assert callable(getattr(workflow_service, name))

    tree = ast.parse(
        (PROJECT_ROOT / "app/learn/workflow_service.py").read_text(encoding="utf-8")
    )
    forbidden = {
        "interpret_learning_stage_worker_result",
        "_ensure_next_managed_stage_operation",
        "_start_next_managed_stage_worker",
    }
    violations: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name not in expected:
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                called = (
                    child.func.id
                    if isinstance(child.func, ast.Name)
                    else child.func.attr
                    if isinstance(child.func, ast.Attribute)
                    else ""
                )
                if called in forbidden:
                    violations.append((called, child.lineno))
    assert violations == []


def test_benchmark_v2_c3_start_routes_before_generic_registry(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import app.learn.workflow_service as workflow_service

    events: list[str] = []

    class _Registry(_UnitCleanupReceiptAuthority):
        def start(self, **_kwargs):
            events.append("generic.start")
            raise AssertionError("benchmark start reached generic Registry.start")

    composition = workflow_service.compose_test_learning_workflow_service_unit(
        store=object(),
        worker_registry=_Registry(),
        project_root=tmp_path,
        benchmark_supervision_root=object(),
        provider_case_resolver=object(),
    )
    monkeypatch.setattr(
        workflow_service,
        "_start_benchmark_v2_incumbent_operation",
        lambda **kwargs: events.append("benchmark.start")
        or {
            "worker_id": "worker-c3",
            "request": deepcopy(kwargs["request"]),
        },
    )
    result = workflow_service.start_guarded_learning_stage_worker(
        composition=composition,
        run_id="run-c3",
        expected_revision=3,
        stage="screen_understanding",
        operation_id="operation-c3",
        task_kind="vision_observe_screen",
        payload={
            "benchmark_v2_incumbent": {
                "provider_case_ref": {
                    "case_id": "case-c3",
                    "case_content_sha256": "1" * 64,
                },
                "window_binding_ref": {"id": "binding-c3", "content_sha256": "2" * 64},
                "capture_ref": {"id": "capture-c3", "content_sha256": "3" * 64},
            }
        },
    )
    assert result["worker_id"] == "worker-c3"
    assert events == ["benchmark.start"]


def test_benchmark_v2_c3_continue_cancel_and_recover_route_one_resume_path(
    monkeypatch,
    tmp_path: Path,
    source_bundle: dict[str, object],
) -> None:
    import app.learn.workflow_service as workflow_service

    operation = _prepared_document(source_bundle)
    state = {
        "run_id": "run-c3",
        "revision": 7,
        "current_stage": "screen_understanding",
        "stages": {
            "screen_understanding": {
                "status": "running",
                "evidence_refs": {
                    "stage_execution": {
                        "contract_version": "learning_workflow_stage_operation_v1",
                        "owner": "backend_lease",
                        "operation_id": "operation-c3",
                        "benchmark_v2_incumbent": operation,
                    }
                },
            }
        },
    }

    class _Store:
        def get(self, _run_id):
            return deepcopy(state)

    class _Registry(_UnitCleanupReceiptAuthority):
        def read_adopted_result(self, **_kwargs):
            raise AssertionError("benchmark continue reached generic adopted-result reader")

        def cancel_by_operation(self, **_kwargs):
            raise AssertionError("benchmark cancel reached generic Registry.cancel")

    composition = workflow_service.compose_test_learning_workflow_service_unit(
        store=_Store(),
        worker_registry=_Registry(),
        project_root=tmp_path,
        benchmark_supervision_root=object(),
        provider_case_resolver=object(),
    )
    events: list[str] = []
    monkeypatch.setattr(
        workflow_service,
        "_recover_or_resume_benchmark_v2_incumbent_operation",
        lambda **_kwargs: events.append("resume") or {"status": "complete"},
    )
    monkeypatch.setattr(
        workflow_service,
        "_cancel_benchmark_v2_incumbent_operation",
        lambda **_kwargs: events.append("cancel") or {"status": "cancelled"},
    )
    monkeypatch.setattr(
        workflow_service,
        "require_active_learning_workflow_stage_operation",
        lambda **_kwargs: state["stages"]["screen_understanding"]["evidence_refs"]["stage_execution"],
    )
    assert workflow_service.continue_guarded_learning_stage_worker_result(
        composition=composition,
        run_id="run-c3",
        expected_revision=7,
        stage="screen_understanding",
        operation_id="operation-c3",
        worker_id="worker-c1",
    ) == {"status": "complete"}
    assert workflow_service.cancel_guarded_learning_workflow_stage_operation(
        composition=composition,
        run_id="run-c3",
        expected_revision=7,
        stage="screen_understanding",
        operation_id="operation-c3",
        reason="operator cancel",
    ) == {"status": "cancelled"}
    assert workflow_service.recover_guarded_learning_workflow_stage_operation(
        composition=composition,
        run_id="run-c3",
        expected_revision=7,
    ) == {"status": "complete"}
    assert events == ["resume", "cancel", "resume"]


def test_benchmark_v2_c3_start_persists_exact_phases_before_launch(
    tmp_path: Path,
    validated_provider_snapshot,
    monkeypatch,
) -> None:
    from app.learn.recognition.uei.canonical import content_sha256, seal_immutable
    from app.learn.workflow_service import (
        compose_test_learning_workflow_service_unit,
        start_guarded_learning_stage_worker,
        start_learning_workflow_stage_operation,
    )

    store, _real_registry, root, resolver = _test_pair(
        tmp_path / "pair", validated_provider_snapshot
    )
    events: list[str] = []
    operation_id = "operation-c3-start"
    case_ref = _case_ref(resolver)
    case = resolver.resolve(case_ref)
    binding, image_sha = _binding_for_case(tmp_path, case, operation_id)

    class _Registry(_UnitCleanupReceiptAuthority):
        def __init__(self) -> None:
            self.reservation = None
            self.anchored = None
            self.provider = None
            self.launch_owner = None

        def prepare_benchmark_worker_identity(self, **kwargs):
            events.append("prepare")
            source = deepcopy(kwargs["handler_payload_source"])
            reservation = seal_immutable(
                {
                    "contract_version": "benchmark_worker_identity_reservation_v1",
                    "authority_kind": root.authority_kind,
                    "run_id": kwargs["run_id"],
                    "stage": kwargs["stage"],
                    "operation_id": kwargs["operation_id"],
                    "workflow_revision": kwargs["workflow_revision"],
                    "task_kind": kwargs["task_kind"],
                    "payload_sha256": source["handler_payload_sha256"],
                    "handler_payload_source": source,
                    "handler_payload_source_ref": {
                        "contract_version": "benchmark_v2_incumbent_handler_payload_source_ref_v1",
                        "content_sha256": source["content_sha256"]
                    },
                    "worker_id": "1" * 32,
                    "model_request_id": "request-c3-start",
                    "execution_nonce": "2" * 32,
                    "supervision_inputs_ref": {
                        "content_sha256": content_sha256(
                            {
                                "authority_kind": root.authority_kind,
                                "store_identity_sha256": root.store_identity_sha256,
                                "journal_root": str(root.journal_root.resolve()),
                            }
                        )
                    },
                    "reservation_state": "reserved",
                    "abort_observation_ref": None,
                    "predecessor_content_sha256": source["content_sha256"],
                }
            )
            self.reservation = reservation
            return deepcopy(reservation)

        def confirm_prepared_benchmark_worker_anchor(self, **_kwargs):
            events.append("confirm")
            anchored_body = deepcopy(self.reservation)
            anchored_body.pop("content_sha256")
            anchored_body["reservation_state"] = "anchored"
            anchored_body["predecessor_content_sha256"] = self.reservation[
                "content_sha256"
            ]
            self.anchored = seal_immutable(anchored_body)
            return {
                "anchored_reservation_ref": {
                    "content_sha256": self.anchored["content_sha256"]
                }
            }

        def inspect_prepared_benchmark_worker_identity(self, **_kwargs):
            events.append("inspect")
            return deepcopy(self.anchored)

        def prepare_benchmark_provider_acquisition(self, **kwargs):
            events.append("provider")
            self.provider = seal_immutable(
                {
                    "contract_version": "benchmark_provider_acquisition_ref_v1",
                    "authority_kind": root.authority_kind,
                    "run_id": "run-c3-start",
                    "stage": "screen_understanding",
                    "operation_id": operation_id,
                    "worker_id": "1" * 32,
                    "model_request_id": "request-c3-start",
                    "payload_sha256": self.reservation["payload_sha256"],
                    "reservation_ref": deepcopy(kwargs["reservation_ref"]),
                    "acquisition_owner_ref": {"content_sha256": "f" * 64},
                    "acquisition_intent_ref": {"content_sha256": "3" * 64},
                    "prepared_acquisition_observation_ref": {
                        "content_sha256": "7" * 64
                    },
                    "prepared_materialization_ledger_ref": {
                        "content_sha256": "8" * 64
                    },
                    "acquisition_observation_ref": {"content_sha256": "7" * 64},
                    "materialization_ledger_ref": {"content_sha256": "8" * 64},
                    "runtime_owner_ref": {
                        "content_sha256": kwargs["runtime_owner_ref"][
                            "content_sha256"
                        ]
                    },
                }
            )
            return deepcopy(self.provider)

        def launch_prepared_benchmark_worker(self, **kwargs):
            events.append("launch")
            assert kwargs["authoritative_payload"]["provider_mode"] == "local_understanding"
            self.authoritative_payload = deepcopy(kwargs["authoritative_payload"])
            return {
                "contract_version": "learning_stage_worker_v1",
                "worker_id": "1" * 32,
                "run_id": "run-c3-start",
                "stage": "screen_understanding",
                "operation_id": operation_id,
                "task_kind": "vision_observe_screen",
                "status": "running",
            }

        def inspect_benchmark_worker_launch_owner(self, **kwargs):
            events.append("launch_owner")
            if self.launch_owner is None:
                self.launch_owner = seal_immutable(
                    {
                        "contract_version": "benchmark_worker_launch_owner_inspection_v1",
                        "authority_kind": root.authority_kind,
                        "run_id": "run-c3-start",
                        "stage": "screen_understanding",
                        "operation_id": operation_id,
                        "worker_id": "1" * 32,
                        "model_request_id": "request-c3-start",
                        "payload_sha256": self.reservation["payload_sha256"],
                        "execution_nonce": self.reservation["execution_nonce"],
                        "reservation_ref": deepcopy(kwargs["reservation_ref"]),
                        "current_reservation_ref": {"content_sha256": "4" * 64},
                        "operation_anchor_ref": {
                            "content_sha256": kwargs["expected_operation_anchor"][
                                "anchor_identity_sha256"
                            ]
                        },
                        "expected_supervision_ref": deepcopy(
                            kwargs["expected_operation_anchor"][
                                "expected_supervision_ref"
                            ]
                        ),
                        "supervision_ref": {"content_sha256": "6" * 64},
                        "reservation_state": "launched",
                        "owner_phase": "gate_released",
                        "assignment_state": "proven",
                        "process_identity": {"pid": 321, "create_time_ns": 654},
                        "scope_name": "Local\\AgentGuiBenchmarkWorker-" + "1" * 64,
                        "assignment_proven_ref": {"content_sha256": "5" * 64},
                        "artifact_is_authorization": False,
                        "execute_binding_enabled": False,
                    }
                )
            if "worker_cleanup" in events:
                after = deepcopy(self.launch_owner)
                after.pop("content_sha256")
                after["owner_phase"] = "cleanup_finalization_intent"
                return seal_immutable(after)
            return deepcopy(self.launch_owner)

        def inspect_completed_result_identity(self, **_kwargs):
            events.append("inspect_result")
            return {
                "contract_version": "learning_stage_worker_completed_result_identity_v1",
                "status": "completed",
                "worker_id": "1" * 32,
                "run_id": "run-c3-start",
                "stage": "screen_understanding",
                "operation_id": operation_id,
                "task_kind": "vision_observe_screen",
                "model_request_id": "request-c3-start",
                "payload_sha256": self.reservation["payload_sha256"],
                "result_sha256": "a" * 64,
                "result_available": True,
                "normal_binding_evidence_ref": {"content_sha256": "b" * 64},
                "provider_cleanup_evidence_ref": {"content_sha256": "c" * 64},
            }

        def adopt_result(self, **_kwargs):
            events.append("adopt")
            from app.learn.hybrid import benchmark_v2_dispatch_attestation as dispatch

            context = self.authoritative_payload[
                "_benchmark_v2_dispatch_context"
            ]
            with dispatch.install_benchmark_dispatch_attestor(
                dispatch_context=context
            ):
                dispatch.attest_benchmark_provider_dispatch(
                    provider="qwen",
                    operation_ref=context["operation_ref"],
                    window_binding=context["window_binding"],
                    provider_runtime={"fake": "qwen"},
                )
                dispatch_refs = dispatch.current_benchmark_dispatch_receipt_refs()
            response = {
                "success": True,
                "_benchmark_v2_provider_dispatch_receipt_refs": dispatch_refs,
            }
            validator = _kwargs.get("result_validator")
            if callable(validator):
                validator(deepcopy(response))
            return {
                "contract_version": "learning_stage_worker_result_adoption_v1",
                "status": "adopted",
                "receipt": {
                    "contract_version": "learning_stage_worker_result_adoption_v1",
                    "worker_id": "1" * 32,
                    "run_id": "run-c3-start",
                    "stage": "screen_understanding",
                    "operation_id": operation_id,
                    "task_kind": "vision_observe_screen",
                    "model_request_id": "request-c3-start",
                    "payload_sha256": self.reservation["payload_sha256"],
                    "result_sha256": "a" * 64,
                    "adopted_at": "2026-08-27T00:00:00+00:00",
                },
                "response": response,
            }

        def observe_benchmark_worker_cleanup(self, **_kwargs):
            events.append("worker_cleanup")
            return seal_immutable(
                {
                    "contract_version": "benchmark_worker_cleanup_receipt_v1",
                    "outcome": "verified_exact_worker_exited",
                    "operation_anchor_ref": self.launch_owner[
                        "operation_anchor_ref"
                    ],
                    "reservation_ref": self.launch_owner[
                        "current_reservation_ref"
                    ],
                    "supervision_ref": self.launch_owner["supervision_ref"],
                    "run_id": "run-c3-start",
                    "stage": "screen_understanding",
                    "operation_id": operation_id,
                    "worker_id": "1" * 32,
                    "process_identity": self.launch_owner["process_identity"],
                    "assignment_proven_ref": self.launch_owner[
                        "assignment_proven_ref"
                    ],
                    "finalization_intent_ref": {"content_sha256": "7" * 64},
                    "exact_handle_observation_refs": {
                        "process": {"content_sha256": "8" * 64}
                    },
                    "job_absence_observation_ref": {"content_sha256": "9" * 64},
                    "worker_absence_observation_ref": {"content_sha256": "d" * 64},
                    "supervisor_absence_observation_ref": None,
                    "reservation_abort_ref": None,
                    "artifact_is_authorization": False,
                    "execute_binding_enabled": False,
                }
            )

        def reconcile_benchmark_provider_cleanup(self, **_kwargs):
            events.append("provider_cleanup")
            return seal_immutable(
                {
                    "contract_version": "benchmark_provider_cleanup_ref_v1",
                    "status": "cleanup_verified",
                    "outcome": "verified_exact_process_exited",
                    "authority_kind": root.authority_kind,
                    "run_id": "run-c3-start",
                    "stage": "screen_understanding",
                    "operation_id": operation_id,
                    "worker_id": "1" * 32,
                    "model_request_id": "request-c3-start",
                    "payload_sha256": self.reservation["payload_sha256"],
                    "reservation_ref": self.provider["reservation_ref"],
                    "acquisition_owner_ref": self.provider[
                        "acquisition_owner_ref"
                    ],
                    "acquisition_intent_ref": self.provider[
                        "acquisition_intent_ref"
                    ],
                    "runtime_owner_ref": {
                        "content_sha256": self.provider["runtime_owner_ref"][
                            "content_sha256"
                        ]
                    },
                    "cleanup_receipt_ref": {"content_sha256": "c" * 64},
                }
            )

    registry = _Registry()
    try:
        from app.learn.hybrid import benchmark_v2_dispatch_attestation as dispatch

        monkeypatch.setattr(dispatch, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(
            dispatch,
            "_attest_exact_window",
            lambda value: {"content_sha256": "e" * 64},
        )

        def _exact_provider_attestation(provider, _value):
            process = {"pid": 101, "create_time_ns": 202}
            profile_sha256 = "f" * 64
            identity = dispatch.compose_benchmark_provider_runtime_identity(
                provider=provider,
                lease_identity={
                    "lease_id": "lease-c3-start",
                    "incarnation_id": "incarnation-c3-start",
                    "owner_request_id": "request-c3-start",
                },
                profile_ref={"content_sha256": profile_sha256},
                listener_owner={
                    "host": "127.0.0.1",
                    "port": 8080,
                    "process_identities": [process],
                },
                process_identities=[process],
                process_scope={
                    "scope_name": "scope-c3-start",
                    "member_pids": [process["pid"]],
                    "process_identities": [process],
                },
            )
            return {
                "runtime_identity": identity,
                "profile": {
                    "profile_id": "profile-c3-start",
                    "profile_sha256": profile_sha256,
                    "profile_payload_sha256": profile_sha256,
                },
                "installed_configuration_snapshot": None,
            }

        monkeypatch.setattr(
            dispatch,
            "_attest_exact_provider_runtime",
            _exact_provider_attestation,
        )
        binding_started = store.transition(
            run_id="run-c3-start",
            expected_revision=0,
            stage="bind_capture",
            outcome="running",
            evidence_refs={},
        )
        initial = store.transition(
            run_id="run-c3-start",
            expected_revision=binding_started["revision"],
            stage="bind_capture",
            outcome="completed",
            evidence_refs={"image_path": str((PROJECT_ROOT / str(case["image"]["path"])).resolve())},
        )
        started_operation = start_learning_workflow_stage_operation(
            store=store,
            project_root=tmp_path,
            run_id="run-c3-start",
            expected_revision=initial["revision"],
            stage="screen_understanding",
            operation_id=operation_id,
        )
        composition = compose_test_learning_workflow_service_unit(
            store=store,
            worker_registry=registry,
            project_root=tmp_path,
            benchmark_supervision_root=root,
            provider_case_resolver=resolver,
            benchmark_v2_worker_binding_resolver=object(),
        )
        monkeypatch.setattr(
            "app.learn.hybrid.benchmark_v2_worker_binding.resolve_server_worker_window_binding",
            lambda **kwargs: {
                "serialized_window_binding": deepcopy(binding),
                "worker_process_identity": deepcopy(
                    kwargs.get("worker_process_identity")
                ),
                "normal_binding_evidence_ref": deepcopy(
                    kwargs.get("normal_binding_evidence_ref")
                ),
            },
        )
        result = start_guarded_learning_stage_worker(
            composition=composition,
            run_id="run-c3-start",
            expected_revision=started_operation["workflow_state"]["revision"],
            stage="screen_understanding",
            operation_id=operation_id,
            task_kind="vision_observe_screen",
            payload={
                "benchmark_v2_incumbent": {
                    "provider_case_ref": case_ref,
                    "window_binding_ref": {
                        "id": "binding-c3-start",
                        "content_sha256": binding["payload_sha256"],
                    },
                    "capture_ref": {
                        "id": "capture-c3-start",
                        "content_sha256": image_sha,
                    },
                }
            },
        )
        assert result["worker_id"] == "1" * 32
        assert events == [
            "prepare",
            "confirm",
            "inspect",
            "provider",
            "launch",
            "launch_owner",
        ]
        current = store.get("run-c3-start")
        operation = current["stages"]["screen_understanding"]["evidence_refs"][
            "stage_execution"
        ]["benchmark_v2_incumbent"]
        durable_bytes = json.dumps(current, ensure_ascii=False, sort_keys=True)
        for forbidden_name in (
            "benchmark_v2_incumbent_request",
            "serialized_window_binding",
            "capture_image_path",
            "owner_journal_path",
        ):
            assert forbidden_name not in durable_bytes
        assert operation["phase"] == "worker_bound"
        assert operation["current_document_revision"] == current["revision"]
        monkeypatch.setattr(
            "app.learn.hybrid.benchmark_v2_worker_binding.validate_benchmark_v2_worker_window_binding_adoption_from_resolver",
            lambda **_kwargs: seal_immutable(
                {
                    "contract_version": "portfolio_hybrid_benchmark_v2_worker_window_binding_adoption_v1",
                    "normal_clear_receipt_ref": "b" * 64,
                    "artifact_is_authorization": False,
                    "execute_binding_enabled": False,
                }
            ),
        )
        from app.learn.workflow_service import continue_guarded_learning_stage_worker_result

        completed = continue_guarded_learning_stage_worker_result(
            composition=composition,
            run_id="run-c3-start",
            expected_revision=current["revision"],
            stage="screen_understanding",
            operation_id=operation_id,
            worker_id="1" * 32,
        )
        terminal_bytes = json.dumps(
            completed["terminal_receipt"], sort_keys=True, separators=(",", ":")
        )
        replay_state = store.get("run-c3-start")
        replay = continue_guarded_learning_stage_worker_result(
            composition=composition,
            run_id="run-c3-start",
            expected_revision=replay_state["revision"],
            stage="screen_understanding",
            operation_id=operation_id,
            worker_id="1" * 32,
        )
        assert replay["status"] == "complete"
        assert json.dumps(
            replay["terminal_receipt"], sort_keys=True, separators=(",", ":")
        ) == terminal_bytes
        assert events == [
            "prepare",
            "confirm",
            "inspect",
            "provider",
            "launch",
            "launch_owner",
            "inspect_result",
            "launch_owner",
            "worker_cleanup",
            "launch_owner",
            "provider_cleanup",
            "adopt",
        ]
    finally:
        store.close()


def test_payload_projection_is_literal_and_source_contains_no_raw_case(
    source_bundle: dict[str, object]
) -> None:
    from app.learn.hybrid.benchmark_v2_incumbent_operation import (
        BENCHMARK_V2_INCUMBENT_PAYLOAD_PROJECTION_RULES,
        validate_benchmark_v2_incumbent_handler_payload_source,
    )
    from app.learn.hybrid.benchmark_v2_contracts import content_sha256

    payload = source_bundle["authoritative_payload"]
    assert set(payload) == {
        "task",
        "app_name",
        "state_hint",
        "provider_mode",
        "agent_mode",
        "learn_depth",
        "write_policy",
        "metadata",
        "operation_context",
        "capture_live",
        "image_path",
        "_benchmark_v2_window_binding",
    }
    assert payload["provider_mode"] == "local_understanding"
    assert payload["capture_live"] is False
    source = validate_benchmark_v2_incumbent_handler_payload_source(
        source_bundle["handler_payload_source"]
    )
    assert source["projection_rules_content_sha256"] == content_sha256(
        BENCHMARK_V2_INCUMBENT_PAYLOAD_PROJECTION_RULES
    )
    serialized = json.dumps(source, sort_keys=True)
    assert "goal" not in serialized
    assert "image_path" not in serialized


@pytest.mark.parametrize("provider_mode", ["qwen", "local", "local_grounding", "api", None])
def test_payload_projection_rejects_wrong_mode_and_default(
    source_bundle: dict[str, object], provider_mode: str | None
) -> None:
    from app.learn.hybrid.benchmark_v2_incumbent_operation import (
        validate_benchmark_v2_incumbent_payload_projection,
    )

    payload = deepcopy(source_bundle["authoritative_payload"])
    payload["provider_mode"] = provider_mode
    with pytest.raises(ValueError, match="payload projection"):
        validate_benchmark_v2_incumbent_payload_projection(
            payload=payload,
            handler_payload_source=source_bundle["handler_payload_source"],
            provider_case_resolver=source_bundle["provider_case_resolver"],
            serialized_window_binding=payload["_benchmark_v2_window_binding"],
        )


def test_document_closed_hash_and_legal_transition_chain(
    source_bundle: dict[str, object]
) -> None:
    from app.learn.hybrid.benchmark_v2_incumbent_operation import (
        transition_benchmark_v2_incumbent_operation,
        validate_benchmark_v2_incumbent_operation,
    )

    prepared = _prepared_document(source_bundle)
    validated = validate_benchmark_v2_incumbent_operation(prepared)
    assert validated["phase"] == "prepared"
    owner_prepared = transition_benchmark_v2_incumbent_operation(
        validated,
        to_phase="provider_owner_prepared",
        changes=_provider_owner_changes(),
    )
    assert owner_prepared["predecessor_content_sha256"] == prepared["content_sha256"]
    assert owner_prepared["current_document_revision"] == 8
    with pytest.raises(ValueError, match="legal transition"):
        transition_benchmark_v2_incumbent_operation(
            owner_prepared,
            to_phase="complete",
            changes={},
        )
    assert owner_prepared["content_sha256"] != prepared["content_sha256"]


def test_intent_race_has_one_winner_and_forbidden_edge_has_zero_mutation(
    source_bundle: dict[str, object]
) -> None:
    from app.learn.hybrid.benchmark_v2_incumbent_operation import (
        compose_benchmark_v2_incumbent_cancel_intent,
        compose_benchmark_v2_incumbent_terminal_intent,
        transition_benchmark_v2_incumbent_operation,
    )
    from app.learn.workflow_service import get_learning_workflow_operation_lock
    from app.learn.workflow_store import LearningWorkflowRunStore

    document = _prepared_document(source_bundle)
    for phase, changes in (
        (
            "provider_owner_prepared",
            _provider_owner_changes(),
        ),
        ("worker_starting", {}),
        (
            "worker_bound",
            {
                "worker_ref": {
                    **document["worker_ref"],
                    "supervision_ref": {"content_sha256": "9" * 64},
                }
            },
        ),
        ("result_ready", {"result_identity_ref": {"content_sha256": "a" * 64}}),
    ):
        document = transition_benchmark_v2_incumbent_operation(
            document, to_phase=phase, changes=changes
        )
    store = LearningWorkflowRunStore()
    lock = get_learning_workflow_operation_lock(
        store=store, run_id=document["run_id"], operation_id=document["operation_id"]
    )
    holder = {"document": document}

    def compete(kind: str) -> str:
        with lock:
            current = holder["document"]
            try:
                if kind == "complete":
                    intent = compose_benchmark_v2_incumbent_terminal_intent(
                        operation=current,
                        result_sha256="a" * 64,
                        normal_binding_evidence_ref={"content_sha256": "c" * 64},
                        provider_cleanup_evidence_ref={"content_sha256": "d" * 64},
                        worker_cleanup_evidence_ref={"content_sha256": "e" * 64},
                        intent_at="2026-08-27T00:00:00+00:00",
                    )
                    target, changes = "terminal_intent", {"terminal_intent": intent}
                else:
                    intent = compose_benchmark_v2_incumbent_cancel_intent(
                        operation=current,
                        reason="race",
                        intent_at="2026-08-27T00:00:00+00:00",
                        process_identity=None,
                        scope_name=None,
                        assignment_proven_ref=None,
                    )
                    target, changes = "cancel_intent", {"cancel_intent": intent}
                holder["document"] = transition_benchmark_v2_incumbent_operation(
                    current, to_phase=target, changes=changes
                )
                return kind
            except ValueError:
                return "lost"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(compete, ("complete", "cancel")))
    assert outcomes.count("lost") == 1
    assert (holder["document"]["terminal_intent"] is None) != (
        holder["document"]["cancel_intent"] is None
    )


def test_terminal_replay_is_byte_identical_and_returns_deepcopy(
    source_bundle: dict[str, object]
) -> None:
    from app.learn.hybrid.benchmark_v2_incumbent_operation import (
        replay_benchmark_v2_incumbent_terminal,
        transition_benchmark_v2_incumbent_operation,
    )
    from app.learn.hybrid.benchmark_v2_contracts import canonical_json_bytes

    terminal = transition_benchmark_v2_incumbent_operation(
        _prepared_document(source_bundle),
        to_phase="safe_stopped",
        changes={},
    )
    first = replay_benchmark_v2_incumbent_terminal(terminal)
    second = replay_benchmark_v2_incumbent_terminal(terminal)
    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    first["phase"] = "mutated"
    assert second["phase"] == "safe_stopped"


def test_terminal_receipt_document_complete_and_cancel_replay_are_byte_identical(
    source_bundle: dict[str, object]
) -> None:
    from app.learn.hybrid.benchmark_v2_incumbent_operation import (
        advance_benchmark_v2_incumbent_cancel_cleanup,
        compose_benchmark_v2_incumbent_cancel_intent,
        compose_benchmark_v2_incumbent_terminal_intent,
        compose_benchmark_v2_incumbent_terminal_receipt,
        replay_benchmark_v2_incumbent_terminal,
        transition_benchmark_v2_incumbent_operation,
    )
    from app.learn.hybrid.benchmark_v2_contracts import canonical_json_bytes
    from app.learn.recognition.uei.canonical import seal_immutable

    prepared = _prepared_document(source_bundle)
    owner_changes = _provider_owner_changes()
    complete = transition_benchmark_v2_incumbent_operation(
        prepared, to_phase="provider_owner_prepared", changes=owner_changes
    )
    complete = transition_benchmark_v2_incumbent_operation(
        complete, to_phase="worker_starting", changes={}
    )
    complete = transition_benchmark_v2_incumbent_operation(
        complete,
        to_phase="worker_bound",
        changes={
            "worker_ref": {
                **complete["worker_ref"],
                "supervision_ref": {"content_sha256": "9" * 64},
            }
        },
    )
    complete = transition_benchmark_v2_incumbent_operation(
        complete,
        to_phase="result_ready",
        changes={"result_identity_ref": {"content_sha256": "a" * 64}},
    )
    terminal_intent = compose_benchmark_v2_incumbent_terminal_intent(
        operation=complete,
        result_sha256="a" * 64,
        normal_binding_evidence_ref={"content_sha256": "b" * 64},
        provider_cleanup_evidence_ref={"content_sha256": "c" * 64},
        worker_cleanup_evidence_ref={"content_sha256": "d" * 64},
        intent_at="2026-08-27T00:00:00+00:00",
    )
    complete = transition_benchmark_v2_incumbent_operation(
        complete,
        to_phase="terminal_intent",
        changes={"terminal_intent": terminal_intent},
    )
    complete = transition_benchmark_v2_incumbent_operation(
        complete,
        to_phase="adopted",
        changes={"generic_adoption_ref": {"content_sha256": "a" * 64}},
    )
    receipt = compose_benchmark_v2_incumbent_terminal_receipt(
        operation=complete,
        outcome="benchmark_v2_incumbent_observe_complete",
        window_adoption_ref={"content_sha256": "e" * 64},
        worker_cleanup_ref={"content_sha256": "f" * 64},
        provider_cleanup_ref=seal_immutable(
            {"outcome": "verified_exact_process_exited"}
        ),
        terminal_at="2026-08-27T00:01:00+00:00",
    )
    complete = transition_benchmark_v2_incumbent_operation(
        complete,
        to_phase="complete",
        changes={
            "window_adoption_ref": receipt["window_adoption_ref"],
            "worker_cleanup_ref": receipt["worker_cleanup_ref"],
            "provider_cleanup_ref": receipt["provider_cleanup_ref"],
            "terminal_receipt": receipt,
        },
    )

    cancelled = transition_benchmark_v2_incumbent_operation(
        prepared, to_phase="provider_owner_prepared", changes=owner_changes
    )
    cancel_intent = compose_benchmark_v2_incumbent_cancel_intent(
        operation=cancelled,
        reason="cancel",
        intent_at="2026-08-27T00:00:00+00:00",
        process_identity=None,
        scope_name=None,
        assignment_proven_ref=None,
    )
    cancelled = transition_benchmark_v2_incumbent_operation(
        cancelled,
        to_phase="cancel_intent",
        changes={"cancel_intent": cancel_intent},
    )
    cancelled = advance_benchmark_v2_incumbent_cancel_cleanup(
        cancelled,
        worker_cleanup_ref={"content_sha256": "b" * 64},
        provider_cleanup_ref=seal_immutable({"outcome": "verified_not_acquired"}),
        provider_materialization_state="aborted_never_materialized",
        provider_lease_acquired=False,
        terminal_at="2026-08-27T00:01:00+00:00",
    )
    for terminal in (complete, cancelled):
        first = replay_benchmark_v2_incumbent_terminal(terminal)
        second = replay_benchmark_v2_incumbent_terminal(terminal)
        assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert complete["terminal_receipt"]["artifact_is_authorization"] is False
    assert cancelled["terminal_receipt"]["execute_binding_enabled"] is False


def test_cancel_intent_replay_materialization_without_lease_remains_cleanup_pending(
    source_bundle: dict[str, object]
) -> None:
    from app.learn.hybrid.benchmark_v2_incumbent_operation import (
        advance_benchmark_v2_incumbent_cancel_cleanup,
        compose_benchmark_v2_incumbent_cancel_intent,
        transition_benchmark_v2_incumbent_operation,
    )

    document = _prepared_document(source_bundle)
    document = transition_benchmark_v2_incumbent_operation(
        document,
        to_phase="provider_owner_prepared",
        changes=_provider_owner_changes(),
    )
    intent = compose_benchmark_v2_incumbent_cancel_intent(
        operation=document,
        reason="cancel",
        intent_at="2026-08-27T00:00:00+00:00",
        process_identity=None,
        scope_name=None,
        assignment_proven_ref=None,
    )
    document = transition_benchmark_v2_incumbent_operation(
        document,
        to_phase="cancel_intent",
        changes={"cancel_intent": intent},
    )
    pending = advance_benchmark_v2_incumbent_cancel_cleanup(
        document,
        worker_cleanup_ref={"content_sha256": "c" * 64},
        provider_cleanup_ref=None,
        provider_materialization_state="materialization_possible",
        provider_lease_acquired=False,
        terminal_at="2026-08-27T00:01:00+00:00",
    )
    assert pending["phase"] == "cleanup_pending"
    assert pending["terminal_receipt"] is None


def test_document_static_no_action_runtime_click_or_publish_import() -> None:
    path = (
        PROJECT_ROOT
        / "app"
        / "learn"
        / "hybrid"
        / "benchmark_v2_incumbent_operation.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    forbidden = ("action", "runtime", "click", "publish")
    assert not any(token in name.casefold() for name in imports for token in forbidden)


def test_production_corpus_validation_cut_installs_one_replayable_resolver(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    validated_provider_snapshot,
) -> None:
    from app.learn.hybrid import benchmark_v2_provider_corpus as corpus_module
    from app.learn.hybrid.benchmark_v2_contracts import canonical_json_bytes
    from app.learn import workflow_service

    corpus, corpus_file_ref = validated_provider_snapshot
    path = tmp_path / "provider-corpus.v2.json"
    path.write_bytes(canonical_json_bytes(corpus, pretty=True))
    monkeypatch.setattr(corpus_module, "_PRODUCTION_PROVIDER_CASE_RESOLVER", None)
    monkeypatch.setattr(
        workflow_service, "_PRODUCTION_LEARNING_WORKFLOW_SERVICE_COMPOSITION", None
    )

    loaded = corpus_module.load_provider_corpus(
        child_path=path,
        expected_sha256=corpus_file_ref["file_sha256"],
    )
    first = corpus_module.get_production_provider_case_resolver()
    second = corpus_module.get_production_provider_case_resolver()
    composition = workflow_service.get_production_learning_workflow_service_composition()

    assert loaded == corpus
    assert first is second is composition.provider_case_resolver
    assert composition.composition_kind == "production"
    assert composition.benchmark_supervision_root is not None


def test_panel_production_composition_never_falls_back_to_an_unvalidated_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import panel as panel_api

    def unavailable():
        raise ValueError("production validated provider corpus is unavailable")

    monkeypatch.setattr(
        panel_api, "get_production_learning_workflow_service_composition", unavailable
    )
    with pytest.raises(
        ValueError, match="production validated provider corpus is unavailable"
    ):
        panel_api._panel_learning_workflow_service_composition()


def test_resume_rejects_wrong_operation_identity_before_sidecar_or_registry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from contextlib import nullcontext
    from app.learn import workflow_service

    operation = {
        "run_id": "run",
        "stage": "screen_understanding",
        "operation_id": "operation-current",
        "phase": "result_ready",
        "worker_ref": {"worker_id": "worker"},
    }

    class _Store:
        def get(self, _run_id):
            return {"revision": 7}

    composition = workflow_service.compose_test_learning_workflow_service_unit(
        store=_Store(), worker_registry=object(), project_root=tmp_path,
        benchmark_supervision_root=type(
            "_Root", (), {"authority_kind": "test"}
        )(),
        provider_case_resolver=object(),
    )
    monkeypatch.setattr(
        workflow_service, "get_learning_workflow_operation_lock",
        lambda **_kwargs: nullcontext(),
    )
    monkeypatch.setattr(
        "app.learn.workflow_worker.hold_benchmark_worker_controller",
        lambda **_kwargs: nullcontext(),
    )
    monkeypatch.setattr(
        workflow_service, "_benchmark_v2_incumbent_operation_from_state",
        lambda *_args: operation,
    )
    monkeypatch.setattr(
        workflow_service, "_benchmark_v2_sidecars",
        lambda *_args: (_ for _ in ()).throw(AssertionError("sidecar read")),
    )

    with pytest.raises(
        workflow_service.LearningWorkflowStageOperationError,
        match="operation identity differs",
    ):
        workflow_service._resume_benchmark_v2_incumbent_operation(
            composition=composition, run_id="run", expected_revision=7,
            stage="screen_understanding", operation_id="operation-wrong",
            worker_id="worker",
        )


@pytest.mark.parametrize("entrypoint", ["adopt", "continue"])
@pytest.mark.parametrize(
    "phase", ["prepared", "provider_owner_prepared", "worker_starting"]
)
def test_guarded_pre_result_rejects_wrong_worker_before_any_effect(
    entrypoint: str,
    phase: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source_bundle: dict[str, object],
) -> None:
    from contextlib import nullcontext

    from app.learn import workflow_service
    from app.learn.hybrid.benchmark_v2_incumbent_operation import (
        transition_benchmark_v2_incumbent_operation,
    )
    from app.learn.workflow_service import start_learning_workflow_stage_operation
    from app.learn.workflow_store import LearningWorkflowRunStore

    operation = _prepared_document(source_bundle, prepared_revision=4)
    operation_documents = [operation]
    if phase in {"provider_owner_prepared", "worker_starting"}:
        operation = transition_benchmark_v2_incumbent_operation(
            operation,
            to_phase="provider_owner_prepared",
            changes=_provider_owner_changes(),
        )
        operation_documents.append(operation)
    if phase == "worker_starting":
        operation = transition_benchmark_v2_incumbent_operation(
            operation, to_phase="worker_starting", changes={}
        )
        operation_documents.append(operation)

    calls = {
        "sidecar": 0,
        "resolver": 0,
        "registry_other": 0,
        "registry_recovery": 0,
        "registry_launch": 0,
        "spawn": 0,
        "store_cas": 0,
    }

    class _ForbiddenRegistry:
        def __getattr__(self, name: str):
            def forbidden_call(**_kwargs):
                if name == "recover_launching_benchmark_worker":
                    calls["registry_recovery"] += 1
                elif name == "launch_prepared_benchmark_worker":
                    calls["registry_launch"] += 1
                    calls["spawn"] += 1
                else:
                    calls["registry_other"] += 1
                raise AssertionError(f"forbidden Registry call: {name}")

            return forbidden_call

    state_path = tmp_path / f"{entrypoint}-{phase}-state.json"
    store = LearningWorkflowRunStore(state_path=state_path)
    try:
        first = store.transition(
            run_id=operation["run_id"],
            expected_revision=0,
            stage="bind_capture",
            outcome="running",
            evidence_refs={},
        )
        bound = store.transition(
            run_id=operation["run_id"],
            expected_revision=first["revision"],
            stage="bind_capture",
            outcome="completed",
            evidence_refs={"image_path": str(tmp_path / "capture.bmp")},
        )
        current = start_learning_workflow_stage_operation(
            store=store,
            project_root=tmp_path,
            run_id=operation["run_id"],
            expected_revision=bound["revision"],
            stage=operation["stage"],
            operation_id=operation["operation_id"],
        )["workflow_state"]
        for operation_document in operation_documents:
            stage_execution = deepcopy(
                current["stages"][operation["stage"]]["evidence_refs"][
                    "stage_execution"
                ]
            )
            stage_execution["benchmark_v2_incumbent"] = deepcopy(operation_document)
            stage_execution["benchmark_v2_operation_anchor"] = {
                "contract_version": "benchmark_worker_operation_anchor_v1",
                "anchor_identity_sha256": operation["operation_anchor_ref"][
                    "content_sha256"
                ],
                "expected_supervision_ref": deepcopy(
                    operation["expected_supervision_ref"]
                ),
            }
            current = store.transition(
                run_id=operation["run_id"],
                expected_revision=current["revision"],
                stage=operation["stage"],
                outcome="running",
                evidence_refs={"stage_execution": stage_execution},
            )
            assert current["revision"] == operation_document["current_document_revision"]

        composition = workflow_service.compose_test_learning_workflow_service_unit(
            store=store,
            worker_registry=_ForbiddenRegistry(),
            project_root=tmp_path,
            benchmark_supervision_root=type(
                "_Root", (), {"authority_kind": "test"}
            )(),
            provider_case_resolver=object(),
            benchmark_v2_worker_binding_resolver=object(),
        )
        closed_request = {
            "provider_case_ref": deepcopy(
                operation["handler_payload_source"]["provider_case_ref"]
            ),
            "window_binding_ref": deepcopy(operation["window_binding_ref"]),
            "capture_ref": deepcopy(operation["capture_ref"]),
        }

        def observe_sidecars(*_args):
            calls["sidecar"] += 1
            return deepcopy(closed_request), {"anchor": True}

        def reject_resolver(**_kwargs):
            calls["resolver"] += 1
            raise AssertionError("forbidden resolver call")

        def reject_cas(**_kwargs):
            calls["store_cas"] += 1
            raise AssertionError("forbidden store CAS")

        monkeypatch.setattr(
            "app.learn.workflow_worker.hold_benchmark_worker_controller",
            lambda **_kwargs: nullcontext(),
        )
        monkeypatch.setattr(workflow_service, "_benchmark_v2_sidecars", observe_sidecars)
        monkeypatch.setattr(
            workflow_service, "_benchmark_v2_source_projection", reject_resolver
        )
        monkeypatch.setattr(store, "transition", reject_cas)
        before_state = store.get(operation["run_id"])
        before_bytes = state_path.read_bytes()
        before_revision = before_state["revision"]

        guarded = (
            workflow_service.adopt_guarded_learning_stage_worker_result
            if entrypoint == "adopt"
            else workflow_service.continue_guarded_learning_stage_worker_result
        )
        with pytest.raises(
            workflow_service.LearningWorkflowStageOperationError,
            match="benchmark_v2 incumbent worker identity differs",
        ):
            guarded(
                composition=composition,
                worker_id="worker-stale",
                run_id=operation["run_id"],
                expected_revision=before_revision,
                stage=operation["stage"],
                operation_id=operation["operation_id"],
            )

        after_state = store.get(operation["run_id"])
        assert calls == {
            "sidecar": 0,
            "resolver": 0,
            "registry_other": 0,
            "registry_recovery": 0,
            "registry_launch": 0,
            "spawn": 0,
            "store_cas": 0,
        }
        assert state_path.read_bytes() == before_bytes
        assert after_state == before_state
        assert after_state["revision"] == before_revision
    finally:
        store.close()


@pytest.mark.parametrize(
    ("recovery_case", "expected_launches", "expected_phase"),
    [
        ("anchored", 1, "worker_bound"),
        ("launching", 0, "worker_bound"),
        ("launching_cleanup", 0, "safe_stopped"),
        ("launched", 0, "worker_bound"),
    ],
)
def test_worker_starting_restart_reuses_the_same_reservation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source_bundle: dict[str, object],
    recovery_case: str,
    expected_launches: int,
    expected_phase: str,
) -> None:
    from contextlib import nullcontext
    from app.learn import workflow_service
    from app.learn.hybrid.benchmark_v2_incumbent_operation import (
        transition_benchmark_v2_incumbent_operation,
    )
    from app.learn.recognition.uei.canonical import seal_immutable

    operation = _prepared_document(source_bundle)
    operation = transition_benchmark_v2_incumbent_operation(
        operation,
        to_phase="provider_owner_prepared",
        changes=_provider_owner_changes(),
    )
    operation = transition_benchmark_v2_incumbent_operation(
        operation, to_phase="worker_starting", changes={}
    )
    run_id = operation["run_id"]
    stage = operation["stage"]
    operation_id = operation["operation_id"]
    launches: list[dict[str, object]] = []
    recoveries: list[dict[str, object]] = []
    reservation_state = (
        "launching" if recovery_case == "launching_cleanup" else recovery_case
    )
    closed_request = {
        "provider_case_ref": deepcopy(
            operation["handler_payload_source"]["provider_case_ref"]
        ),
        "window_binding_ref": deepcopy(operation["window_binding_ref"]),
        "capture_ref": deepcopy(operation["capture_ref"]),
    }

    class _Store:
        def get(self, _run_id):
            return {"revision": 9}

    class _Registry(_UnitCleanupReceiptAuthority):
        def inspect_prepared_benchmark_worker_identity(self, **_kwargs):
            return {
                "reservation_state": reservation_state,
                "worker_id": operation["worker_ref"]["worker_id"],
                "content_sha256": "9" * 64,
            }

        def confirm_prepared_benchmark_worker_anchor(self, **_kwargs):
            return {"anchored_reservation_ref": {"content_sha256": "9" * 64}}

        def launch_prepared_benchmark_worker(self, **kwargs):
            launches.append(kwargs)
            return {"worker_id": operation["worker_ref"]["worker_id"], "status": "running"}

        def status(self, **_kwargs):
            assert reservation_state in {"launching", "launched"}
            return {"worker_id": operation["worker_ref"]["worker_id"], "status": "running"}

        def recover_launching_benchmark_worker(self, **kwargs):
            recoveries.append(deepcopy(kwargs))
            owner = self.inspect_benchmark_worker_launch_owner()
            if recovery_case == "launching_cleanup":
                owner = {
                    **owner,
                    "reservation_state": "launching",
                    "owner_phase": "acquiring",
                    "assignment_state": "not_proven",
                    "process_identity": None,
                    "scope_name": None,
                    "assignment_proven_ref": None,
                }
            return seal_immutable(
                {
                    "contract_version": "benchmark_worker_launch_recovery_v1",
                    "outcome": (
                        "verified_cleanup_safe_stop"
                        if recovery_case == "launching_cleanup"
                        else "recovered_gate_released"
                    ),
                    **{
                        field: deepcopy(owner[field])
                        for field in (
                            "authority_kind", "run_id", "stage", "operation_id",
                            "worker_id", "model_request_id", "payload_sha256",
                            "execution_nonce", "reservation_ref",
                            "current_reservation_ref", "operation_anchor_ref",
                            "expected_supervision_ref", "supervision_ref",
                            "reservation_state", "owner_phase", "assignment_state",
                            "process_identity", "scope_name", "assignment_proven_ref",
                        )
                    },
                    "gate_release_performed": False,
                    "spawn_retry": False,
                    "cleanup_ref": (
                        {"content_sha256": "7" * 64}
                        if recovery_case == "launching_cleanup"
                        else None
                    ),
                    "artifact_is_authorization": False,
                    "execute_binding_enabled": False,
                }
            )

        def inspect_benchmark_worker_launch_owner(self, **_kwargs):
            return seal_immutable(
                {
                    "contract_version": "benchmark_worker_launch_owner_inspection_v1",
                    "authority_kind": "test",
                    "run_id": run_id,
                    "stage": stage,
                    "operation_id": operation_id,
                    "worker_id": operation["worker_ref"]["worker_id"],
                    "model_request_id": operation["worker_ref"]["model_request_id"],
                    "payload_sha256": operation["worker_ref"]["payload_sha256"],
                    "execution_nonce": operation["execution_nonce"],
                    "reservation_ref": operation["reservation_ref"],
                    "current_reservation_ref": {"content_sha256": "9" * 64},
                    "operation_anchor_ref": operation["operation_anchor_ref"],
                    "expected_supervision_ref": operation[
                        "expected_supervision_ref"
                    ],
                    "supervision_ref": {"content_sha256": "6" * 64},
                    "reservation_state": "launched",
                    "owner_phase": "gate_released",
                    "assignment_state": "proven",
                    "process_identity": {"pid": 101, "create_time_ns": 202},
                    "scope_name": "Local\\AgentGuiBenchmarkWorker-" + "1" * 64,
                    "assignment_proven_ref": {"content_sha256": "5" * 64},
                    "artifact_is_authorization": False,
                    "execute_binding_enabled": False,
                }
            )

    composition = workflow_service.compose_test_learning_workflow_service_unit(
        store=_Store(), worker_registry=_Registry(), project_root=tmp_path,
        benchmark_supervision_root=type(
            "_Root", (), {"authority_kind": "test"}
        )(),
        provider_case_resolver=object(), benchmark_v2_worker_binding_resolver=object(),
    )
    monkeypatch.setattr(
        workflow_service, "get_learning_workflow_operation_lock",
        lambda **_kwargs: nullcontext(),
    )
    monkeypatch.setattr(
        "app.learn.workflow_worker.hold_benchmark_worker_controller",
        lambda **_kwargs: nullcontext(),
    )
    monkeypatch.setattr(
        workflow_service, "require_active_learning_workflow_stage_operation",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr(
        workflow_service, "_benchmark_v2_incumbent_operation_from_state",
        lambda *_args: operation,
    )
    monkeypatch.setattr(
        workflow_service, "_benchmark_v2_sidecars",
        lambda *_args: (deepcopy(closed_request), {"anchor": True}),
    )
    monkeypatch.setattr(
        workflow_service, "_benchmark_v2_source_projection",
        lambda **_kwargs: {
            **source_bundle,
            "worker_binding_resolution": {
                "serialized_window_binding": source_bundle[
                    "authoritative_payload"
                ]["_benchmark_v2_window_binding"]
            },
        },
    )
    monkeypatch.setattr(
        "app.learn.hybrid.benchmark_v2_incumbent_operation.validate_benchmark_v2_incumbent_payload_projection",
        lambda **kwargs: kwargs["payload"],
    )
    persisted: list[dict[str, object]] = []
    monkeypatch.setattr(
        workflow_service, "_persist_benchmark_v2_incumbent_operation",
        lambda **kwargs: persisted.append(deepcopy(kwargs["operation"])) or {"revision": 10},
    )

    result = workflow_service._start_benchmark_v2_incumbent_operation(
        composition=composition, run_id=run_id, expected_revision=9,
        stage=stage, operation_id=operation_id, task_kind="vision_observe_screen",
        request=closed_request,
    )
    if expected_phase == "worker_bound":
        assert result["worker_id"] == operation["worker_ref"]["worker_id"]
    else:
        assert result["status"] == "safe_stopped"
    assert len(launches) == expected_launches
    assert len(recoveries) == (0 if recovery_case == "anchored" else 1)
    assert persisted[-1]["phase"] == expected_phase


def test_incumbent_request_accepts_only_closed_selectors_and_uses_task5_resolver(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    validated_provider_snapshot,
) -> None:
    from app.learn import workflow_service

    store, registry, root, provider_resolver = _test_pair(
        tmp_path / "closed-request", validated_provider_snapshot
    )
    case_ref = _case_ref(provider_resolver)
    case = provider_resolver.resolve(case_ref)
    binding, image_sha = _binding_for_case(tmp_path, case, "operation-closed")
    request = {
        "provider_case_ref": case_ref,
        "window_binding_ref": {
            "id": "binding-closed",
            "content_sha256": binding["payload_sha256"],
        },
        "capture_ref": {"id": "capture-closed", "content_sha256": image_sha},
    }
    resolution_calls: list[dict[str, object]] = []

    def resolve_binding(**kwargs):
        resolution_calls.append(kwargs)
        return {
            "contract_version": "benchmark_v2_worker_window_binding_resolution_v1",
            "authority_kind": root.authority_kind,
            "run_id": "run-closed",
            "stage": "screen_understanding",
            "operation_id": "operation-closed",
            "window_binding_ref": deepcopy(request["window_binding_ref"]),
            "capture_ref": deepcopy(request["capture_ref"]),
            "binding_authority_ref": {"content_sha256": "9" * 64},
            "serialized_window_binding": binding,
            "worker_process_identity": None,
            "normal_binding_evidence_ref": None,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "content_sha256": "8" * 64,
        }

    monkeypatch.setattr(
        "app.learn.hybrid.benchmark_v2_worker_binding.resolve_server_worker_window_binding",
        resolve_binding,
    )
    composition = workflow_service.compose_test_learning_workflow_service_unit(
        store=store,
        worker_registry=registry,
        project_root=tmp_path,
        benchmark_supervision_root=root,
        provider_case_resolver=provider_resolver,
        benchmark_v2_worker_binding_resolver=object(),
    )
    try:
        assert workflow_service._benchmark_v2_request(request) == request
        for forbidden_name, forbidden_value in (
            ("serialized_window_binding", binding),
            ("capture_image_path", binding["capture_image_path"]),
            ("owner_journal_path", binding["owner_journal_path"]),
        ):
            with pytest.raises(
                workflow_service.LearningWorkflowStageOperationError,
                match="request is not closed",
            ):
                workflow_service._benchmark_v2_request(
                    {**request, forbidden_name: forbidden_value}
                )

        projection = workflow_service._benchmark_v2_source_projection(
            composition=composition,
            run_id="run-closed",
            stage="screen_understanding",
            operation_id="operation-closed",
            request=request,
        )
        assert projection["authoritative_payload"][
            "_benchmark_v2_window_binding"
        ] == binding
        assert len(resolution_calls) == 1
        assert resolution_calls[0] == {
            "resolver": composition.benchmark_v2_worker_binding_resolver,
            "run_id": "run-closed",
            "stage": "screen_understanding",
            "operation_id": "operation-closed",
            "window_binding_ref": request["window_binding_ref"],
            "capture_ref": request["capture_ref"],
        }
    finally:
        store.close()


def test_incumbent_c_source_has_no_private_task5_journal_or_raw_sidecar() -> None:
    import app.learn.workflow_service as workflow_service

    tree = ast.parse(
        (PROJECT_ROOT / "app/learn/workflow_service.py").read_text(encoding="utf-8")
    )
    target_names = {
        "_benchmark_v2_request",
        "_benchmark_v2_source_projection",
        "_benchmark_v2_sidecars",
        "_start_benchmark_v2_incumbent_operation",
        "_resume_benchmark_v2_incumbent_operation",
    }
    target_nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in target_names
    ]
    target_source = "\n".join(ast.unparse(node) for node in target_nodes)
    assert len(target_nodes) == len(target_names)
    assert "_owner_from_journal" not in target_source
    assert "_assert_owner_matches_serialized" not in target_source
    assert "benchmark_v2_incumbent_request" not in target_source
    assert not hasattr(workflow_service, "_validate_benchmark_v2_current_window_binding")


def test_result_ready_rejects_same_identity_a_remint_before_intent_or_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source_bundle: dict[str, object],
) -> None:
    from contextlib import nullcontext
    from app.learn import workflow_service
    from app.learn.recognition.uei.canonical import seal_immutable

    base = _prepared_document(source_bundle)
    worker = base["worker_ref"]
    snapshot = {
        "contract_version": "learning_stage_worker_completed_result_identity_v1",
        "status": "completed",
        "worker_id": worker["worker_id"],
        "run_id": base["run_id"],
        "stage": base["stage"],
        "operation_id": base["operation_id"],
        "task_kind": "vision_observe_screen",
        "model_request_id": worker["model_request_id"],
        "payload_sha256": worker["payload_sha256"],
        "result_sha256": "a" * 64,
        "result_available": True,
        "normal_binding_evidence_ref": {"content_sha256": "b" * 64},
        "provider_cleanup_evidence_ref": {"content_sha256": "c" * 64},
    }
    operation = _result_ready_document(
        source_bundle, result_identity=seal_immutable(snapshot)
    )
    reminted = {**snapshot, "result_sha256": "d" * 64}
    events: list[str] = []

    class _Store:
        def get(self, _run_id):
            return {"revision": operation["current_document_revision"]}

    class _Registry(_UnitCleanupReceiptAuthority):
        def inspect_completed_result_identity(self, **_kwargs):
            events.append("inspect_a")
            return deepcopy(reminted)

        def inspect_benchmark_worker_launch_owner(self, **_kwargs):
            events.append("inspect_b1")
            raise AssertionError("B1 inspection follows exact A replay")

        def observe_benchmark_worker_cleanup(self, **_kwargs):
            events.append("cleanup")
            raise AssertionError("cleanup is forbidden after A remint")

    composition = workflow_service.compose_test_learning_workflow_service_unit(
        store=_Store(),
        worker_registry=_Registry(),
        project_root=tmp_path,
        benchmark_supervision_root=object(),
        provider_case_resolver=object(),
        benchmark_v2_worker_binding_resolver=object(),
    )
    monkeypatch.setattr(
        workflow_service, "get_learning_workflow_operation_lock", lambda **_kwargs: nullcontext()
    )
    monkeypatch.setattr(
        "app.learn.workflow_worker.hold_benchmark_worker_controller",
        lambda **_kwargs: nullcontext(),
    )
    monkeypatch.setattr(
        workflow_service,
        "_benchmark_v2_incumbent_operation_from_state",
        lambda *_args: deepcopy(operation),
    )
    monkeypatch.setattr(
        workflow_service,
        "_benchmark_v2_sidecars",
        lambda *_args: ({}, {"anchor": True}),
    )
    persisted: list[dict[str, object]] = []
    monkeypatch.setattr(
        workflow_service,
        "_persist_benchmark_v2_incumbent_operation",
        lambda **kwargs: persisted.append(deepcopy(kwargs["operation"]))
        or {"revision": kwargs["operation"]["current_document_revision"]},
    )

    with pytest.raises(
        workflow_service.LearningWorkflowStageOperationError,
        match="A inspection changed after first snapshot",
    ):
        workflow_service._resume_benchmark_v2_incumbent_operation(
            composition=composition,
            run_id=operation["run_id"],
            expected_revision=operation["current_document_revision"],
            stage=operation["stage"],
            operation_id=operation["operation_id"],
            worker_id=worker["worker_id"],
        )
    assert events == ["inspect_a"]
    assert persisted == []


def test_completion_rejects_task5_b1_create_time_cross_pair_before_intent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source_bundle: dict[str, object],
) -> None:
    from contextlib import nullcontext
    from app.learn import workflow_service
    from app.learn.recognition.uei.canonical import seal_immutable

    base = _prepared_document(source_bundle)
    worker = base["worker_ref"]
    snapshot = {
        "contract_version": "learning_stage_worker_completed_result_identity_v1",
        "status": "completed",
        "worker_id": worker["worker_id"],
        "run_id": base["run_id"],
        "stage": base["stage"],
        "operation_id": base["operation_id"],
        "task_kind": "vision_observe_screen",
        "model_request_id": worker["model_request_id"],
        "payload_sha256": worker["payload_sha256"],
        "result_sha256": "a" * 64,
        "result_available": True,
        "normal_binding_evidence_ref": {"content_sha256": "b" * 64},
        "provider_cleanup_evidence_ref": {"content_sha256": "c" * 64},
    }
    sealed_snapshot = seal_immutable(snapshot)
    operation = _result_ready_document(
        source_bundle, result_identity=sealed_snapshot
    )
    process_identity = {"pid": 321, "create_time_ns": 654}
    inspection = seal_immutable(
        {
            "contract_version": "benchmark_worker_launch_owner_inspection_v1",
            "authority_kind": "test",
            "run_id": operation["run_id"],
            "stage": operation["stage"],
            "operation_id": operation["operation_id"],
            "worker_id": worker["worker_id"],
            "model_request_id": worker["model_request_id"],
            "payload_sha256": worker["payload_sha256"],
            "execution_nonce": operation["execution_nonce"],
            "reservation_ref": operation["reservation_ref"],
            "current_reservation_ref": {"content_sha256": "4" * 64},
            "operation_anchor_ref": operation["operation_anchor_ref"],
            "expected_supervision_ref": operation["expected_supervision_ref"],
            "supervision_ref": operation["worker_ref"]["supervision_ref"],
            "reservation_state": "launched",
            "owner_phase": "gate_released",
            "assignment_state": "proven",
            "process_identity": process_identity,
            "scope_name": "Local\\AgentGuiBenchmarkWorker-" + "1" * 64,
            "assignment_proven_ref": {"content_sha256": "5" * 64},
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    events: list[str] = []

    class _Store:
        def get(self, _run_id):
            return {"revision": operation["current_document_revision"]}

    class _Registry(_UnitCleanupReceiptAuthority):
        def inspect_completed_result_identity(self, **_kwargs):
            events.append("inspect_a")
            return deepcopy(snapshot)

        def inspect_benchmark_worker_launch_owner(self, **_kwargs):
            events.append("inspect_b1")
            return deepcopy(inspection)

        def observe_benchmark_worker_cleanup(self, **_kwargs):
            events.append("cleanup")
            raise AssertionError("cleanup is forbidden after cross-pair rejection")

    def resolve_binding(**_kwargs):
        events.append("resolve_task5")
        return {
            "worker_process_identity": {
                "pid": process_identity["pid"],
                "create_time_ns": process_identity["create_time_ns"] + 1,
            },
            "normal_binding_evidence_ref": deepcopy(
                snapshot["normal_binding_evidence_ref"]
            ),
        }

    monkeypatch.setattr(
        "app.learn.hybrid.benchmark_v2_worker_binding.resolve_server_worker_window_binding",
        resolve_binding,
    )
    composition = workflow_service.compose_test_learning_workflow_service_unit(
        store=_Store(), worker_registry=_Registry(), project_root=tmp_path,
        benchmark_supervision_root=type(
            "_Root", (), {"authority_kind": "test"}
        )(),
        provider_case_resolver=object(), benchmark_v2_worker_binding_resolver=object(),
    )
    monkeypatch.setattr(
        workflow_service, "get_learning_workflow_operation_lock", lambda **_kwargs: nullcontext()
    )
    monkeypatch.setattr(
        "app.learn.workflow_worker.hold_benchmark_worker_controller",
        lambda **_kwargs: nullcontext(),
    )
    monkeypatch.setattr(
        workflow_service, "_benchmark_v2_incumbent_operation_from_state",
        lambda *_args: deepcopy(operation),
    )
    monkeypatch.setattr(
        workflow_service, "_benchmark_v2_sidecars",
        lambda *_args: (
            {
                "provider_case_ref": operation["handler_payload_source"]["provider_case_ref"],
                "window_binding_ref": operation["window_binding_ref"],
                "capture_ref": operation["capture_ref"],
            },
            {"anchor": True},
        ),
    )
    persisted: list[dict[str, object]] = []
    monkeypatch.setattr(
        workflow_service, "_persist_benchmark_v2_incumbent_operation",
        lambda **kwargs: persisted.append(deepcopy(kwargs["operation"]))
        or {"revision": kwargs["operation"]["current_document_revision"]},
    )

    with pytest.raises(
        workflow_service.LearningWorkflowStageOperationError,
        match="Task5 and B1 process identity differ",
    ):
        workflow_service._resume_benchmark_v2_incumbent_operation(
            composition=composition, run_id=operation["run_id"],
            expected_revision=operation["current_document_revision"],
            stage=operation["stage"], operation_id=operation["operation_id"],
            worker_id=worker["worker_id"],
        )
    assert events == ["inspect_a", "inspect_b1", "resolve_task5"]
    assert persisted == []


def test_post_launch_cancel_intent_copies_exact_b1_identity_before_cas(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source_bundle: dict[str, object],
) -> None:
    from contextlib import nullcontext
    from app.learn import workflow_service
    from app.learn.hybrid.benchmark_v2_incumbent_operation import (
        transition_benchmark_v2_incumbent_operation,
    )
    from app.learn.recognition.uei.canonical import seal_immutable

    prepared = _prepared_document(source_bundle)
    operation = transition_benchmark_v2_incumbent_operation(
        prepared,
        to_phase="provider_owner_prepared",
        changes=_provider_owner_changes(),
    )
    operation = transition_benchmark_v2_incumbent_operation(
        operation, to_phase="worker_starting", changes={}
    )
    operation = transition_benchmark_v2_incumbent_operation(
        operation,
        to_phase="worker_bound",
        changes={
            "worker_ref": {
                **operation["worker_ref"],
                "supervision_ref": {"content_sha256": "9" * 64},
            }
        },
    )
    expected_process = {"pid": 456, "create_time_ns": 789}
    expected_scope = "Local\\AgentGuiBenchmarkWorker-" + "2" * 64
    expected_assignment = {"content_sha256": "3" * 64}
    inspection = seal_immutable(
        {
            "contract_version": "benchmark_worker_launch_owner_inspection_v1",
            "authority_kind": "test",
            "run_id": operation["run_id"],
            "stage": operation["stage"],
            "operation_id": operation["operation_id"],
            "worker_id": operation["worker_ref"]["worker_id"],
            "model_request_id": operation["worker_ref"]["model_request_id"],
            "payload_sha256": operation["worker_ref"]["payload_sha256"],
            "execution_nonce": operation["execution_nonce"],
            "reservation_ref": operation["reservation_ref"],
            "current_reservation_ref": {"content_sha256": "4" * 64},
            "operation_anchor_ref": operation["operation_anchor_ref"],
            "expected_supervision_ref": operation["expected_supervision_ref"],
            "supervision_ref": operation["worker_ref"]["supervision_ref"],
            "reservation_state": "launched",
            "owner_phase": "gate_released",
            "assignment_state": "proven",
            "process_identity": expected_process,
            "scope_name": expected_scope,
            "assignment_proven_ref": expected_assignment,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    events: list[str] = []

    class _Store:
        def get(self, _run_id):
            return {"revision": operation["current_document_revision"]}

    class _Registry(_UnitCleanupReceiptAuthority):
        def inspect_benchmark_worker_launch_owner(self, **_kwargs):
            events.append("inspect_b1")
            return deepcopy(inspection)

    composition = workflow_service.compose_test_learning_workflow_service_unit(
        store=_Store(), worker_registry=_Registry(), project_root=tmp_path,
        benchmark_supervision_root=type(
            "_Root", (), {"authority_kind": "test"}
        )(),
        provider_case_resolver=object(), benchmark_v2_worker_binding_resolver=object(),
    )
    monkeypatch.setattr(
        workflow_service, "get_learning_workflow_operation_lock", lambda **_kwargs: nullcontext()
    )
    monkeypatch.setattr(
        "app.learn.workflow_worker.hold_benchmark_worker_controller",
        lambda **_kwargs: nullcontext(),
    )
    monkeypatch.setattr(
        workflow_service, "_benchmark_v2_incumbent_operation_from_state",
        lambda *_args: deepcopy(operation),
    )
    monkeypatch.setattr(
        workflow_service, "_benchmark_v2_sidecars",
        lambda *_args: ({}, {"anchor": True}),
    )
    persisted: list[dict[str, object]] = []

    def crash_after_intent(**kwargs):
        persisted.append(deepcopy(kwargs["operation"]))
        raise RuntimeError("crash after intent")

    monkeypatch.setattr(
        workflow_service, "_persist_benchmark_v2_incumbent_operation", crash_after_intent
    )
    with pytest.raises(RuntimeError, match="crash after intent"):
        workflow_service._cancel_benchmark_v2_incumbent_operation(
            composition=composition, run_id=operation["run_id"],
            expected_revision=operation["current_document_revision"],
            stage=operation["stage"], operation_id=operation["operation_id"],
            reason="operator cancel",
        )
    assert events == ["inspect_b1"]
    assert len(persisted) == 1
    intent = persisted[0]["cancel_intent"]
    assert intent["process_identity"] == expected_process
    assert intent["scope_name"] == expected_scope
    assert intent["assignment_proven_ref"] == expected_assignment


@pytest.mark.parametrize(
    "mutation",
    [
        "extra",
        "missing",
        "wrong_authority",
        "cross_reservation",
        "cross_runtime_owner",
    ],
)
def test_provider_preparation_projection_rejects_resealed_schema_and_lineage_drift(
    mutation: str,
    source_bundle: dict[str, object],
) -> None:
    from app.learn import workflow_service
    from app.learn.recognition.uei.canonical import seal_immutable

    operation = _prepared_document(source_bundle)
    reservation_ref = {"content_sha256": "6" * 64}
    runtime_owner = seal_immutable(
        {
            "contract_version": "benchmark_provider_runtime_owner_v1",
            "authority_kind": "test",
            "run_id": operation["run_id"],
            "stage": operation["stage"],
            "operation_id": operation["operation_id"],
            "worker_id": operation["worker_ref"]["worker_id"],
            "model_request_id": operation["worker_ref"]["model_request_id"],
            "payload_sha256": operation["worker_ref"]["payload_sha256"],
            "reservation_ref": reservation_ref,
        }
    )
    projection = {
        "contract_version": "benchmark_provider_acquisition_ref_v1",
        "authority_kind": "test",
        "run_id": operation["run_id"],
        "stage": operation["stage"],
        "operation_id": operation["operation_id"],
        "worker_id": operation["worker_ref"]["worker_id"],
        "model_request_id": operation["worker_ref"]["model_request_id"],
        "payload_sha256": operation["worker_ref"]["payload_sha256"],
        "reservation_ref": reservation_ref,
        "acquisition_owner_ref": {"content_sha256": "f" * 64},
        "acquisition_intent_ref": {"content_sha256": "7" * 64},
        "prepared_acquisition_observation_ref": {"content_sha256": "a" * 64},
        "prepared_materialization_ledger_ref": {"content_sha256": "b" * 64},
        "acquisition_observation_ref": {"content_sha256": "a" * 64},
        "materialization_ledger_ref": {"content_sha256": "b" * 64},
        "runtime_owner_ref": {"content_sha256": runtime_owner["content_sha256"]},
    }
    if mutation == "extra":
        projection["unexpected"] = False
    elif mutation == "missing":
        projection.pop("prepared_acquisition_observation_ref")
    elif mutation == "wrong_authority":
        projection["authority_kind"] = "cross-pair"
    elif mutation == "cross_reservation":
        projection["reservation_ref"] = {"content_sha256": "d" * 64}
    elif mutation == "cross_runtime_owner":
        projection["runtime_owner_ref"] = {"content_sha256": "d" * 64}
    with pytest.raises(workflow_service.LearningWorkflowStageOperationError):
        workflow_service._validate_benchmark_v2_provider_preparation_parent(
            provider=seal_immutable(projection),
            operation=operation,
            reservation_ref=reservation_ref,
            runtime_owner=runtime_owner,
            authority_kind="test",
        )


def test_b1_launch_owner_rejects_cross_authority_before_parent_use(
    source_bundle: dict[str, object],
) -> None:
    from app.learn import workflow_service
    from app.learn.recognition.uei.canonical import seal_immutable

    operation = _result_ready_document(
        source_bundle, result_identity={"content_sha256": "a" * 64}
    )
    worker = operation["worker_ref"]
    owner = seal_immutable(
        {
            "contract_version": "benchmark_worker_launch_owner_inspection_v1",
            "authority_kind": "cross-pair",
            "run_id": operation["run_id"],
            "stage": operation["stage"],
            "operation_id": operation["operation_id"],
            "worker_id": worker["worker_id"],
            "model_request_id": worker["model_request_id"],
            "payload_sha256": worker["payload_sha256"],
            "execution_nonce": operation["execution_nonce"],
            "reservation_ref": operation["reservation_ref"],
            "current_reservation_ref": {"content_sha256": "4" * 64},
            "operation_anchor_ref": operation["operation_anchor_ref"],
            "expected_supervision_ref": operation["expected_supervision_ref"],
            "supervision_ref": worker["supervision_ref"],
            "reservation_state": "launched",
            "owner_phase": "gate_released",
            "assignment_state": "proven",
            "process_identity": {"pid": 321, "create_time_ns": 654},
            "scope_name": "Local\\AgentGuiBenchmarkWorker-" + "1" * 64,
            "assignment_proven_ref": {"content_sha256": "5" * 64},
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )

    class _Registry(_UnitCleanupReceiptAuthority):
        def inspect_benchmark_launch_owner(self, **_kwargs):
            return owner

    root = type("_Root", (), {"authority_kind": "test"})()
    with pytest.raises(
        workflow_service.LearningWorkflowStageOperationError,
        match="launch owner lineage differs",
    ):
        workflow_service._inspect_benchmark_v2_launch_owner(
            registry=_Registry(),
            operation=operation,
            anchor={"anchor": True},
            root=root,
            require_assignment=True,
        )


@pytest.mark.parametrize(
    ("parent_kind", "mutation"),
    [
        ("b1", "extra"),
        ("b1", "missing"),
        ("b1", "cross_parent"),
        ("b2", "extra"),
        ("b2", "missing"),
        ("b2", "cross_reservation"),
        ("b2", "cross_acquisition_owner"),
        ("b2", "wrong_authority"),
    ],
)
def test_cleanup_parent_projection_rejects_resealed_schema_and_lineage_drift(
    parent_kind: str,
    mutation: str,
    source_bundle: dict[str, object],
) -> None:
    from app.learn import workflow_service
    from app.learn.recognition.uei.canonical import seal_immutable

    operation = _result_ready_document(
        source_bundle,
        result_identity={"content_sha256": "a" * 64},
    )
    original = deepcopy(operation)
    worker = operation["worker_ref"]
    launch_owner = seal_immutable(
        {
            "contract_version": "benchmark_worker_launch_owner_inspection_v1",
            "authority_kind": "test",
            "run_id": operation["run_id"],
            "stage": operation["stage"],
            "operation_id": operation["operation_id"],
            "worker_id": worker["worker_id"],
            "model_request_id": worker["model_request_id"],
            "payload_sha256": worker["payload_sha256"],
            "execution_nonce": operation["execution_nonce"],
            "reservation_ref": operation["reservation_ref"],
            "current_reservation_ref": {"content_sha256": "4" * 64},
            "operation_anchor_ref": operation["operation_anchor_ref"],
            "expected_supervision_ref": operation["expected_supervision_ref"],
            "supervision_ref": worker["supervision_ref"],
            "reservation_state": "launched",
            "owner_phase": "cleanup_finalization_intent",
            "assignment_state": "proven",
            "process_identity": {"pid": 321, "create_time_ns": 654},
            "scope_name": "Local\\AgentGuiBenchmarkWorker-" + "1" * 64,
            "assignment_proven_ref": {"content_sha256": "5" * 64},
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    b1 = {
        "contract_version": "benchmark_worker_cleanup_receipt_v1",
        "outcome": "verified_exact_worker_exited",
        "operation_anchor_ref": operation["operation_anchor_ref"],
        "reservation_ref": launch_owner["current_reservation_ref"],
        "supervision_ref": launch_owner["supervision_ref"],
        "run_id": operation["run_id"],
        "stage": operation["stage"],
        "operation_id": operation["operation_id"],
        "worker_id": worker["worker_id"],
        "process_identity": launch_owner["process_identity"],
        "assignment_proven_ref": launch_owner["assignment_proven_ref"],
        "finalization_intent_ref": {"content_sha256": "6" * 64},
        "exact_handle_observation_refs": {"process": {"content_sha256": "7" * 64}},
        "job_absence_observation_ref": {"content_sha256": "8" * 64},
        "worker_absence_observation_ref": {"content_sha256": "9" * 64},
        "supervisor_absence_observation_ref": None,
        "reservation_abort_ref": None,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    b2 = {
        "contract_version": "benchmark_provider_cleanup_ref_v1",
        "status": "cleanup_verified",
        "outcome": "verified_exact_process_exited",
        "authority_kind": "test",
        "run_id": operation["run_id"],
        "stage": operation["stage"],
        "operation_id": operation["operation_id"],
        "worker_id": worker["worker_id"],
        "model_request_id": worker["model_request_id"],
        "payload_sha256": worker["payload_sha256"],
        "reservation_ref": operation["provider_reservation_ref"],
        "acquisition_owner_ref": operation["acquisition_owner_ref"],
        "acquisition_intent_ref": operation["acquisition_intent_ref"],
        "runtime_owner_ref": operation["runtime_owner_ref"],
        "cleanup_receipt_ref": {"content_sha256": "c" * 64},
    }
    target = b1 if parent_kind == "b1" else b2
    if mutation == "extra":
        target["unexpected"] = False
    elif mutation == "missing":
        target.pop("status" if parent_kind == "b2" else "finalization_intent_ref")
    elif mutation == "cross_parent":
        target["supervision_ref"] = {"content_sha256": "d" * 64}
    elif mutation == "cross_reservation":
        target["reservation_ref"] = {"content_sha256": "d" * 64}
    elif mutation == "cross_acquisition_owner":
        target["acquisition_owner_ref"] = {"content_sha256": "d" * 64}
    elif mutation == "wrong_authority":
        target["authority_kind"] = "cross-pair"
    sealed = seal_immutable(target)
    with pytest.raises(workflow_service.LearningWorkflowStageOperationError):
        if parent_kind == "b1":
            workflow_service._validate_benchmark_v2_worker_cleanup_parent(
                cleanup=sealed,
                operation=operation,
                launch_owner=launch_owner,
                allowed_outcomes={"verified_exact_worker_exited"},
            )
        else:
            workflow_service._validate_benchmark_v2_provider_cleanup_parent(
                cleanup=sealed,
                operation=operation,
                result_identity=None,
                authority_kind="test",
                allowed_outcomes={"verified_exact_process_exited"},
            )
    assert operation == original


def test_b2_pending_cleanup_keeps_exact_lineage_without_becoming_evidence(
    source_bundle: dict[str, object],
) -> None:
    from app.learn import workflow_service
    from app.learn.recognition.uei.canonical import seal_immutable

    operation = _result_ready_document(
        source_bundle,
        result_identity={"content_sha256": "a" * 64},
    )
    worker = operation["worker_ref"]
    pending = seal_immutable(
        {
            "contract_version": "benchmark_provider_cleanup_ref_v1",
            "status": "cleanup_pending",
            "outcome": "indeterminate",
            "authority_kind": "test",
            "run_id": operation["run_id"],
            "stage": operation["stage"],
            "operation_id": operation["operation_id"],
            "worker_id": worker["worker_id"],
            "model_request_id": worker["model_request_id"],
            "payload_sha256": worker["payload_sha256"],
            "reservation_ref": operation["provider_reservation_ref"],
            "acquisition_owner_ref": operation["acquisition_owner_ref"],
            "acquisition_intent_ref": operation["acquisition_intent_ref"],
            "runtime_owner_ref": operation["runtime_owner_ref"],
            "cleanup_receipt_ref": None,
        }
    )

    with pytest.raises(
        workflow_service.LearningWorkflowStageOperationError,
        match="B2 cleanup lineage differs",
    ):
        workflow_service._validate_benchmark_v2_provider_cleanup_parent(
            cleanup=pending,
            operation=operation,
            result_identity=None,
            authority_kind="test",
            allowed_outcomes={"verified_exact_process_exited"},
        )

    accepted = workflow_service._validate_benchmark_v2_provider_cleanup_parent(
        cleanup=pending,
        operation=operation,
        result_identity=None,
        authority_kind="test",
        allowed_outcomes={"verified_exact_process_exited"},
        allow_pending=True,
    )
    assert accepted == pending
    assert accepted["cleanup_receipt_ref"] is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("reservation_ref", {"content_sha256": "f" * 64}),
        ("outcome", "verified_exact_process_exited"),
        ("cleanup_receipt_ref", {"content_sha256": "e" * 64}),
    ],
)
def test_b2_pending_cleanup_rejects_resealed_authority_drift(
    source_bundle: dict[str, object],
    field: str,
    value: object,
) -> None:
    from app.learn import workflow_service
    from app.learn.recognition.uei.canonical import seal_immutable

    operation = _result_ready_document(
        source_bundle,
        result_identity={"content_sha256": "a" * 64},
    )
    worker = operation["worker_ref"]
    body = {
        "contract_version": "benchmark_provider_cleanup_ref_v1",
        "status": "cleanup_pending",
        "outcome": "indeterminate",
        "authority_kind": "test",
        "run_id": operation["run_id"],
        "stage": operation["stage"],
        "operation_id": operation["operation_id"],
        "worker_id": worker["worker_id"],
        "model_request_id": worker["model_request_id"],
        "payload_sha256": worker["payload_sha256"],
        "reservation_ref": operation["provider_reservation_ref"],
        "acquisition_owner_ref": operation["acquisition_owner_ref"],
        "acquisition_intent_ref": operation["acquisition_intent_ref"],
        "runtime_owner_ref": operation["runtime_owner_ref"],
        "cleanup_receipt_ref": None,
    }
    body[field] = value

    with pytest.raises(
        workflow_service.LearningWorkflowStageOperationError,
        match="B2 cleanup lineage differs",
    ):
        workflow_service._validate_benchmark_v2_provider_cleanup_parent(
            cleanup=seal_immutable(body),
            operation=operation,
            result_identity=None,
            authority_kind="test",
            allowed_outcomes={"verified_exact_process_exited"},
            allow_pending=True,
        )


def test_b1_not_launched_cleanup_rejects_correctly_resealed_wrong_reservation(
    source_bundle: dict[str, object],
) -> None:
    from app.learn import workflow_service
    from app.learn.recognition.uei.canonical import seal_immutable

    operation = _result_ready_document(
        source_bundle,
        result_identity={"content_sha256": "a" * 64},
    )
    worker = operation["worker_ref"]
    launch_owner = seal_immutable(
        {
            "contract_version": "benchmark_worker_launch_owner_inspection_v1",
            "authority_kind": "test",
            "run_id": operation["run_id"],
            "stage": operation["stage"],
            "operation_id": operation["operation_id"],
            "worker_id": worker["worker_id"],
            "model_request_id": worker["model_request_id"],
            "payload_sha256": worker["payload_sha256"],
            "execution_nonce": operation["execution_nonce"],
            "reservation_ref": operation["reservation_ref"],
            "current_reservation_ref": {"content_sha256": "4" * 64},
            "operation_anchor_ref": operation["operation_anchor_ref"],
            "expected_supervision_ref": operation["expected_supervision_ref"],
            "supervision_ref": None,
            "reservation_state": "aborted_before_launch",
            "owner_phase": "reservation_aborted",
            "assignment_state": "not_proven",
            "process_identity": None,
            "scope_name": None,
            "assignment_proven_ref": None,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    cleanup = seal_immutable(
        {
            "contract_version": "benchmark_worker_cleanup_receipt_v1",
            "outcome": "verified_not_launched",
            "operation_anchor_ref": operation["operation_anchor_ref"],
            "reservation_ref": {"content_sha256": "d" * 64},
            "supervision_ref": None,
            "run_id": operation["run_id"],
            "stage": operation["stage"],
            "operation_id": operation["operation_id"],
            "worker_id": worker["worker_id"],
            "process_identity": None,
            "assignment_proven_ref": None,
            "finalization_intent_ref": None,
            "exact_handle_observation_refs": {},
            "job_absence_observation_ref": None,
            "worker_absence_observation_ref": {"content_sha256": "8" * 64},
            "supervisor_absence_observation_ref": None,
            "reservation_abort_ref": {"content_sha256": "9" * 64},
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )

    with pytest.raises(
        workflow_service.LearningWorkflowStageOperationError,
        match="B1 cleanup owner differs",
    ):
        workflow_service._validate_benchmark_v2_worker_cleanup_parent(
            cleanup=cleanup,
            operation=operation,
            launch_owner=launch_owner,
            allowed_outcomes={"verified_not_launched"},
        )


@pytest.mark.parametrize(
    ("parent_kind", "mutation"),
    [
        ("b1", "extra"),
        ("b1", "missing"),
        ("b1", "cross_parent"),
        ("b2", "extra"),
        ("b2", "missing"),
        ("b2", "cross_parent"),
    ],
)
def test_result_ready_completion_rejects_resealed_cleanup_projection_without_store_cas(
    parent_kind: str,
    mutation: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source_bundle: dict[str, object],
) -> None:
    from contextlib import nullcontext

    from app.learn import workflow_service
    from app.learn.hybrid.benchmark_v2_incumbent_operation import (
        transition_benchmark_v2_incumbent_operation,
    )
    from app.learn.recognition.uei.canonical import seal_immutable
    from app.learn.workflow_service import start_learning_workflow_stage_operation
    from app.learn.workflow_store import LearningWorkflowRunStore

    result_snapshot = {
        "contract_version": "learning_stage_worker_completed_result_identity_v1",
        "status": "completed",
        "worker_id": "worker-c1",
        "run_id": "run-c1",
        "stage": "screen_understanding",
        "operation_id": "operation-c1",
        "task_kind": "vision_observe_screen",
        "model_request_id": "request-c1",
        "payload_sha256": source_bundle["handler_payload_source"][
            "handler_payload_sha256"
        ],
        "result_sha256": "a" * 64,
        "result_available": True,
        "normal_binding_evidence_ref": {"content_sha256": "b" * 64},
        "provider_cleanup_evidence_ref": {"content_sha256": "c" * 64},
    }
    operation = _prepared_document(source_bundle, prepared_revision=4)
    operation_documents = [operation]
    operation = transition_benchmark_v2_incumbent_operation(
        operation,
        to_phase="provider_owner_prepared",
        changes=_provider_owner_changes(),
    )
    operation_documents.append(operation)
    operation = transition_benchmark_v2_incumbent_operation(
        operation,
        to_phase="worker_starting",
        changes={},
    )
    operation_documents.append(operation)
    operation = transition_benchmark_v2_incumbent_operation(
        operation,
        to_phase="worker_bound",
        changes={
            "worker_ref": {
                **operation["worker_ref"],
                "supervision_ref": {"content_sha256": "9" * 64},
            }
        },
    )
    operation_documents.append(operation)
    operation = transition_benchmark_v2_incumbent_operation(
        operation,
        to_phase="result_ready",
        changes={"result_identity_ref": seal_immutable(result_snapshot)},
    )
    operation_documents.append(operation)
    worker = operation["worker_ref"]
    process_identity = {"pid": 321, "create_time_ns": 654}
    launch_owner = seal_immutable(
        {
            "contract_version": "benchmark_worker_launch_owner_inspection_v1",
            "authority_kind": "test",
            "run_id": operation["run_id"],
            "stage": operation["stage"],
            "operation_id": operation["operation_id"],
            "worker_id": worker["worker_id"],
            "model_request_id": worker["model_request_id"],
            "payload_sha256": worker["payload_sha256"],
            "execution_nonce": operation["execution_nonce"],
            "reservation_ref": operation["reservation_ref"],
            "current_reservation_ref": {"content_sha256": "4" * 64},
            "operation_anchor_ref": operation["operation_anchor_ref"],
            "expected_supervision_ref": operation["expected_supervision_ref"],
            "supervision_ref": worker["supervision_ref"],
            "reservation_state": "launched",
            "owner_phase": "gate_released",
            "assignment_state": "proven",
            "process_identity": process_identity,
            "scope_name": "Local\\AgentGuiBenchmarkWorker-" + "1" * 64,
            "assignment_proven_ref": {"content_sha256": "5" * 64},
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    b1_body = {
        "contract_version": "benchmark_worker_cleanup_receipt_v1",
        "outcome": "verified_exact_worker_exited",
        "operation_anchor_ref": operation["operation_anchor_ref"],
        "reservation_ref": launch_owner["current_reservation_ref"],
        "supervision_ref": launch_owner["supervision_ref"],
        "run_id": operation["run_id"],
        "stage": operation["stage"],
        "operation_id": operation["operation_id"],
        "worker_id": worker["worker_id"],
        "process_identity": process_identity,
        "assignment_proven_ref": launch_owner["assignment_proven_ref"],
        "finalization_intent_ref": {"content_sha256": "6" * 64},
        "exact_handle_observation_refs": {
            "process": {"content_sha256": "7" * 64}
        },
        "job_absence_observation_ref": {"content_sha256": "8" * 64},
        "worker_absence_observation_ref": {"content_sha256": "9" * 64},
        "supervisor_absence_observation_ref": None,
        "reservation_abort_ref": None,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    b2_body = {
        "contract_version": "benchmark_provider_cleanup_ref_v1",
        "status": "cleanup_verified",
        "outcome": "verified_exact_process_exited",
        "authority_kind": "test",
        "run_id": operation["run_id"],
        "stage": operation["stage"],
        "operation_id": operation["operation_id"],
        "worker_id": worker["worker_id"],
        "model_request_id": worker["model_request_id"],
        "payload_sha256": worker["payload_sha256"],
        "reservation_ref": operation["provider_reservation_ref"],
        "acquisition_owner_ref": operation["acquisition_owner_ref"],
        "acquisition_intent_ref": operation["acquisition_intent_ref"],
        "runtime_owner_ref": operation["runtime_owner_ref"],
        "cleanup_receipt_ref": result_snapshot["provider_cleanup_evidence_ref"],
    }
    target = deepcopy(b1_body if parent_kind == "b1" else b2_body)
    if mutation == "extra":
        target["unexpected"] = False
    elif mutation == "missing":
        target.pop("finalization_intent_ref" if parent_kind == "b1" else "status")
    elif parent_kind == "b1":
        target["supervision_ref"] = {"content_sha256": "d" * 64}
    else:
        target["acquisition_owner_ref"] = {"content_sha256": "d" * 64}
    malformed = seal_immutable(target)
    worker_cleanup = malformed if parent_kind == "b1" else seal_immutable(b1_body)
    provider_cleanup = malformed if parent_kind == "b2" else seal_immutable(b2_body)
    events: list[str] = []

    class _Registry(_UnitCleanupReceiptAuthority):
        def inspect_completed_result_identity(self, **_kwargs):
            events.append("inspect_a")
            return deepcopy(result_snapshot)

        def inspect_benchmark_worker_launch_owner(self, **_kwargs):
            events.append("inspect_b1")
            if "worker_cleanup" not in events:
                return deepcopy(launch_owner)
            after = deepcopy(launch_owner)
            after.pop("content_sha256")
            after["owner_phase"] = "cleanup_finalization_intent"
            return seal_immutable(after)

        def observe_benchmark_worker_cleanup(self, **_kwargs):
            events.append("worker_cleanup")
            return deepcopy(worker_cleanup)

        def verify_benchmark_worker_cleanup_receipt(self, **kwargs):
            events.append("worker_verify")
            if parent_kind == "b1":
                raise ValueError("B1 authority rejected invented cleanup leaves")
            return deepcopy(kwargs["receipt"])

        def reconcile_benchmark_provider_cleanup(self, **_kwargs):
            events.append("provider_cleanup")
            return deepcopy(provider_cleanup)

        def adopt_result(self, **_kwargs):
            events.append("adopt")
            raise AssertionError("cleanup projection reached terminal adoption")

    monkeypatch.setattr(
        "app.learn.hybrid.benchmark_v2_worker_binding.resolve_server_worker_window_binding",
        lambda **kwargs: {
            "worker_process_identity": deepcopy(kwargs["worker_process_identity"]),
            "normal_binding_evidence_ref": deepcopy(
                kwargs["normal_binding_evidence_ref"]
            ),
        },
    )
    monkeypatch.setattr(
        "app.learn.workflow_worker.hold_benchmark_worker_controller",
        lambda **_kwargs: nullcontext(),
    )

    state_path = tmp_path / f"{parent_kind}-{mutation}-state.json"
    store = LearningWorkflowRunStore(state_path=state_path)
    try:
        first = store.transition(
            run_id=operation["run_id"],
            expected_revision=0,
            stage="bind_capture",
            outcome="running",
            evidence_refs={},
        )
        bound = store.transition(
            run_id=operation["run_id"],
            expected_revision=first["revision"],
            stage="bind_capture",
            outcome="completed",
            evidence_refs={"image_path": str(tmp_path / "capture.bmp")},
        )
        started = start_learning_workflow_stage_operation(
            store=store,
            project_root=tmp_path,
            run_id=operation["run_id"],
            expected_revision=bound["revision"],
            stage=operation["stage"],
            operation_id=operation["operation_id"],
        )["workflow_state"]
        current = started
        for operation_document in operation_documents:
            stage_execution = deepcopy(
                current["stages"][operation["stage"]]["evidence_refs"][
                    "stage_execution"
                ]
            )
            stage_execution["benchmark_v2_incumbent"] = deepcopy(operation_document)
            stage_execution["benchmark_v2_operation_anchor"] = {
                "contract_version": "benchmark_worker_operation_anchor_v1",
                "anchor_identity_sha256": operation["operation_anchor_ref"][
                    "content_sha256"
                ],
                "expected_supervision_ref": deepcopy(
                    operation["expected_supervision_ref"]
                ),
            }
            current = store.transition(
                run_id=operation["run_id"],
                expected_revision=current["revision"],
                stage=operation["stage"],
                outcome="running",
                evidence_refs={"stage_execution": stage_execution},
            )
            assert current["revision"] == operation_document["current_document_revision"]
        anchored = current
        assert anchored["revision"] == operation["current_document_revision"]
        composition = workflow_service.compose_test_learning_workflow_service_unit(
            store=store,
            worker_registry=_Registry(),
            project_root=tmp_path,
            benchmark_supervision_root=type(
                "_Root", (), {"authority_kind": "test"}
            )(),
            provider_case_resolver=source_bundle["provider_case_resolver"],
            benchmark_v2_worker_binding_resolver=object(),
        )
        before_state = store.get(operation["run_id"])
        before_bytes = state_path.read_bytes()
        cas_winners: list[int] = []
        real_transition = store.transition

        def observe_cas(**kwargs):
            state = real_transition(**kwargs)
            cas_winners.append(int(state["revision"]))
            return state

        monkeypatch.setattr(store, "transition", observe_cas)
        with pytest.raises(workflow_service.LearningWorkflowStageOperationError):
            workflow_service.continue_guarded_learning_stage_worker_result(
                composition=composition,
                run_id=operation["run_id"],
                expected_revision=anchored["revision"],
                stage=operation["stage"],
                operation_id=operation["operation_id"],
                worker_id=worker["worker_id"],
            )

        after_state = store.get(operation["run_id"])
        after_operation = after_state["stages"][operation["stage"]]["evidence_refs"][
            "stage_execution"
        ]["benchmark_v2_incumbent"]
        assert state_path.read_bytes() == before_bytes
        assert after_state == before_state
        assert after_state["revision"] == anchored["revision"]
        assert after_operation["phase"] == "result_ready"
        assert after_operation.get("terminal_intent") is None
        assert cas_winners == []
        assert "adopt" not in events
    finally:
        store.close()


def test_completion_persists_real_b1_cleanup_parent_only_after_all_parent_joins(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source_bundle: dict[str, object],
) -> None:
    from contextlib import nullcontext
    from app.learn import workflow_service
    from app.learn.recognition.uei.canonical import seal_immutable

    base = _prepared_document(source_bundle)
    worker = base["worker_ref"]
    snapshot = {
        "contract_version": "learning_stage_worker_completed_result_identity_v1",
        "status": "completed",
        "worker_id": worker["worker_id"],
        "run_id": base["run_id"],
        "stage": base["stage"],
        "operation_id": base["operation_id"],
        "task_kind": "vision_observe_screen",
        "model_request_id": worker["model_request_id"],
        "payload_sha256": worker["payload_sha256"],
        "result_sha256": "a" * 64,
        "result_available": True,
        "normal_binding_evidence_ref": {"content_sha256": "b" * 64},
        "provider_cleanup_evidence_ref": {"content_sha256": "c" * 64},
    }
    operation = _result_ready_document(
        source_bundle, result_identity=seal_immutable(snapshot)
    )
    process_identity = {"pid": 321, "create_time_ns": 654}
    launch_owner = seal_immutable(
        {
            "contract_version": "benchmark_worker_launch_owner_inspection_v1",
            "authority_kind": "test",
            "run_id": operation["run_id"],
            "stage": operation["stage"],
            "operation_id": operation["operation_id"],
            "worker_id": worker["worker_id"],
            "model_request_id": worker["model_request_id"],
            "payload_sha256": worker["payload_sha256"],
            "execution_nonce": operation["execution_nonce"],
            "reservation_ref": operation["reservation_ref"],
            "current_reservation_ref": {"content_sha256": "4" * 64},
            "operation_anchor_ref": operation["operation_anchor_ref"],
            "expected_supervision_ref": operation["expected_supervision_ref"],
            "supervision_ref": operation["worker_ref"]["supervision_ref"],
            "reservation_state": "launched",
            "owner_phase": "gate_released",
            "assignment_state": "proven",
            "process_identity": process_identity,
            "scope_name": "Local\\AgentGuiBenchmarkWorker-" + "1" * 64,
            "assignment_proven_ref": {"content_sha256": "5" * 64},
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    worker_cleanup = seal_immutable(
        {
            "contract_version": "benchmark_worker_cleanup_receipt_v1",
            "outcome": "verified_exact_worker_exited",
            "operation_anchor_ref": operation["operation_anchor_ref"],
            "reservation_ref": launch_owner["current_reservation_ref"],
            "supervision_ref": launch_owner["supervision_ref"],
            "run_id": operation["run_id"],
            "stage": operation["stage"],
            "operation_id": operation["operation_id"],
            "worker_id": worker["worker_id"],
            "process_identity": process_identity,
            "assignment_proven_ref": launch_owner["assignment_proven_ref"],
            "finalization_intent_ref": {"content_sha256": "6" * 64},
            "exact_handle_observation_refs": {"process": {"content_sha256": "d" * 64}},
            "job_absence_observation_ref": {"content_sha256": "e" * 64},
            "worker_absence_observation_ref": {"content_sha256": "f" * 64},
            "supervisor_absence_observation_ref": None,
            "reservation_abort_ref": None,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    provider_cleanup = seal_immutable(
        {
            "contract_version": "benchmark_provider_cleanup_ref_v1",
            "status": "cleanup_verified",
            "outcome": "verified_exact_process_exited",
            "authority_kind": "test",
            "run_id": operation["run_id"],
            "stage": operation["stage"],
            "operation_id": operation["operation_id"],
            "worker_id": worker["worker_id"],
            "model_request_id": worker["model_request_id"],
            "payload_sha256": worker["payload_sha256"],
            "reservation_ref": operation["provider_reservation_ref"],
            "acquisition_owner_ref": operation["acquisition_owner_ref"],
            "acquisition_intent_ref": operation["acquisition_intent_ref"],
            "runtime_owner_ref": operation["runtime_owner_ref"],
            "cleanup_receipt_ref": snapshot["provider_cleanup_evidence_ref"],
        }
    )
    events: list[str] = []

    class _Store:
        def get(self, _run_id):
            return {"revision": operation["current_document_revision"]}

    class _Registry(_UnitCleanupReceiptAuthority):
        def inspect_completed_result_identity(self, **_kwargs):
            events.append("inspect_a")
            return deepcopy(snapshot)

        def inspect_benchmark_worker_launch_owner(self, **_kwargs):
            events.append("inspect_b1")
            if "worker_cleanup" not in events:
                return deepcopy(launch_owner)
            after = deepcopy(launch_owner)
            after.pop("content_sha256")
            after["owner_phase"] = "cleanup_finalization_intent"
            return seal_immutable(after)

        def observe_benchmark_worker_cleanup(self, **_kwargs):
            events.append("worker_cleanup")
            return deepcopy(worker_cleanup)

        def reconcile_benchmark_provider_cleanup(self, **_kwargs):
            events.append("provider_cleanup")
            return deepcopy(provider_cleanup)

    def resolve_binding(**_kwargs):
        events.append("resolve_task5")
        return {
            "worker_process_identity": deepcopy(process_identity),
            "normal_binding_evidence_ref": deepcopy(
                snapshot["normal_binding_evidence_ref"]
            ),
        }

    monkeypatch.setattr(
        "app.learn.hybrid.benchmark_v2_worker_binding.resolve_server_worker_window_binding",
        resolve_binding,
    )
    composition = workflow_service.compose_test_learning_workflow_service_unit(
        store=_Store(), worker_registry=_Registry(), project_root=tmp_path,
        benchmark_supervision_root=type(
            "_Root", (), {"authority_kind": "test"}
        )(),
        provider_case_resolver=object(), benchmark_v2_worker_binding_resolver=object(),
    )
    monkeypatch.setattr(
        workflow_service, "get_learning_workflow_operation_lock", lambda **_kwargs: nullcontext()
    )
    monkeypatch.setattr(
        "app.learn.workflow_worker.hold_benchmark_worker_controller",
        lambda **_kwargs: nullcontext(),
    )
    monkeypatch.setattr(
        workflow_service, "_benchmark_v2_incumbent_operation_from_state",
        lambda *_args: deepcopy(operation),
    )
    monkeypatch.setattr(
        workflow_service, "_benchmark_v2_sidecars", lambda *_args: ({}, {"anchor": True})
    )
    persisted: list[dict[str, object]] = []

    def crash_after_intent(**kwargs):
        events.append("persist_intent")
        persisted.append(deepcopy(kwargs["operation"]))
        raise RuntimeError("crash after intent")

    monkeypatch.setattr(
        workflow_service, "_persist_benchmark_v2_incumbent_operation", crash_after_intent
    )
    with pytest.raises(RuntimeError, match="crash after intent"):
        workflow_service._resume_benchmark_v2_incumbent_operation(
            composition=composition, run_id=operation["run_id"],
            expected_revision=operation["current_document_revision"],
            stage=operation["stage"], operation_id=operation["operation_id"],
            worker_id=worker["worker_id"],
        )
    assert events == [
        "inspect_a",
        "inspect_b1",
        "resolve_task5",
        "worker_cleanup",
        "inspect_b1",
        "provider_cleanup",
        "persist_intent",
    ]
    assert persisted[0]["terminal_intent"]["worker_cleanup_evidence_ref"] == worker_cleanup


def test_cancel_restart_rejects_b1_identity_drift_before_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source_bundle: dict[str, object],
) -> None:
    from contextlib import nullcontext
    from app.learn import workflow_service
    from app.learn.hybrid.benchmark_v2_incumbent_operation import (
        compose_benchmark_v2_incumbent_cancel_intent,
        transition_benchmark_v2_incumbent_operation,
    )
    from app.learn.recognition.uei.canonical import seal_immutable

    operation = _prepared_document(source_bundle)
    operation = transition_benchmark_v2_incumbent_operation(
        operation,
        to_phase="provider_owner_prepared",
        changes=_provider_owner_changes(),
    )
    operation = transition_benchmark_v2_incumbent_operation(
        operation, to_phase="worker_starting", changes={}
    )
    operation = transition_benchmark_v2_incumbent_operation(
        operation,
        to_phase="worker_bound",
        changes={
            "worker_ref": {
                **operation["worker_ref"],
                "supervision_ref": {"content_sha256": "9" * 64},
            }
        },
    )
    process_identity = {"pid": 456, "create_time_ns": 789}
    scope_name = "Local\\AgentGuiBenchmarkWorker-" + "2" * 64
    assignment_ref = {"content_sha256": "3" * 64}
    intent = compose_benchmark_v2_incumbent_cancel_intent(
        operation=operation,
        reason="cancel",
        intent_at="2026-08-27T00:00:00+00:00",
        process_identity=process_identity,
        scope_name=scope_name,
        assignment_proven_ref=assignment_ref,
    )
    operation = transition_benchmark_v2_incumbent_operation(
        operation, to_phase="cancel_intent", changes={"cancel_intent": intent}
    )
    inspection = seal_immutable(
        {
            "contract_version": "benchmark_worker_launch_owner_inspection_v1",
            "authority_kind": "test",
            "run_id": operation["run_id"],
            "stage": operation["stage"],
            "operation_id": operation["operation_id"],
            "worker_id": operation["worker_ref"]["worker_id"],
            "model_request_id": operation["worker_ref"]["model_request_id"],
            "payload_sha256": operation["worker_ref"]["payload_sha256"],
            "execution_nonce": operation["execution_nonce"],
            "reservation_ref": operation["reservation_ref"],
            "current_reservation_ref": {"content_sha256": "4" * 64},
            "operation_anchor_ref": operation["operation_anchor_ref"],
            "expected_supervision_ref": operation["expected_supervision_ref"],
            "supervision_ref": operation["worker_ref"]["supervision_ref"],
            "reservation_state": "launched",
            "owner_phase": "gate_released",
            "assignment_state": "proven",
            "process_identity": process_identity,
            "scope_name": scope_name + "-drift",
            "assignment_proven_ref": assignment_ref,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    events: list[str] = []

    class _Store:
        def get(self, _run_id):
            return {"revision": operation["current_document_revision"]}

    class _Registry(_UnitCleanupReceiptAuthority):
        def inspect_benchmark_worker_launch_owner(self, **_kwargs):
            events.append("inspect_b1")
            return deepcopy(inspection)

        def observe_benchmark_worker_cleanup(self, **_kwargs):
            events.append("cleanup")
            raise AssertionError("cleanup is forbidden after identity drift")

    composition = workflow_service.compose_test_learning_workflow_service_unit(
        store=_Store(), worker_registry=_Registry(), project_root=tmp_path,
        benchmark_supervision_root=type(
            "_Root", (), {"authority_kind": "test"}
        )(),
        provider_case_resolver=object(), benchmark_v2_worker_binding_resolver=object(),
    )
    monkeypatch.setattr(
        workflow_service, "get_learning_workflow_operation_lock", lambda **_kwargs: nullcontext()
    )
    monkeypatch.setattr(
        "app.learn.workflow_worker.hold_benchmark_worker_controller",
        lambda **_kwargs: nullcontext(),
    )
    monkeypatch.setattr(
        workflow_service, "_benchmark_v2_incumbent_operation_from_state",
        lambda *_args: deepcopy(operation),
    )
    monkeypatch.setattr(
        workflow_service, "_benchmark_v2_sidecars", lambda *_args: ({}, {"anchor": True})
    )
    persisted: list[object] = []
    monkeypatch.setattr(
        workflow_service, "_persist_benchmark_v2_incumbent_operation",
        lambda **kwargs: persisted.append(kwargs) or {},
    )
    with pytest.raises(
        workflow_service.LearningWorkflowStageOperationError,
        match="cancel intent B1 identity differs",
    ):
        workflow_service._cancel_benchmark_v2_incumbent_operation(
            composition=composition, run_id=operation["run_id"],
            expected_revision=operation["current_document_revision"],
            stage=operation["stage"], operation_id=operation["operation_id"],
            reason="cancel replay",
        )
    assert events == ["inspect_b1"]
    assert persisted == []


def test_cancel_rejects_self_sealed_invented_b1_cleanup_leaves_before_any_cas(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source_bundle: dict[str, object],
) -> None:
    from contextlib import nullcontext
    from app.learn import workflow_service
    from app.learn.hybrid.benchmark_v2_incumbent_operation import (
        compose_benchmark_v2_incumbent_cancel_intent,
        transition_benchmark_v2_incumbent_operation,
    )
    from app.learn.recognition.uei.canonical import seal_immutable

    operation = _prepared_document(source_bundle)
    operation = transition_benchmark_v2_incumbent_operation(
        operation,
        to_phase="provider_owner_prepared",
        changes=_provider_owner_changes(),
    )
    operation = transition_benchmark_v2_incumbent_operation(
        operation, to_phase="worker_starting", changes={}
    )
    operation = transition_benchmark_v2_incumbent_operation(
        operation,
        to_phase="worker_bound",
        changes={
            "worker_ref": {
                **operation["worker_ref"],
                "supervision_ref": {"content_sha256": "9" * 64},
            }
        },
    )
    process_identity = {"pid": 456, "create_time_ns": 789}
    scope_name = "Local\\AgentGuiBenchmarkWorker-" + "2" * 64
    assignment_ref = {"content_sha256": "3" * 64}
    intent = compose_benchmark_v2_incumbent_cancel_intent(
        operation=operation,
        reason="cancel",
        intent_at="2026-08-27T00:00:00+00:00",
        process_identity=process_identity,
        scope_name=scope_name,
        assignment_proven_ref=assignment_ref,
    )
    operation = transition_benchmark_v2_incumbent_operation(
        operation, to_phase="cancel_intent", changes={"cancel_intent": intent}
    )
    inspection = seal_immutable(
        {
            "contract_version": "benchmark_worker_launch_owner_inspection_v1",
            "authority_kind": "test",
            "run_id": operation["run_id"],
            "stage": operation["stage"],
            "operation_id": operation["operation_id"],
            "worker_id": operation["worker_ref"]["worker_id"],
            "model_request_id": operation["worker_ref"]["model_request_id"],
            "payload_sha256": operation["worker_ref"]["payload_sha256"],
            "execution_nonce": operation["execution_nonce"],
            "reservation_ref": operation["reservation_ref"],
            "current_reservation_ref": {"content_sha256": "4" * 64},
            "operation_anchor_ref": operation["operation_anchor_ref"],
            "expected_supervision_ref": operation["expected_supervision_ref"],
            "supervision_ref": operation["worker_ref"]["supervision_ref"],
            "reservation_state": "launched",
            "owner_phase": "gate_released",
            "assignment_state": "proven",
            "process_identity": process_identity,
            "scope_name": scope_name,
            "assignment_proven_ref": assignment_ref,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    invented_cleanup = seal_immutable(
        {
            "contract_version": "benchmark_worker_cleanup_receipt_v1",
            "outcome": "verified_exact_worker_exited",
            "operation_anchor_ref": operation["operation_anchor_ref"],
            "reservation_ref": inspection["current_reservation_ref"],
            "supervision_ref": inspection["supervision_ref"],
            "run_id": operation["run_id"],
            "stage": operation["stage"],
            "operation_id": operation["operation_id"],
            "worker_id": operation["worker_ref"]["worker_id"],
            "process_identity": process_identity,
            "assignment_proven_ref": assignment_ref,
            "finalization_intent_ref": {"content_sha256": "a" * 64},
            "exact_handle_observation_refs": {
                "worker_process": {"content_sha256": "b" * 64},
                "startup_event": {"content_sha256": "c" * 64},
                "beacon_file": {"content_sha256": "d" * 64},
                "owner_job": {"content_sha256": "e" * 64},
            },
            "job_absence_observation_ref": {"content_sha256": "f" * 64},
            "worker_absence_observation_ref": {"content_sha256": "1" * 64},
            "supervisor_absence_observation_ref": None,
            "reservation_abort_ref": None,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    events: list[str] = []

    class _Store:
        def get(self, _run_id):
            return {"revision": operation["current_document_revision"]}

    class _Registry(_UnitCleanupReceiptAuthority):
        def inspect_benchmark_worker_launch_owner(self, **_kwargs):
            events.append("inspect_b1")
            return deepcopy(inspection)

        def observe_benchmark_worker_cleanup(self, **_kwargs):
            events.append("cleanup")
            return deepcopy(invented_cleanup)

        def verify_benchmark_worker_cleanup_receipt(self, **_kwargs):
            events.append("verify_b1")
            raise ValueError("B1 authority rejected invented cleanup leaves")

        def reconcile_benchmark_provider_cleanup(self, **_kwargs):
            raise AssertionError("invented B1 cleanup reached B2 reconciliation")

    composition = workflow_service.compose_test_learning_workflow_service_unit(
        store=_Store(),
        worker_registry=_Registry(),
        project_root=tmp_path,
        benchmark_supervision_root=type(
            "_Root", (), {"authority_kind": "test"}
        )(),
        provider_case_resolver=object(),
        benchmark_v2_worker_binding_resolver=object(),
    )
    monkeypatch.setattr(
        workflow_service,
        "get_learning_workflow_operation_lock",
        lambda **_kwargs: nullcontext(),
    )
    monkeypatch.setattr(
        "app.learn.workflow_worker.hold_benchmark_worker_controller",
        lambda **_kwargs: nullcontext(),
    )
    monkeypatch.setattr(
        workflow_service,
        "_benchmark_v2_incumbent_operation_from_state",
        lambda *_args: deepcopy(operation),
    )
    monkeypatch.setattr(
        workflow_service,
        "_benchmark_v2_sidecars",
        lambda *_args: ({}, {"anchor": True}),
    )
    cas_winners: list[dict[str, object]] = []
    monkeypatch.setattr(
        workflow_service,
        "_persist_benchmark_v2_incumbent_operation",
        lambda **kwargs: cas_winners.append(deepcopy(kwargs["operation"])),
    )
    with pytest.raises(ValueError, match="invented cleanup leaves"):
        workflow_service._cancel_benchmark_v2_incumbent_operation(
            composition=composition,
            run_id=operation["run_id"],
            expected_revision=operation["current_document_revision"],
            stage=operation["stage"],
            operation_id=operation["operation_id"],
            reason="cancel",
        )
    assert events == ["inspect_b1", "cleanup", "verify_b1"]
    assert cas_winners == []


def test_window_adoption_rebuild_uses_only_resolver_and_exact_a_b1_parents(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source_bundle: dict[str, object],
) -> None:
    from app.learn import workflow_service
    from app.learn.recognition.uei.canonical import seal_immutable

    operation = _prepared_document(source_bundle)
    result_identity = seal_immutable(
        {
            "contract_version": "learning_stage_worker_completed_result_identity_v1",
            "status": "completed",
            "worker_id": operation["worker_ref"]["worker_id"],
            "run_id": operation["run_id"],
            "stage": operation["stage"],
            "operation_id": operation["operation_id"],
            "task_kind": "vision_observe_screen",
            "model_request_id": operation["worker_ref"]["model_request_id"],
            "payload_sha256": operation["worker_ref"]["payload_sha256"],
            "result_sha256": "a" * 64,
            "result_available": True,
            "normal_binding_evidence_ref": {"content_sha256": "b" * 64},
            "provider_cleanup_evidence_ref": {"content_sha256": "c" * 64},
        }
    )
    launch_owner = {
        "process_identity": {"pid": 123, "create_time_ns": 456},
    }
    resolver = object()
    composition = workflow_service.compose_test_learning_workflow_service_unit(
        store=object(), worker_registry=object(), project_root=tmp_path,
        provider_case_resolver=object(), benchmark_v2_worker_binding_resolver=resolver,
    )
    generic_adoption = {
        "contract_version": "learning_stage_worker_result_adoption_v1",
        "status": "adopted",
        "receipt": {"result_sha256": result_identity["result_sha256"]},
        "response": {"success": True},
    }
    calls: list[dict[str, object]] = []
    expected = seal_immutable(
        {
            "contract_version": "portfolio_hybrid_benchmark_v2_worker_window_binding_adoption_v1",
            "normal_clear_receipt_ref": result_identity[
                "normal_binding_evidence_ref"
            ]["content_sha256"],
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )

    def adopt_from_resolver(**kwargs):
        calls.append(kwargs)
        return deepcopy(expected)

    monkeypatch.setattr(
        "app.learn.hybrid.benchmark_v2_worker_binding.validate_benchmark_v2_worker_window_binding_adoption_from_resolver",
        adopt_from_resolver,
    )
    rebuilt = workflow_service._rebuild_benchmark_v2_window_adoption(
        composition=composition,
        operation=operation,
        generic_adoption=generic_adoption,
        authoritative_payload=source_bundle["authoritative_payload"],
        launch_owner=launch_owner,
        result_identity=result_identity,
    )
    assert rebuilt == expected
    assert calls == [
        {
            "resolver": resolver,
            "run_id": operation["run_id"],
            "stage": operation["stage"],
            "operation_id": operation["operation_id"],
            "window_binding_ref": operation["window_binding_ref"],
            "capture_ref": operation["capture_ref"],
            "worker_process_identity": launch_owner["process_identity"],
            "normal_binding_evidence_ref": result_identity[
                "normal_binding_evidence_ref"
            ],
            "worker_payload": source_bundle["authoritative_payload"],
            "generic_adoption": generic_adoption,
        }
    ]


@pytest.mark.skipif(os.name != "nt", reason="Windows benchmark ownership required")
def test_real_registry_spawn_recorded_qwen_completion_survives_fresh_restarts(
    tmp_path: Path,
    validated_provider_snapshot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import psutil

    from app.core import model_server
    from app.learn.hybrid.benchmark_v2_provider_corpus import (
        compose_test_provider_case_resolver,
    )
    from app.learn.hybrid.benchmark_v2_window_owner import (
        close_owned_window,
        launch_owned_window,
    )
    from app.learn.hybrid.benchmark_v2_worker_binding import (
        compose_test_server_worker_window_binding_publisher,
        publish_server_worker_window_binding,
    )
    from app.learn.hybrid.windows_process_scope import (
        WindowsProcessScope,
        benchmark_worker_controller_mutex_name_v1,
        observe_process_scope_cleanup,
        process_scope_name,
        spawn_process_in_scope,
    )
    from app.learn.workflow_service import (
        compose_test_learning_workflow_service,
        continue_guarded_learning_stage_worker_result,
        start_guarded_learning_stage_worker,
        start_learning_workflow_stage_operation,
    )
    from app.learn.workflow_store import LearningWorkflowRunStore
    from app.learn.workflow_worker import (
        LearningStageWorkerRegistry,
        compose_test_benchmark_worker_supervision_root,
    )

    project_root = tmp_path / "real-c-service"
    project_root.mkdir()
    state_path = project_root / "state.json"
    worker_root = project_root / "workers"
    lease_dir = project_root / "qwen-leases"
    from PIL import Image

    from app.learn.hybrid.benchmark_v2_contracts import canonical_json_bytes
    from app.learn.hybrid.benchmark_v2_provider_corpus import (
        validate_preloaded_provider_corpus,
    )
    from app.learn.recognition.uei.canonical import content_sha256, seal_immutable

    base_corpus, _base_file_ref = validated_provider_snapshot
    source_case = base_corpus["cases"][0]
    source_image = (PROJECT_ROOT / str(source_case["image"]["path"])).resolve()
    benchmark_bmp = project_root / "recorded-qwen-provider.bmp"
    with Image.open(source_image) as opened:
        opened.convert("RGB").save(benchmark_bmp, format="BMP")
    benchmark_bmp_sha = hashlib.sha256(benchmark_bmp.read_bytes()).hexdigest()
    corpus_candidate = deepcopy(base_corpus)
    source_group = source_case["screen_group"]
    for candidate in corpus_candidate["cases"]:
        if candidate["screen_group"] == source_group:
            candidate["image"]["sha256"] = benchmark_bmp_sha
    corpus_candidate.pop("content_sha256")
    corpus_candidate["content_sha256"] = content_sha256(corpus_candidate)
    corpus_raw = canonical_json_bytes(corpus_candidate, pretty=True)
    corpus_file_sha = hashlib.sha256(corpus_raw).hexdigest()
    corpus = validate_preloaded_provider_corpus(
        raw=corpus_raw, expected_sha256=corpus_file_sha
    )
    corpus_file_ref = seal_immutable(
        {
            "contract_version": "benchmark_v2_provider_corpus_file_ref_v1",
            "relative_path": "provider-corpus.v2.json",
            "file_sha256": corpus_file_sha,
            "source_parent_ref": {
                "content_sha256": corpus["source_parent_ref"]["content_sha256"]
            },
        }
    )
    run_id = "run-c-real-recorded"
    stage = "screen_understanding"
    operation_id = "operation-c-real-recorded"
    recorded_response = {
        "success": True,
        "recorded_qwen_response": {
            "model": "recorded-qwen",
            "content": "harmless observation only",
        },
        "action_candidates": [],
        "execute_binding_enabled": False,
    }
    context = multiprocessing.get_context("spawn")
    release_event = context.Event()
    provider_scope = None
    provider_helper = None
    provider_port = None
    owner = None
    owner_journal = project_root / "task5-owner.json"
    worker_identity = None
    worker_scope_name = None
    startup_event_name = None
    controller_mutex_name = None
    worker_id = None
    current_store = None
    current_registry = None
    current_root = None
    current_composition = None
    cleanup_errors: list[str] = []
    restart_cut_identities: list[dict[str, int]] = []
    restart_resources: list[dict[str, object]] = []

    def _fresh_composition(*, process_factory=None):
        store = current_store or LearningWorkflowRunStore(state_path=state_path)
        root = current_root or compose_test_benchmark_worker_supervision_root(
                journal_root=worker_root,
                test_capability=object(),
                workflow_store=store,
                test_store_capability=object(),
            )
        registry = LearningStageWorkerRegistry(
            result_root=worker_root,
            process_factory=process_factory,
            benchmark_supervision_root=root,
        )
        case_resolver = compose_test_provider_case_resolver(
            validated_corpus=corpus,
            provider_corpus_file_ref=corpus_file_ref,
            workflow_store=store,
            benchmark_supervision_root=root,
        )
        composition = compose_test_learning_workflow_service(
            store=store,
            worker_registry=registry,
            project_root=project_root,
            benchmark_supervision_root=root,
            provider_case_resolver=case_resolver,
        )
        return store, root, registry, case_resolver, composition

    def _drop_current() -> None:
        nonlocal current_store, current_registry, current_root, current_composition
        current_registry = None
        current_composition = None
        gc.collect()

    def _fresh_resume_cut(*, cleanup: bool = False) -> dict[str, object]:
        result_queue = context.Queue()
        process = context.Process(
            target=_recorded_qwen_incumbent_resume_cut,
            args=(
                str(project_root),
                str(state_path),
                str(worker_root),
                str(lease_dir),
                corpus_raw,
                corpus_file_sha,
                corpus_file_ref,
                run_id,
                stage,
                operation_id,
                worker_id,
                result_queue,
                cleanup,
            ),
            name="benchmark-v2-incumbent-fresh-resume",
        )
        resource = {"process": process, "queue": result_queue, "closed": False}
        restart_resources.append(resource)
        process.start()
        assert process.pid is not None
        restart_cut_identities.append(
            {
                "pid": process.pid,
                "create_time_ns": int(
                    round(psutil.Process(process.pid).create_time() * 1_000_000_000)
                ),
            }
        )
        message = result_queue.get(timeout=45)
        process.join(10)
        assert not process.is_alive(), message
        exitcode = process.exitcode
        process.close()
        result_queue.close()
        result_queue.join_thread()
        resource["closed"] = True
        assert exitcode == 0, message
        assert message["status"] == "ok", message
        return message["result"]

    try:
        monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", lease_dir)
        current_store, current_root, current_registry, case_resolver, current_composition = (
            _fresh_composition()
        )
        case_ref = _case_ref(case_resolver)
        case = case_resolver.resolve(case_ref)
        image_path = benchmark_bmp
        image_sha = hashlib.sha256(image_path.read_bytes()).hexdigest()
        owner = launch_owned_window(
            image_path=image_path,
            expected_sha256=image_sha,
            operation_id=operation_id,
            journal_path=owner_journal,
        )
        capture_ref = {
            "id": "capture-c-real-recorded",
            "content_sha256": image_sha,
        }
        authority = publish_server_worker_window_binding(
            publisher=compose_test_server_worker_window_binding_publisher(
                authority_root=project_root
            ),
            run_id=run_id,
            stage=stage,
            operation_id=operation_id,
            owner=owner,
            capture_ref=capture_ref,
        )
        first = current_store.transition(
            run_id=run_id,
            expected_revision=0,
            stage="bind_capture",
            outcome="running",
            evidence_refs={},
        )
        bound = current_store.transition(
            run_id=run_id,
            expected_revision=first["revision"],
            stage="bind_capture",
            outcome="completed",
            evidence_refs={"image_path": str(benchmark_bmp)},
        )
        started_operation = start_learning_workflow_stage_operation(
            store=current_store,
            project_root=project_root,
            run_id=run_id,
            expected_revision=bound["revision"],
            stage=stage,
            operation_id=operation_id,
        )

        def _recorded_process_factory(*, target, args, name):
            return context.Process(
                target=_recorded_qwen_benchmark_worker_entry,
                args=(
                    target,
                    args,
                    release_event,
                    str(lease_dir),
                    str(args[3]),
                    recorded_response,
                ),
                name=name,
            )

        _drop_current()
        current_store, current_root, current_registry, case_resolver, current_composition = (
            _fresh_composition(process_factory=_recorded_process_factory)
        )
        started = start_guarded_learning_stage_worker(
            composition=current_composition,
            run_id=run_id,
            expected_revision=started_operation["workflow_state"]["revision"],
            stage=stage,
            operation_id=operation_id,
            task_kind="vision_observe_screen",
            payload={
                "benchmark_v2_incumbent": {
                    "provider_case_ref": case_ref,
                    "window_binding_ref": authority["window_binding_ref"],
                    "capture_ref": capture_ref,
                }
            },
        )
        worker_id = started["worker_id"]
        operation_state = current_store.get(run_id)
        stage_execution = operation_state["stages"][stage]["evidence_refs"][
            "stage_execution"
        ]
        operation = stage_execution["benchmark_v2_incumbent"]
        launch_owner = current_registry.inspect_benchmark_worker_launch_owner(
            worker_id=worker_id,
            run_id=run_id,
            stage=stage,
            operation_id=operation_id,
            reservation_ref=operation["reservation_ref"],
            expected_operation_anchor=stage_execution[
                "benchmark_v2_operation_anchor"
            ],
            supervision_root=current_root,
        )
        worker_identity = deepcopy(launch_owner["process_identity"])
        worker_scope_name = launch_owner["scope_name"]
        startup_event_name = (
            "Local\\AgentGuiBenchmarkWorkerGate-"
            + hashlib.sha256(
                json.dumps(
                    {"scope_name": worker_scope_name},
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
        )
        controller_mutex_name = benchmark_worker_controller_mutex_name_v1(
            authority_kind=current_root.authority_kind,
            run_id=run_id,
            stage=stage,
            operation_id=operation_id,
        )

        provider_lineage = {
            "run_id": run_id,
            "workflow_revision": operation_state["revision"],
            "operation_id": operation_id,
            "stage": stage,
            "stage_execution_id": f"execution-{operation_id}",
        }
        provider_scope_name = process_scope_name(provider_lineage, "qwen")
        provider_scope = WindowsProcessScope(provider_scope_name, create=True)
        provider_helper = spawn_process_in_scope(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            scope_name=provider_scope_name,
            cwd=project_root,
        )
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            provider_port = int(probe.getsockname()[1])
        endpoint = f"http://127.0.0.1:{provider_port}/v1/chat/completions"
        base_url = f"http://127.0.0.1:{provider_port}/v1"
        readiness = {
            "started": True,
            "after": {
                "status": "running",
                "base_url": base_url,
                "model_id": "recorded-qwen",
                "server_process_identity": deepcopy(
                    provider_helper.process_identity
                ),
                "server_socket": {"host": "127.0.0.1", "port": provider_port},
            },
        }
        profile = {
            "profile_id": "recorded-qwen-benchmark",
            "endpoint": endpoint,
            "pid_file": str(project_root / "recorded-qwen.pid"),
        }
        monkeypatch.setenv("AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME", provider_scope_name)
        monkeypatch.setattr(
            model_server,
            "_observe_qwen_server_binding",
            lambda _selected, observed: {
                "server_process_identity": deepcopy(
                    observed["after"]["server_process_identity"]
                ),
                "server_socket": deepcopy(observed["after"]["server_socket"]),
            },
        )
        monkeypatch.setattr(
            model_server,
            "_attest_exact_qwen_socket_owner",
            lambda _server_socket, process_identity: (
                model_server._current_process_identity(process_identity["pid"])
                == process_identity
            ),
        )
        monkeypatch.setattr(
            model_server,
            "check_model_server",
            lambda _selected, timeout=1.0: {"status": "unreachable"},
        )
        lease = model_server.acquire_qwen_model_lease(
            profile=profile,
            request_id=operation["worker_ref"]["model_request_id"],
            readiness=readiness,
        )
        released = model_server._release_exact_qwen_lease(
            lease, reason="recorded-qwen-response-complete"
        )
        assert released["server_termination"] == "verified_exact_process_exited"
        release_event.set()

        deadline = time.monotonic() + 30
        status = None
        while time.monotonic() < deadline:
            status = current_registry.status(
                worker_id=worker_id,
                run_id=run_id,
                operation_id=operation_id,
            )
            if status["status"] == "completed":
                break
            time.sleep(0.05)
        assert status is not None and status["status"] == "completed"
        first_a = current_registry.inspect_completed_result_identity(
            worker_id=worker_id,
            run_id=run_id,
            stage=stage,
            operation_id=operation_id,
        )
        provider_receipt = model_server.observe_qwen_model_request_cleanup(
            operation["worker_ref"]["model_request_id"]
        )
        assert first_a["provider_cleanup_evidence_ref"] == {
            "content_sha256": provider_receipt["content_sha256"]
        }

        original_adopt = LearningStageWorkerRegistry.adopt_result

        def _crash_after_terminal_intent(self, **_kwargs):
            raise RuntimeError("crash after terminal intent")

        monkeypatch.setattr(
            LearningStageWorkerRegistry, "adopt_result", _crash_after_terminal_intent
        )
        with pytest.raises(RuntimeError, match="crash after terminal intent"):
            continue_guarded_learning_stage_worker_result(
                composition=current_composition,
                run_id=run_id,
                expected_revision=current_store.get(run_id)["revision"],
                stage=stage,
                operation_id=operation_id,
                worker_id=worker_id,
            )
        intent_state = current_store.get(run_id)
        intent_operation = intent_state["stages"][stage]["evidence_refs"][
            "stage_execution"
        ]["benchmark_v2_incumbent"]
        assert intent_operation["phase"] == "terminal_intent"
        monkeypatch.setattr(LearningStageWorkerRegistry, "adopt_result", original_adopt)

        current_store.close()
        current_store = None
        current_registry = None
        current_root = None
        current_composition = None
        gc.collect()
        completed = _fresh_resume_cut()
        assert completed["status"] == "complete"
        assert completed["terminal_receipt"]["provider_cleanup_outcome"] == (
            "verified_exact_process_exited"
        )
        terminal_bytes = json.dumps(
            completed["terminal_receipt"], sort_keys=True, separators=(",", ":")
        )

        replay = _fresh_resume_cut()
        assert replay["status"] == "complete"
        assert json.dumps(
            replay["terminal_receipt"], sort_keys=True, separators=(",", ":")
        ) == terminal_bytes
    finally:
        for resource in restart_resources:
            if resource["closed"]:
                continue
            process = resource["process"]
            queue = resource["queue"]
            try:
                if process.is_alive():
                    process.terminate()
                process.join(20)
                if process.is_alive():
                    cleanup_errors.append("restart process remained alive")
                process.close()
            except BaseException as error:
                cleanup_errors.append(f"restart process cleanup: {error}")
            try:
                queue.close()
                queue.join_thread()
            except BaseException as error:
                cleanup_errors.append(f"restart queue cleanup: {error}")
            resource["closed"] = True
        if current_registry is not None and worker_id is not None:
            try:
                current_registry.observe_benchmark_worker_cleanup(
                    worker_id=worker_id,
                    run_id=run_id,
                    stage=stage,
                    operation_id=operation_id,
                    terminate=True,
                    expected_operation_anchor=stage_execution[
                        "benchmark_v2_operation_anchor"
                    ],
                    supervision_root=current_root,
                )
            except BaseException as error:
                cleanup_errors.append(f"worker cleanup: {error}")
            try:
                current_registry.reconcile_benchmark_provider_cleanup(
                    worker_id=worker_id,
                    run_id=run_id,
                    stage=stage,
                    operation_id=operation_id,
                )
            except BaseException as error:
                cleanup_errors.append(f"provider cleanup: {error}")
        if current_store is not None:
            try:
                current_store.close()
            except BaseException as error:
                cleanup_errors.append(f"store close: {error}")
            current_store = None
        current_registry = None
        current_root = None
        current_composition = None
        gc.collect()
        if state_path.exists():
            try:
                _fresh_resume_cut(cleanup=True)
            except BaseException as error:
                cleanup_errors.append(f"fresh composition cleanup: {error}")
        for resource in restart_resources:
            if resource["closed"]:
                continue
            process = resource["process"]
            queue = resource["queue"]
            try:
                if process.is_alive():
                    process.terminate()
                process.join(20)
                if process.is_alive():
                    cleanup_errors.append("cleanup process remained alive")
                process.close()
            except BaseException as error:
                cleanup_errors.append(f"cleanup process close: {error}")
            try:
                queue.close()
                queue.join_thread()
            except BaseException as error:
                cleanup_errors.append(f"cleanup queue close: {error}")
            resource["closed"] = True
        if provider_helper is not None:
            try:
                provider_helper.close()
            except BaseException as error:
                cleanup_errors.append(f"provider helper: {error}")
        if provider_scope is not None:
            try:
                provider_scope.close()
            except BaseException as error:
                cleanup_errors.append(f"provider scope: {error}")
        window_receipt = None
        if owner_journal.exists():
            try:
                window_receipt = close_owned_window(
                    journal_path=owner_journal, reason="recorded_qwen_test_finally"
                )
            except BaseException as error:
                cleanup_errors.append(f"window cleanup: {error}")

        if worker_identity is not None:
            try:
                process = psutil.Process(worker_identity["pid"])
            except psutil.NoSuchProcess:
                process = None
            except BaseException as error:
                process = None
                cleanup_errors.append(f"worker identity probe: {error}")
            if process is not None:
                if int(round(process.create_time() * 1_000_000_000)) == (
                    worker_identity["create_time_ns"]
                ):
                    cleanup_errors.append("worker process identity remained live")
        for cut_identity in restart_cut_identities:
            try:
                cut_process = psutil.Process(cut_identity["pid"])
            except psutil.NoSuchProcess:
                cut_process = None
            except BaseException as error:
                cut_process = None
                cleanup_errors.append(f"restart identity probe: {error}")
            if cut_process is not None:
                if int(round(cut_process.create_time() * 1_000_000_000)) == (
                    cut_identity["create_time_ns"]
                ):
                    cleanup_errors.append("restart process identity remained live")
        if worker_scope_name is not None:
            try:
                worker_zero = observe_process_scope_cleanup(
                    worker_scope_name, terminate=True, stable_zero_observations=3
                )
                if worker_zero["cleanup_status"] != "verified":
                    cleanup_errors.append("worker scope was not verified zero")
                if worker_zero["member_pids_after"] != []:
                    cleanup_errors.append("worker scope retained members")
            except BaseException as error:
                cleanup_errors.append(f"worker scope probe: {error}")
        if provider_scope is not None:
            try:
                provider_zero = observe_process_scope_cleanup(
                    provider_scope.name,
                    terminate=True,
                    listener_ports=(() if provider_port is None else (provider_port,)),
                    stable_zero_observations=3,
                )
                if provider_zero["cleanup_status"] != "verified":
                    cleanup_errors.append("provider scope was not verified zero")
                if provider_zero["member_pids_after"] != []:
                    cleanup_errors.append("provider scope retained members")
                if provider_zero["active_listeners_after"] != []:
                    cleanup_errors.append("provider scope retained listeners")
            except BaseException as error:
                cleanup_errors.append(f"provider scope probe: {error}")
        if startup_event_name is not None or controller_mutex_name is not None:
            import win32api
            import win32event

            if startup_event_name is not None:
                try:
                    handle = win32event.OpenEvent(
                        0x00100000, False, startup_event_name
                    )
                except BaseException as error:
                    if getattr(error, "winerror", error.args[0]) != 2:
                        cleanup_errors.append(f"startup event probe: {error}")
                else:
                    win32api.CloseHandle(handle)
                    cleanup_errors.append("startup event handle remained")
            if controller_mutex_name is not None:
                try:
                    handle = win32event.OpenMutex(0x00100000, False, controller_mutex_name)
                except BaseException as error:
                    if getattr(error, "winerror", error.args[0]) != 2:
                        cleanup_errors.append(f"controller mutex probe: {error}")
                else:
                    win32api.CloseHandle(handle)
                    cleanup_errors.append("controller mutex handle remained")
        if window_receipt is not None:
            if window_receipt["cleanup_status"] != "verified":
                cleanup_errors.append("window cleanup was not verified")
            if window_receipt["matching_owned_windows_after"] != []:
                cleanup_errors.append("owned HWND residue remained")
            if window_receipt["member_pids_after"] != []:
                cleanup_errors.append("window owner process residue remained")
            if window_receipt["active_listeners_after"] != []:
                cleanup_errors.append("window owner listener residue remained")

        def _remove_readonly(function, path, _error_info):
            import stat

            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            function(path)

        try:
            shutil.rmtree(project_root, onerror=_remove_readonly)
        except FileNotFoundError:
            pass
        except BaseException as error:
            cleanup_errors.append(f"temporary root cleanup: {error}")
        if project_root.exists():
            cleanup_errors.append("temporary project root remained")
        assert cleanup_errors == []


@pytest.mark.skipif(os.name != "nt", reason="Windows benchmark ownership required")
def test_real_registry_spawn_recorded_qwen_cancel_survives_durable_intent_restart(
    tmp_path: Path,
    validated_provider_snapshot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import psutil
    from PIL import Image

    from app.core import model_server
    from app.learn.hybrid.benchmark_v2_contracts import canonical_json_bytes
    from app.learn.hybrid.benchmark_v2_provider_corpus import (
        compose_test_provider_case_resolver,
        validate_preloaded_provider_corpus,
    )
    from app.learn.hybrid.benchmark_v2_window_owner import (
        close_owned_window,
        launch_owned_window,
    )
    from app.learn.hybrid.benchmark_v2_worker_binding import (
        compose_test_server_worker_window_binding_publisher,
        publish_server_worker_window_binding,
    )
    from app.learn.hybrid.windows_process_scope import (
        WindowsProcessScope,
        benchmark_worker_controller_mutex_name_v1,
        observe_process_scope_cleanup,
        process_scope_name,
        spawn_process_in_scope,
    )
    from app.learn.recognition.uei.canonical import content_sha256, seal_immutable
    from app.learn.workflow_service import start_learning_workflow_stage_operation
    from app.learn.workflow_store import LearningWorkflowRunStore
    from app.learn.workflow_worker import compose_test_benchmark_worker_supervision_root

    project_root = tmp_path / "real-c-cancel-service"
    project_root.mkdir()
    state_path = project_root / "state.json"
    worker_root = project_root / "workers"
    lease_dir = project_root / "qwen-leases"
    owner_journal = project_root / "task5-owner.json"
    base_corpus, _base_file_ref = validated_provider_snapshot
    source_case = base_corpus["cases"][0]
    source_image = (PROJECT_ROOT / str(source_case["image"]["path"])).resolve()
    benchmark_bmp = project_root / "recorded-qwen-provider.bmp"
    with Image.open(source_image) as opened:
        opened.convert("RGB").save(benchmark_bmp, format="BMP")
    benchmark_bmp_sha = hashlib.sha256(benchmark_bmp.read_bytes()).hexdigest()
    corpus_candidate = deepcopy(base_corpus)
    source_group = source_case["screen_group"]
    for candidate in corpus_candidate["cases"]:
        if candidate["screen_group"] == source_group:
            candidate["image"]["sha256"] = benchmark_bmp_sha
    corpus_candidate.pop("content_sha256")
    corpus_candidate["content_sha256"] = content_sha256(corpus_candidate)
    corpus_raw = canonical_json_bytes(corpus_candidate, pretty=True)
    corpus_file_sha = hashlib.sha256(corpus_raw).hexdigest()
    corpus = validate_preloaded_provider_corpus(
        raw=corpus_raw, expected_sha256=corpus_file_sha
    )
    corpus_file_ref = seal_immutable(
        {
            "contract_version": "benchmark_v2_provider_corpus_file_ref_v1",
            "relative_path": "provider-corpus.v2.json",
            "file_sha256": corpus_file_sha,
            "source_parent_ref": {
                "content_sha256": corpus["source_parent_ref"]["content_sha256"]
            },
        }
    )
    run_id = "run-c-real-cancel"
    stage = "screen_understanding"
    operation_id = "operation-c-real-cancel"
    context = multiprocessing.get_context("spawn")
    release_event = context.Event()
    cancel_event = context.Event()
    recorded_response = {
        "success": True,
        "recorded_qwen_response": {
            "model": "recorded-qwen",
            "content": "harmless observation only",
        },
        "action_candidates": [],
        "execute_binding_enabled": False,
    }
    owner = None
    provider_scope = None
    provider_helper = None
    provider_port = None
    worker_identity = None
    worker_scope_name = None
    startup_event_name = None
    controller_mutex_name = None
    cut_process = None
    cut_queue = None
    resume_process = None
    resume_queue = None
    cut_identities: list[dict[str, int]] = []
    cleanup_errors: list[str] = []
    cancelled = None

    try:
        monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", lease_dir)
        store = LearningWorkflowRunStore(state_path=state_path)
        root = compose_test_benchmark_worker_supervision_root(
            journal_root=worker_root,
            test_capability=object(),
            workflow_store=store,
            test_store_capability=object(),
        )
        resolver = compose_test_provider_case_resolver(
            validated_corpus=corpus,
            provider_corpus_file_ref=corpus_file_ref,
            workflow_store=store,
            benchmark_supervision_root=root,
        )
        case_ref = _case_ref(resolver)
        owner = launch_owned_window(
            image_path=benchmark_bmp,
            expected_sha256=benchmark_bmp_sha,
            operation_id=operation_id,
            journal_path=owner_journal,
        )
        capture_ref = {
            "id": "capture-c-real-cancel",
            "content_sha256": benchmark_bmp_sha,
        }
        authority = publish_server_worker_window_binding(
            publisher=compose_test_server_worker_window_binding_publisher(
                authority_root=project_root
            ),
            run_id=run_id,
            stage=stage,
            operation_id=operation_id,
            owner=owner,
            capture_ref=capture_ref,
        )
        first = store.transition(
            run_id=run_id,
            expected_revision=0,
            stage="bind_capture",
            outcome="running",
            evidence_refs={},
        )
        bound = store.transition(
            run_id=run_id,
            expected_revision=first["revision"],
            stage="bind_capture",
            outcome="completed",
            evidence_refs={"image_path": str(benchmark_bmp)},
        )
        start_learning_workflow_stage_operation(
            store=store,
            project_root=project_root,
            run_id=run_id,
            expected_revision=bound["revision"],
            stage=stage,
            operation_id=operation_id,
        )
        store.close()
        del resolver, root, store
        gc.collect()

        cut_queue = context.Queue()
        cut_process = context.Process(
            target=_recorded_qwen_incumbent_cancel_intent_cut,
            args=(
                str(project_root),
                str(state_path),
                str(worker_root),
                str(lease_dir),
                corpus_raw,
                corpus_file_sha,
                corpus_file_ref,
                run_id,
                stage,
                operation_id,
                case_ref,
                authority["window_binding_ref"],
                capture_ref,
                release_event,
                cancel_event,
                recorded_response,
                cut_queue,
            ),
            name="benchmark-v2-incumbent-cancel-intent-cut",
        )
        cut_process.start()
        assert cut_process.pid is not None
        cut_identities.append(
            {
                "pid": cut_process.pid,
                "create_time_ns": int(
                    round(
                        psutil.Process(cut_process.pid).create_time()
                        * 1_000_000_000
                    )
                ),
            }
        )
        started = cut_queue.get(timeout=45)
        assert started["status"] == "started", started
        worker_identity = deepcopy(started["process_identity"])
        worker_scope_name = started["scope_name"]
        startup_event_name = (
            "Local\\AgentGuiBenchmarkWorkerGate-"
            + hashlib.sha256(
                json.dumps(
                    {"scope_name": worker_scope_name},
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
        )
        controller_mutex_name = benchmark_worker_controller_mutex_name_v1(
            authority_kind=started["authority_kind"],
            run_id=run_id,
            stage=stage,
            operation_id=operation_id,
        )

        provider_lineage = {
            "run_id": run_id,
            "workflow_revision": started["workflow_revision"],
            "operation_id": operation_id,
            "stage": stage,
            "stage_execution_id": f"execution-{operation_id}",
        }
        provider_scope_name = process_scope_name(provider_lineage, "qwen")
        provider_scope = WindowsProcessScope(provider_scope_name, create=True)
        provider_helper = spawn_process_in_scope(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            scope_name=provider_scope_name,
            cwd=project_root,
        )
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            provider_port = int(probe.getsockname()[1])
        endpoint = f"http://127.0.0.1:{provider_port}/v1/chat/completions"
        readiness = {
            "started": True,
            "after": {
                "status": "running",
                "base_url": f"http://127.0.0.1:{provider_port}/v1",
                "model_id": "recorded-qwen",
                "server_process_identity": deepcopy(
                    provider_helper.process_identity
                ),
                "server_socket": {"host": "127.0.0.1", "port": provider_port},
            },
        }
        profile = {
            "profile_id": "recorded-qwen-benchmark",
            "endpoint": endpoint,
            "pid_file": str(project_root / "recorded-qwen.pid"),
        }
        monkeypatch.setenv("AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME", provider_scope_name)
        monkeypatch.setattr(
            model_server,
            "_observe_qwen_server_binding",
            lambda _selected, observed: {
                "server_process_identity": deepcopy(
                    observed["after"]["server_process_identity"]
                ),
                "server_socket": deepcopy(observed["after"]["server_socket"]),
            },
        )
        monkeypatch.setattr(
            model_server,
            "_attest_exact_qwen_socket_owner",
            lambda _server_socket, process_identity: (
                model_server._current_process_identity(process_identity["pid"])
                == process_identity
            ),
        )
        monkeypatch.setattr(
            model_server,
            "check_model_server",
            lambda _selected, timeout=1.0: {"status": "unreachable"},
        )
        lease = model_server.acquire_qwen_model_lease(
            profile=profile,
            request_id=started["model_request_id"],
            readiness=readiness,
        )
        released = model_server._release_exact_qwen_lease(
            lease, reason="recorded-qwen-cancel-materialized"
        )
        assert released["server_termination"] == "verified_exact_process_exited"

        cancel_event.set()
        durable = cut_queue.get(timeout=45)
        assert durable["status"] == "intent_durable", durable
        durable_operation = durable["operation"]
        assert durable_operation["phase"] == "cancel_intent"
        assert durable_operation["worker_ref"]["worker_id"] == started["worker_id"]
        assert durable_operation["execution_nonce"] == started["execution_nonce"]
        for name in (
            "process_identity",
            "scope_name",
            "assignment_proven_ref",
        ):
            assert durable_operation["cancel_intent"][name] == started[name]
        cut_process.join(20)
        assert not cut_process.is_alive()
        assert cut_process.exitcode == 0
        cut_process.close()
        cut_process = None
        cut_queue.close()
        cut_queue.join_thread()
        cut_queue = None

        resume_queue = context.Queue()
        resume_process = context.Process(
            target=_recorded_qwen_incumbent_cancel_resume_cut,
            args=(
                str(project_root),
                str(state_path),
                str(worker_root),
                str(lease_dir),
                corpus_raw,
                corpus_file_sha,
                corpus_file_ref,
                run_id,
                stage,
                operation_id,
                resume_queue,
            ),
            name="benchmark-v2-incumbent-cancel-resume-cut",
        )
        resume_process.start()
        assert resume_process.pid is not None
        cut_identities.append(
            {
                "pid": resume_process.pid,
                "create_time_ns": int(
                    round(
                        psutil.Process(resume_process.pid).create_time()
                        * 1_000_000_000
                    )
                ),
            }
        )
        message = resume_queue.get(timeout=45)
        resume_process.join(20)
        assert not resume_process.is_alive(), message
        assert resume_process.exitcode == 0, message
        assert message["status"] == "ok", message
        cancelled = message["result"]
        resume_process.close()
        resume_process = None
        resume_queue.close()
        resume_queue.join_thread()
        resume_queue = None

        assert cancelled["status"] == "cancelled"
        cancelled_operation = cancelled["operation"]
        assert cancelled_operation["worker_ref"]["worker_id"] == started["worker_id"]
        assert cancelled_operation["execution_nonce"] == started["execution_nonce"]
        assert cancelled_operation["provider_cleanup_ref"]["outcome"] == (
            "verified_exact_process_exited"
        )
        assert cancelled_operation["worker_cleanup_ref"]["outcome"] == (
            "verified_exact_worker_exited"
        )
        for name in (
            "process_identity",
            "assignment_proven_ref",
        ):
            assert cancelled_operation["worker_cleanup_ref"][name] == (
                cancelled_operation["cancel_intent"][name]
            )
        assert cancelled_operation["cancel_intent"]["scope_name"] == started[
            "scope_name"
        ]
        assignment_files = list(worker_root.glob("*.benchmark-assignment.json"))
        assert len(assignment_files) == 1
        assert assignment_files[0].name == (
            f"{started['worker_id']}.benchmark-assignment.json"
        )
    finally:
        for label, process in (
            ("cancel intent cut", cut_process),
            ("cancel resume cut", resume_process),
        ):
            if process is None:
                continue
            try:
                if process.is_alive():
                    process.terminate()
                process.join(20)
                if process.is_alive():
                    cleanup_errors.append(f"{label}: process remained alive")
                process.close()
            except BaseException as error:
                cleanup_errors.append(f"{label}: {error}")
        for label, queue in (
            ("cancel intent queue", cut_queue),
            ("cancel resume queue", resume_queue),
        ):
            if queue is None:
                continue
            try:
                queue.close()
                queue.join_thread()
            except BaseException as error:
                cleanup_errors.append(f"{label}: {error}")
        if provider_helper is not None:
            try:
                provider_helper.close()
            except BaseException as error:
                cleanup_errors.append(f"provider helper: {error}")
        if provider_scope is not None:
            try:
                provider_scope.close()
            except BaseException as error:
                cleanup_errors.append(f"provider scope: {error}")
        window_receipt = None
        if owner_journal.exists():
            try:
                window_receipt = close_owned_window(
                    journal_path=owner_journal,
                    reason="recorded_qwen_cancel_test_finally",
                )
            except BaseException as error:
                cleanup_errors.append(f"window cleanup: {error}")

        if worker_identity is not None:
            try:
                process = psutil.Process(worker_identity["pid"])
                if int(round(process.create_time() * 1_000_000_000)) == (
                    worker_identity["create_time_ns"]
                ):
                    cleanup_errors.append("worker process identity remained live")
            except psutil.NoSuchProcess:
                pass
            except BaseException as error:
                cleanup_errors.append(f"worker identity probe: {error}")
        for cut_identity in cut_identities:
            try:
                process = psutil.Process(cut_identity["pid"])
                if int(round(process.create_time() * 1_000_000_000)) == (
                    cut_identity["create_time_ns"]
                ):
                    cleanup_errors.append("restart cut process identity remained live")
            except psutil.NoSuchProcess:
                pass
            except BaseException as error:
                cleanup_errors.append(f"restart cut identity probe: {error}")
        if worker_scope_name is not None:
            try:
                worker_zero = observe_process_scope_cleanup(
                    worker_scope_name, terminate=True, stable_zero_observations=3
                )
                if worker_zero["cleanup_status"] != "verified":
                    cleanup_errors.append("worker scope was not verified zero")
                if worker_zero["member_pids_after"] != []:
                    cleanup_errors.append("worker scope retained members")
            except BaseException as error:
                cleanup_errors.append(f"worker scope probe: {error}")
        if provider_scope is not None:
            try:
                provider_zero = observe_process_scope_cleanup(
                    provider_scope.name,
                    terminate=True,
                    listener_ports=(() if provider_port is None else (provider_port,)),
                    stable_zero_observations=3,
                )
                if provider_zero["cleanup_status"] != "verified":
                    cleanup_errors.append("provider scope was not verified zero")
                if provider_zero["member_pids_after"] != []:
                    cleanup_errors.append("provider scope retained members")
                if provider_zero["active_listeners_after"] != []:
                    cleanup_errors.append("provider scope retained listeners")
            except BaseException as error:
                cleanup_errors.append(f"provider scope probe: {error}")
        if startup_event_name is not None or controller_mutex_name is not None:
            import win32api
            import win32event

            if startup_event_name is not None:
                try:
                    handle = win32event.OpenEvent(
                        0x00100000, False, startup_event_name
                    )
                except BaseException as error:
                    if getattr(error, "winerror", error.args[0]) != 2:
                        cleanup_errors.append(f"startup event probe: {error}")
                else:
                    win32api.CloseHandle(handle)
                    cleanup_errors.append("startup event handle remained")
            if controller_mutex_name is not None:
                try:
                    handle = win32event.OpenMutex(
                        0x00100000, False, controller_mutex_name
                    )
                except BaseException as error:
                    if getattr(error, "winerror", error.args[0]) != 2:
                        cleanup_errors.append(f"controller mutex probe: {error}")
                else:
                    win32api.CloseHandle(handle)
                    cleanup_errors.append("controller mutex handle remained")
        if window_receipt is not None:
            if window_receipt["cleanup_status"] != "verified":
                cleanup_errors.append("window cleanup was not verified")
            if window_receipt["matching_owned_windows_after"] != []:
                cleanup_errors.append("owned HWND residue remained")
            if window_receipt["member_pids_after"] != []:
                cleanup_errors.append("window owner process residue remained")
            if window_receipt["active_listeners_after"] != []:
                cleanup_errors.append("window owner listener residue remained")

        def _remove_readonly(function, path, _error_info):
            import stat

            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            function(path)

        try:
            shutil.rmtree(project_root, onerror=_remove_readonly)
        except FileNotFoundError:
            pass
        except BaseException as error:
            cleanup_errors.append(f"temporary root cleanup: {error}")
        if project_root.exists():
            cleanup_errors.append("temporary project root remained")
        assert cleanup_errors == []
