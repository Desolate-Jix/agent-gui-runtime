from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.learn.recognition.uei.canonical import seal_immutable
from tests.uei_v1_helpers import build_context_from_sidecar, load_expected, project_case


_FORBIDDEN = {
    "artifact_is_authorization",
    "execute_binding_enabled",
    "authorization",
    "action",
    "click_point",
    "confidence",
    "trust",
    "score",
}


def _walk_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | set().union(*(_walk_keys(child) for child in value.values()))
    if isinstance(value, list):
        return set().union(*(_walk_keys(child) for child in value)) if value else set()
    return set()


@pytest.mark.parametrize("case", ["ocr", "uia", "screen-parser"])
def test_static_sidecar_case_matches_safe_projection(case: str, tmp_path: Path):
    context = build_context_from_sidecar(tmp_path, case)
    actual = project_case(context)
    expected = seal_immutable(load_expected(case))
    report = {"case": case, "status": actual["status"], "result_id": actual["result_id"]}

    assert actual == expected
    assert not (_walk_keys(actual) & _FORBIDDEN)
    assert report["status"] == "success"


def test_sidecar_rollout_is_disabled_and_fixture_bindings_are_complete():
    sidecar = json.loads(Path("tests/fixtures/uei-v1/static-projection-sidecar-v1.json").read_text(encoding="utf-8"))

    assert sidecar["rollout"] == {"state": "Disabled", "enabled": False, "egress_policy": "disabled"}
    for case in sidecar["cases"].values():
        binding = case["fixture_binding"]
        assert set(binding) == {"artifact_sha256", "image_size"}
        assert len(binding["artifact_sha256"]) == 64
        assert set(binding["image_size"]) == {"width", "height"}


def test_docs_describe_exact_m2_shadow_boundary_and_non_authorization():
    readme = Path("README.md").read_text(encoding="utf-8")
    design = Path(
        "docs/superpowers/specs/2026-08-21-uei-provider-shadow-runtime.md"
    ).read_text(encoding="utf-8")

    assert "Universal Evidence Interface v1" in readme
    assert "review-only provider/shadow" in readme
    assert "不是主叙事，也不是生产 Learn、GUI、replay 或 Execute 集成" in readme
    assert "不能成为点击授权" in readme
    assert "Shadow-only" in design
    assert "does not authorize clicks" in design
    assert "fixed server-owned UEI shadow store" in design
    assert "cold duration, at least three warm durations" in design
