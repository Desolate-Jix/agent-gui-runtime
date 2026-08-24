from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from threading import Event

import pytest

from app.learn.recognition.uei.canonical import content_sha256


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


def test_parser_preserves_exact_utf8_labels_and_covers_every_candidate() -> None:
    from app.learn.hybrid.qwen_binding import parse_qwen_candidate_bindings
    from tests.test_learn_hybrid_contracts import inventory_fixture

    inventory = inventory_fixture(candidate_count=2)
    parsed = parse_qwen_candidate_bindings(_raw_for(inventory), inventory)

    assert [item["label"] for item in parsed["bindings"]] == ["申请职位 0", "申请职位 1"]
    assert [item["candidate_id"] for item in parsed["bindings"]] == [
        item["candidate_id"] for item in inventory["candidates"]
    ]


def test_parser_rejects_unknown_duplicate_and_omitted_candidate_ids() -> None:
    from app.learn.hybrid.qwen_binding import parse_qwen_candidate_bindings
    from tests.test_learn_hybrid_contracts import inventory_fixture

    inventory = inventory_fixture(candidate_count=2)
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

    inventory = inventory_fixture(candidate_count=2)
    raw = _raw_for(inventory)
    for field in ("role", "label", "description", "relation"):
        raw["bindings"][1][field] = raw["bindings"][0][field]

    with pytest.raises(ValueError, match="semantic target bound to multiple candidate IDs"):
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

    inventory = inventory_fixture()
    raw = _raw_for(inventory)
    raw["bindings"][0].update(injection)

    with pytest.raises(ValueError, match="forbidden Qwen field"):
        parse_qwen_candidate_bindings(raw, inventory)


def test_parser_rejects_unbound_prose() -> None:
    from app.learn.hybrid.qwen_binding import parse_qwen_candidate_bindings
    from tests.test_learn_hybrid_contracts import inventory_fixture

    inventory = inventory_fixture()
    raw = {**_raw_for(inventory), "summary": "可以点击此按钮"}

    with pytest.raises(ValueError, match="unbound Qwen prose"):
        parse_qwen_candidate_bindings(raw, inventory)


def test_important_element_without_candidate_is_orphan_semantic_only() -> None:
    from app.learn.hybrid.qwen_binding import parse_qwen_candidate_bindings
    from tests.test_learn_hybrid_contracts import inventory_fixture

    inventory = inventory_fixture()
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

    inventory = inventory_fixture()
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

    def runner(*, request, image_path, cancellation_event=None):
        seen.update(request=request, image_path=image_path, cancellation_event=cancellation_event)
        return _raw_for(facts["inventory"])

    result = run_qwen_candidate_binding(
        deepcopy(facts["qwen_payload"]),
        model_runner=runner,
        cancellation_event=cancellation,
    )

    assert result["contract_version"] == "hybrid_qwen_bindings_v1"
    assert result["content_sha256"] == content_sha256(result)
    assert seen["cancellation_event"] is cancellation
    assert seen["image_path"] == Path(facts["image"]).resolve()


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

    def release(*, sealed_artifact):
        assert sealed_artifact["content_sha256"] == content_sha256(sealed_artifact)
        events.append("release")
        return {"status": "released"}

    result = hybrid_qwen.run_hybrid_qwen_task(
        payload,
        model_runner=runner,
        model_releaser=release,
    )

    assert result["content_sha256"] == content_sha256(result)
    assert events == ["model", "release"]
