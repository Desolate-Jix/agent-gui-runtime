from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PARENT_MANIFEST = (
    PROJECT_ROOT
    / "tests"
    / "fixtures"
    / "portfolio_hybrid_v1_1"
    / "corpus-manifest.v1.json"
)
SHA = "a" * 64


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


def _prepared_document(source_bundle: dict[str, object]) -> dict[str, object]:
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
        prepared_revision=7,
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

    class _Registry:
        def start(self, **_kwargs):
            events.append("generic.start")
            raise AssertionError("benchmark start reached generic Registry.start")

    composition = workflow_service.LearningWorkflowServiceComposition(
        store=object(),
        worker_registry=_Registry(),
        project_root=tmp_path,
        composition_kind="test",
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

    class _Registry:
        def read_adopted_result(self, **_kwargs):
            raise AssertionError("benchmark continue reached generic adopted-result reader")

        def cancel_by_operation(self, **_kwargs):
            raise AssertionError("benchmark cancel reached generic Registry.cancel")

    composition = workflow_service.LearningWorkflowServiceComposition(
        store=_Store(),
        worker_registry=_Registry(),
        project_root=tmp_path,
        composition_kind="test",
        benchmark_supervision_root=object(),
        provider_case_resolver=object(),
    )
    events: list[str] = []
    monkeypatch.setattr(
        workflow_service,
        "_resume_benchmark_v2_incumbent_operation",
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
        LearningWorkflowServiceComposition,
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

    class _Registry:
        def __init__(self) -> None:
            self.reservation = None
            self.anchored = None

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
            return seal_immutable(
                {
                    "contract_version": "benchmark_provider_acquisition_ref_v1",
                    "acquisition_intent_ref": {"content_sha256": "3" * 64},
                    "runtime_owner_ref": deepcopy(kwargs["runtime_owner_ref"]),
                }
            )

        def launch_prepared_benchmark_worker(self, **kwargs):
            events.append("launch")
            assert kwargs["authoritative_payload"]["provider_mode"] == "local_understanding"
            return {
                "contract_version": "learning_stage_worker_v1",
                "worker_id": "1" * 32,
                "run_id": "run-c3-start",
                "stage": "screen_understanding",
                "operation_id": operation_id,
                "task_kind": "vision_observe_screen",
                "status": "running",
            }

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
                "response": {"success": True},
            }

        def observe_benchmark_worker_cleanup(self, **_kwargs):
            events.append("worker_cleanup")
            return seal_immutable(
                {
                    "contract_version": "benchmark_worker_cleanup_ref_v1",
                    "outcome": "verified_exact_worker_exited",
                }
            )

        def reconcile_benchmark_provider_cleanup(self, **_kwargs):
            events.append("provider_cleanup")
            return seal_immutable(
                {
                    "contract_version": "benchmark_provider_cleanup_ref_v1",
                    "outcome": "verified_exact_process_exited",
                }
            )

    registry = _Registry()
    try:
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
        composition = LearningWorkflowServiceComposition(
            store=store,
            worker_registry=registry,
            project_root=tmp_path,
            composition_kind="test",
            benchmark_supervision_root=root,
            provider_case_resolver=resolver,
            benchmark_v2_worker_binding_resolver=object(),
        )
        monkeypatch.setattr(
            "app.learn.hybrid.benchmark_v2_worker_binding.resolve_server_worker_window_binding",
            lambda **_kwargs: {
                "serialized_window_binding": deepcopy(binding),
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
        assert events == ["prepare", "confirm", "inspect", "provider", "launch"]
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
            "app.learn.workflow_service._rebuild_benchmark_v2_window_adoption",
            lambda **_kwargs: seal_immutable(
                {
                    "contract_version": "portfolio_hybrid_benchmark_v2_worker_window_binding_adoption_v1",
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
            "inspect_result",
            "adopt",
            "worker_cleanup",
            "provider_cleanup",
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
        changes={
            "acquisition_intent_ref": {"content_sha256": "7" * 64},
            "runtime_owner_ref": {"content_sha256": "8" * 64},
        },
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
            {
                "acquisition_intent_ref": {"content_sha256": "7" * 64},
                "runtime_owner_ref": {"content_sha256": "8" * 64},
            },
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
    owner_changes = {
        "acquisition_intent_ref": {"content_sha256": "7" * 64},
        "runtime_owner_ref": {"content_sha256": "8" * 64},
    }
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
        changes={
            "acquisition_intent_ref": {"content_sha256": "7" * 64},
            "runtime_owner_ref": {"content_sha256": "8" * 64},
        },
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

    composition = workflow_service.LearningWorkflowServiceComposition(
        store=_Store(), worker_registry=object(), project_root=tmp_path,
        composition_kind="test", benchmark_supervision_root=object(),
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


@pytest.mark.parametrize(
    ("reservation_state", "expected_launches"),
    [("anchored", 1), ("launched", 0)],
)
def test_worker_starting_restart_reuses_the_same_reservation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source_bundle: dict[str, object],
    reservation_state: str,
    expected_launches: int,
) -> None:
    from contextlib import nullcontext
    from app.learn import workflow_service
    from app.learn.hybrid.benchmark_v2_incumbent_operation import (
        transition_benchmark_v2_incumbent_operation,
    )

    operation = _prepared_document(source_bundle)
    operation = transition_benchmark_v2_incumbent_operation(
        operation,
        to_phase="provider_owner_prepared",
        changes={
            "acquisition_intent_ref": {"content_sha256": "7" * 64},
            "runtime_owner_ref": {"content_sha256": "8" * 64},
        },
    )
    operation = transition_benchmark_v2_incumbent_operation(
        operation, to_phase="worker_starting", changes={}
    )
    run_id = operation["run_id"]
    stage = operation["stage"]
    operation_id = operation["operation_id"]
    launches: list[dict[str, object]] = []
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

    class _Registry:
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
            assert reservation_state == "launched"
            return {"worker_id": operation["worker_ref"]["worker_id"], "status": "running"}

    composition = workflow_service.LearningWorkflowServiceComposition(
        store=_Store(), worker_registry=_Registry(), project_root=tmp_path,
        composition_kind="test", benchmark_supervision_root=object(),
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
    assert result["worker_id"] == operation["worker_ref"]["worker_id"]
    assert len(launches) == expected_launches
    assert persisted[-1]["phase"] == "worker_bound"


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
    composition = workflow_service.LearningWorkflowServiceComposition(
        store=store,
        worker_registry=registry,
        project_root=tmp_path,
        composition_kind="test",
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
