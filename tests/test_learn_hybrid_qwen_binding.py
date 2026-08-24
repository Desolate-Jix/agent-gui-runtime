from __future__ import annotations

from copy import deepcopy
import base64
import json
from pathlib import Path
from threading import Event

import pytest

from app.learn.recognition.uei.canonical import content_sha256


@pytest.fixture(autouse=True)
def _inherit_real_model_wrapper_deny(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_GUI_TEST_DENY_REAL_MODEL_WRAPPER", "1")


def _sealed_inventory(value: dict[str, object]) -> dict[str, object]:
    from app.learn.recognition.uei.canonical import seal_immutable

    return seal_immutable(value)


def _binding(candidate_id: str, *, label: str = "申请职位") -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "role": "button",
        "label": label,
        "description": "打开申请流程",
        "semantic_confidence": 0.94,
        "task_relevance": 0.88,
        "relation": "primary_action",
        "ambiguity": None,
    }


def _raw_for(inventory: dict[str, object]) -> dict[str, object]:
    return {
        "bindings": [
            _binding(candidate["candidate_id"], label=f"申请职位 {index}")
            for index, candidate in enumerate(inventory["candidates"])
        ],
        "orphan_semantics": [],
    }


def _qwen_facts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    from app.learn.hybrid import omni_discovery
    from app.learn.hybrid.capture import load_and_verify_hybrid_capture_bundle
    from tests.test_learn_hybrid_omni_discovery import _RecordedAdapter, _facts

    facts = _facts(tmp_path)
    monkeypatch.setattr(
        omni_discovery,
        "OmniParserShadowAdapter",
        lambda: _RecordedAdapter(),
    )
    discovery = omni_discovery.run_hybrid_omni_discovery(deepcopy(facts["payload"]))
    bundle = load_and_verify_hybrid_capture_bundle(
        project_root=tmp_path,
        bundle_ref=deepcopy(facts["payload"]["hybrid_capture_bundle_ref"]),
        expected_run_id="run-omni",
        expected_workflow_revision=7,
    )
    payload = {
        "project_root": str(tmp_path),
        "run_id": "run-omni",
        "workflow_revision": 7,
        "hybrid_capture_bundle_ref": deepcopy(facts["payload"]["hybrid_capture_bundle_ref"]),
        "capture_image_path": facts["payload"]["capture_image_path"],
        "omni_inventory": deepcopy(discovery["inventory"]),
    }
    return {**facts, "bundle": bundle, "inventory": discovery["inventory"], "qwen_payload": payload}


def test_request_contains_canonical_screenshot_closed_geometry_and_same_capture_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid.qwen_binding import build_qwen_binding_request

    facts = _qwen_facts(tmp_path, monkeypatch)
    request = build_qwen_binding_request(facts["bundle"], facts["inventory"])

    identity = facts["inventory"]["capture_identity"]
    assert request["contract_version"] == "hybrid_qwen_binding_request_v1"
    assert request["screenshot"] == {
        "artifact_ref": identity["artifact_ref"],
        "screenshot_sha256": identity["screenshot_sha256"],
        "image_size": identity["image_size"],
        "coordinate_space": "capture_pixel_xyxy",
    }
    assert request["candidates"] == [
        {
            "candidate_id": candidate["candidate_id"],
            "bbox_original": candidate["bbox_original"],
            "coordinate_space": "capture_pixel_xyxy",
            "active": candidate["active"],
            "inactive_reason": candidate["inactive_reason"],
        }
        for candidate in facts["inventory"]["candidates"]
    ]
    assert request["ocr_uia_context"] == facts["bundle"]["context"]
    assert {
        source["source_kind"] for source in request["ocr_uia_context"]["sources"]
    } == {"ocr", "uia"}
    assert all(
        source["capture_lineage_ref"] == identity["capture_lineage_ref"]
        for source in request["ocr_uia_context"]["sources"]
    )
    assert request["content_sha256"] == content_sha256(request)


def test_request_rejects_extra_or_cross_capture_ocr_uia_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid.qwen_binding import build_qwen_binding_request
    from app.learn.recognition.uei.canonical import seal_immutable

    facts = _qwen_facts(tmp_path, monkeypatch)
    bundle = deepcopy(facts["bundle"])
    context = deepcopy(bundle["context"])
    context.pop("content_sha256")
    context["sources"].append(deepcopy(context["sources"][0]))
    bundle["context"] = seal_immutable(context)

    with pytest.raises(ValueError, match="requires sealed OCR and UIA sources"):
        build_qwen_binding_request(bundle, facts["inventory"])


def test_direct_and_managed_boundaries_reject_unsealed_or_mismatched_omni_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid.qwen_binding import run_qwen_candidate_binding
    from app.learn.workflow_tasks import hybrid_qwen

    facts = _qwen_facts(tmp_path, monkeypatch)
    for inventory in (
        {key: deepcopy(value) for key, value in facts["inventory"].items() if key != "content_sha256"},
        {**deepcopy(facts["inventory"]), "content_sha256": "A" * 64},
    ):
        payload = deepcopy(facts["qwen_payload"])
        payload["omni_inventory"] = inventory
        with pytest.raises(ValueError, match="sealed Omni inventory"):
            run_qwen_candidate_binding(payload, model_runner=lambda **kwargs: pytest.fail(kwargs))

        managed = deepcopy(payload)
        managed.pop("project_root")
        monkeypatch.setattr(hybrid_qwen, "_PROJECT_ROOT", tmp_path)
        with pytest.raises(ValueError, match="sealed Omni inventory"):
            hybrid_qwen.run_hybrid_qwen_task(
                managed,
                model_runner=lambda **kwargs: pytest.fail(kwargs),
                model_releaser=lambda **kwargs: pytest.fail(kwargs),
                model_lease={"lease_id": "controlled"},
            )


def test_parser_preserves_exact_utf8_labels_and_covers_every_candidate() -> None:
    from app.learn.hybrid.qwen_binding import parse_qwen_candidate_bindings
    from tests.test_learn_hybrid_contracts import inventory_fixture

    inventory = _sealed_inventory(inventory_fixture(candidate_count=2))
    parsed = parse_qwen_candidate_bindings(_raw_for(inventory), inventory)

    assert [item["label"] for item in parsed["bindings"]] == ["申请职位 0", "申请职位 1"]
    assert [item["candidate_id"] for item in parsed["bindings"]] == [
        item["candidate_id"] for item in inventory["candidates"]
    ]


def test_parser_rejects_unknown_duplicate_and_omitted_candidate_ids() -> None:
    from app.learn.hybrid.qwen_binding import parse_qwen_candidate_bindings
    from tests.test_learn_hybrid_contracts import inventory_fixture

    inventory = _sealed_inventory(inventory_fixture(candidate_count=2))
    raw = _raw_for(inventory)
    raw["bindings"][0]["candidate_id"] = "candidate/foreign"
    with pytest.raises(ValueError, match="unknown candidate_id"):
        parse_qwen_candidate_bindings(raw, inventory)

    raw = _raw_for(inventory)
    raw["bindings"][1]["candidate_id"] = raw["bindings"][0]["candidate_id"]
    with pytest.raises(ValueError, match="duplicate candidate_id"):
        parse_qwen_candidate_bindings(raw, inventory)

    raw = _raw_for(inventory)
    raw["bindings"].pop()
    with pytest.raises(ValueError, match="candidate omission"):
        parse_qwen_candidate_bindings(raw, inventory)


def test_parser_rejects_one_semantic_target_bound_to_multiple_ids() -> None:
    from app.learn.hybrid.qwen_binding import parse_qwen_candidate_bindings
    from tests.test_learn_hybrid_contracts import inventory_fixture

    inventory = _sealed_inventory(inventory_fixture(candidate_count=2))
    raw = _raw_for(inventory)
    for field in ("role", "label", "description", "relation"):
        raw["bindings"][1][field] = raw["bindings"][0][field]

    with pytest.raises(ValueError, match="semantic target bound to multiple candidate IDs"):
        parse_qwen_candidate_bindings(raw, inventory)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Apply Now", "  apply\tNOW "),
        ("Ｃｏｎｔｉｎｕｅ", "continue"),
        ("Cafe\u0301", "CAFÉ"),
    ],
)
def test_parser_rejects_canonical_case_whitespace_and_unicode_duplicates(
    left: str,
    right: str,
) -> None:
    from app.learn.hybrid.qwen_binding import parse_qwen_candidate_bindings
    from tests.test_learn_hybrid_contracts import inventory_fixture

    inventory = _sealed_inventory(inventory_fixture(candidate_count=2))
    raw = _raw_for(inventory)
    raw["bindings"][0]["label"] = left
    raw["bindings"][1]["label"] = right
    raw["bindings"][1]["role"] = raw["bindings"][0]["role"].upper()
    raw["bindings"][1]["description"] = "  打开申请流程  "

    with pytest.raises(ValueError, match="semantic target bound to multiple candidate IDs"):
        parse_qwen_candidate_bindings(raw, inventory)


def test_parser_rejects_same_semantic_target_as_binding_and_orphan() -> None:
    from app.learn.hybrid.qwen_binding import parse_qwen_candidate_bindings
    from tests.test_learn_hybrid_contracts import inventory_fixture

    inventory = _sealed_inventory(inventory_fixture())
    raw = _raw_for(inventory)
    binding = raw["bindings"][0]
    raw["orphan_semantics"] = [{
        "semantic_id": "semantic/duplicate",
        "role": binding["role"].upper(),
        "label": f"  {binding['label']}  ",
        "description": binding["description"],
        "reason": "ORPHAN_SEMANTIC",
    }]

    with pytest.raises(ValueError, match="semantic target bound and orphaned"):
        parse_qwen_candidate_bindings(raw, inventory)


def test_parser_bounds_depth_orphans_and_every_model_string() -> None:
    from app.learn.hybrid.qwen_binding import parse_qwen_candidate_bindings
    from tests.test_learn_hybrid_contracts import inventory_fixture

    inventory = _sealed_inventory(inventory_fixture())
    raw = _raw_for(inventory)
    deep: object = "leaf"
    for _ in range(40):
        deep = {"nested": deep}
    raw["bindings"][0]["ambiguity"] = deep
    with pytest.raises(ValueError, match="maximum JSON depth"):
        parse_qwen_candidate_bindings(raw, inventory)

    raw = _raw_for(inventory)
    raw["orphan_semantics"] = [
        {
            "semantic_id": f"semantic/{index}",
            "role": "text",
            "label": str(index),
            "description": "orphan",
            "reason": "ORPHAN_SEMANTIC",
        }
        for index in range(65)
    ]
    with pytest.raises(ValueError, match="orphan count"):
        parse_qwen_candidate_bindings(raw, inventory)

    raw = _raw_for(inventory)
    raw["bindings"][0]["label"] = "界" * 2000
    with pytest.raises(ValueError, match="UTF-8 byte limit"):
        parse_qwen_candidate_bindings(raw, inventory)


@pytest.mark.parametrize(
    "injection",
    [
        {"bbox": [0, 0, 1, 1]},
        {"coordinate_space": "capture_pixel_xyxy"},
        {"approved_to_click": True},
        {"execute": True},
        {"new_candidate": {"candidate_id": "candidate/free"}},
    ],
)
def test_qwen_output_cannot_inject_geometry_authority_or_candidates(injection: dict) -> None:
    from app.learn.hybrid.qwen_binding import parse_qwen_candidate_bindings
    from tests.test_learn_hybrid_contracts import inventory_fixture

    inventory = _sealed_inventory(inventory_fixture())
    raw = _raw_for(inventory)
    raw["bindings"][0].update(injection)

    with pytest.raises(ValueError, match="forbidden Qwen field"):
        parse_qwen_candidate_bindings(raw, inventory)


def test_parser_rejects_unbound_prose() -> None:
    from app.learn.hybrid.qwen_binding import parse_qwen_candidate_bindings
    from tests.test_learn_hybrid_contracts import inventory_fixture

    inventory = _sealed_inventory(inventory_fixture())
    raw = {**_raw_for(inventory), "summary": "可以点击此按钮"}

    with pytest.raises(ValueError, match="unbound Qwen prose"):
        parse_qwen_candidate_bindings(raw, inventory)


def test_important_element_without_candidate_is_orphan_semantic_only() -> None:
    from app.learn.hybrid.qwen_binding import parse_qwen_candidate_bindings
    from tests.test_learn_hybrid_contracts import inventory_fixture

    inventory = _sealed_inventory(inventory_fixture())
    raw = _raw_for(inventory)
    raw["orphan_semantics"] = [
        {
            "semantic_id": "semantic/missing-primary-action",
            "role": "button",
            "label": "继续",
            "description": "截图中可见但 Omni 未提供候选框",
            "reason": "ORPHAN_SEMANTIC",
        }
    ]

    parsed = parse_qwen_candidate_bindings(raw, inventory)

    orphan = parsed["orphan_semantics"][0]
    assert orphan["reason"] == "ORPHAN_SEMANTIC"
    assert "candidate_id" not in orphan
    assert len(parsed["bindings"]) == len(inventory["candidates"])


def test_orphan_semantic_cannot_fabricate_candidate_shaped_identity() -> None:
    from app.learn.hybrid.qwen_binding import parse_qwen_candidate_bindings
    from tests.test_learn_hybrid_contracts import inventory_fixture

    inventory = _sealed_inventory(inventory_fixture())
    raw = _raw_for(inventory)
    raw["orphan_semantics"] = [
        {
            "semantic_id": "candidate/fabricated",
            "role": "button",
            "label": "继续",
            "description": "缺少 Omni 候选",
            "reason": "ORPHAN_SEMANTIC",
        }
    ]

    with pytest.raises(ValueError, match="fabricated candidate"):
        parse_qwen_candidate_bindings(raw, inventory)


def test_run_seals_binding_and_passes_cancellation_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid.qwen_binding import run_qwen_candidate_binding

    facts = _qwen_facts(tmp_path, monkeypatch)
    cancellation = Event()
    seen: dict[str, object] = {}

    expected_bytes = Path(facts["image"]).read_bytes()

    def runner(
        *, request, screenshot_bytes, screenshot_media_type, screenshot_sha256,
        cancellation_event=None, model_lease=None
    ):
        seen.update(
            request=request,
            screenshot_bytes=screenshot_bytes,
            screenshot_media_type=screenshot_media_type,
            screenshot_sha256=screenshot_sha256,
            cancellation_event=cancellation_event,
            model_lease=model_lease,
        )
        return _raw_for(facts["inventory"])

    result = run_qwen_candidate_binding(
        deepcopy(facts["qwen_payload"]),
        model_runner=runner,
        cancellation_event=cancellation,
        model_lease={"lease_id": "exact-controlled-lease"},
    )

    assert result["contract_version"] == "hybrid_qwen_bindings_v1"
    assert result["content_sha256"] == content_sha256(result)
    assert seen["cancellation_event"] is cancellation
    assert seen["model_lease"] == {"lease_id": "exact-controlled-lease"}
    assert seen["screenshot_bytes"] == expected_bytes
    assert seen["screenshot_media_type"] == "image/png"
    assert seen["screenshot_sha256"] == facts["inventory"]["capture_identity"]["screenshot_sha256"]


def test_capture_file_mutation_after_single_read_cannot_change_runner_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid.qwen_binding import run_qwen_candidate_binding

    facts = _qwen_facts(tmp_path, monkeypatch)
    image = Path(facts["image"])
    expected = image.read_bytes()

    def runner(*, screenshot_bytes, **kwargs):
        del kwargs
        image.write_bytes(b"mutated-after-verification")
        assert screenshot_bytes == expected
        return _raw_for(facts["inventory"])

    run_qwen_candidate_binding(deepcopy(facts["qwen_payload"]), model_runner=runner)


def test_http_runner_encodes_exact_task2_bytes_despite_file_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import model_server
    from app.learn.hybrid.qwen_binding import run_qwen_candidate_binding

    facts = _qwen_facts(tmp_path, monkeypatch)
    image = Path(facts["image"])
    expected = image.read_bytes()
    seen: dict[str, object] = {}
    profile = {
        "profile_id": "qwen3_vl_8b_q4_k_m",
        "model_name": "controlled-qwen",
        "endpoint": "http://127.0.0.1:13240/v1/chat/completions",
    }
    monkeypatch.setattr(model_server, "profile_for_stage", lambda stage: profile)

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, size=-1):
            raw = json.dumps({
                "choices": [{"message": {"content": json.dumps(_raw_for(facts["inventory"]), ensure_ascii=False)}}]
            }, ensure_ascii=False).encode("utf-8")
            return raw if size < 0 else raw[:size]

    def urlopen(request, timeout):
        del timeout
        image.write_bytes(b"mutated-before-http-send")
        seen["body"] = json.loads(request.data.decode("utf-8"))
        return Response()

    monkeypatch.setattr(model_server.urllib.request, "urlopen", urlopen)
    run_qwen_candidate_binding(
        deepcopy(facts["qwen_payload"]),
        model_runner=model_server.run_qwen_binding_model,
    )

    body = seen["body"]
    image_url = body["messages"][1]["content"][1]["image_url"]["url"]
    assert base64.b64decode(image_url.split(",", 1)[1]) == expected


def test_model_timeout_and_cancel_leave_prior_omni_inventory_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid.qwen_binding import (
        QwenBindingCancelled,
        QwenBindingTimeout,
        run_qwen_candidate_binding,
    )

    facts = _qwen_facts(tmp_path, monkeypatch)
    before = deepcopy(facts["inventory"])

    def timeout_runner(**kwargs):
        del kwargs
        raise TimeoutError("controlled timeout")

    with pytest.raises(QwenBindingTimeout, match="model timeout"):
        run_qwen_candidate_binding(
            deepcopy(facts["qwen_payload"]),
            model_runner=timeout_runner,
        )
    assert facts["inventory"] == before

    cancelled = Event()
    cancelled.set()
    with pytest.raises(QwenBindingCancelled, match="cancelled"):
        run_qwen_candidate_binding(
            deepcopy(facts["qwen_payload"]),
            model_runner=lambda **kwargs: pytest.fail("cancelled request reached model"),
            cancellation_event=cancelled,
        )
    assert facts["inventory"] == before


def test_cancellation_induced_runner_error_maps_to_binding_cancelled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid.qwen_binding import QwenBindingCancelled, run_qwen_candidate_binding

    facts = _qwen_facts(tmp_path, monkeypatch)
    cancellation = Event()

    def runner(**kwargs):
        del kwargs
        cancellation.set()
        raise RuntimeError("transport closed by cancellation")

    with pytest.raises(QwenBindingCancelled, match="cancelled"):
        run_qwen_candidate_binding(
            deepcopy(facts["qwen_payload"]),
            model_runner=runner,
            cancellation_event=cancellation,
        )



def test_workflow_task_releases_qwen_only_after_sealed_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.workflow_tasks import hybrid_qwen

    facts = _qwen_facts(tmp_path, monkeypatch)
    payload = deepcopy(facts["qwen_payload"])
    payload.pop("project_root")
    monkeypatch.setattr(hybrid_qwen, "_PROJECT_ROOT", tmp_path)
    events: list[str] = []

    def runner(**kwargs):
        del kwargs
        events.append("model")
        return _raw_for(facts["inventory"])

    lease = {"lease_id": "controlled-lease", "owner_request_id": "controlled-request"}

    def release(*, sealed_artifact, omni_inventory, model_lease):
        assert sealed_artifact["content_sha256"] == content_sha256(sealed_artifact)
        assert omni_inventory == facts["inventory"]
        assert model_lease == lease
        events.append("release")
        return {"status": "released"}

    result = hybrid_qwen.run_hybrid_qwen_task(
        payload,
        model_runner=runner,
        model_releaser=release,
        model_lease=lease,
    )

    assert result["content_sha256"] == content_sha256(result)
    assert events == ["model", "release"]


@pytest.mark.parametrize(
    ("failure_kind", "expected_compute_completed"),
    [
        ("timeout", False),
        ("invalid_json", True),
        ("parser_rejection", True),
        ("release_failure", True),
    ],
)
def test_workflow_failure_finalizer_reconciles_exact_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
    expected_compute_completed: bool,
) -> None:
    from app.learn.workflow_tasks import hybrid_qwen

    facts = _qwen_facts(tmp_path, monkeypatch)
    payload = deepcopy(facts["qwen_payload"])
    payload.pop("project_root")
    monkeypatch.setattr(hybrid_qwen, "_PROJECT_ROOT", tmp_path)
    lease = {"lease_id": "failure-lease", "owner_request_id": "failure-request"}
    reconciliations: list[dict[str, object]] = []

    def runner(**kwargs):
        del kwargs
        if failure_kind == "timeout":
            raise TimeoutError("controlled timeout")
        if failure_kind == "invalid_json":
            return "not-json"
        if failure_kind == "parser_rejection":
            raw = _raw_for(facts["inventory"])
            raw["bindings"][0]["candidate_id"] = "candidate/unknown"
            return raw
        return _raw_for(facts["inventory"])

    def release(**kwargs):
        del kwargs
        if failure_kind == "release_failure":
            raise RuntimeError("controlled release failure")
        return {"status": "released"}

    with pytest.raises((ValueError, RuntimeError)):
        hybrid_qwen.run_hybrid_qwen_task(
            payload,
            model_runner=runner,
            model_releaser=release,
            model_lease=lease,
            model_failure_reconciler=lambda **kwargs: reconciliations.append(kwargs)
            or {"status": "reconciled"},
        )

    assert len(reconciliations) == 1
    assert reconciliations[0]["model_lease"] == lease
    assert reconciliations[0]["compute_completed"] is expected_compute_completed
    assert reconciliations[0]["reason"] == failure_kind


def test_workflow_release_failure_uses_production_reconciler_and_removes_completed_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import model_server
    from app.learn.workflow_tasks import hybrid_qwen

    facts = _qwen_facts(tmp_path, monkeypatch)
    payload = deepcopy(facts["qwen_payload"])
    payload.pop("project_root")
    monkeypatch.setattr(hybrid_qwen, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path / "qwen-leases")
    profile = {"profile_id": "qwen", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    readiness = {
        "started": False,
        "before": {
            "status": "running",
            "base_url": "http://127.0.0.1:13240/v1",
            "model_id": "qwen",
            "server_process_identity": {"pid": 9101, "create_time_ns": 111},
            "server_socket": {"host": "127.0.0.1", "port": 13240},
        },
    }
    monkeypatch.setattr(
        model_server,
        "_observe_qwen_server_binding",
        lambda selected, current: {
            "server_process_identity": dict(current["before"]["server_process_identity"]),
            "server_socket": dict(current["before"]["server_socket"]),
        },
    )
    lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="release-failure-request",
        readiness=readiness,
    )

    with pytest.raises(RuntimeError, match="release failure"):
        hybrid_qwen.run_hybrid_qwen_task(
            payload,
            model_runner=lambda **kwargs: _raw_for(facts["inventory"]),
            model_releaser=lambda **kwargs: (_ for _ in ()).throw(
                RuntimeError("controlled release failure")
            ),
            model_lease=lease,
        )

    assert model_server.qwen_model_lease_is_active(lease) is False
